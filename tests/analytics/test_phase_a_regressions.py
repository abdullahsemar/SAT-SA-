"""Phase A Acceptance Regressions for SAT-SA Evidence Semantics.

Covers all 16 required Phase A criteria:
1. No claims source declared -> POL-KPI-004 produces no finding.
2. Declared-but-missing claims source -> insufficient_evidence, preserves gap, no manufactured claim.
3. Non-numeric and out-of-range claim values -> rejected/quarantined during intake, not reconciled.
4. Valid out-of-scope claim -> explicit exclusion reason, not malformed, not compared.
5. Contradicted claim with complete outcomes -> contradictory (e.g. claim 99%, upper bound 50%).
6. Compatible claim with unknown outcomes -> insufficient_evidence (interval 50%-100%).
7. Incomplete or unknown eligible denominator -> insufficient_evidence, full rate not calculated.
8. Missing escalation source -> insufficient_evidence.
9. Incomplete / wrong-scope escalation evidence (e.g. only action logs) -> insufficient_evidence.
10. Complete evidence with genuinely overdue missing escalation -> potential_concern.
11. Future-due obligation at cutoff -> no adverse finding.
12. Timely escalation and valid exception -> no adverse finding.
13. root_cause only, missing required artifacts -> potential_concern.
14. Complete supported closure evidence -> no adverse finding.
15. Missing closure-artifact source -> insufficient_evidence.
16. Empty authoritative export: established completeness vs unknown completeness.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from db.models.evidence import NormalizedRecord, RawRecord, Submission, SubmissionFile
from packages.analytics.context import AssessmentContext
from packages.analytics.detectors import (
    EscalationEvidenceDetector,
    InvestigationEvidenceDetector,
    KPIReconciliationDetector,
)
from packages.analytics.obligations import ObligationEvaluator, PolicyException
from packages.analytics.reconstruction import EvidenceGraphReconstructor
from packages.ingestion.manifest import ManifestDeclaration
from packages.ingestion.quality import normalize_record


@pytest.fixture
def demo_policy():
    policy_path = (
        Path(__file__).resolve().parent.parent.parent / "config" / "policies" / "demo-v1.json"
    )
    with open(policy_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def rules_config():
    rules_path = (
        Path(__file__).resolve().parent.parent.parent / "config" / "detectors" / "rules-v1.json"
    )
    with open(rules_path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_submission(
    sub_id: str = "SUB-PHASE-A",
    entity_id: str = "CSE-BANK-01",
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-08-31T23:59:59Z",
    sources: list[dict[str, Any]] | None = None,
    files: list[SubmissionFile] | None = None,
) -> Submission:
    """Builds a test Submission with a valid manifest."""
    if sources is None:
        sources = [
            {
                "source_id": "src-cases",
                "record_type": "cases",
                "declared_row_count": 0,
                "export_scope": "Cases",
                "lineage": "SIEM",
                "sampling_method": "full_population",
            }
        ]
    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": entity_id,
        "period_start": period_start,
        "period_end": period_end,
        "source_timezone": "UTC",
        "sources": sources,
    }
    sub = Submission(
        id=sub_id,
        entity_id=entity_id,
        period_start=datetime.fromisoformat(period_start),
        period_end=datetime.fromisoformat(period_end),
        manifest_json=json.dumps(manifest),
        status="committed",
    )
    sub.files = files or []
    for file in sub.files:
        declared = next(source for source in sources if source["source_id"] == file.source_id)
        file.actual_row_count = declared["declared_row_count"]
        file.declared_row_count = declared["declared_row_count"]
    return sub


def create_record(
    sub_id: str,
    entity_id: str,
    record_type: str,
    source_id: str,
    native_id: str,
    data: dict[str, Any],
    row_num: int = 1,
) -> tuple[RawRecord, NormalizedRecord]:
    """Creates a linked RawRecord and NormalizedRecord pair."""
    if record_type == "reported_claims":
        data = {
            "period": "2026-08",
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-31T23:59:59Z",
            **data,
        }
    raw = RawRecord(
        id=f"RAW-{record_type.upper()}-{native_id}",
        submission_id=sub_id,
        source_id=source_id,
        record_type=record_type,
        row_locator=f"line_{row_num}",
        raw_payload=json.dumps(data),
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    norm = NormalizedRecord(
        id=f"NORM-{record_type.upper()}-{native_id}",
        raw_record_id=raw.id,
        submission_id=sub_id,
        entity_id=entity_id,
        source_id=source_id,
        record_type=record_type,
        native_id=native_id,
        normalized_data=json.dumps(data),
        is_quarantined=False,
    )
    return raw, norm


# =========================================================================
# 1. No claims source declared -> POL-KPI-004 produces no finding
# =========================================================================
def test_1_no_claims_source_declared(demo_policy, rules_config):
    sub = make_submission(
        sources=[
            {
                "source_id": "src-cases",
                "record_type": "cases",
                "declared_row_count": 0,
                "export_scope": "Cases",
                "lineage": "SIEM",
                "sampling_method": "full_population",
            }
        ]
    )
    ctx = AssessmentContext(sub, normalized_records=[], raw_records=[])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()
    assert findings == []


# =========================================================================
# 2. Declared-but-missing claims source -> insufficient_evidence
# =========================================================================
def test_2_declared_but_missing_claims_source(demo_policy, rules_config):
    sources = [
        {
            "source_id": "src-claims",
            "record_type": "reported_claims",
            "declared_row_count": 1,
            "export_scope": "SLA Claims Export",
            "lineage": "GRC System",
            "sampling_method": "full_population",
        }
    ]
    sub = make_submission(sources=sources)
    ctx = AssessmentContext(sub, normalized_records=[], raw_records=[])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "POL-KPI-004"
    assert f.evidence_state == "insufficient_evidence"
    assert f.primary_object_type == "source"
    assert f.primary_object_id == "src-claims"
    assert "no claim records were submitted" in f.rationale


# =========================================================================
# 3. Non-numeric and out-of-range claim values -> rejected/quarantined
# =========================================================================
def test_3_malformed_and_out_of_range_claim_values():
    manifest = ManifestDeclaration(
        manifest_version="1.0.0",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00Z"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59Z"),
        source_timezone="UTC",
        sources=[
            {
                "source_id": "src-claims",
                "record_type": "reported_claims",
                "declared_row_count": 1,
                "export_scope": "Claims",
                "lineage": "GRC",
                "sampling_method": "full_population",
            }
        ],
    )

    # Non-numeric
    norm, issues = normalize_record(
        record_type="reported_claims",
        raw_data={
            "native_id": "CLM-INVALID-1",
            "metric_name": "incident_sla_pct",
            "period": "2026-08",
            "metric_value": "NOT_A_NUM",
        },
        source_id="src-claims",
        row_locator="row_1",
        manifest=manifest,
    )
    assert norm is None
    assert any(i.issue_type == "INVALID_FIELD_TYPE" for i in issues)

    # Out of range (> 100)
    norm, issues = normalize_record(
        record_type="reported_claims",
        raw_data={
            "native_id": "CLM-INVALID-2",
            "metric_name": "incident_sla_pct",
            "period": "2026-08",
            "metric_value": 150.0,
        },
        source_id="src-claims",
        row_locator="row_2",
        manifest=manifest,
    )
    assert norm is None
    assert any(i.issue_type == "VALUE_OUT_OF_RANGE" for i in issues)


# =========================================================================
# 4. Valid out-of-scope claim -> explicit exclusion reason
# =========================================================================
def test_4_valid_out_of_scope_claim(demo_policy, rules_config):
    sources = [
        {
            "source_id": "src-claims",
            "record_type": "reported_claims",
            "declared_row_count": 1,
            "export_scope": "Claims",
            "lineage": "GRC",
            "sampling_method": "full_population",
        }
    ]
    sub = make_submission(entity_id="CSE-BANK-01", sources=sources)

    # Claim belongs to different entity
    raw, norm = create_record(
        sub_id="SUB-PHASE-A",
        entity_id="CSE-BANK-01",
        record_type="reported_claims",
        source_id="src-claims",
        native_id="CLM-OTHER-ENTITY",
        data={
            "metric_name": "incident_sla_pct",
            "metric_value": 98.0,
            "entity_id": "CSE-OTHER-02",
        },
    )
    ctx = AssessmentContext(sub, normalized_records=[norm], raw_records=[raw])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()

    # Out of scope claim is excluded, NOT compared, producing no finding
    assert findings == []
    assert len(ctx.excluded_claims) == 1
    assert ctx.excluded_claims[0]["reason"] == "out_of_scope_entity"


# =========================================================================
# 5. Contradicted claim with complete outcomes
# =========================================================================
def test_5_actual_contradicted_claim_with_complete_outcomes(demo_policy, rules_config):
    sources = [
        {
            "source_id": "src-claims",
            "record_type": "reported_claims",
            "declared_row_count": 1,
            "export_scope": "Claims",
            "lineage": "GRC",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 100,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
    ]
    files = [
        SubmissionFile(
            id="FILE-CLM",
            submission_id="SUB-PHASE-A",
            source_id="src-claims",
            original_filename="claims.json",
            record_type="reported_claims",
            byte_size=100,
            sha256_hash="hash-clm",
            declared_row_count=1,
            actual_row_count=1,
        ),
        SubmissionFile(
            id="FILE-CASES",
            submission_id="SUB-PHASE-A",
            source_id="src-cases",
            original_filename="cases.json",
            record_type="cases",
            byte_size=5000,
            sha256_hash="hash-cases",
            declared_row_count=100,
            actual_row_count=100,
        ),
    ]
    sub = make_submission(sources=sources, files=files)

    raws, norms = [], []
    r_clm, n_clm = create_record(
        sub.id,
        sub.entity_id,
        "reported_claims",
        "src-claims",
        "CLM-SLA-99",
        {"metric_name": "incident_sla_compliance", "metric_value": 99.0},
    )
    raws.append(r_clm)
    norms.append(n_clm)

    # 50 compliant cases (closed in 1 hr <= 4 hr SLA for HIGH)
    for i in range(50):
        r, n = create_record(
            sub.id,
            sub.entity_id,
            "cases",
            "src-cases",
            f"CASE-COMP-{i}",
            {
                "severity": "HIGH",
                "created_at": "2026-08-10T10:00:00Z",
                "closed_at": "2026-08-10T11:00:00Z",
            },
            row_num=i + 1,
        )
        raws.append(r)
        norms.append(n)

    # 50 non-compliant cases (closed in 26 hr > 12 hr SLA for HIGH)
    for i in range(50):
        r, n = create_record(
            sub.id,
            sub.entity_id,
            "cases",
            "src-cases",
            f"CASE-FAIL-{i}",
            {
                "severity": "HIGH",
                "created_at": "2026-08-10T10:00:00Z",
                "closed_at": "2026-08-11T12:00:00Z",
            },
            row_num=50 + i + 1,
        )
        raws.append(r)
        norms.append(n)

    ctx = AssessmentContext(sub, normalized_records=norms, raw_records=raws)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.evidence_state == "contradictory"
    assert f.severity == "high"
    assert f.extra_metadata["is_contradicted"] is True
    assert f.extra_metadata["upper_bound_pct"] == 50.0


# =========================================================================
# 6. Compatible claim with unknown outcomes
# =========================================================================
def test_6_compatible_claim_with_unknown_outcomes(demo_policy, rules_config):
    sources = [
        {
            "source_id": "src-claims",
            "record_type": "reported_claims",
            "declared_row_count": 1,
            "export_scope": "Claims",
            "lineage": "GRC",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 100,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
    ]
    files = [
        SubmissionFile(
            id="FILE-CLM",
            submission_id="SUB-PHASE-A",
            source_id="src-claims",
            original_filename="claims.json",
            record_type="reported_claims",
            byte_size=100,
            sha256_hash="hash-clm",
            declared_row_count=1,
            actual_row_count=1,
        ),
        SubmissionFile(
            id="FILE-CASES",
            submission_id="SUB-PHASE-A",
            source_id="src-cases",
            original_filename="cases.json",
            record_type="cases",
            byte_size=5000,
            sha256_hash="hash-cases",
            declared_row_count=100,
            actual_row_count=100,
        ),
    ]
    sub = make_submission(period_end="2026-08-31T23:59:59Z", sources=sources, files=files)

    raws, norms = [], []
    r_clm, n_clm = create_record(
        sub.id,
        sub.entity_id,
        "reported_claims",
        "src-claims",
        "CLM-SLA-99",
        {"metric_name": "incident_sla_compliance", "metric_value": 99.0},
    )
    raws.append(r_clm)
    norms.append(n_clm)

    # 50 compliant cases
    for i in range(50):
        r, n = create_record(
            sub.id,
            sub.entity_id,
            "cases",
            "src-cases",
            f"CASE-COMP-{i}",
            {
                "severity": "HIGH",
                "created_at": "2026-08-10T10:00:00Z",
                "closed_at": "2026-08-10T11:00:00Z",
            },
            row_num=i + 1,
        )
        raws.append(r)
        norms.append(n)

    # 50 open cases created 1 hour before cutoff (not yet due at cutoff -> unknown outcome)
    for i in range(50):
        r, n = create_record(
            sub.id,
            sub.entity_id,
            "cases",
            "src-cases",
            f"CASE-OPEN-{i}",
            {
                "severity": "HIGH",
                "created_at": "2026-08-31T23:00:00Z",  # due at +4h, well after cutoff
                "closed_at": None,
            },
            row_num=50 + i + 1,
        )
        raws.append(r)
        norms.append(n)

    ctx = AssessmentContext(sub, normalized_records=norms, raw_records=raws)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.evidence_state == "insufficient_evidence"
    assert f.extra_metadata["is_contradicted"] is False
    assert f.extra_metadata["lower_bound_pct"] == 50.0
    assert f.extra_metadata["upper_bound_pct"] == 100.0


# =========================================================================
# 7. Incomplete or unknown eligible denominator
# =========================================================================
def test_7_incomplete_or_unknown_eligible_denominator(demo_policy, rules_config):
    # Manifest states sampling method is 'sample' rather than 'full_population'
    sources = [
        {
            "source_id": "src-claims",
            "record_type": "reported_claims",
            "declared_row_count": 1,
            "export_scope": "Claims",
            "lineage": "GRC",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 10,
            "export_scope": "Sample cases",
            "lineage": "SIEM",
            "sampling_method": "random_sample",
        },
    ]
    sub = make_submission(sources=sources)

    raws, norms = [], []
    r_clm, n_clm = create_record(
        sub.id,
        sub.entity_id,
        "reported_claims",
        "src-claims",
        "CLM-SLA-90",
        {"metric_name": "incident_sla_compliance", "metric_value": 90.0},
    )
    raws.append(r_clm)
    norms.append(n_clm)

    r_c, n_c = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-01",
        {
            "severity": "HIGH",
            "created_at": "2026-08-10T10:00:00Z",
            "closed_at": "2026-08-10T11:00:00Z",
        },
    )
    raws.append(r_c)
    norms.append(n_c)

    ctx = AssessmentContext(sub, normalized_records=norms, raw_records=raws)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.evidence_state == "insufficient_evidence"
    assert "incomplete or unknown" in f.rationale


# =========================================================================
# 8. Missing escalation source -> insufficient_evidence
# =========================================================================
def test_8_missing_escalation_source(demo_policy, rules_config):
    # Only cases declared, no escalation source declared
    sources = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        }
    ]
    sub = make_submission(sources=sources)
    # Critical case created early in period, still open at cutoff (overdue for escalation)
    r_c, n_c = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-CRIT-OVERDUE",
        {"severity": "CRITICAL", "created_at": "2026-08-05T10:00:00Z", "closed_at": None},
    )
    ctx = AssessmentContext(sub, normalized_records=[n_c], raw_records=[r_c])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.primary_object_id == "CASE-CRIT-OVERDUE"
    assert f.evidence_state == "insufficient_evidence"
    assert "authoritative escalation" in f.rationale.lower()


# =========================================================================
# 9. Uploaded but incomplete / wrong-scope escalation evidence
# =========================================================================
def test_9_uploaded_but_incomplete_wrong_scope_escalation_evidence(demo_policy, rules_config):
    # Declares actions source, but not escalations source
    sources = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-actions",
            "record_type": "investigation_actions",
            "declared_row_count": 1,
            "export_scope": "Actions",
            "lineage": "SOAR",
            "sampling_method": "full_population",
        },
    ]
    sub = make_submission(sources=sources)
    r_c, n_c = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-CRIT-01",
        {"severity": "CRITICAL", "created_at": "2026-08-05T10:00:00Z", "closed_at": None},
    )
    r_a, n_a = create_record(
        sub.id,
        sub.entity_id,
        "investigation_actions",
        "src-actions",
        "ACT-01",
        {
            "case_id": "CASE-CRIT-01",
            "action_type": "ANALYSIS_COMMENT",
            "details": {"comment": "Investigating"},
        },
    )
    ctx = AssessmentContext(sub, normalized_records=[n_c, n_a], raw_records=[r_c, r_a])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 1
    assert findings[0].evidence_state == "insufficient_evidence"


# =========================================================================
# 10. Complete evidence with genuinely overdue missing escalation
# =========================================================================
def test_10_complete_evidence_with_genuinely_overdue_missing_escalation(demo_policy, rules_config):
    # Authoritative escalation source declared and submitted with verified completeness
    sources = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-esc",
            "record_type": "escalations",
            "declared_row_count": 1,
            "export_scope": "Escalations Log",
            "lineage": "PagerDuty",
            "sampling_method": "full_population",
        },
    ]
    sub_file = SubmissionFile(
        id="FILE-ESC",
        submission_id="SUB-PHASE-A",
        source_id="src-esc",
        original_filename="escalations.csv",
        record_type="escalations",
        byte_size=100,
        sha256_hash="abc",
    )
    sub = make_submission(sources=sources, files=[sub_file])

    r_c, n_c = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-OVERDUE-01",
        {"severity": "CRITICAL", "created_at": "2026-08-05T10:00:00Z", "closed_at": None},
    )
    # An escalation for an unrelated case exists in the log
    r_e, n_e = create_record(
        sub.id,
        sub.entity_id,
        "escalations",
        "src-esc",
        "ESC-99",
        {"case_id": "CASE-OTHER", "escalated_at": "2026-08-05T11:00:00Z", "tier": "TIER_3"},
    )

    ctx = AssessmentContext(sub, normalized_records=[n_c, n_e], raw_records=[r_c, r_e])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.primary_object_id == "CASE-OVERDUE-01"
    assert f.evidence_state == "potential_concern"


# =========================================================================
# 11. Future-due obligation at cutoff -> no adverse finding
# =========================================================================
def test_11_future_due_obligation_at_cutoff(demo_policy, rules_config):
    # Case created 1 hour before cutoff. Escalation SLA for CRITICAL is 2 hours.
    # Therefore deadline is 1 hour after cutoff!
    sources = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-esc",
            "record_type": "escalations",
            "declared_row_count": 0,
            "export_scope": "Escalations Log",
            "lineage": "PagerDuty",
            "sampling_method": "full_population",
        },
    ]
    sub_file = SubmissionFile(
        id="FILE-ESC",
        submission_id="SUB-PHASE-A",
        source_id="src-esc",
        original_filename="escalations.csv",
        record_type="escalations",
        byte_size=0,
        sha256_hash="abc",
    )
    sub = make_submission(period_end="2026-08-31T23:59:59Z", sources=sources, files=[sub_file])

    r_c, n_c = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-FUTURE-DUE",
        {"severity": "CRITICAL", "created_at": "2026-08-31T23:45:00Z", "closed_at": None},
    )
    ctx = AssessmentContext(sub, normalized_records=[n_c], raw_records=[r_c])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()
    assert findings == []


# =========================================================================
# 12. Timely escalation and valid exception -> no adverse finding
# =========================================================================
def test_12_timely_escalation_and_valid_exception(demo_policy, rules_config):
    demo_policy["exceptions"] = [
        {
            "exception_id": "EXC-2026-01",
            "rule_id": "*",
            "target_type": "*",
            "target_id": "CASE-EXCUSED",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": "2026-12-31T23:59:59Z",
            "approved_by": "CISO",
            "reason": "Policy exception approved by CISO",
        }
    ]
    sources = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 2,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-esc",
            "record_type": "escalations",
            "declared_row_count": 1,
            "export_scope": "Escalations Log",
            "lineage": "PagerDuty",
            "sampling_method": "full_population",
        },
    ]
    sub_file = SubmissionFile(
        id="FILE-ESC",
        submission_id="SUB-PHASE-A",
        source_id="src-esc",
        original_filename="escalations.csv",
        record_type="escalations",
        byte_size=100,
        sha256_hash="abc",
    )
    sub = make_submission(sources=sources, files=[sub_file])

    # Case A: Timely escalation (created 10:00, escalated 10:15, SLA is 30 mins)
    r_ca, n_ca = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-TIMELY",
        {"severity": "CRITICAL", "created_at": "2026-08-10T10:00:00Z", "closed_at": None},
    )
    r_e, n_e = create_record(
        sub.id,
        sub.entity_id,
        "escalations",
        "src-esc",
        "ESC-TIMELY",
        {"case_id": "CASE-TIMELY", "escalated_at": "2026-08-10T10:15:00Z", "tier": "TIER_3"},
    )

    # Case B: Approved exception recorded in notes and policy
    r_cb, n_cb = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-EXCUSED",
        {
            "severity": "CRITICAL",
            "created_at": "2026-08-10T10:00:00Z",
            "closed_at": None,
            "disposition": "Policy exception approved by CISO ref #EXC-2026-01",
        },
    )

    ctx = AssessmentContext(
        sub, normalized_records=[n_ca, n_cb, n_e], raw_records=[r_ca, r_cb, r_e]
    )
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()
    assert findings == []


def test_policy_exception_evaluations(demo_policy):
    """Verifies missing, expired, future, wrong-target, and wrong-rule policy exceptions."""
    evaluator = ObligationEvaluator(demo_policy)
    event_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Missing exception
    assert (
        evaluator.match_exception(
            rule_id="POL-ESC-002",
            target_type="case",
            target_id="CASE-UNKNOWN",
            event_time=event_time,
        )
        is None
    )

    evaluator.policy.exceptions = [
        PolicyException(
            exception_id="EXC-EXPIRED",
            rule_id="POL-ESC-002",
            target_type="case",
            target_id="CASE-EXPIRED",
            valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            valid_to=datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
            approved_by="CISO",
            reason="Expired exception",
        ),
        PolicyException(
            exception_id="EXC-FUTURE",
            rule_id="POL-ESC-002",
            target_type="case",
            target_id="CASE-FUTURE",
            valid_from=datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
            valid_to=datetime(2026, 12, 31, 0, 0, 0, tzinfo=timezone.utc),
            approved_by="CISO",
            reason="Future exception",
        ),
        PolicyException(
            exception_id="EXC-WRONG-TARGET",
            rule_id="POL-ESC-002",
            target_type="case",
            target_id="CASE-OTHER",
            valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            valid_to=datetime(2026, 12, 31, 0, 0, 0, tzinfo=timezone.utc),
            approved_by="CISO",
            reason="Wrong target exception",
        ),
        PolicyException(
            exception_id="EXC-WRONG-RULE",
            rule_id="POL-INV-001",
            target_type="case",
            target_id="CASE-ACTIVE",
            valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            valid_to=datetime(2026, 12, 31, 0, 0, 0, tzinfo=timezone.utc),
            approved_by="CISO",
            reason="Wrong rule exception",
        ),
        PolicyException(
            exception_id="EXC-VALID",
            rule_id="POL-ESC-002",
            target_type="case",
            target_id="CASE-ACTIVE",
            valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            valid_to=datetime(2026, 12, 31, 0, 0, 0, tzinfo=timezone.utc),
            approved_by="CISO",
            reason="Valid active exception",
            remediation_owner="Infrastructure Team",
        ),
    ]

    # 2. Expired exception does not match
    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-EXPIRED", event_time) is None

    # 3. Future exception does not match
    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-FUTURE", event_time) is None

    # 4. Wrong target exception does not match
    assert (
        evaluator.match_exception("POL-ESC-002", "case", "CASE-ACTIVE-DIFFERENT", event_time)
        is None
    )

    # 5. Wrong rule exception does not match
    assert evaluator.match_exception("POL-ESC-999", "case", "CASE-ACTIVE", event_time) is None

    # 6. Valid exception matches and preserves remediation_owner
    matched = evaluator.match_exception("POL-ESC-002", "case", "CASE-ACTIVE", event_time)
    assert matched is not None
    assert matched.exception_id == "EXC-VALID"
    assert matched.remediation_owner == "Infrastructure Team"

    # 7. Submitted exception ingestion: ignores unapproved or missing provenance
    evaluator.add_submitted_exceptions(
        [
            {
                "native_id": "EXC-UNAPPROVED",
                "status": "PENDING",
                "affected_scope": "case:CASE-PENDING",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": "2026-12-31T23:59:59Z",
                "approved_by": "CISO",
                "reason": "Pending exception",
                "_source_ref": {"source_id": "src-exc"},
            },
            {
                "native_id": "EXC-NO-SOURCE",
                "status": "APPROVED",
                "affected_scope": "case:CASE-NO-SOURCE",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": "2026-12-31T23:59:59Z",
                "approved_by": "CISO",
                "reason": "Unprovenanced exception",
            },
            {
                "native_id": "EXC-SUBMITTED-VALID",
                "status": "APPROVED",
                "policy_reference": "POL-ESC-002",
                "affected_scope": "case:CASE-SUBMITTED",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": "2026-12-31T23:59:59Z",
                "approved_by": "CISO",
                "reason": "Approved external dependency exception",
                "remediation_owner": "Vendor SecOps",
                "_source_ref": {"source_id": "src-exc", "row_locator": "1"},
            },
        ]
    )
    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-PENDING", event_time) is None
    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-NO-SOURCE", event_time) is None
    sub_matched = evaluator.match_exception("POL-ESC-002", "case", "CASE-SUBMITTED", event_time)
    assert sub_matched is not None
    assert sub_matched.exception_id == "EXC-SUBMITTED-VALID"
    assert sub_matched.remediation_owner == "Vendor SecOps"


# =========================================================================
# 13. root_cause only, missing required artifacts -> potential_concern
# =========================================================================
def test_13_root_cause_only_with_missing_required_artifacts(demo_policy, rules_config):
    # Policy requires HOST_ISOLATION and FORENSIC_TRIAGE with artifact hash for CRITICAL
    sources = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-actions",
            "record_type": "investigation_actions",
            "declared_row_count": 1,
            "export_scope": "Actions",
            "lineage": "SOAR",
            "sampling_method": "full_population",
        },
    ]
    files = [
        SubmissionFile(
            id="FILE-CASES",
            submission_id="SUB-PHASE-A",
            source_id="src-cases",
            original_filename="cases.json",
            record_type="cases",
            byte_size=100,
            sha256_hash="hash-cases",
            declared_row_count=1,
            actual_row_count=1,
        ),
        SubmissionFile(
            id="FILE-ACTIONS",
            submission_id="SUB-PHASE-A",
            source_id="src-actions",
            original_filename="actions.json",
            record_type="investigation_actions",
            byte_size=100,
            sha256_hash="hash-actions",
            declared_row_count=1,
            actual_row_count=1,
        ),
    ]
    sub = make_submission(sources=sources, files=files)

    # Case has root_cause text, but actions missing artifact_hash
    r_c, n_c = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-RC-ONLY",
        {
            "severity": "CRITICAL",
            "created_at": "2026-08-10T10:00:00Z",
            "closed_at": "2026-08-10T10:05:00Z",
            "root_cause": "Phishing credential theft led to lateral movement",
        },
    )
    # Action exists but is generic and missing forensic triage / isolation artifact hash
    r_a, n_a = create_record(
        sub.id,
        sub.entity_id,
        "investigation_actions",
        "src-actions",
        "ACT-01",
        {"case_id": "CASE-RC-ONLY", "action_type": "NOTE", "timestamp": "2026-08-10T10:02:00Z"},
    )

    ctx = AssessmentContext(sub, normalized_records=[n_c, n_a], raw_records=[r_c, r_a])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = InvestigationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["investigation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.primary_object_id == "CASE-RC-ONLY"
    assert f.evidence_state == "potential_concern"
    assert "other policy-required closure artifacts are absent" in f.rationale


# =========================================================================
# 14. Complete supported closure evidence -> no adverse finding
# =========================================================================
def test_14_complete_supported_closure_evidence(demo_policy, rules_config):
    sources = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-actions",
            "record_type": "investigation_actions",
            "declared_row_count": 2,
            "export_scope": "Actions",
            "lineage": "SOAR",
            "sampling_method": "full_population",
        },
    ]
    sub = make_submission(sources=sources)

    r_c, n_c = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-SUPPORTED-CLOSURE",
        {
            "severity": "CRITICAL",
            "created_at": "2026-08-10T10:00:00Z",
            "closed_at": "2026-08-10T11:00:00Z",
            "root_cause": "Malware command and control beaconing detected and mitigated",
        },
    )
    r_a1, n_a1 = create_record(
        sub.id,
        sub.entity_id,
        "investigation_actions",
        "src-actions",
        "ACT-ISO",
        {
            "case_id": "CASE-SUPPORTED-CLOSURE",
            "action_type": "HOST_ISOLATION",
            "timestamp": "2026-08-10T10:15:00Z",
            "artifact_hash": "a1b2c3d4e5f607182930415263748596a1b2c3d4e5f607182930415263748596",
        },
    )
    r_a2, n_a2 = create_record(
        sub.id,
        sub.entity_id,
        "investigation_actions",
        "src-actions",
        "ACT-TRIAGE",
        {
            "case_id": "CASE-SUPPORTED-CLOSURE",
            "action_type": "FORENSIC_TRIAGE",
            "timestamp": "2026-08-10T10:30:00Z",
            "artifact_hash": "b2c3d4e5f607182930415263748596a1b2c3d4e5f607182930415263748596a1",
        },
    )

    ctx = AssessmentContext(
        sub, normalized_records=[n_c, n_a1, n_a2], raw_records=[r_c, r_a1, r_a2]
    )
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = InvestigationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["investigation_evidence"]
    )
    findings = detector.run()
    assert findings == []


# =========================================================================
# 15. Missing closure-artifact source -> insufficient_evidence
# =========================================================================
def test_15_missing_closure_artifact_source(demo_policy, rules_config):
    # Only cases table submitted; actions/artifact source missing
    sources = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        }
    ]
    sub = make_submission(sources=sources)
    r_c, n_c = create_record(
        sub.id,
        sub.entity_id,
        "cases",
        "src-cases",
        "CASE-FAST-NO-ACTIONS",
        {
            "severity": "CRITICAL",
            "created_at": "2026-08-10T10:00:00Z",
            "closed_at": "2026-08-10T10:02:00Z",
            "root_cause": "UNKNOWN",
        },
    )
    ctx = AssessmentContext(sub, normalized_records=[n_c], raw_records=[r_c])
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = InvestigationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["investigation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.evidence_state == "insufficient_evidence"
    assert "action logs are missing or incomplete" in f.rationale


# =========================================================================
# 16. Empty authoritative export: established vs unknown completeness
# =========================================================================
def test_16_empty_authoritative_export_completeness(demo_policy, rules_config):
    # Sub-case A: Established completeness (declared_row_count = 0, full_population, submitted file present)
    sources_a = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-esc",
            "record_type": "escalations",
            "declared_row_count": 0,
            "export_scope": "Escalations export",
            "lineage": "PagerDuty",
            "sampling_method": "full_population",
        },
    ]
    sub_file_a = SubmissionFile(
        id="FILE-ESC-A",
        submission_id="SUB-A",
        source_id="src-esc",
        original_filename="escalations.csv",
        record_type="escalations",
        byte_size=0,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    sub_a = make_submission(sub_id="SUB-A", sources=sources_a, files=[sub_file_a])
    r_ca, n_ca = create_record(
        sub_a.id,
        sub_a.entity_id,
        "cases",
        "src-cases",
        "CASE-OVERDUE-A",
        {"severity": "CRITICAL", "created_at": "2026-08-05T10:00:00Z", "closed_at": None},
    )
    ctx_a = AssessmentContext(sub_a, normalized_records=[n_ca], raw_records=[r_ca])
    graph_a = EvidenceGraphReconstructor(ctx_a)
    evaluator = ObligationEvaluator(demo_policy)
    det_a = EscalationEvidenceDetector(
        ctx_a, graph_a, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings_a = det_a.run()

    # Established completeness + overdue case + 0 escalations -> potential_concern
    assert len(findings_a) == 1
    assert findings_a[0].evidence_state == "potential_concern"

    # Sub-case B: Declared row count is 10, but 0 records present (completeness NOT established)
    sources_b = [
        {
            "source_id": "src-cases",
            "record_type": "cases",
            "declared_row_count": 1,
            "export_scope": "Cases",
            "lineage": "SIEM",
            "sampling_method": "full_population",
        },
        {
            "source_id": "src-esc",
            "record_type": "escalations",
            "declared_row_count": 10,
            "export_scope": "Escalations export",
            "lineage": "PagerDuty",
            "sampling_method": "full_population",
        },
    ]
    sub_file_b = SubmissionFile(
        id="FILE-ESC-B",
        submission_id="SUB-B",
        source_id="src-esc",
        original_filename="escalations.csv",
        record_type="escalations",
        byte_size=0,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    sub_b = make_submission(sub_id="SUB-B", sources=sources_b, files=[sub_file_b])
    r_cb, n_cb = create_record(
        sub_b.id,
        sub_b.entity_id,
        "cases",
        "src-cases",
        "CASE-OVERDUE-B",
        {"severity": "CRITICAL", "created_at": "2026-08-05T10:00:00Z", "closed_at": None},
    )
    ctx_b = AssessmentContext(sub_b, normalized_records=[n_cb], raw_records=[r_cb])
    graph_b = EvidenceGraphReconstructor(ctx_b)
    det_b = EscalationEvidenceDetector(
        ctx_b, graph_b, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings_b = det_b.run()

    # Completeness unknown -> insufficient_evidence
    assert len(findings_b) == 1
    assert findings_b[0].evidence_state == "insufficient_evidence"
