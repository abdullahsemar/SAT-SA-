"""Candidate unit generation for supervisory examiner review portfolios.

Generates candidate units from frozen analysis runs and submission contexts:
- Supports unit types: 'case', 'asset_period', 'source_period', 'claim_cohort'.
- Absence-of-coverage concerns are reviewable even when no alert or case exists.
- Tracks declared sampling frame, eligible control population, and logged exclusions.
- Assigns nonnegative review values (examiner-review rubric, not SOC probabilities).
- Requires positive estimated review minutes for every candidate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set

from db.models.assessment import Finding
from packages.analytics.context import AssessmentContext


@dataclass
class CandidateUnit:
    unit_id: str
    unit_type: str  # "case" | "asset_period" | "source_period" | "claim_cohort"
    scope: str
    finding_id: Optional[str]
    hypothesis_links: List[str]
    group_keys: Dict[str, str]  # e.g. {"asset": "...", "category": "...", "period": "..."}
    evidence_references: List[Dict[str, Any]]
    unknowns: List[str]
    estimated_review_minutes: float
    what_examiner_could_learn: str
    review_value: float
    coverage_weights: Dict[str, float] = field(default_factory=dict)
    is_control: bool = False
    stratum: str = "targeted"  # "targeted" | "control" | "exploratory"

    def __post_init__(self) -> None:
        if self.estimated_review_minutes <= 0:
            raise ValueError(
                f"CandidateUnit {self.unit_id} must have positive estimated_review_minutes, got {self.estimated_review_minutes}"
            )
        if self.review_value < 0:
            raise ValueError(
                f"CandidateUnit {self.unit_id} must have non-negative review_value, got {self.review_value}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CandidatePopulation:
    run_id: str
    entity_id: str
    period_key: str
    targeted_candidates: List[CandidateUnit]
    control_candidates: List[CandidateUnit]
    exploratory_candidates: List[CandidateUnit]
    all_candidates: List[CandidateUnit]
    excluded_records: List[Dict[str, Any]]
    sampling_frame_summary: Dict[str, Any]


class CandidateGenerator:
    """Extracts candidate units from a frozen analysis run and assessment context."""

    RULE_HYPOTHESIS_MAP = {
        "POL-INV-001": "hyp:investigation_quality",
        "POL-ESC-002": "hyp:escalation_timeliness",
        "POL-COV-003": "hyp:monitoring_coverage",
        "POL-KPI-004": "hyp:claim_reconciliation",
        "POL-REC-005": "hyp:recurrence_loop",
    }

    SEVERITY_VALUE_MAP = {
        "critical": 3.0,
        "high": 2.0,
        "medium": 1.0,
        "low": 0.5,
    }

    SEVERITY_MINUTES_MAP = {
        "critical": 15.0,
        "high": 12.0,
        "medium": 10.0,
        "low": 6.0,
    }

    def __init__(self, context: AssessmentContext):
        self.ctx = context
        sub = context.submission
        self.entity_id = getattr(sub, "entity_id", "CSE-UNKNOWN")
        # Build period key e.g. 2026-08
        p_start = (
            sub.period_start.strftime("%Y-%m")
            if hasattr(sub, "period_start") and sub.period_start
            else "period"
        )
        self.period_key = p_start

    def generate_candidates(
        self,
        run_id: str,
        findings: List[Finding],
    ) -> CandidatePopulation:
        targeted: List[CandidateUnit] = []
        control_candidates: List[CandidateUnit] = []
        exploratory: List[CandidateUnit] = []
        excluded_records: List[Dict[str, Any]] = []

        flagged_case_ids: Set[str] = set()
        flagged_asset_ids: Set[str] = set()

        # 1. Generate units from machine findings
        for f in findings:
            obj_type = f.primary_object_type
            obj_id = f.primary_object_id
            f_meta = f.finding_metadata
            severity = str(f_meta.get("severity", f.severity or "medium")).lower()

            # Record flagged objects for control sampling exclusion
            if obj_type in ("case", "cases"):
                flagged_case_ids.add(obj_id)
                for s_ref in f.supporting_records or []:
                    if isinstance(s_ref, dict):
                        r_type = s_ref.get("record_type")
                        n_id = s_ref.get("native_id")
                        if n_id and r_type in ("case", "cases"):
                            flagged_case_ids.add(n_id)
            if obj_type in ("asset", "assets"):
                flagged_asset_ids.add(obj_id)
                for s_ref in f.supporting_records or []:
                    if isinstance(s_ref, dict):
                        r_type = s_ref.get("record_type")
                        n_id = s_ref.get("native_id")
                        if n_id and r_type in ("asset", "assets"):
                            flagged_asset_ids.add(n_id)
            for aid in f.affected_asset_ids:
                flagged_asset_ids.add(aid)

            hyp_id = self.RULE_HYPOTHESIS_MAP.get(f.family, f"hyp:{f.family.lower()}")
            category = f.family
            asset_ref = (
                obj_id
                if obj_type in ("asset", "assets")
                else (f.affected_asset_ids[0] if f.affected_asset_ids else "unassigned")
            )

            group_keys = {
                "asset": asset_ref,
                "category": category,
                "period": self.period_key,
            }

            review_val = self.SEVERITY_VALUE_MAP.get(severity, 1.0)
            review_min = self.SEVERITY_MINUTES_MAP.get(severity, 10.0)

            # Map unit type
            if obj_type in ("case", "cases"):
                unit_type = "case"
                scope_str = f"case:{obj_id}"
                what_learns = (
                    f"Evaluate workflow triage notes, disposition rigor, and artifact sufficiency "
                    f"for case {obj_id} to determine if supervisory proposition holds: {f.proposition}"
                )
            elif obj_type in ("asset", "assets"):
                unit_type = "asset_period"
                scope_str = f"asset:{obj_id}:{self.period_key}"
                what_learns = (
                    f"Examine monitoring coverage, sensor telemetry, and agent heartbeat records for asset {obj_id} "
                    f"across period {self.period_key} to verify telemetry silence vs monitoring omission."
                )
            elif obj_type in ("claim", "claims"):
                unit_type = "claim_cohort"
                scope_str = f"claim:{obj_id}"
                what_learns = f"Audit self-reported claim reconciliation data and sample cases to substantiate claim {obj_id}."
            else:
                unit_type = "case"
                scope_str = f"{obj_type}:{obj_id}"
                what_learns = f"Inspect supervisory evidence regarding {f.proposition}."

            unknowns_list: List[str] = []
            if f.unknowns_json:
                try:
                    unknowns_list = json.loads(f.unknowns_json)
                except Exception:
                    unknowns_list = [f.unknowns_json]

            unit = CandidateUnit(
                unit_id=f"unit-tgt-{f.id[:8]}",
                unit_type=unit_type,
                scope=scope_str,
                finding_id=f.id,
                hypothesis_links=[hyp_id],
                group_keys=group_keys,
                evidence_references=f.supporting_records or [],
                unknowns=unknowns_list,
                estimated_review_minutes=review_min,
                what_examiner_could_learn=what_learns,
                review_value=review_val,
                coverage_weights={hyp_id: 1.0},
                is_control=False,
                stratum="targeted",
            )
            targeted.append(unit)

        # 2. Absence-of-coverage concerns without a case or alert
        # Check all assets in submission for telemetry anomalies that have no machine finding
        assets = self.ctx.get_records("assets")
        for asset in assets:
            aid = asset.get("asset_id") or asset.get("id") or asset.get("native_id")
            if not aid:
                continue

            agent_status = str(asset.get("agent_status", "")).upper()
            criticality = str(asset.get("criticality", "MEDIUM")).upper()
            status = str(asset.get("status", "ACTIVE")).upper()

            # Check if this active asset has an unflagged absence-of-coverage gap
            is_unhealthy = agent_status in ("UNHEALTHY", "DISCONNECTED", "MISSING")
            if is_unhealthy and status == "ACTIVE" and aid not in flagged_asset_ids:
                flagged_asset_ids.add(aid)
                ref = self.ctx.get_source_reference("assets", "asset_id", aid)
                evidence_refs = [ref.to_dict()] if ref else []
                hyp = "hyp:absence_of_coverage"
                unit = CandidateUnit(
                    unit_id=f"unit-cov-{aid}",
                    unit_type="asset_period",
                    scope=f"asset:{aid}:{self.period_key}",
                    finding_id=None,
                    hypothesis_links=[hyp],
                    group_keys={
                        "asset": aid,
                        "category": "absence_of_coverage",
                        "period": self.period_key,
                    },
                    evidence_references=evidence_refs,
                    unknowns=[
                        f"Asset {aid} has agent status '{agent_status}' but generated 0 alerts/cases; potential blind spot."
                    ],
                    estimated_review_minutes=12.0,
                    what_examiner_could_learn=(
                        f"Investigate unmonitored critical asset {aid} across period {self.period_key} to determine "
                        f"whether sensor telemetry disconnection represents an intentional maintenance window or supervisory gap."
                    ),
                    review_value=2.0 if criticality in ("CRITICAL", "HIGH") else 1.0,
                    coverage_weights={hyp: 1.0},
                    is_control=False,
                    stratum="targeted",
                )
                targeted.append(unit)

        # 3. Source-level review candidates (source_period)
        declared_sources = getattr(self.ctx.submission, "sources", []) or []
        for s in declared_sources:
            s_id = (
                getattr(s, "source_id", None) or s.get("source_id") if isinstance(s, dict) else ""
            )
            if not s_id:
                continue
            is_optional = (
                getattr(s, "is_optional", False)
                if hasattr(s, "is_optional")
                else s.get("is_optional", False)
            )
            declared_rows = (
                getattr(s, "declared_row_count", 0)
                if hasattr(s, "declared_row_count")
                else s.get("declared_row_count", 0)
            )
            if is_optional and declared_rows == 0:
                hyp = "hyp:optional_source_omission"
                unit = CandidateUnit(
                    unit_id=f"unit-src-{s_id}",
                    unit_type="source_period",
                    scope=f"source:{s_id}:{self.period_key}",
                    finding_id=None,
                    hypothesis_links=[hyp],
                    group_keys={
                        "asset": "telemetry-pipeline",
                        "category": "source_omission",
                        "period": self.period_key,
                    },
                    evidence_references=[],
                    unknowns=[f"Declared optional source '{s_id}' provided 0 records."],
                    estimated_review_minutes=8.0,
                    what_examiner_could_learn=f"Verify whether omission of optional source '{s_id}' impacts detection completeness.",
                    review_value=0.8,
                    coverage_weights={hyp: 1.0},
                    is_control=False,
                    stratum="targeted",
                )
                targeted.append(unit)

        # 4. Unflagged Eligible Control Population Sampling Frame
        # Eligible cases: closed cases with valid disposition and not flagged by any finding
        cases = self.ctx.get_records("cases")
        for c in cases:
            cid = str(c.get("native_id") or c.get("case_id") or c.get("id") or "")
            if not cid:
                continue

            if cid in flagged_case_ids:
                excluded_records.append(
                    {
                        "record_type": "cases",
                        "id": cid,
                        "reason": "flagged_by_machine_finding",
                    }
                )
                continue

            # Candidate unflagged control case: must resolve real source reference
            ref = self.ctx.get_source_reference("cases", "case_id", cid)
            if not ref:
                excluded_records.append(
                    {
                        "record_type": "cases",
                        "id": cid,
                        "reason": "unresolved_evidence_reference",
                    }
                )
                continue

            evidence_refs = [ref.to_dict()]
            hyp = "hyp:baseline_compliance"
            assigned = str(c.get("assigned_to", c.get("assigned_analyst", "analyst")))

            unit = CandidateUnit(
                unit_id=f"unit-ctrl-case-{cid}",
                unit_type="case",
                scope=f"case:{cid}",
                finding_id=None,
                hypothesis_links=[hyp],
                group_keys={
                    "asset": assigned,
                    "category": "baseline_control",
                    "period": self.period_key,
                },
                evidence_references=evidence_refs,
                unknowns=[],
                estimated_review_minutes=7.0,
                what_examiner_could_learn=(
                    f"Audit unflagged case {cid} against normal SOP to confirm false-negative absence "
                    f"and baseline investigation quality."
                ),
                review_value=0.5,
                coverage_weights={hyp: 0.5},
                is_control=True,
                stratum="control",
            )
            control_candidates.append(unit)

        # Also consider healthy quiet assets as eligible controls
        for asset in assets:
            aid = str(asset.get("native_id") or asset.get("asset_id") or asset.get("id") or "")
            if not aid:
                continue
            if aid in flagged_asset_ids:
                excluded_records.append(
                    {
                        "record_type": "assets",
                        "id": aid,
                        "reason": "flagged_by_coverage_or_asset_finding",
                    }
                )
                continue

            agent_status = str(asset.get("agent_status", "")).upper()
            if agent_status == "HEALTHY":
                ref = self.ctx.get_source_reference("assets", "asset_id", aid)
                if not ref:
                    excluded_records.append(
                        {
                            "record_type": "assets",
                            "id": aid,
                            "reason": "unresolved_evidence_reference",
                        }
                    )
                    continue
                evidence_refs = [ref.to_dict()]
                hyp = "hyp:baseline_healthy_silence"
                unit = CandidateUnit(
                    unit_id=f"unit-ctrl-asset-{aid}",
                    unit_type="asset_period",
                    scope=f"asset:{aid}:{self.period_key}",
                    finding_id=None,
                    hypothesis_links=[hyp],
                    group_keys={
                        "asset": aid,
                        "category": "baseline_control",
                        "period": self.period_key,
                    },
                    evidence_references=evidence_refs,
                    unknowns=[],
                    estimated_review_minutes=6.0,
                    what_examiner_could_learn=f"Confirm healthy silence for asset {aid} over period {self.period_key}.",
                    review_value=0.4,
                    coverage_weights={hyp: 0.5},
                    is_control=True,
                    stratum="control",
                )
                control_candidates.append(unit)

        # 5. Exploratory Units
        # Construct exploratory candidates from boundary items (e.g. low-severity findings or claims)
        claims = self.ctx.get_records("claims")
        for clm in claims:
            cid = str(clm.get("native_id") or clm.get("claim_id") or clm.get("id") or "")
            if not cid:
                continue
            ref = self.ctx.get_source_reference("claims", "claim_id", cid)
            if not ref:
                excluded_records.append(
                    {
                        "record_type": "claims",
                        "id": cid,
                        "reason": "unresolved_evidence_reference",
                    }
                )
                continue
            hyp = "hyp:exploratory_metric"
            evidence_refs = [ref.to_dict()]
            unit = CandidateUnit(
                unit_id=f"unit-exp-claim-{cid}",
                unit_type="claim_cohort",
                scope=f"claim:{cid}",
                finding_id=None,
                hypothesis_links=[hyp],
                group_keys={
                    "asset": "kpi-reporting",
                    "category": "exploratory",
                    "period": self.period_key,
                },
                evidence_references=evidence_refs,
                unknowns=["Exploratory metric validation cohort."],
                estimated_review_minutes=10.0,
                what_examiner_could_learn=f"Explore underlying data distribution for self-reported KPI {cid}.",
                review_value=0.6,
                coverage_weights={hyp: 1.0},
                is_control=False,
                stratum="exploratory",
            )
            exploratory.append(unit)

        # Additional exploratory items from border cases if real evidence is resolvable
        for c in cases[:2]:
            cid = str(c.get("native_id") or c.get("case_id") or c.get("id") or "")
            if not cid or cid in flagged_case_ids:
                continue
            ref = self.ctx.get_source_reference("cases", "case_id", cid)
            if not ref:
                excluded_records.append(
                    {
                        "record_type": "cases",
                        "id": cid,
                        "reason": "unresolved_evidence_reference",
                    }
                )
                continue
            hyp = "hyp:exploratory_edge_case"
            unit = CandidateUnit(
                unit_id=f"unit-exp-case-{cid}",
                unit_type="case",
                scope=f"case:{cid}",
                finding_id=None,
                hypothesis_links=[hyp],
                group_keys={
                    "asset": "edge-cases",
                    "category": "exploratory",
                    "period": self.period_key,
                },
                evidence_references=[ref.to_dict()],
                unknowns=["Exploratory boundary sampling."],
                estimated_review_minutes=8.0,
                what_examiner_could_learn=f"Explore edge case behavior on case {cid}.",
                review_value=0.5,
                coverage_weights={hyp: 0.8},
                is_control=False,
                stratum="exploratory",
            )
            exploratory.append(unit)

        all_cands = targeted + control_candidates + exploratory

        sampling_frame_summary = {
            "eligible_control_cases_count": sum(
                1 for c in control_candidates if c.unit_type == "case"
            ),
            "eligible_control_assets_count": sum(
                1 for c in control_candidates if c.unit_type == "asset_period"
            ),
            "total_control_eligible_count": len(control_candidates),
            "total_excluded_flagged_count": len(excluded_records),
            "declared_population_reference": f"submission-{self.ctx.submission_id}-period-{self.period_key}",
        }

        return CandidatePopulation(
            run_id=run_id,
            entity_id=self.entity_id,
            period_key=self.period_key,
            targeted_candidates=targeted,
            control_candidates=control_candidates,
            exploratory_candidates=exploratory,
            all_candidates=all_cands,
            excluded_records=excluded_records,
            sampling_frame_summary=sampling_frame_summary,
        )
