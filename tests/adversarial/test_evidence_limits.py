"""Adversarial and boundary tests for supervisory evidence assessment.

Verifies:
- Attempting analysis on uncommitted/draft submissions fails (HTTP 409 / SubmissionNotCommittedError).
- Cross-tenant / wrong-entity access is rejected (HTTP 403).
- Deterministic replayability (identical input hash and finding counts).
- Missing files and empty tables yield 'insufficient_evidence', never silent crashes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db.models.evidence import Submission, SubmissionFile
from packages.analytics.service import AnalysisService
from tests.conftest import authenticate_user
from tests.scenario_adapter import attach_scenario


@pytest.fixture
def assessment_scenario():
    scenario_path = (
        Path(__file__).resolve().parent.parent.parent
        / "synthetic"
        / "scenarios"
        / "assessment.json"
    )
    with open(scenario_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_uncommitted_submission_rejected(
    client: TestClient, db_session: Session, bank_examiner, assessment_scenario
):
    """Verifies that running an analysis on a draft/uncommitted submission returns 409 Conflict."""
    draft_sub = Submission(
        id="SUB-DRAFT-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="draft",
    )
    attach_scenario(draft_sub, assessment_scenario)
    db_session.add(draft_sub)
    db_session.commit()

    headers = authenticate_user(client, bank_examiner, db_session)

    response = client.post(
        "/api/v1/analysis-runs",
        headers=headers,
        json={"submission_id": "SUB-DRAFT-01"},
    )
    assert response.status_code == 409
    data = response.json()
    assert "Only 'committed' submissions can be analyzed" in data["message"]


def test_cross_tenant_scope_forbidden(
    client: TestClient, db_session: Session, fintech_examiner, assessment_scenario
):
    """Verifies that an examiner with scope for CSE-FINTECH-02 cannot analyze CSE-BANK-01 submissions."""
    sub = Submission(
        id="SUB-COMMITTED-BANK-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, assessment_scenario)
    db_session.add(sub)
    db_session.commit()

    # fintech_examiner only has scope for CSE-FINTECH-02
    headers = authenticate_user(client, fintech_examiner, db_session)

    response = client.post(
        "/api/v1/analysis-runs",
        headers=headers,
        json={"submission_id": "SUB-COMMITTED-BANK-01"},
    )
    assert response.status_code == 403
    data = response.json()
    assert "Access denied" in data["message"]


def test_deterministic_replayability(db_session: Session, assessment_scenario):
    """Verifies that running assessment twice on the same committed data produces identical findings and hash."""
    sub = Submission(
        id="SUB-REPLAY-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, assessment_scenario)
    db_session.add(sub)
    db_session.commit()

    service = AnalysisService(db_session)
    run_1 = service.run_assessment("SUB-REPLAY-01", "CSE-BANK-01")
    findings_1 = service.list_findings(run_id=run_1.run_id)

    run_2 = service.run_assessment("SUB-REPLAY-01", "CSE-BANK-01")
    findings_2 = service.list_findings(run_id=run_2.run_id)

    assert run_1.input_hash == run_2.input_hash
    assert len(findings_1) == len(findings_2)

    states_1 = sorted([f.rule_id + ":" + f.evidence_state for f in findings_1])
    states_2 = sorted([f.rule_id + ":" + f.evidence_state for f in findings_2])
    assert states_1 == states_2


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


def test_missing_claims_source_never_invents_claim(demo_policy, rules_config):
    """Verifies that a submission with no claims table never invents a claim (e.g. SELF-REPORTED-SLA=98.0%)."""
    from packages.analytics.context import AssessmentContext
    from packages.analytics.detectors import KPIReconciliationDetector
    from packages.analytics.obligations import ObligationEvaluator
    from packages.analytics.reconstruction import EvidenceGraphReconstructor

    scenario_no_claims = {
        "cases": [
            {
                "case_id": "CAS-101",
                "severity": "HIGH",
                "created_at": "2026-08-05T10:00:00Z",
                "closed_at": "2026-08-05T11:00:00Z",
                "status": "CLOSED",
                "root_cause": "Normal resolution",
            }
        ],
        "assets": [{"asset_id": "AST-01", "criticality": "HIGH"}],
    }

    sub = Submission(
        id="SUB-NO-CLAIMS",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario_no_claims)

    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()

    # Must be empty; never invent an SLA claim or declare contradiction
    assert len(findings) == 0


def test_malformed_claim_does_not_produce_attributed_claim_or_adverse_contradiction(
    demo_policy, rules_config
):
    """Verifies that non-numeric or invalid claimed values do not produce an attributed finding."""
    from packages.analytics.context import AssessmentContext
    from packages.analytics.detectors import KPIReconciliationDetector
    from packages.analytics.obligations import ObligationEvaluator
    from packages.analytics.reconstruction import EvidenceGraphReconstructor

    scenario_malformed = {
        "claims": [
            {
                "claim_id": "CLM-MALFORMED",
                "claim_type": "sla_compliance",
                "metric_name": "incident_sla_compliance_pct",
                "claimed_value": "NOT_A_NUMBER",
            },
            {
                "claim_id": "CLM-OUT-OF-BOUNDS",
                "claim_type": "sla_compliance",
                "metric_name": "incident_sla_compliance_pct",
                "claimed_value": 150.0,
            },
        ],
        "cases": [
            {
                "case_id": "CAS-101",
                "severity": "HIGH",
                "created_at": "2026-08-05T10:00:00Z",
                "closed_at": "2026-08-06T11:00:00Z",
                "status": "CLOSED",
            }
        ],
    }

    sub = Submission(
        id="SUB-MALFORMED-CLAIM",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario_malformed)

    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()

    assert len(findings) == 0


def test_real_claim_with_contradiction_retains_source_citations(demo_policy, rules_config):
    """Verifies that a valid, actually submitted claim that fails SLA retains real source citations."""
    from packages.analytics.context import AssessmentContext
    from packages.analytics.detectors import KPIReconciliationDetector
    from packages.analytics.obligations import ObligationEvaluator
    from packages.analytics.reconstruction import EvidenceGraphReconstructor

    scenario_real_claim = {
        "claims": [
            {
                "claim_id": "CLM-REAL-01",
                "claim_type": "sla_compliance",
                "metric_name": "incident_sla_compliance_pct",
                "claimed_value": 99.0,
                "period_start": "2026-08-01T00:00:00Z",
                "period_end": "2026-08-31T23:59:59Z",
            }
        ],
        "cases": [
            {
                "case_id": "CAS-COMPLIANT",
                "severity": "HIGH",
                "created_at": "2026-08-05T10:00:00Z",
                "closed_at": "2026-08-05T11:00:00Z",
                "status": "CLOSED",
            },
            {
                "case_id": "CAS-NONCOMPLIANT",
                "severity": "HIGH",
                "created_at": "2026-08-10T10:00:00Z",
                "closed_at": "2026-08-11T12:00:00Z",  # 26h > 12h SLA
                "status": "CLOSED",
            },
        ],
    }

    sub = Submission(
        id="SUB-REAL-CLAIM",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario_real_claim)

    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = KPIReconciliationDetector(
        ctx, graph, evaluator, rules_config["families"]["kpi_reconciliation"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.primary_object_id == "CLM-REAL-01"
    assert f.evidence_state == "contradictory"
    assert len([r for r in f.supporting_records if r["record_type"] == "reported_claims"]) == 1
    assert f.supporting_records[0]["native_id"] == "CLM-REAL-01"


def test_missing_actions_source_suspends_verdict_as_insufficient_evidence(
    demo_policy, rules_config
):
    """Verifies that an unescalated case without actions source produces insufficient_evidence, not verified failure."""
    from packages.analytics.context import AssessmentContext
    from packages.analytics.detectors import EscalationEvidenceDetector
    from packages.analytics.obligations import ObligationEvaluator
    from packages.analytics.reconstruction import EvidenceGraphReconstructor

    scenario_no_actions = {
        "cases": [
            {
                "case_id": "CAS-501",
                "severity": "HIGH",
                "status": "CLOSED",
                "created_at": "2026-08-05T08:30:00Z",
                "closed_at": "2026-08-06T10:00:00Z",
                "root_cause": "Credential stuffing attack neutralized",
            }
        ]
    }

    sub = Submission(
        id="SUB-NO-ACTIONS",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario_no_actions)

    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.primary_object_id == "CAS-501"
    assert f.evidence_state == "insufficient_evidence"
    assert "supervisory verdict suspended" in f.uncertainty_note.lower()
    assert "verified missing from action log" not in f.uncertainty_note.lower()


def test_unrelated_actions_log_alone_yields_insufficient_evidence_for_escalation(
    demo_policy, rules_config
):
    """Verifies that an unrelated investigation-action log cannot establish escalation completeness.
    Per A3: Do not call an escalation 'verified missing' when only an unrelated
    investigation-action log was submitted -> yields insufficient_evidence.
    """
    from packages.analytics.context import AssessmentContext
    from packages.analytics.detectors import EscalationEvidenceDetector
    from packages.analytics.obligations import ObligationEvaluator
    from packages.analytics.reconstruction import EvidenceGraphReconstructor

    scenario_with_unrelated_actions = {
        "cases": [
            {
                "case_id": "CAS-OVERDUE",
                "severity": "HIGH",
                "status": "OPEN",
                "created_at": "2026-08-05T08:30:00Z",
            }
        ],
        "actions": [
            {
                "action_id": "ACT-TRIAGE-01",
                "case_id": "CAS-OVERDUE",
                "action_type": "triage_notes",
                "created_at": "2026-08-05T09:00:00Z",
            }
        ],
    }

    sub = Submission(
        id="SUB-WITH-ACTIONS",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario_with_unrelated_actions)

    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.primary_object_id == "CAS-OVERDUE"
    # Unrelated actions log alone cannot prove absence -> insufficient_evidence
    assert f.evidence_state == "insufficient_evidence"


def test_genuinely_overdue_case_with_complete_escalation_evidence_triggers_potential_concern(
    demo_policy, rules_config
):
    """Verifies that an unescalated case with complete authoritative escalation evidence triggers potential_concern."""
    from packages.analytics.context import AssessmentContext
    from packages.analytics.detectors import EscalationEvidenceDetector
    from packages.analytics.obligations import ObligationEvaluator
    from packages.analytics.reconstruction import EvidenceGraphReconstructor

    scenario_with_escalations = {
        "cases": [
            {
                "case_id": "CAS-OVERDUE-AUTH",
                "severity": "HIGH",
                "status": "OPEN",
                "created_at": "2026-08-05T08:30:00Z",
            }
        ],
        "escalations": [],
    }

    manifest = {
        "sources": [
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
    }

    sub = Submission(
        id="SUB-WITH-ESC",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json=json.dumps(manifest),
        status="committed",
    )
    sub_file = SubmissionFile(
        id="FILE-ESC",
        submission_id="SUB-WITH-ESC",
        source_id="src-esc",
        original_filename="escalations.csv",
        record_type="escalations",
        byte_size=0,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    sub.files = [sub_file]
    attach_scenario(sub, scenario_with_escalations)

    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 1
    f = findings[0]
    assert f.primary_object_id == "CAS-OVERDUE-AUTH"
    assert f.evidence_state == "potential_concern"


def test_case_with_root_cause_and_required_actions_not_penalized(demo_policy, rules_config):
    """Verifies that a case carrying root_cause and policy-required closure actions is not penalized.
    Per A4: root_cause is not sufficient by itself. Both root_cause and required artifacts must be supported.
    """
    from packages.analytics.context import AssessmentContext
    from packages.analytics.detectors import InvestigationEvidenceDetector
    from packages.analytics.obligations import ObligationEvaluator
    from packages.analytics.reconstruction import EvidenceGraphReconstructor

    # Case has root_cause AND required FORENSIC_TRIAGE action for HIGH severity
    scenario = {
        "cases": [
            {
                "case_id": "CAS-501",
                "severity": "HIGH",
                "status": "CLOSED",
                "created_at": "2026-08-05T08:30:00Z",
                "closed_at": "2026-08-06T10:00:00Z",
                "root_cause": "Credential stuffing attack neutralized",
            }
        ],
        "actions": [
            {
                "action_id": "ACT-501-TRIAGE",
                "case_id": "CAS-501",
                "action_type": "FORENSIC_TRIAGE",
                "timestamp": "2026-08-05T09:00:00Z",
            }
        ],
    }

    sub = Submission(
        id="SUB-ROOT-CAUSE",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario)

    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = InvestigationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["investigation_evidence"]
    )
    findings = detector.run()

    # CAS-501 has root_cause AND required action; all closure obligations satisfied
    assert len(findings) == 0


def test_future_due_case_remains_indeterminate(demo_policy, rules_config):
    """Verifies that a case created near cutoff with SLA due after cutoff remains non-adverse."""
    from packages.analytics.context import AssessmentContext
    from packages.analytics.detectors import EscalationEvidenceDetector
    from packages.analytics.obligations import ObligationEvaluator
    from packages.analytics.reconstruction import EvidenceGraphReconstructor

    scenario = {
        "cases": [
            {
                "case_id": "CAS-FUTURE-DUE",
                "severity": "HIGH",
                "status": "OPEN",
                "created_at": "2026-08-31T23:30:00Z",  # 30m before cutoff; SLA is 2h -> due 01:30 Sept 1
            }
        ],
        "actions": [],
    }

    sub = Submission(
        id="SUB-FUTURE-DUE",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario)

    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    detector = EscalationEvidenceDetector(
        ctx, graph, evaluator, rules_config["families"]["escalation_evidence"]
    )
    findings = detector.run()

    assert len(findings) == 0
