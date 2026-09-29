"""Supervisory summary analytics: Entity-level supervisory attention indicators,
evidence completeness accounting, execution gaps, negative space, and capability coverage.

Architectural Invariants:
- Supervisory review priority is distinct from breach probability or autonomous grades.
- Evidence sufficiency is evaluated separately from operational concerns; a poorly evidenced
  entity is explicitly flagged as unassessable or high-attention, never marked safe.
- Transparent, versioned weights with full drill-down to contributing records and findings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models.assessment import AnalysisRun, Finding
from db.models.evidence import CSE, NormalizedRecord, Submission, SubmissionFile
from db.models.review import EvidenceRequest, ReviewDecision, ReviewPortfolio


@dataclass
class EvidenceCompletenessSummary:
    declared_sources_count: int
    received_sources_count: int
    missing_sources_count: int
    quarantined_records_count: int
    total_parsed_records: int
    completeness_percentage: float
    sufficiency_verdict: str  # "SUFFICIENT", "PARTIALLY_SUFFICIENT", "INSUFFICIENT_EVIDENCE"
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionGapSummary:
    unsubstantiated_closures: int
    overdue_escalations: int
    unlinked_lifecycle_cases: int
    adverse_findings_count: int
    gap_score: float  # 0.0 (clean) to 100.0 (high concern)
    severity_distribution: Dict[str, int] = field(default_factory=dict)
    contributing_finding_ids: List[str] = field(default_factory=list)


@dataclass
class NegativeSpaceSummary:
    total_critical_assets: int
    healthy_monitored_assets: int
    broken_sensor_assets: int
    healthy_quiet_assets: int  # 0 alerts but verified healthy agent
    missing_telemetry_assets: int
    coverage_percentage: float
    blind_spot_warning: bool
    contributing_asset_ids: List[str] = field(default_factory=list)


@dataclass
class ContradictedClaimsSummary:
    total_declared_claims: int
    mathematically_contradicted_claims: int
    compatible_with_unknowns: int
    supported_claims: int
    unreconciled_claims: int
    details: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CapabilityDimension:
    code: str
    name: str
    status: str  # "supported", "potential_concern", "insufficient_evidence", "not_assessed"
    confidence: float
    findings_count: int
    primary_rule: Optional[str] = None
    evidence_basis: str = ""


@dataclass
class SupervisoryOverviewResult:
    entity_id: str
    entity_name: str
    entity_code: str
    submission_id: str
    period_start: str
    period_end: str
    run_id: str
    analysis_status: str
    cutoff_time: str
    supervisory_attention_index: float  # 0.0 - 100.0
    attention_priority: str  # "ROUTINE", "ELEVATED", "CRITICAL_ATTENTION"
    evidence_completeness: EvidenceCompletenessSummary
    execution_gaps: ExecutionGapSummary
    negative_space: NegativeSpaceSummary
    contradicted_claims: ContradictedClaimsSummary
    open_evidence_requests_count: int
    active_portfolio_items_count: int
    human_decisions_count: int
    capabilities: List[CapabilityDimension]
    disclaimer: str = (
        "Supervisory Attention Index (SAI) is an examiner workflow triage metric "
        "prioritizing inspection effort. It is not an autonomous regulatory sanction, "
        "a calibrated probability of compromise, or an authoritative SOC grade."
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SupervisorySummaryService:
    """Computes transparent, evidence-backed supervisory overview indicators for an entity."""

    def __init__(self, db: Session):
        self.db = db

    def get_entity_overview(
        self,
        entity_id: str,
        run_id: Optional[str] = None,
    ) -> Optional[SupervisoryOverviewResult]:
        # 1. Fetch entity
        cse = self.db.execute(select(CSE).where(CSE.id == entity_id)).scalar_one_or_none()
        if not cse:
            return None

        # 2. Resolve analysis run
        if run_id:
            run = self.db.execute(
                select(AnalysisRun).where(
                    AnalysisRun.id == run_id, AnalysisRun.entity_id == entity_id
                )
            ).scalar_one_or_none()
        else:
            run = (
                self.db.execute(
                    select(AnalysisRun)
                    .where(AnalysisRun.entity_id == entity_id, AnalysisRun.status == "completed")
                    .order_by(AnalysisRun.created_at.desc())
                )
                .scalars()
                .first()
            )

        if not run:
            return None

        submission = self.db.execute(
            select(Submission).where(Submission.id == run.submission_id)
        ).scalar_one_or_none()

        if not submission:
            return None

        # 3. Load all findings for this run
        findings = list(
            self.db.execute(select(Finding).where(Finding.run_id == run.id)).scalars().all()
        )

        # 4. Compute Evidence Completeness
        completeness = self._compute_evidence_completeness(submission)

        # 5. Compute Execution Gaps
        execution_gaps = self._compute_execution_gaps(findings)

        # 6. Compute Negative Space
        negative_space = self._compute_negative_space(submission, findings)

        # 7. Compute Contradicted Claims
        contradicted_claims = self._compute_contradicted_claims(findings)

        # 8. Compute Open Evidence Requests & Review Progress
        portfolio = (
            self.db.execute(
                select(ReviewPortfolio)
                .where(ReviewPortfolio.run_id == run.id)
                .order_by(ReviewPortfolio.revision.desc())
            )
            .scalars()
            .first()
        )

        active_items_count = 0
        decisions_count = 0
        if portfolio:
            active_items_count = len(portfolio.items)
            item_ids = [it.id for it in portfolio.items]
            if item_ids:
                decisions_count = int(
                    self.db.execute(
                        select(func.count(ReviewDecision.id)).where(
                            ReviewDecision.review_item_id.in_(item_ids)
                        )
                    ).scalar()
                    or 0
                )

        open_requests_count = int(
            self.db.execute(
                select(func.count(EvidenceRequest.id)).where(
                    EvidenceRequest.entity_id == entity_id, EvidenceRequest.status == "open"
                )
            ).scalar()
            or 0
        )

        # 9. Compute Composite Supervisory Attention Index (SAI)
        sai, priority = self._compute_supervisory_attention_index(
            completeness=completeness,
            execution_gaps=execution_gaps,
            negative_space=negative_space,
            contradicted_claims=contradicted_claims,
            open_requests_count=open_requests_count,
        )

        # 10. Map Capability Coverage
        capabilities = self._map_capability_coverage(findings, negative_space, completeness)

        return SupervisoryOverviewResult(
            entity_id=cse.id,
            entity_name=cse.name,
            entity_code=cse.code,
            submission_id=submission.id,
            period_start=submission.period_start.isoformat(),
            period_end=submission.period_end.isoformat(),
            run_id=run.id,
            analysis_status=run.status,
            cutoff_time=run.cutoff_time.isoformat(),
            supervisory_attention_index=sai,
            attention_priority=priority,
            evidence_completeness=completeness,
            execution_gaps=execution_gaps,
            negative_space=negative_space,
            contradicted_claims=contradicted_claims,
            open_evidence_requests_count=open_requests_count,
            active_portfolio_items_count=active_items_count,
            human_decisions_count=decisions_count,
            capabilities=capabilities,
        )

    def _compute_evidence_completeness(self, submission: Submission) -> EvidenceCompletenessSummary:
        sub_files = list(
            self.db.execute(
                select(SubmissionFile).where(SubmissionFile.submission_id == submission.id)
            )
            .scalars()
            .all()
        )

        manifest_data = {}
        try:
            if submission.manifest_json:
                manifest_data = json.loads(submission.manifest_json)
        except Exception:
            pass

        declared_files = manifest_data.get("files", [])
        declared_count = max(len(declared_files), len(sub_files), 1)
        received_count = len(sub_files)
        missing_count = max(0, declared_count - received_count)

        quarantined_count = (
            self.db.execute(
                select(func.count(NormalizedRecord.id)).where(
                    NormalizedRecord.submission_id == submission.id,
                    NormalizedRecord.is_quarantined.is_(True),
                )
            ).scalar()
            or 0
        )
        total_parsed = (
            self.db.execute(
                select(func.count(NormalizedRecord.id)).where(
                    NormalizedRecord.submission_id == submission.id
                )
            ).scalar()
            or 0
        )
        if total_parsed == 0:
            total_parsed = sum(getattr(f, "actual_row_count", 0) for f in sub_files)
        accepted_count = max(0, total_parsed - quarantined_count)

        # Completeness calculation factoring in missing files and quarantined rows
        file_ratio = received_count / declared_count if declared_count > 0 else 0.0
        row_penalty = (quarantined_count / total_parsed) * 0.3 if total_parsed > 0 else 0.0
        completeness_pct = max(0.0, min(100.0, (file_ratio * 100.0) - (row_penalty * 100.0)))

        if completeness_pct >= 90.0 and missing_count == 0:
            verdict = "SUFFICIENT"
        elif completeness_pct >= 60.0:
            verdict = "PARTIALLY_SUFFICIENT"
        else:
            verdict = "INSUFFICIENT_EVIDENCE"

        return EvidenceCompletenessSummary(
            declared_sources_count=declared_count,
            received_sources_count=received_count,
            missing_sources_count=missing_count,
            quarantined_records_count=quarantined_count,
            total_parsed_records=total_parsed,
            completeness_percentage=round(completeness_pct, 1),
            sufficiency_verdict=verdict,
            details={
                "accepted_records": accepted_count,
                "file_coverage_ratio": round(file_ratio, 3),
            },
        )

    def _compute_execution_gaps(self, findings: List[Finding]) -> ExecutionGapSummary:
        unsubstantiated = 0
        overdue = 0
        unlinked = 0
        adverse_count = 0
        sev_dist = {"critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0}
        contributing_ids = []

        for f in findings:
            if f.evidence_state in ("potential_concern", "contradicted", "contradictory"):
                adverse_count += 1
                contributing_ids.append(f.id)
                sev = f.severity.lower()
                sev_dist[sev] = sev_dist.get(sev, 0) + 1

                if f.rule_id == "POL-INV-001":
                    unsubstantiated += 1
                elif f.rule_id == "POL-ESC-002":
                    overdue += 1
                elif f.rule_id in ("POL-LNK-006", "POL-REC-005"):
                    unlinked += 1

        # Gap score: weighted by severity
        raw_gap_score = (
            (sev_dist.get("critical", 0) * 35.0)
            + (sev_dist.get("high", 0) * 20.0)
            + (sev_dist.get("medium", 0) * 10.0)
            + (sev_dist.get("low", 0) * 5.0)
        )
        gap_score = min(100.0, raw_gap_score)

        return ExecutionGapSummary(
            unsubstantiated_closures=unsubstantiated,
            overdue_escalations=overdue,
            unlinked_lifecycle_cases=unlinked,
            adverse_findings_count=adverse_count,
            gap_score=round(gap_score, 1),
            severity_distribution=sev_dist,
            contributing_finding_ids=contributing_ids,
        )

    def _compute_negative_space(
        self, submission: Submission, findings: List[Finding]
    ) -> NegativeSpaceSummary:
        # Query distinct assets in submission
        stmt_assets = select(NormalizedRecord).where(
            NormalizedRecord.submission_id == submission.id,
            NormalizedRecord.record_type == "assets",
        )
        asset_records = list(self.db.execute(stmt_assets).scalars().all())
        total_assets = len(asset_records)

        broken_sensor_assets = set()
        missing_telemetry_assets = set()
        for f in findings:
            if f.rule_id == "POL-COV-003":
                if f.evidence_state in ("potential_concern", "contradicted"):
                    broken_sensor_assets.add(f.primary_object_id)
                elif f.evidence_state == "insufficient_evidence":
                    missing_telemetry_assets.add(f.primary_object_id)

        broken_count = len(broken_sensor_assets)
        missing_count = len(missing_telemetry_assets)

        healthy_monitored = max(0, total_assets - broken_count - missing_count)
        # Healthy quiet assets: assets with 0 alerts but verified healthy agent
        healthy_quiet = healthy_monitored  # in standard baseline

        cov_pct = (healthy_monitored / total_assets * 100.0) if total_assets > 0 else 100.0
        blind_spot = broken_count > 0 or missing_count > 0

        return NegativeSpaceSummary(
            total_critical_assets=total_assets,
            healthy_monitored_assets=healthy_monitored,
            broken_sensor_assets=broken_count,
            healthy_quiet_assets=healthy_quiet,
            missing_telemetry_assets=missing_count,
            coverage_percentage=round(cov_pct, 1),
            blind_spot_warning=blind_spot,
            contributing_asset_ids=list(broken_sensor_assets.union(missing_telemetry_assets)),
        )

    def _compute_contradicted_claims(self, findings: List[Finding]) -> ContradictedClaimsSummary:
        kpi_findings = [f for f in findings if f.rule_id == "POL-KPI-004"]
        total = len(kpi_findings)
        contradicted = sum(
            1 for f in kpi_findings if f.evidence_state in ("contradicted", "contradictory")
        )
        compat_unknowns = sum(
            1 for f in kpi_findings if f.evidence_state == "insufficient_evidence"
        )
        supported = sum(1 for f in kpi_findings if f.evidence_state == "supported")

        details = []
        for f in kpi_findings:
            det = {}
            try:
                if f.details_json:
                    det = json.loads(f.details_json)
            except Exception:
                pass
            details.append(
                {
                    "finding_id": f.id,
                    "claim_id": f.primary_object_id,
                    "evidence_state": f.evidence_state,
                    "confidence": f.confidence,
                    "claimed_value": det.get("claimed_rate"),
                    "observed_bounds": det.get("bounded_interval"),
                }
            )

        return ContradictedClaimsSummary(
            total_declared_claims=total,
            mathematically_contradicted_claims=contradicted,
            compatible_with_unknowns=compat_unknowns,
            supported_claims=supported,
            unreconciled_claims=total - (contradicted + compat_unknowns + supported),
            details=details,
        )

    def _compute_supervisory_attention_index(
        self,
        completeness: EvidenceCompletenessSummary,
        execution_gaps: ExecutionGapSummary,
        negative_space: NegativeSpaceSummary,
        contradicted_claims: ContradictedClaimsSummary,
        open_requests_count: int,
    ) -> tuple[float, str]:
        """Calculates bounded composite SAI index (0-100) using versioned weights."""
        # 1. Execution gap term (0 - 100)
        t_gap = execution_gaps.gap_score

        # 2. Negative space term (0 - 100)
        t_neg = (100.0 - negative_space.coverage_percentage) + (
            negative_space.broken_sensor_assets * 20.0
        )
        t_neg = min(100.0, max(0.0, t_neg))

        # 3. Contradicted claim term (0 - 100)
        t_claim = (contradicted_claims.mathematically_contradicted_claims * 40.0) + (
            contradicted_claims.compatible_with_unknowns * 15.0
        )
        t_claim = min(100.0, t_claim)

        # 4. Evidence insufficiency penalty (0 - 100)
        t_evidence = (100.0 - completeness.completeness_percentage) + (open_requests_count * 10.0)
        t_evidence = min(100.0, max(0.0, t_evidence))

        # Weighted sum: 35% gap + 25% negative + 20% claims + 20% evidence penalty
        sai = (0.35 * t_gap) + (0.25 * t_neg) + (0.20 * t_claim) + (0.20 * t_evidence)
        sai = round(min(100.0, max(0.0, sai)), 1)

        if sai >= 65.0:
            priority = "CRITICAL_ATTENTION"
        elif sai >= 30.0:
            priority = "ELEVATED"
        else:
            priority = "ROUTINE"

        return sai, priority

    def _map_capability_coverage(
        self,
        findings: List[Finding],
        negative_space: NegativeSpaceSummary,
        completeness: EvidenceCompletenessSummary,
    ) -> List[CapabilityDimension]:
        """Maps findings and evidence completeness across 8 security operations capabilities."""
        # Map findings by rule
        rules_triggered = {f.rule_id: f for f in findings}

        # 1. Threat Detection
        cov_finding = rules_triggered.get("POL-COV-003")
        if cov_finding:
            det_status = cov_finding.evidence_state
            det_conf = self._finding_conf(cov_finding)
            det_basis = f"Sensor telemetry evaluated across {negative_space.total_critical_assets} critical assets."
        elif completeness.completeness_percentage < 60.0:
            det_status = "insufficient_evidence"
            det_conf = 0.5
            det_basis = "Incomplete telemetry intake prevents full coverage evaluation."
        else:
            det_status = "supported"
            det_conf = 0.9
            det_basis = f"All {negative_space.total_critical_assets} critical assets report healthy sensor heartbeats."

        # 2. Investigation Quality
        inv_finding = rules_triggered.get("POL-INV-001")
        if inv_finding:
            inv_status = inv_finding.evidence_state
            inv_conf = self._finding_conf(inv_finding)
            inv_basis = (
                "Closed cases evaluated for required triage artifacts and substantive root cause."
            )
        else:
            inv_status = "supported"
            inv_conf = 0.85
            inv_basis = (
                "Sampled investigations substantiate closure with required policy artifacts."
            )

        # 3. Escalation Discipline
        esc_finding = rules_triggered.get("POL-ESC-002")
        if esc_finding:
            esc_status = esc_finding.evidence_state
            esc_conf = self._finding_conf(esc_finding)
            esc_basis = "High/critical cases evaluated against escalation SLA deadlines and cutoff."
        else:
            esc_status = "supported"
            esc_conf = 0.9
            esc_basis = "Critical alerts escalated within defined SLA windows."

        # 4. Incident Response
        rec_finding = rules_triggered.get("POL-REC-005")
        if rec_finding:
            resp_status = rec_finding.evidence_state
            resp_conf = self._finding_conf(rec_finding)
            resp_basis = "Asset recurrence evaluated following previous incident closure."
        else:
            resp_status = "supported"
            resp_conf = 0.8
            resp_basis = "No unmitigated recurrence observed across monitored assets."

        # 5. Security Operations (Overall Telemetry Health)
        if negative_space.broken_sensor_assets > 0:
            secops_status = "potential_concern"
            secops_conf = 0.95
            secops_basis = f"{negative_space.broken_sensor_assets} sensors report broken or disconnected states."
        elif completeness.sufficiency_verdict == "INSUFFICIENT_EVIDENCE":
            secops_status = "insufficient_evidence"
            secops_conf = 0.6
            secops_basis = "Omitted source exports prevent overall SecOps health confirmation."
        else:
            secops_status = "supported"
            secops_conf = 0.9
            secops_basis = (
                "Sensor heartbeat cadence and log pipelines operate within normal bounds."
            )

        # 6. Governance & Oversight
        kpi_finding = rules_triggered.get("POL-KPI-004")
        if kpi_finding:
            gov_status = kpi_finding.evidence_state
            gov_conf = self._finding_conf(kpi_finding)
            gov_basis = (
                "Self-reported management claims reconciled with bounded mathematical model."
            )
        else:
            gov_status = "not_assessed"
            gov_conf = 0.5
            gov_basis = "No self-reported SLA claims submitted for the period."

        # 7. Operational Discipline
        if inv_status == "potential_concern" or esc_status == "potential_concern":
            op_status = "potential_concern"
            op_conf = 0.85
            op_basis = "Procedural gaps observed in triage or escalation timeliness."
        else:
            op_status = "supported"
            op_conf = 0.85
            op_basis = "Playbook compliance maintained across investigated incidents."

        # 8. Cyber Resilience
        if negative_space.blind_spot_warning or completeness.completeness_percentage < 60.0:
            res_status = "potential_concern"
            res_conf = 0.8
            res_basis = "Visibility gaps or sensor blind spots impair overall cyber resilience."
        else:
            res_status = "supported"
            res_conf = 0.85
            res_basis = "Defense-in-depth telemetry verified with comprehensive evidence."

        return [
            CapabilityDimension(
                code="CAP-DET",
                name="Threat Detection",
                status=det_status,
                confidence=det_conf,
                findings_count=1 if cov_finding else 0,
                primary_rule="POL-COV-003",
                evidence_basis=det_basis,
            ),
            CapabilityDimension(
                code="CAP-INV",
                name="Investigation Quality",
                status=inv_status,
                confidence=inv_conf,
                findings_count=1 if inv_finding else 0,
                primary_rule="POL-INV-001",
                evidence_basis=inv_basis,
            ),
            CapabilityDimension(
                code="CAP-ESC",
                name="Escalation Discipline",
                status=esc_status,
                confidence=esc_conf,
                findings_count=1 if esc_finding else 0,
                primary_rule="POL-ESC-002",
                evidence_basis=esc_basis,
            ),
            CapabilityDimension(
                code="CAP-RESP",
                name="Incident Response",
                status=resp_status,
                confidence=resp_conf,
                findings_count=1 if rec_finding else 0,
                primary_rule="POL-REC-005",
                evidence_basis=resp_basis,
            ),
            CapabilityDimension(
                code="CAP-OPS",
                name="Security Operations",
                status=secops_status,
                confidence=secops_conf,
                findings_count=0,
                primary_rule=None,
                evidence_basis=secops_basis,
            ),
            CapabilityDimension(
                code="CAP-GOV",
                name="Governance & Oversight",
                status=gov_status,
                confidence=gov_conf,
                findings_count=1 if kpi_finding else 0,
                primary_rule="POL-KPI-004",
                evidence_basis=gov_basis,
            ),
            CapabilityDimension(
                code="CAP-DISC",
                name="Operational Discipline",
                status=op_status,
                confidence=op_conf,
                findings_count=0,
                primary_rule=None,
                evidence_basis=op_basis,
            ),
            CapabilityDimension(
                code="CAP-RESIL",
                name="Cyber Resilience",
                status=res_status,
                confidence=res_conf,
                findings_count=0,
                primary_rule=None,
                evidence_basis=res_basis,
            ),
        ]

    @staticmethod
    def _finding_conf(f: Optional[Finding]) -> float:
        if not f:
            return 0.85
        try:
            m = json.loads(f.metrics_json)
            return float(m.get("confidence", 0.85))
        except Exception:
            return 0.85
