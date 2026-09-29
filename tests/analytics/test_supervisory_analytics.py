"""Tests for SAT-SA supervisory analytics, peer comparisons, period trends,
unusual pattern hypotheses, and selector endpoints.
"""

from __future__ import annotations

import datetime
import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db.models.access import User
from db.models.assessment import AnalysisRun, Finding
from db.models.evidence import CSE, NormalizedRecord, RawRecord, Submission, SubmissionFile
from packages.analytics.peer_comparison import PeerComparisonService
from packages.analytics.supervisory_summary import SupervisorySummaryService
from packages.analytics.trends import PeriodTrendsService
from packages.analytics.unusual_patterns import UnusualPatternService
from tests.conftest import authenticate_user


def _seed_test_world(session: Session) -> dict:
    """Seeds multi-entity, multi-period data for supervisory testing."""
    cses = [
        CSE(id="CSE-BANK-01", code="CSE-BANK-01", name="Apex National Bank"),
        CSE(id="CSE-BANK-02", code="CSE-BANK-02", name="Metro Commercial Bank"),
        CSE(id="CSE-BANK-03", code="CSE-BANK-03", name="Union Trust Bank"),
        CSE(id="CSE-BANK-04", code="CSE-BANK-04", name="Pinnacle Financial CSE"),
        CSE(id="CSE-HEALTH-01", code="CSE-HEALTH-01", name="Central Health Authority"),
    ]
    for c in cses:
        if not session.get(CSE, c.id):
            session.add(c)
    session.commit()

    now = datetime.datetime.now(datetime.timezone.utc)

    # Helper to add 2 files to a submission
    def add_files(sub_id: str):
        f1 = SubmissionFile(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            source_id="cases.csv",
            record_type="case",
            original_filename="cases.csv",
            storage_path=f"/tmp/cases_{sub_id}.csv",
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            byte_size=1024,
            actual_row_count=10,
        )
        f2 = SubmissionFile(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            source_id="alerts.csv",
            record_type="alert",
            original_filename="alerts.csv",
            storage_path=f"/tmp/alerts_{sub_id}.csv",
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b856",
            byte_size=2048,
            actual_row_count=20,
        )
        session.add_all([f1, f2])

    # 1. CSE-BANK-01 Q1 and Q3 (skipping Q2 for gap test)
    q1_sub = Submission(
        id=str(uuid.uuid4()),
        entity_id="CSE-BANK-01",
        period_start=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        period_end=datetime.datetime(2026, 3, 31, tzinfo=datetime.timezone.utc),
        status="committed",
        manifest_json=json.dumps({"declared_sources": ["cases.csv", "alerts.csv"]}),
        committed_at=now,
    )
    q3_sub = Submission(
        id=str(uuid.uuid4()),
        entity_id="CSE-BANK-01",
        period_start=datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc),
        period_end=datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc),
        status="committed",
        manifest_json=json.dumps({"declared_sources": ["cases.csv", "alerts.csv"]}),
        committed_at=now,
    )
    session.add_all([q1_sub, q3_sub])
    session.commit()
    add_files(q1_sub.id)
    add_files(q3_sub.id)

    # 2. Peer Submissions (Q3) for CSE-BANK-02, 03, 04
    peer_subs = []
    for peer_id in ["CSE-BANK-02", "CSE-BANK-03", "CSE-BANK-04"]:
        s = Submission(
            id=str(uuid.uuid4()),
            entity_id=peer_id,
            period_start=datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc),
            period_end=datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc),
            status="committed",
            manifest_json=json.dumps({"declared_sources": ["cases.csv", "alerts.csv"]}),
            committed_at=now,
        )
        session.add(s)
        session.commit()
        add_files(s.id)
        peer_subs.append(s)

    # 3. Healthcare Submission (for isolated cohort test)
    health_sub = Submission(
        id=str(uuid.uuid4()),
        entity_id="CSE-HEALTH-01",
        period_start=datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc),
        period_end=datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc),
        status="committed",
        manifest_json=json.dumps({"declared_sources": ["cases.csv", "alerts.csv"]}),
        committed_at=now,
    )
    session.add(health_sub)
    session.commit()
    add_files(health_sub.id)

    # Add normalized records for q3_sub (including rapid closure, templated narrative, and assets)
    raw_sub = RawRecord(
        id=str(uuid.uuid4()),
        submission_id=q3_sub.id,
        source_id="cases.csv",
        record_type="case",
        row_locator="row:1",
        sha256_hash="abc",
        raw_payload="{}",
    )
    session.add(raw_sub)
    session.commit()

    cases_data = [
        # Rapid closures with templated text
        {
            "id": "CASE-101",
            "duration_seconds": 45,
            "disposition": "false_positive",
            "closure_notes": "Standard false positive verified by automated signature check.",
            "assigned_to": "analyst_1",
            "created_at": "2026-08-01T10:00:00Z",
            "closed_at": "2026-08-01T10:00:45Z",
            "asset_id": "SRV-CORE-01",
        },
        {
            "id": "CASE-102",
            "duration_seconds": 55,
            "disposition": "false_positive",
            "closure_notes": "Standard false positive verified by automated signature check.",
            "assigned_to": "analyst_1",
            "created_at": "2026-08-01T10:05:00Z",
            "closed_at": "2026-08-01T10:05:55Z",
            "asset_id": "SRV-CORE-01",
        },
        {
            "id": "CASE-103",
            "duration_seconds": 50,
            "disposition": "false_positive",
            "closure_notes": "Standard false positive verified by automated signature check.",
            "assigned_to": "analyst_2",
            "created_at": "2026-08-01T10:10:00Z",
            "closed_at": "2026-08-01T10:10:50Z",
            "asset_id": "SRV-CORE-02",
        },
        # Standard case
        {
            "id": "CASE-104",
            "duration_seconds": 3600,
            "disposition": "remediated",
            "closure_notes": "Malware removed and host patched by endpoint engineering team.",
            "assigned_to": "analyst_3",
            "created_at": "2026-08-02T12:00:00Z",
            "closed_at": "2026-08-02T13:00:00Z",
            "asset_id": "SRV-CORE-01",
        },
    ]

    for c in cases_data:
        nr = NormalizedRecord(
            id=str(uuid.uuid4()),
            raw_record_id=raw_sub.id,
            submission_id=q3_sub.id,
            entity_id="CSE-BANK-01",
            source_id="cases.csv",
            record_type="case",
            native_id=c["id"],
            timestamp=datetime.datetime(2026, 8, 1, 10, 0, tzinfo=datetime.timezone.utc),
            normalized_data=json.dumps(c),
            is_quarantined=False,
        )
        session.add(nr)

    # Post-remediation alert on SRV-CORE-01 to trigger recurrence detector
    alert_rec = NormalizedRecord(
        id=str(uuid.uuid4()),
        raw_record_id=raw_sub.id,
        submission_id=q3_sub.id,
        entity_id="CSE-BANK-01",
        source_id="alerts.csv",
        record_type="alert",
        native_id="ALT-999",
        timestamp=datetime.datetime(2026, 8, 5, 14, 0, tzinfo=datetime.timezone.utc),
        normalized_data=json.dumps(
            {
                "asset_id": "SRV-CORE-01",
                "rule_name": "Repeated C2 Beaconing",
                "timestamp": "2026-08-05T14:00:00Z",
            }
        ),
        is_quarantined=False,
    )
    session.add(alert_rec)

    # Analysis runs for Q1 and Q3
    run_q1 = AnalysisRun(
        id=str(uuid.uuid4()),
        submission_id=q1_sub.id,
        entity_id="CSE-BANK-01",
        status="completed",
        input_hash="hash_q1",
        policy_version="demo-v1",
        rule_version="rules-v1",
        parameters_json="{}",
        cutoff_time=now,
        findings_count=3,
        summary_counts_json=json.dumps({"potential_concern": 3}),
        completed_at=now,
    )
    run_q3 = AnalysisRun(
        id=str(uuid.uuid4()),
        submission_id=q3_sub.id,
        entity_id="CSE-BANK-01",
        status="completed",
        input_hash="hash_q3",
        policy_version="demo-v1",
        rule_version="rules-v1",
        parameters_json="{}",
        cutoff_time=now,
        findings_count=2,
        summary_counts_json=json.dumps({"potential_concern": 2}),
        completed_at=now,
    )
    session.add_all([run_q1, run_q3])

    # Findings for run_q3
    f_gap = Finding(
        id=str(uuid.uuid4()),
        run_id=run_q3.id,
        submission_id=q3_sub.id,
        entity_id="CSE-BANK-01",
        proposition="Unsubstantiated rapid closure without triage notes",
        scope="case",
        family="POL-INV-001",
        direction="adverse",
        evidence_state="potential_concern",
        applicable_obligation="Mandatory Investigation Triage Standard",
        supporting_sources_json=json.dumps([{"native_id": "CASE-101"}]),
        contradicting_sources_json="[]",
        lineage_json="[]",
        unknowns_json="[]",
        alternative_explanations_json="[]",
        additional_evidence_needed_json="[]",
        metrics_json=json.dumps({"severity": "high"}),
    )
    f_esc = Finding(
        id=str(uuid.uuid4()),
        run_id=run_q3.id,
        submission_id=q3_sub.id,
        entity_id="CSE-BANK-01",
        proposition="Overdue escalation for critical threat",
        scope="case",
        family="POL-ESC-002",
        direction="adverse",
        evidence_state="potential_concern",
        applicable_obligation="Critical Incident Escalation Standard",
        supporting_sources_json=json.dumps([{"native_id": "CASE-102"}]),
        contradicting_sources_json="[]",
        lineage_json="[]",
        unknowns_json="[]",
        alternative_explanations_json="[]",
        additional_evidence_needed_json="[]",
        metrics_json=json.dumps({"severity": "high"}),
    )
    session.add_all([f_gap, f_esc])

    # Runs for peers
    for p_sub in peer_subs:
        p_run = AnalysisRun(
            id=str(uuid.uuid4()),
            submission_id=p_sub.id,
            entity_id=p_sub.entity_id,
            status="completed",
            input_hash=f"hash_{p_sub.entity_id}",
            policy_version="demo-v1",
            rule_version="rules-v1",
            parameters_json="{}",
            cutoff_time=now,
            findings_count=1,
            summary_counts_json=json.dumps({"supported": 1}),
            completed_at=now,
        )
        session.add(p_run)

    # Run for health
    health_run = AnalysisRun(
        id=str(uuid.uuid4()),
        submission_id=health_sub.id,
        entity_id="CSE-HEALTH-01",
        status="completed",
        input_hash="hash_health",
        policy_version="demo-v1",
        rule_version="rules-v1",
        parameters_json="{}",
        cutoff_time=now,
        findings_count=0,
        summary_counts_json=json.dumps({"supported": 0}),
        completed_at=now,
    )
    session.add(health_run)

    session.commit()
    return {
        "q1_sub": q1_sub,
        "q3_sub": q3_sub,
        "run_q3": run_q3,
        "peer_subs": peer_subs,
    }


def test_supervisory_summary_service(db_session: Session):
    data = _seed_test_world(db_session)
    service = SupervisorySummaryService(db_session)

    overview = service.get_entity_overview(
        entity_id="CSE-BANK-01",
        run_id=data["run_q3"].id,
    )

    assert overview is not None
    assert overview.entity_id == "CSE-BANK-01"
    assert overview.supervisory_attention_index >= 0.0
    assert overview.supervisory_attention_index <= 100.0
    assert overview.attention_priority in ("ROUTINE", "ELEVATED", "CRITICAL_ATTENTION")
    assert overview.execution_gaps.adverse_findings_count == 2
    assert len(overview.capabilities) == 8
    assert overview.evidence_completeness.total_parsed_records >= 0


def test_peer_comparison_service_valid_cohort(db_session: Session):
    _seed_test_world(db_session)
    service = PeerComparisonService(db_session)

    res = service.evaluate_peer_comparison(target_entity_id="CSE-BANK-01")
    assert res is not None
    assert res.target_entity_id == "CSE-BANK-01"
    # We have 3 peer banks (CSE-BANK-02, 03, 04)
    assert res.eligible_peer_count == 3
    assert res.minimum_peers_required == 3
    assert res.is_cohort_sufficient is True
    assert res.status == "VALID_COMPARISON"

    # Verify target entity is strictly EXCLUDED from peer distribution
    for metric in res.metric_comparisons:
        if metric.peer_distribution:
            assert metric.peer_distribution.count == 3
        assert metric.explanation is not None

    # Privacy verification: no raw case IDs in eligible_peers
    for peer in res.eligible_peers:
        assert "entity_id" in peer
        assert "case_id" not in peer
        assert "narrative" not in peer


def test_peer_comparison_service_insufficient_cohort(db_session: Session):
    _seed_test_world(db_session)
    service = PeerComparisonService(db_session)

    # Healthcare entity has 0 peers in healthcare sector
    res = service.evaluate_peer_comparison(target_entity_id="CSE-HEALTH-01")
    assert res is not None
    assert res.is_cohort_sufficient is False
    assert res.status == "INSUFFICIENT_PEERS"
    assert "minimum 3 required" in res.status_reason


def test_period_trends_service_gap_detection(db_session: Session):
    _seed_test_world(db_session)
    service = PeriodTrendsService(db_session)

    trends = service.compute_trends(entity_id="CSE-BANK-01")
    assert trends is not None
    assert trends.entity_id == "CSE-BANK-01"
    # There should be Q1, missing Q2 gap, and Q3
    assert len(trends.points) >= 3
    # Check that missing period gap was detected and NOT fabricated as zeros
    gap_points = [p for p in trends.points if not p.has_data]
    assert len(gap_points) >= 1
    assert "Reporting gap detected" in gap_points[0].gap_reason
    assert gap_points[0].supervisory_attention_index is None
    assert gap_points[0].adverse_findings_count is None


def test_unusual_patterns_service(db_session: Session):
    data = _seed_test_world(db_session)
    service = UnusualPatternService(db_session)

    result = service.analyze_patterns(
        submission_id=data["q3_sub"].id,
        run_id=data["run_q3"].id,
    )
    assert result is not None
    assert result.submission_id == data["q3_sub"].id
    assert result.hypotheses_count >= 1

    pattern_codes = [h.pattern_code for h in result.hypotheses]
    # Check that rapid closures was flagged
    assert "PAT-RAPID-CLOSURE" in pattern_codes
    # Check that repeated narrative was flagged (3 cases with identical notes)
    assert "PAT-REPEATED-NARRATIVE" in pattern_codes
    # Check that post-remediation recurrence was flagged (SRV-CORE-01 alert after remediation)
    assert "PAT-RECURRENCE-POST-REMEDIATION" in pattern_codes

    # Verify each hypothesis contains observed value, baseline definition, and examiner guidance
    for h in result.hypotheses:
        assert h.observed_value >= 0.0
        assert len(h.baseline_definition) > 0
        assert len(h.suggested_examiner_action) > 0


def test_supervisory_api_routes(
    client: TestClient,
    admin_user: User,
    bank_examiner: User,
    fintech_examiner: User,
    db_session: Session,
):
    data = _seed_test_world(db_session)

    # 1. Admin accesses /entities -> sees all entities
    admin_headers = authenticate_user(client, admin_user, db_session)
    resp = client.get("/api/v1/supervisory/entities", headers=admin_headers)
    assert resp.status_code == 200
    entities = resp.json()
    assert len(entities) >= 4

    # 2. Bank examiner accesses /entities -> sees ONLY CSE-BANK-01
    bank_headers = authenticate_user(client, bank_examiner, db_session)
    resp = client.get("/api/v1/supervisory/entities", headers=bank_headers)
    assert resp.status_code == 200
    bank_entities = resp.json()
    assert len(bank_entities) == 1
    assert bank_entities[0]["id"] == "CSE-BANK-01"

    # 3. Bank examiner accesses periods for CSE-BANK-01 -> success
    resp = client.get(
        "/api/v1/supervisory/periods?entity_id=CSE-BANK-01",
        headers=bank_headers,
    )
    assert resp.status_code == 200
    periods = resp.json()
    assert len(periods) >= 2

    # 4. Bank examiner tries to access CSE-FINTECH-02 -> 403 Forbidden
    resp = client.get(
        "/api/v1/supervisory/periods?entity_id=CSE-FINTECH-02",
        headers=bank_headers,
    )
    assert resp.status_code == 403

    # 5. Overview endpoint
    resp = client.get(
        f"/api/v1/supervisory/overview?entity_id=CSE-BANK-01&run_id={data['run_q3'].id}",
        headers=bank_headers,
    )
    assert resp.status_code == 200
    overview_data = resp.json()
    assert overview_data["entity_id"] == "CSE-BANK-01"
    assert "supervisory_attention_index" in overview_data

    # 6. Peer comparison endpoint
    resp = client.get(
        "/api/v1/supervisory/peer-comparison?entity_id=CSE-BANK-01",
        headers=bank_headers,
    )
    assert resp.status_code == 200
    peer_data = resp.json()
    assert peer_data["status"] == "VALID_COMPARISON"

    # 7. Trends endpoint
    resp = client.get(
        "/api/v1/supervisory/trends?entity_id=CSE-BANK-01",
        headers=bank_headers,
    )
    assert resp.status_code == 200
    trends_data = resp.json()
    assert len(trends_data["points"]) >= 3

    # 8. Unusual patterns endpoint
    resp = client.get(
        f"/api/v1/supervisory/unusual-patterns?submission_id={data['q3_sub'].id}&entity_id=CSE-BANK-01",
        headers=bank_headers,
    )
    assert resp.status_code == 200
    patterns_data = resp.json()
    assert patterns_data["hypotheses_count"] >= 1
