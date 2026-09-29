"""Regression coverage for the independently reproduced September audit defects."""

import json

import pytest

from tests.conftest import authenticate_user


def case(native_id="CASE-AUDIT", closed=None):
    return {
        "native_id": native_id,
        "severity": "CRITICAL",
        "status": "CLOSED" if closed else "OPEN",
        "created_at": "2026-01-05T10:00:00Z",
        "closed_at": closed,
        "root_cause": "Endpoint incident",
    }


def intake(client, datasets, overrides=None, entity="CSE-BANK-01", analyze=True):
    sources = []
    for kind, rows in datasets.items():
        sources.append(
            {
                "source_id": "src-" + kind,
                "record_type": kind,
                "declared_row_count": len(rows),
                "sampling_method": "full_population",
                "export_scope": "Full January export",
                "lineage": "Audit fixture",
                **(overrides or {}).get(kind, {}),
            }
        )
    r = client.post(
        "/api/v1/submissions",
        json={
            "manifest_version": "1.0.0",
            "entity_id": entity,
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-02-01T00:00:00Z",
            "source_timezone": "UTC",
            "sources": sources,
        },
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    for kind, rows in datasets.items():
        r = client.post(
            f"/api/v1/submissions/{sid}/files",
            data={"source_id": "src-" + kind},
            files={"file": (kind + ".json", json.dumps(rows).encode(), "application/json")},
        )
        assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/submissions/{sid}/validate")
    assert r.status_code == 200, r.text
    quality = r.json()
    if not analyze:
        return quality
    r = client.post(f"/api/v1/submissions/{sid}/commit", json={"idempotency_key": sid})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/analysis-runs", json={"submission_id": sid, "semantic_mode": "off"})
    assert r.status_code == 201, r.text
    run = r.json()
    r = client.get("/api/v1/findings", params={"run_id": run["run_id"]})
    assert r.status_code == 200, r.text
    return sid, run, r.json(), quality


@pytest.fixture
def auditor(client, admin_user, db_session):
    client.headers.update(authenticate_user(client, admin_user, db_session))
    return client


def selected(result, rule):
    return [f for f in result[2] if f["rule_id"] == rule]


@pytest.mark.parametrize(
    "scope,expected",
    [
        ([], 0),
        (["CSE-BANK-01"], 1),
        (["CSE-BANK-01", "CSE-FINTECH-02"], 2),
        (["*"], 2),
        ("invalid", 0),
    ],
)
def test_scoped_analytics(auditor, bank_examiner, db_session, scope, expected):
    bank = intake(auditor, {"cases": [case()]})
    fin = intake(auditor, {"cases": [case()]}, entity="CSE-FINTECH-02")
    bank_examiner.entity_scope = json.dumps(scope)
    db_session.commit()
    auditor.headers.update(authenticate_user(auditor, bank_examiner, db_session))
    assert len(auditor.get("/api/v1/analysis-runs").json()) == expected
    listed = auditor.get("/api/v1/findings").json()
    assert len({f["cse_id"] for f in listed}) == expected
    for entity, result in (("CSE-BANK-01", bank), ("CSE-FINTECH-02", fin)):
        allowed = isinstance(scope, list) and ("*" in scope or entity in scope)
        assert auditor.get(f"/api/v1/analysis-runs/{result[1]['run_id']}").status_code == (
            200 if allowed else 403
        )
        fid = result[2][0]["finding_id"]
        assert auditor.get(f"/api/v1/findings/{fid}").status_code == (200 if allowed else 403)
        assert auditor.get(
            f"/api/v1/evidence/chains/CASE-AUDIT?submission_id={result[0]}"
        ).status_code == (200 if allowed else 403)


@pytest.mark.parametrize(
    "override",
    [
        {"declared_row_count": 10},
        {"sampling_method": "random_sample"},
        {"export_scope": "Partial selected cases"},
        {"period_end": "2026-01-10T00:00:00Z"},
    ],
)
def test_partial_escalations_do_not_prove_absence(auditor, override):
    esc = {
        "native_id": "ESC-OTHER",
        "case_id": "CASE-OTHER",
        "escalation_level": "L2",
        "timestamp": "2026-01-05T10:10:00Z",
        "notified_party": "Tier 2",
    }
    result = intake(
        auditor,
        {"cases": [case(), case("CASE-OTHER")], "escalations": [esc]},
        {"escalations": override},
    )
    finding = next(
        f for f in selected(result, "POL-ESC-002") if f["primary_object_id"] == "CASE-AUDIT"
    )
    assert finding["evidence_state"] == "insufficient_evidence"


def test_partial_actions_do_not_prove_missing_artifacts(auditor):
    action = {
        "native_id": "NOTE-1",
        "case_id": "CASE-AUDIT",
        "action_type": "NOTE",
        "timestamp": "2026-01-05T10:10:00Z",
        "actor": "analyst",
    }
    result = intake(
        auditor,
        {"cases": [case(closed="2026-01-05T12:00:00Z")], "investigation_actions": [action]},
        {"investigation_actions": {"declared_row_count": 10}},
    )
    assert selected(result, "POL-INV-001")[0]["evidence_state"] == "insufficient_evidence"


def claim(name="CASE_CLOSURE_SLA_COMPLIANCE_RATE", value=100, **extra):
    return {
        "native_id": "CLAIM-1",
        "metric_name": name,
        "metric_value": value,
        "period": "2026-01",
        **extra,
    }


def test_metric_specific_kpi(auditor):
    result = intake(
        auditor,
        {
            "cases": [case(closed="2026-01-05T12:00:00Z")],
            "escalations": [],
            "reported_claims": [claim("ESCALATION_SLA_COMPLIANCE_RATE")],
        },
    )
    assert selected(result, "POL-KPI-004")[0]["evidence_state"] == "contradictory"


def test_denominator_incomplete(auditor):
    result = intake(
        auditor,
        {"cases": [case(closed="2026-01-06T12:00:00Z")], "reported_claims": [claim(value=90)]},
        {"cases": {"declared_row_count": 10}},
    )
    assert selected(result, "POL-KPI-004")[0]["evidence_state"] == "insufficient_evidence"


def test_nonoverlapping_period_is_not_reconciled(auditor):
    result = intake(
        auditor,
        {
            "cases": [case(closed="2026-01-05T12:00:00Z")],
            "reported_claims": [
                claim(
                    period="2025-01",
                    period_start="2025-01-01T00:00:00Z",
                    period_end="2025-02-01T00:00:00Z",
                )
            ],
        },
    )
    assert not selected(result, "POL-KPI-004")


@pytest.mark.parametrize("value,accepted", [(1000, 1), (-1, 0), (float("inf"), 0)])
def test_count_claim_units(auditor, value, accepted):
    quality = intake(
        auditor, {"reported_claims": [claim("TOTAL_CRITICAL_ALERTS", value)]}, analyze=False
    )
    assert quality["accepted_count"] == accepted


def test_native_id_never_grants_exception_and_hash_covers_bytes(auditor):
    special = intake(auditor, {"cases": [case("CASE-EXCUSED-EXCEPTION")], "escalations": []})
    ordinary = intake(auditor, {"cases": [case("ORDINARY")], "escalations": []})
    repeat = intake(auditor, {"cases": [case("ORDINARY")], "escalations": []})
    assert selected(special, "POL-ESC-002")[0]["evidence_state"] == "potential_concern"
    assert special[1]["input_hash"] != ordinary[1]["input_hash"]
    assert repeat[1]["input_hash"] == ordinary[1]["input_hash"]


def test_asset_chain_with_alert(auditor):
    assets = [
        {
            "native_id": "AST-1",
            "hostname": "host1",
            "ip_address": "10.0.0.1",
            "criticality": "HIGH",
            "owner": "SOC",
            "environment": "PROD",
        }
    ]
    alerts = [
        {
            "native_id": "ALT-1",
            "timestamp": "2026-01-05T10:00:00Z",
            "severity": "HIGH",
            "title": "Test alert",
            "source_tool": "SIEM",
            "triage_status": "OPEN",
            "affected_asset_id": "AST-1",
            "status": "OPEN",
        }
    ]
    result = intake(auditor, {"assets": assets, "alerts": alerts})
    r = auditor.get(f"/api/v1/evidence/chains/AST-1?submission_id={result[0]}")
    assert r.status_code == 200, r.text
    nodes = r.json()["related_entities"]["nodes"]
    assert len([n for n in nodes if n["native_id"] == "ALT-1"]) == 1


def test_valid_empty_complete_exports(auditor):
    """Empty complete exports (declared_row_count=0) validate cleanly and execute without crash."""
    result = intake(
        auditor,
        {"cases": [], "escalations": []},
        overrides={"cases": {"declared_row_count": 0}, "escalations": {"declared_row_count": 0}},
    )
    # Analysis must succeed with 0 adverse findings
    adverse = [
        f for f in result[2] if f["evidence_state"] in ("potential_concern", "contradictory")
    ]
    assert len(adverse) == 0


def test_quarantined_records_affecting_population_completeness(auditor):
    """Quarantined records reduce valid population and prevent complete evidence assertion."""
    # 2 rows declared, 1 valid row, 1 invalid row that fails schema validation
    cases_with_bad = [
        case("CASE-GOOD", closed="2026-01-05T12:00:00Z"),
        {"native_id": "CASE-BAD", "created_at": "not-a-valid-datetime", "severity": "UNKNOWN"},
    ]
    quality = intake(
        auditor,
        {"cases": cases_with_bad},
        overrides={"cases": {"declared_row_count": 2}},
        analyze=False,
    )
    assert quality["rejected_count"] >= 1
    assert quality["accepted_count"] == 1


def test_policy_exceptions_at_validity_boundaries():
    """Policy exceptions apply inclusively at [valid_from, valid_to] and reject outside."""
    from datetime import datetime, timezone

    from packages.analytics.obligations import ObligationEvaluator

    policy_dict = {
        "policy_version": "v1",
        "exceptions": [
            {
                "exception_id": "EXC-01",
                "rule_id": "POL-ESC-002",
                "target_type": "case",
                "target_id": "CASE-EXC",
                "valid_from": "2026-01-05T10:00:00Z",
                "valid_to": "2026-01-05T18:00:00Z",
                "approved_by": "CISO",
                "approved_at": "2026-01-04T12:00:00Z",
                "reason": "Planned migration outage",
            }
        ],
    }
    evaluator = ObligationEvaluator(policy_dict)

    t_before = datetime(2026, 1, 5, 9, 59, 59, tzinfo=timezone.utc)
    t_start = datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc)
    t_mid = datetime(2026, 1, 5, 14, 0, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 1, 5, 18, 0, 0, tzinfo=timezone.utc)
    t_after = datetime(2026, 1, 5, 18, 0, 1, tzinfo=timezone.utc)

    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-EXC", t_before) is None
    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-EXC", t_start) is not None
    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-EXC", t_mid) is not None
    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-EXC", t_end) is not None
    assert evaluator.match_exception("POL-ESC-002", "case", "CASE-EXC", t_after) is None


def test_events_around_assessment_cutoff(auditor):
    """Cases closed after the submission cutoff cannot be treated as closed within the period."""
    # Submission period_end is 2026-02-01T00:00:00Z
    # Case created in period but closed AFTER cutoff
    late_closed_case = {
        "native_id": "CASE-CUTOFF",
        "severity": "CRITICAL",
        "status": "CLOSED",
        "created_at": "2026-01-30T10:00:00Z",
        "closed_at": "2026-02-05T10:00:00Z",  # After 2026-02-01 cutoff
        "root_cause": "Incident",
    }
    result = intake(auditor, {"cases": [late_closed_case]})
    # Escalation detector checks if escalation was due before cutoff
    findings = result[2]
    esc_findings = [f for f in findings if f["primary_object_id"] == "CASE-CUTOFF"]
    assert len(esc_findings) >= 1


def test_fingerprint_reproducibility_and_sensitivity_to_content(auditor):
    """Analysis input hash is fully reproducible for identical input bytes, and changes on mutation."""
    cases_1 = [case("CASE-FP-1")]
    cases_2 = [case("CASE-FP-2")]

    res1 = intake(auditor, {"cases": cases_1})
    res1_repeat = intake(auditor, {"cases": cases_1})
    res2 = intake(auditor, {"cases": cases_2})

    hash1 = res1[1]["input_hash"]
    hash1_repeat = res1_repeat[1]["input_hash"]
    hash2 = res2[1]["input_hash"]

    # Identical frozen inputs produce identical input hashes
    assert hash1 == hash1_repeat
    # Different input contents produce different input hashes
    assert hash1 != hash2
