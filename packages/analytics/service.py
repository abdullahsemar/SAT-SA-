"""Analytics service orchestrator for SAT-SA.

Manages the lifecycle of analysis runs and finding generation:
- Enforces strict precondition: submission must be committed (immutable).
- Pre-computes input hashes to guarantee deterministic replayability.
- Orchestrates graph reconstruction, obligation evaluation, and detector passes.
- Persists AnalysisRun and Finding records in the database.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.assessment import AnalysisRun, Finding
from db.models.evidence import Submission
from db.models.semantic_evidence import FindingSimilarPassage, SemanticPassageChunk
from packages.analytics.context import AssessmentContext
from packages.analytics.detectors import (
    EscalationEvidenceDetector,
    InvestigationEvidenceDetector,
    KPIReconciliationDetector,
    MonitoringCoverageDetector,
    RecurrenceContextDetector,
)
from packages.analytics.obligations import ObligationEvaluator
from packages.analytics.reconstruction import EvidenceGraphReconstructor
from packages.analytics.semantics.similarity import SimilarityEngine


class SubmissionNotCommittedError(Exception):
    """Raised when an analysis is requested on a draft or non-committed submission."""

    pass


class SubmissionNotFoundError(Exception):
    """Raised when the specified submission does not exist."""

    pass


class AnalysisService:
    def __init__(self, session: Session):
        self.session = session
        self.config_dir = Path(__file__).resolve().parent.parent.parent / "config"

    def _load_json_config(self, relative_path: str) -> Dict[str, Any]:
        cfg_path = self.config_dir / relative_path
        if not cfg_path.exists():
            return {}
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def run_assessment(
        self,
        submission_id: str,
        cse_id: str,
        policy_id: Optional[str] = "POL-CSE-DEMO-V1",
        run_name: Optional[str] = None,
        semantic_mode: str = "auto",
    ) -> AnalysisRun:
        """Executes full supervisory analytics on a committed submission."""
        # 1. Fetch and validate submission
        stmt = select(Submission).where(
            Submission.id == submission_id,
            Submission.entity_id == cse_id,
        )
        res = self.session.execute(stmt)
        submission = res.scalar_one_or_none()

        if not submission:
            raise SubmissionNotFoundError(f"Submission {submission_id} not found for CSE {cse_id}")

        if submission.status != "committed":
            raise SubmissionNotCommittedError(
                f"Submission {submission_id} is in status '{submission.status}'. "
                f"Only 'committed' submissions can be analyzed."
            )

        policy_config = self._load_json_config("policies/demo-v1.json")
        rules_config = self._load_json_config("detectors/rules-v1.json")
        fingerprint = {
            "fingerprint_version": "assessment-v2",
            "manifest": json.loads(submission.manifest_json or "{}"),
            "files": sorted(
                [
                    {
                        "source_id": f.source_id,
                        "record_type": f.record_type,
                        "sha256": f.sha256_hash,
                        "byte_size": f.byte_size,
                    }
                    for f in submission.files
                ],
                key=lambda f: f["source_id"],
            ),
            "policy": policy_config,
            "rules": rules_config,
            "normalization_version": "intake-v2",
            "semantic_mode": semantic_mode,
        }
        input_hash = hashlib.sha256(
            json.dumps(
                fingerprint, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        run_id = str(uuid.uuid4())

        analysis_run = AnalysisRun(
            id=run_id,
            submission_id=submission_id,
            entity_id=cse_id,
            status="running",
            input_hash=input_hash,
            policy_version=policy_config.get("policy_version", "demo-v1"),
            rule_version=rules_config.get("rule_version", "rules-v1"),
            cutoff_time=submission.period_end,
            parameters_json=json.dumps(
                {
                    "policy_id": policy_id,
                    "run_name": run_name,
                    "semantic_mode": semantic_mode,
                    "input_fingerprint": fingerprint,
                    "policy_snapshot": policy_config,
                    "rules_snapshot": rules_config,
                    "semantic_provenance": {
                        "semantic_mode": semantic_mode,
                        "model_revision": None,
                        "manifest_digest": None,
                        "preprocessing_version": "chunk-v1",
                        "method_used": "disabled" if semantic_mode == "off" else "not_computed",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                }
            ),
        )
        self.session.add(analysis_run)
        self.session.flush()

        try:
            # 4. Load context and build reconstruction graph
            context = AssessmentContext(submission)
            graph = EvidenceGraphReconstructor(context)
            evaluator = ObligationEvaluator(policy_config)

            # Map detector rules from config
            detector_map = {
                "POL-INV-001": InvestigationEvidenceDetector,
                "POL-ESC-002": EscalationEvidenceDetector,
                "POL-COV-003": MonitoringCoverageDetector,
                "POL-KPI-004": KPIReconciliationDetector,
                "POL-REC-005": RecurrenceContextDetector,
            }

            all_results = []
            # Iterate through families in rules_config
            families = rules_config.get("families", {})
            for fam_key, rule_cfg in families.items():
                rid = rule_cfg.get("obligation_id") or rule_cfg.get("rule_id")
                detector_cls = detector_map.get(rid)
                if detector_cls:
                    det = detector_cls(context, graph, evaluator, rule_cfg)
                    all_results.extend(det.run())

            # 5. Persist Findings
            created_findings = []
            for res_item in all_results:
                f_data = res_item.to_dict(submission_id)
                metrics = {
                    "severity": f_data["severity"],
                    "affected_asset_ids": f_data.get("affected_asset_ids", []),
                    "peer_comparison_status": f_data.get(
                        "peer_comparison_status", "peer_comparison_unavailable"
                    ),
                    **f_data.get("finding_metadata", {}),
                }
                unknowns = [f_data["uncertainty_note"]] if f_data.get("uncertainty_note") else []
                finding = Finding(
                    id=f_data["finding_id"],
                    run_id=run_id,
                    submission_id=submission_id,
                    entity_id=cse_id,
                    proposition=f_data["rationale"],
                    scope=f"{f_data['primary_object_type']}:{f_data['primary_object_id']}",
                    family=f_data["rule_id"],
                    evidence_state=f_data["evidence_state"],
                    applicable_obligation=f_data["rule_title"],
                    supporting_sources_json=json.dumps(f_data.get("supporting_records", [])),
                    contradicting_sources_json="[]",
                    lineage_json="[]",
                    unknowns_json=json.dumps(unknowns),
                    alternative_explanations_json="[]",
                    additional_evidence_needed_json="[]",
                    metrics_json=json.dumps(metrics),
                )
                self.session.add(finding)
                created_findings.append(finding)

            # 5b. Evaluate and Persist Semantic Evidence
            if semantic_mode != "off":
                sim_engine = SimilarityEngine(mode=semantic_mode)
                parameters = json.loads(analysis_run.parameters_json)
                parameters["semantic_provenance"].update(
                    {
                        "model_revision": sim_engine.commit_sha,
                        "manifest_digest": sim_engine.manifest_digest,
                        "fallback_reason": sim_engine.fallback_reason,
                        "method_used": "semantic" if sim_engine.encoder else "lexical_fallback",
                    }
                )
                fingerprint["semantic_provenance"] = {
                    k: v for k, v in parameters["semantic_provenance"].items() if k != "timestamp"
                }
                parameters["input_fingerprint"] = fingerprint
                analysis_run.parameters_json = json.dumps(parameters)
                analysis_run.input_hash = hashlib.sha256(
                    json.dumps(
                        fingerprint, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    ).encode("utf-8")
                ).hexdigest()
                all_passages = context.get_investigation_passages()

                # Precompute and save passage chunks into db if encoder is active
                if sim_engine.encoder is not None:
                    from packages.analytics.semantics.chunking import TextChunker

                    chunker = TextChunker(tokenizer=sim_engine.encoder.tokenizer)
                    for p in all_passages:
                        p_chunks = chunker.chunk_text(p["text"])
                        if p_chunks:
                            p_vecs = sim_engine.encoder.encode(
                                [c.normalized_text for c in p_chunks]
                            )
                            for c_idx, c in enumerate(p_chunks):
                                p_chunk_rec = SemanticPassageChunk(
                                    submission_id=submission_id,
                                    entity_id=cse_id,
                                    source_id=p["source_id"],
                                    record_type=p["record_type"],
                                    record_id=p["record_id"],
                                    chunk_index=c.chunk_index,
                                    start_char=c.start_char,
                                    end_char=c.end_char,
                                    raw_text=c.raw_text,
                                    normalized_text=c.normalized_text,
                                    chunk_hash=c.chunk_hash,
                                    vector_json=json.dumps(p_vecs[c_idx].tolist()),
                                )
                                self.session.add(p_chunk_rec)

                # Find similar passages for each finding
                case_records_map = {}
                for c in context.get_records("cases"):
                    for k in ("case_id", "native_id", "id"):
                        val = c.get(k)
                        if val:
                            case_records_map[str(val)] = c

                for finding in created_findings:
                    target_obj_type = finding.primary_object_type
                    target_obj_id = finding.primary_object_id

                    target_text = None
                    target_src_id = "src-cases"
                    target_rec_type = (
                        "cases" if target_obj_type in ("case", "cases") else target_obj_type
                    )

                    if target_obj_type in ("case", "cases") and target_obj_id in case_records_map:
                        case = case_records_map[target_obj_id]
                        s_ref = case.get("_source_ref") or {}
                        target_src_id = s_ref.get("source_id", "src-cases")
                        if case.get("disposition"):
                            target_text = f"Disposition: {case['disposition']}"
                        elif case.get("root_cause") and case.get("root_cause") != "UNKNOWN":
                            target_text = f"Root cause: {case['root_cause']}"
                        elif case.get("title"):
                            target_text = str(case["title"])

                    if target_text:
                        matches = sim_engine.find_similar_passages(
                            target_record_id=target_obj_id,
                            target_source_id=target_src_id,
                            target_record_type=target_rec_type,
                            target_text=target_text,
                            candidates=all_passages,
                            limit=5,
                        )
                        for m in matches:
                            fsp = FindingSimilarPassage(
                                finding_id=finding.id,
                                run_id=run_id,
                                entity_id=cse_id,
                                target_passage_text=m.target_text,
                                target_start_char=m.target_start_char,
                                target_end_char=m.target_end_char,
                                target_record_id=m.target_record_id,
                                matched_passage_text=m.matched_text,
                                matched_start_char=m.matched_start_char,
                                matched_end_char=m.matched_end_char,
                                matched_record_id=m.matched_record_id,
                                matched_source_id=m.matched_source_id,
                                matched_record_type=m.matched_record_type,
                                similarity_score=m.similarity_score,
                                semantic_mode=semantic_mode,
                                method_used=m.method_used,
                                model_revision=m.model_revision,
                                manifest_digest=m.manifest_digest,
                                preprocessing_version="chunk-v1",
                                fallback_reason=m.fallback_reason,
                                possible_explanation=m.possible_explanation,
                                caveats=m.caveats,
                            )
                            self.session.add(fsp)

            # 6. Update AnalysisRun
            analysis_run.status = "completed"
            analysis_run.completed_at = datetime.now(timezone.utc)
            analysis_run.findings_count = len(created_findings)
            summary_dict = {
                "total_findings": len(created_findings),
                "excluded_claims": context.excluded_claims,
                "by_evidence_state": {
                    state: sum(1 for f in created_findings if f.evidence_state == state)
                    for state in [
                        "supported",
                        "potential_concern",
                        "contradictory",
                        "insufficient_evidence",
                        "not_applicable",
                    ]
                },
                "by_severity": {
                    sev: sum(1 for f in created_findings if f.severity == sev)
                    for sev in ["critical", "high", "medium", "low", "info"]
                },
            }
            analysis_run.summary_counts_json = json.dumps(summary_dict)

            # Record signed custody event for assessment finalization
            from packages.evidence_integrity.custody import CustodyLogManager

            custody_mgr = CustodyLogManager(self.session)
            custody_mgr.record_event(
                entity_id=cse_id,
                event_type="assessment_finalized",
                object_type="analysis_run",
                object_id=analysis_run.id,
                object_version=1,
                evidence_commitment=analysis_run.input_hash,
                actor_id="system_analytics",
                metadata={
                    "findings_count": len(created_findings),
                    "policy_version": analysis_run.policy_version,
                },
            )

            self.session.commit()
            self.session.refresh(analysis_run)
            return analysis_run

        except Exception as exc:
            self.session.rollback()
            analysis_run.status = "failed"
            analysis_run.completed_at = datetime.now(timezone.utc)
            analysis_run.error_message = str(exc)
            self.session.add(analysis_run)
            self.session.commit()
            raise

    def get_run(self, run_id: str, cse_id: Optional[str] = None) -> Optional[AnalysisRun]:
        stmt = select(AnalysisRun).where(AnalysisRun.id == run_id)
        if cse_id and cse_id != "*":
            stmt = stmt.where(AnalysisRun.entity_id == cse_id)
        res = self.session.execute(stmt)
        return res.scalar_one_or_none()

    def list_runs(
        self,
        cse_id: Optional[str] = None,
        submission_id: Optional[str] = None,
        entity_ids: list[str] | None = None,
    ) -> List[AnalysisRun]:
        stmt = select(AnalysisRun).order_by(AnalysisRun.created_at.desc())
        if entity_ids is not None:
            stmt = stmt.where(AnalysisRun.entity_id.in_(entity_ids))
        if cse_id and cse_id != "*":
            stmt = stmt.where(AnalysisRun.entity_id == cse_id)
        if submission_id:
            stmt = stmt.where(AnalysisRun.submission_id == submission_id)
        res = self.session.execute(stmt)
        return list(res.scalars().all())

    def get_finding(self, finding_id: str, cse_id: Optional[str] = None) -> Optional[Finding]:
        stmt = select(Finding).where(Finding.id == finding_id)
        if cse_id and cse_id != "*":
            stmt = stmt.where(Finding.entity_id == cse_id)
        res = self.session.execute(stmt)
        return res.scalar_one_or_none()

    def list_findings(
        self,
        cse_id: Optional[str] = None,
        submission_id: Optional[str] = None,
        run_id: Optional[str] = None,
        rule_id: Optional[str] = None,
        evidence_state: Optional[str] = None,
        entity_ids: list[str] | None = None,
    ) -> List[Finding]:
        stmt = select(Finding).order_by(Finding.created_at.desc())
        if entity_ids is not None:
            stmt = stmt.where(Finding.entity_id.in_(entity_ids))
        if cse_id and cse_id != "*":
            stmt = stmt.where(Finding.entity_id == cse_id)
        if submission_id:
            stmt = stmt.where(Finding.submission_id == submission_id)
        if run_id:
            stmt = stmt.where(Finding.run_id == run_id)
        if rule_id:
            stmt = stmt.where(Finding.family == rule_id)
        if evidence_state:
            stmt = stmt.where(Finding.evidence_state == evidence_state)
        res = self.session.execute(stmt)
        return list(res.scalars().all())

    def get_evidence_chain(self, submission_id: str, object_id: str, cse_id: str) -> Dict[str, Any]:
        """Builds an interactive evidence chain for a specific object in a submission."""
        stmt = select(Submission).where(
            Submission.id == submission_id,
            Submission.entity_id == cse_id,
        )
        res = self.session.execute(stmt)
        sub = res.scalar_one_or_none()
        if not sub:
            raise SubmissionNotFoundError(f"Submission {submission_id} not found")

        ctx = AssessmentContext(sub)
        graph = EvidenceGraphReconstructor(ctx)
        return graph.get_full_evidence_chain(object_id)

    def get_similar_passages(
        self,
        finding_id: str,
        cse_id: Optional[str] = None,
        limit: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """Strictly read-only retrieval of previously persisted passage similarity results.

        Never loads the model, calculates embeddings, creates records, or mutates state.
        """
        finding = self.get_finding(finding_id=finding_id, cse_id=cse_id)
        if not finding:
            return None

        # Query persisted matches
        stmt = (
            select(FindingSimilarPassage)
            .where(FindingSimilarPassage.finding_id == finding_id)
            .order_by(FindingSimilarPassage.similarity_score.desc())
            .limit(limit)
        )
        if cse_id and cse_id != "*":
            stmt = stmt.where(FindingSimilarPassage.entity_id == cse_id)

        matches = list(self.session.execute(stmt).scalars().all())

        if matches:
            first = matches[0]
            return {
                "finding_id": finding_id,
                "status": "completed",
                "semantic_mode": first.semantic_mode,
                "method_used": first.method_used,
                "model_revision": first.model_revision,
                "manifest_digest": first.manifest_digest,
                "fallback_reason": first.fallback_reason,
                "target_passage": first.target_passage_text,
                "target_span": {
                    "start_char": first.target_start_char,
                    "end_char": first.target_end_char,
                    "record_id": first.target_record_id,
                },
                "matches": [
                    {
                        "match_id": m.id,
                        "source_id": m.matched_source_id,
                        "record_type": m.matched_record_type,
                        "record_id": m.matched_record_id,
                        "start_char": m.matched_start_char,
                        "end_char": m.matched_end_char,
                        "matched_text": m.matched_passage_text,
                        "similarity": m.similarity_score,
                        "method": m.method_used,
                        "possible_explanation": m.possible_explanation,
                        "caveats": m.caveats,
                        "exact_match": True
                        if "Exact: True" in m.caveats
                        else (False if "Exact: False" in m.caveats else None),
                        "lexical_score": (
                            float(
                                __import__("re").search(r"Lexical:\s*([\d\.]+)", m.caveats).group(1)
                            )
                            if __import__("re").search(r"Lexical:\s*([\d\.]+)", m.caveats)
                            else None
                        ),
                        "tlsh_distance": (
                            int(
                                __import__("re")
                                .search(r"TLSH Distance:\s*(\d+)", m.caveats)
                                .group(1)
                            )
                            if __import__("re").search(r"TLSH Distance:\s*(\d+)", m.caveats)
                            else None
                        ),
                        "semantic_score": (
                            float(
                                __import__("re")
                                .search(r"Semantic:\s*([\d\.]+)", m.caveats)
                                .group(1)
                            )
                            if __import__("re").search(r"Semantic:\s*([\d\.]+)", m.caveats)
                            else None
                        ),
                    }
                    for m in matches
                ],
                "disclaimer": (
                    "Similarity evidence is comparative decision support for human examiners. "
                    "It does not classify SOC quality, prove superficiality, or replace regulatory judgment."
                ),
            }

        # No matches found: inspect run parameter
        run = self.session.get(AnalysisRun, finding.run_id)
        run_mode = "auto"
        if run and run.parameters_json:
            try:
                run_mode = json.loads(run.parameters_json).get("semantic_mode", "auto")
            except Exception:
                pass

        status_code = "disabled" if run_mode == "off" else "not_computed"
        return {
            "finding_id": finding_id,
            "status": status_code,
            "semantic_mode": run_mode,
            "method_used": "disabled" if run_mode == "off" else "none",
            "model_revision": None,
            "manifest_digest": None,
            "fallback_reason": None,
            "target_passage": None,
            "target_span": None,
            "matches": [],
            "disclaimer": (
                "Similarity evidence is comparative decision support for human examiners. "
                "It does not classify SOC quality, prove superficiality, or replace regulatory judgment."
            ),
        }
