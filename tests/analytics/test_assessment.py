"""Tests for SAT-SA supervisory analytics, detectors, and claim reconciliation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from db.models.evidence import Submission
from packages.analytics.claims import ClaimReconciler
from packages.analytics.context import AssessmentContext
from packages.analytics.detectors import (
    EscalationEvidenceDetector,
    InvestigationEvidenceDetector,
    MonitoringCoverageDetector,
    RecurrenceContextDetector,
)
from packages.analytics.obligations import ObligationEvaluator
from packages.analytics.reconstruction import EvidenceGraphReconstructor
from packages.analytics.service import AnalysisService
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


def test_kpi_reconciliation_math():
    """Verifies bounded uncertainty intervals and strict disproof logic.

    817 compliant cases out of 1240 cases against a claimed 98%:
    - If 423 cases are unknown: interval is [65.9%, 100%], not disproved (insufficient_evidence).
    - If all 1240 are known (423 non-compliant): interval is [65.9%, 65.9%], strictly contradicted.
    """
    compliant_ids = {f"CASE-COMP-{i}" for i in range(817)}
    non_compliant_ids = {f"CASE-FAIL-{i}" for i in range(423)}
    unknown_ids = {f"CASE-UNK-{i}" for i in range(423)}

    # Case A: 423 unknown outcomes
    res_unknown = ClaimReconciler.evaluate_sla_claim(
        claimed_pct=98.0,
        compliant_case_ids=compliant_ids,
        non_compliant_case_ids=set(),
        unknown_case_ids=unknown_ids,
    )
    assert res_unknown.total_population == 1240
    assert res_unknown.verified_compliant == 817
    assert res_unknown.unknown_outcomes == 423
    assert res_unknown.lower_bound_pct == pytest.approx(65.89, 0.01)
    assert res_unknown.upper_bound_pct == 100.0
    assert not res_unknown.is_contradicted
    assert res_unknown.evidence_state == "insufficient_evidence"

    # Case B: 0 unknown outcomes (423 verified non-compliant)
    res_known = ClaimReconciler.evaluate_sla_claim(
        claimed_pct=98.0,
        compliant_case_ids=compliant_ids,
        non_compliant_case_ids=non_compliant_ids,
        unknown_case_ids=set(),
    )
    assert res_known.total_population == 1240
    assert res_known.verified_compliant == 817
    assert res_known.verified_non_compliant == 423
    assert res_known.lower_bound_pct == pytest.approx(65.89, 0.01)
    assert res_known.upper_bound_pct == pytest.approx(65.89, 0.01)
    assert res_known.is_contradicted
    assert res_known.evidence_state == "contradictory"


def test_investigation_fast_closure_with_and_without_artifacts(
    assessment_scenario, demo_policy, rules_config
):
    """Verifies that fast closure with required artifacts is NOT penalized, while fast closure without is."""
    sub = Submission(
        id="SUB-TEST-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, assessment_scenario)
    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    rule_cfg = rules_config["families"]["investigation_evidence"]

    detector = InvestigationEvidenceDetector(ctx, graph, evaluator, rule_cfg)
    findings = detector.run()

    flagged_ids = [f.primary_object_id for f in findings]
    assert "CASE-FAST-NO-ARTIFACTS" in flagged_ids
    assert "CASE-FAST-WITH-ARTIFACTS" not in flagged_ids


def test_escalation_exceptions_and_cutoffs(assessment_scenario, demo_policy, rules_config):
    """Verifies that period cutoffs and policy exceptions prevent false overdue findings."""
    sub = Submission(
        id="SUB-TEST-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, assessment_scenario)
    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    rule_cfg = rules_config["families"]["escalation_evidence"]

    detector = EscalationEvidenceDetector(ctx, graph, evaluator, rule_cfg)
    findings = detector.run()

    flagged_ids = [f.primary_object_id for f in findings]
    assert "CASE-OVERDUE-ESCALATION" in flagged_ids
    assert "CASE-NOT-YET-DUE-AT-CUTOFF" not in flagged_ids
    assert "CASE-EXCUSED-EXCEPTION" not in flagged_ids


def test_monitoring_coverage_quiet_assets(assessment_scenario, demo_policy, rules_config):
    """Verifies that quiet well-monitored assets are not flagged, broken agents are flagged, and missing telemetry gives insufficient_evidence."""
    sub = Submission(
        id="SUB-TEST-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, assessment_scenario)
    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    rule_cfg = rules_config["families"]["monitoring_coverage"]

    detector = MonitoringCoverageDetector(ctx, graph, evaluator, rule_cfg)
    findings = detector.run()

    finding_by_asset = {f.primary_object_id: f for f in findings}
    assert "SRV-QUIET-VAULT-01" not in finding_by_asset
    assert "SRV-PAY-API-02" in finding_by_asset
    assert finding_by_asset["SRV-PAY-API-02"].evidence_state == "potential_concern"
    assert "SRV-SWIFT-GW-01" in finding_by_asset
    assert finding_by_asset["SRV-SWIFT-GW-01"].evidence_state == "insufficient_evidence"


def test_recurrence_hypothesis_and_peer_comparison(assessment_scenario, demo_policy, rules_config):
    """Verifies recurrence findings are framed as hypotheses and peer comparison is labeled unavailable."""
    sub = Submission(
        id="SUB-TEST-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, assessment_scenario)
    ctx = AssessmentContext(sub)
    graph = EvidenceGraphReconstructor(ctx)
    evaluator = ObligationEvaluator(demo_policy)
    rule_cfg = rules_config["families"]["recurrence_context"]

    detector = RecurrenceContextDetector(ctx, graph, evaluator, rule_cfg)
    findings = detector.run()

    finding_by_asset = {f.primary_object_id: f for f in findings}
    assert "SRV-RECUR-01" in finding_by_asset
    assert "Hypothesis:" in finding_by_asset["SRV-RECUR-01"].rationale
    assert finding_by_asset["SRV-RECUR-01"].peer_comparison_status == "peer_comparison_unavailable"
    assert "SRV-EXC-MAINT-01" not in finding_by_asset


def test_analysis_service_committed_submission(db_session: Session, assessment_scenario):
    """Verifies end-to-end analysis run creation and finding persistence on committed submission."""
    sub = Submission(
        id="SUB-COMMITTED-01",
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
    run = service.run_assessment(
        submission_id="SUB-COMMITTED-01",
        cse_id="CSE-BANK-01",
    )

    assert run.status == "completed"
    assert run.findings_count > 0
    assert run.input_hash is not None

    findings = service.list_findings(submission_id="SUB-COMMITTED-01")
    assert len(findings) == run.findings_count

    chain = service.get_evidence_chain(
        submission_id="SUB-COMMITTED-01",
        object_id="CASE-OVERDUE-ESCALATION",
        cse_id="CSE-BANK-01",
    )
    assert chain["object_id"] == "CASE-OVERDUE-ESCALATION"
    assert "timeline" in chain
    assert len(chain["timeline"]) > 0
