"""Report snapshot builder.

Constructs a frozen, immutable dictionary representation of an assessment,
including analytical findings, review portfolio, human examiner determinations,
local evidence requests, and cryptographic source provenance.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.assessment import AnalysisRun, Finding
from db.models.evidence import Submission, SubmissionFile, ValidationIssue
from db.models.review import EvidenceRequest, ReviewDecision, ReviewItem, ReviewPortfolio
from db.models.semantic_evidence import FindingSimilarPassage


class ReportSnapshotBuilder:
    """Builds a complete, resolvable, frozen assessment snapshot."""

    def __init__(self, db: Session):
        self.db = db

    def build_snapshot(
        self,
        run_id: str,
        entity_id: str,
        portfolio_id: Optional[str] = None,
        decision_cutoff_time: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Constructs the frozen snapshot dictionary."""
        cutoff = decision_cutoff_time or datetime.now(timezone.utc)
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)

        # 1. Fetch AnalysisRun & verify entity scope
        run = self.db.execute(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id,
                AnalysisRun.entity_id == entity_id,
            )
        ).scalar_one_or_none()
        if not run:
            raise ValueError(f"AnalysisRun '{run_id}' not found for entity '{entity_id}'")

        # 2. Fetch Submission & files
        sub = self.db.execute(
            select(Submission).where(
                Submission.id == run.submission_id,
                Submission.entity_id == entity_id,
            )
        ).scalar_one_or_none()
        if not sub:
            raise ValueError(f"Submission '{run.submission_id}' not found for entity '{entity_id}'")

        sub_files = (
            self.db.execute(
                select(SubmissionFile)
                .where(SubmissionFile.submission_id == sub.id)
                .order_by(SubmissionFile.source_id)
            )
            .scalars()
            .all()
        )

        validation_issues = (
            self.db.execute(select(ValidationIssue).where(ValidationIssue.submission_id == sub.id))
            .scalars()
            .all()
        )

        # 3. Fetch Findings
        findings_query = (
            self.db.execute(select(Finding).where(Finding.run_id == run.id).order_by(Finding.id))
            .scalars()
            .all()
        )

        findings_data: List[Dict[str, Any]] = []
        finding_ids = [f.id for f in findings_query]

        # Fetch similar passages if any
        similar_passages_by_finding: Dict[str, List[Dict[str, Any]]] = {}
        if finding_ids:
            sim_query = (
                self.db.execute(
                    select(FindingSimilarPassage).where(
                        FindingSimilarPassage.finding_id.in_(finding_ids)
                    )
                )
                .scalars()
                .all()
            )
            for sp in sim_query:
                similar_passages_by_finding.setdefault(sp.finding_id, []).append(
                    {
                        "passage_id": getattr(sp, "passage_id", None)
                        or getattr(sp, "matched_record_id", None)
                        or sp.id,
                        "score": float(
                            getattr(sp, "score", None)
                            if getattr(sp, "score", None) is not None
                            else getattr(sp, "similarity_score", 0.0)
                        ),
                        "source_id": getattr(sp, "source_id", None)
                        or getattr(sp, "matched_source_id", "unknown"),
                        "preview": getattr(sp, "preview_text", None)
                        or getattr(sp, "matched_passage_text", ""),
                        "rationale": getattr(sp, "match_rationale", None)
                        or getattr(sp, "possible_explanation", ""),
                    }
                )

        for f in findings_query:
            try:
                metrics_dict = json.loads(f.metrics_json or "{}")
            except Exception:
                metrics_dict = {}

            try:
                sup_records = json.loads(f.supporting_sources_json or "[]")
            except Exception:
                sup_records = []

            try:
                contra_records = json.loads(f.contradicting_sources_json or "[]")
            except Exception:
                contra_records = []

            try:
                alts = json.loads(f.alternative_explanations_json or "[]")
            except Exception:
                alts = []

            try:
                unknowns = json.loads(f.unknowns_json or "[]")
            except Exception:
                unknowns = []

            findings_data.append(
                {
                    "finding_id": f.id,
                    "rule_id": f.family,
                    "rule_title": f.applicable_obligation,
                    "rule_category": f.family,
                    "severity": f.severity,
                    "status": f.evidence_state,
                    "observation": f.proposition,
                    "supervisory_significance": f.applicable_obligation,
                    "metrics": metrics_dict,
                    "supporting_records": sup_records,
                    "contradicting_records": contra_records,
                    "alternatives": alts,
                    "unknowns": unknowns,
                    "similar_passages": similar_passages_by_finding.get(f.id, []),
                }
            )

        # 4. Fetch Review Portfolio
        portfolio_data: Optional[Dict[str, Any]] = None
        portfolio_items_data: List[Dict[str, Any]] = []
        portfolio_item_ids: List[str] = []

        if portfolio_id:
            port = self.db.execute(
                select(ReviewPortfolio).where(
                    ReviewPortfolio.id == portfolio_id,
                    ReviewPortfolio.entity_id == entity_id,
                )
            ).scalar_one_or_none()
        else:
            # Fallback: check if a portfolio exists for this run
            port = (
                self.db.execute(
                    select(ReviewPortfolio)
                    .where(
                        ReviewPortfolio.run_id == run.id,
                        ReviewPortfolio.entity_id == entity_id,
                    )
                    .order_by(ReviewPortfolio.revision.desc())
                )
                .scalars()
                .first()
            )

        if port:
            try:
                port_params = json.loads(port.parameters_json or "{}")
            except Exception:
                port_params = {}
            try:
                port_summary = json.loads(port.summary_json or "{}")
            except Exception:
                port_summary = {}

            p_items = (
                self.db.execute(
                    select(ReviewItem)
                    .where(ReviewItem.portfolio_id == port.id)
                    .order_by(ReviewItem.selection_rank)
                )
                .scalars()
                .all()
            )

            for item in p_items:
                portfolio_item_ids.append(item.id)
                try:
                    reasons = json.loads(item.marginal_reasons_json or "{}")
                except Exception:
                    reasons = {}
                try:
                    item_unknowns = json.loads(item.unknowns_json or "[]")
                except Exception:
                    item_unknowns = []

                portfolio_items_data.append(
                    {
                        "item_id": item.id,
                        "rank": item.selection_rank,
                        "unit_id": item.unit_id,
                        "unit_type": item.unit_type,
                        "scope": {"scope": item.scope}
                        if isinstance(item.scope, str)
                        else item.scope,
                        "finding_id": item.finding_id,
                        "stratum": item.stratum,
                        "review_minutes": float(item.estimated_review_minutes),
                        "review_value": 0.0,
                        "reasons": reasons,
                        "what_examiner_could_learn": item.what_examiner_learns,
                        "unknowns": item_unknowns,
                    }
                )

            portfolio_data = {
                "portfolio_id": port.id,
                "revision": port.revision,
                "seed": port.seed,
                "created_by": port.created_by,
                "created_at": port.created_at.isoformat(),
                "parameters": port_params,
                "summary": port_summary,
                "items": portfolio_items_data,
            }

        # 5. Fetch Examiner Decisions up to Cutoff
        # Finding-level decisions
        finding_decisions_data: List[Dict[str, Any]] = []
        if finding_ids:
            f_decisions = (
                self.db.execute(
                    select(ReviewDecision)
                    .where(
                        ReviewDecision.finding_id.in_(finding_ids),
                        ReviewDecision.entity_id == entity_id,
                        ReviewDecision.created_at <= cutoff,
                    )
                    .order_by(ReviewDecision.created_at.asc())
                )
                .scalars()
                .all()
            )

            # Group by finding_id to identify latest vs superseded
            decisions_by_target: Dict[str, List[ReviewDecision]] = {}
            for d in f_decisions:
                decisions_by_target.setdefault(d.finding_id, []).append(d)

            for target_id, d_list in decisions_by_target.items():
                for idx, d in enumerate(d_list):
                    is_active = idx == len(d_list) - 1
                    try:
                        cited = json.loads(d.cited_evidence_ids_json or "[]")
                    except Exception:
                        cited = []

                    finding_decisions_data.append(
                        {
                            "decision_id": d.id,
                            "finding_id": d.finding_id,
                            "state": d.state,
                            "rationale": d.rationale,
                            "cited_evidence_ids": cited,
                            "version": d.version,
                            "reviewer_id": d.reviewer_id,
                            "created_at": d.created_at.isoformat(),
                            "is_active": is_active,
                            "superseded_decision_id": d.superseded_decision_id,
                        }
                    )

        # Item-level decisions (for control and exploratory items)
        item_decisions_data: List[Dict[str, Any]] = []
        if portfolio_item_ids:
            i_decisions = (
                self.db.execute(
                    select(ReviewDecision)
                    .where(
                        ReviewDecision.review_item_id.in_(portfolio_item_ids),
                        ReviewDecision.entity_id == entity_id,
                        ReviewDecision.created_at <= cutoff,
                    )
                    .order_by(ReviewDecision.created_at.asc())
                )
                .scalars()
                .all()
            )

            decisions_by_item: Dict[str, List[ReviewDecision]] = {}
            for d in i_decisions:
                decisions_by_item.setdefault(d.review_item_id, []).append(d)

            for target_id, d_list in decisions_by_item.items():
                for idx, d in enumerate(d_list):
                    is_active = idx == len(d_list) - 1
                    try:
                        cited = json.loads(d.cited_evidence_ids_json or "[]")
                    except Exception:
                        cited = []

                    item_decisions_data.append(
                        {
                            "decision_id": d.id,
                            "review_item_id": d.review_item_id,
                            "state": d.state,
                            "rationale": d.rationale,
                            "cited_evidence_ids": cited,
                            "version": d.version,
                            "reviewer_id": d.reviewer_id,
                            "created_at": d.created_at.isoformat(),
                            "is_active": is_active,
                            "superseded_decision_id": d.superseded_decision_id,
                        }
                    )

        # 6. Fetch Outstanding Evidence Requests up to Cutoff
        ev_requests = (
            self.db.execute(
                select(EvidenceRequest)
                .where(
                    EvidenceRequest.entity_id == entity_id,
                    EvidenceRequest.created_at <= cutoff,
                )
                .order_by(EvidenceRequest.created_at.asc())
            )
            .scalars()
            .all()
        )

        ev_requests_data: List[Dict[str, Any]] = []
        for r in ev_requests:
            ev_requests_data.append(
                {
                    "request_id": r.id,
                    "review_item_id": r.review_item_id,
                    "finding_id": r.finding_id,
                    "missing_artifact": r.missing_artifact,
                    "distinguishing_question": r.distinguishing_question,
                    "responsible_owner": r.responsible_owner,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                    "status": r.status,
                    "created_at": r.created_at.isoformat(),
                }
            )

        # 7. Check for Comparable Prior Runs
        prior_runs = (
            self.db.execute(
                select(AnalysisRun)
                .where(
                    AnalysisRun.entity_id == entity_id,
                    AnalysisRun.id != run.id,
                    AnalysisRun.status == "completed",
                    AnalysisRun.created_at < run.created_at,
                )
                .order_by(AnalysisRun.created_at.desc())
            )
            .scalars()
            .all()
        )

        prior_runs_data: List[Dict[str, Any]] = []
        for pr in prior_runs[:3]:
            try:
                sc = json.loads(pr.summary_counts_json or "{}")
            except Exception:
                sc = {}
            prior_runs_data.append(
                {
                    "run_id": pr.id,
                    "period_cutoff": pr.cutoff_time.isoformat(),
                    "findings_count": pr.findings_count,
                    "summary_counts": sc,
                }
            )

        # 8. Check Model Manifest & Semantic Status
        model_manifest_path = Path("models/manifest.json")
        model_info: Dict[str, Any] = {
            "mode": "lexical_fallback",
            "manifest_sha256": None,
            "commit": None,
            "device": "offline_cpu",
        }
        if model_manifest_path.is_file():
            try:
                with open(model_manifest_path, "r", encoding="utf-8") as mf:
                    m_data = json.load(mf)
                    model_info["manifest_sha256"] = m_data.get("manifest_sha256")
                    model_info["commit"] = m_data.get("commit")
                    model_info["model_name"] = m_data.get(
                        "model_name", "sentence-transformers/all-MiniLM-L6-v2"
                    )
                    model_info["mode"] = "local_sentence_transformers"
            except Exception:
                pass

        # Build complete snapshot
        snapshot: Dict[str, Any] = {
            "report_schema_version": "v1.0",
            "snapshot_generated_at": datetime.now(timezone.utc).isoformat(),
            "decision_cutoff_time": cutoff.isoformat(),
            "notes": notes,
            "entity": {
                "entity_id": sub.entity_id,
                "source_timezone": sub.source_timezone,
            },
            "submission": {
                "submission_id": sub.id,
                "revision": sub.revision,
                "status": sub.status,
                "period_start": sub.period_start.isoformat(),
                "period_end": sub.period_end.isoformat(),
                "files": [
                    {
                        "source_id": f.source_id,
                        "original_filename": f.original_filename,
                        "filename": f.original_filename,
                        "record_type": f.record_type,
                        "file_type": f.record_type,
                        "byte_size": f.byte_size,
                        "size_bytes": f.byte_size,
                        "sha256_hash": f.sha256_hash,
                        "declared_row_count": f.declared_row_count,
                        "actual_row_count": f.actual_row_count,
                        "record_count": f.actual_row_count,
                    }
                    for f in sub_files
                ],
                "validation_issues_count": len(validation_issues),
            },
            "analysis_run": {
                "run_id": run.id,
                "status": run.status,
                "input_hash": run.input_hash,
                "policy_version": run.policy_version,
                "rule_version": run.rule_version,
                "seed": run.seed,
                "cutoff_time": run.cutoff_time.isoformat(),
                "findings_count": run.findings_count,
                "created_at": run.created_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            },
            "methodology": {
                "rule_version": run.rule_version,
                "policy_version": run.policy_version,
                "semantic_model": model_info,
                "supervisory_notice": (
                    "SAT-SA is an evidence-intake and decision-support analytical workbench for human examiners. "
                    "It does not issue autonomous supervisory pass/fail sanctions or replace human regulatory judgment. "
                    "All findings represent automated anomaly and quality flags requiring human examiner determination."
                ),
            },
            "findings": findings_data,
            "review_portfolio": portfolio_data,
            "examiner_decisions": {
                "finding_decisions": finding_decisions_data,
                "item_decisions": item_decisions_data,
                "total_decisions_count": len(finding_decisions_data) + len(item_decisions_data),
            },
            "evidence_requests": ev_requests_data,
            "comparable_prior_runs": prior_runs_data,
            "trend_status": "COMPARABLE_PRIOR_AVAILABLE"
            if prior_runs_data
            else "NO_COMPARABLE_PRIOR_DATA",
        }

        return snapshot
