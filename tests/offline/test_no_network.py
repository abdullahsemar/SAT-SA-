"""Offline integration test verifying full application workflow with external network access blocked.

Preserves core architectural invariants:
- All communications are strictly loopback (127.0.0.1).
- Positive control demonstrates outbound non-loopback connections are intercepted and denied.
- Full journey (login, intake, analysis, review, decision, frozen export) functions offline.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.auth import hash_password
from db.models.access import User
from db.models.evidence import Submission
from packages.analytics.service import AnalysisService
from tests.conftest import authenticate_user
from tests.scenario_adapter import attach_scenario


class OfflineNetworkBlockedError(RuntimeError):
    """Raised when an attempt is made to open a non-loopback external network connection."""

    pass


@pytest.fixture(autouse=True)
def enforce_strict_offline_network(monkeypatch):
    """Intercepts socket.connect to block any outbound calls outside loopback."""
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0]
        # Allow loopback addresses
        if host in ("127.0.0.1", "localhost", "::1"):
            return real_connect(self, address)
        raise OfflineNetworkBlockedError(
            f"BLOCKED: Outbound external network connection attempted to {address} in offline runtime."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


def test_positive_control_external_network_is_denied():
    """Positive control: Proves that external non-loopback network calls are actively blocked."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(OfflineNetworkBlockedError, match="BLOCKED: Outbound external network"):
        s.connect(("8.8.8.8", 53))


def test_full_offline_examiner_journey(client: TestClient, db_session: Session):
    """Verifies the complete end-to-end supervisory assessment journey runs entirely offline."""
    # 1. Fresh User Login
    user = User(
        id="offline_examiner_01",
        username="offline_lead",
        password_hash=hash_password("OfflinePass123!"),
        role="examiner",
        entity_scope='["CSE-BANK-01"]',
    )
    db_session.add(user)
    db_session.commit()

    headers = authenticate_user(client, user, db_session)
    client.headers.update(headers)

    # 2. Evidence Intake
    scenario_path = Path("synthetic/scenarios/assessment.json")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    sub = Submission(
        id="SUB-OFFLINE-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario_data)
    db_session.add(sub)
    db_session.commit()

    # 3. Assessment Analysis
    service = AnalysisService(db_session)
    run = service.run_assessment(
        submission_id="SUB-OFFLINE-01",
        cse_id="CSE-BANK-01",
        semantic_mode="auto",  # Uses verified local weights or labeled lexical fallback
    )
    assert run.status == "completed"
    findings = service.list_findings(run_id=run.id)
    assert len(findings) > 0

    # 4. Review Portfolio Generation via API
    resp_port = client.post(
        "/api/v1/review-portfolios",
        json={
            "run_id": run.id,
            "max_items": 5,
            "strata_allocation": {"targeted": 3, "control": 1, "exploratory": 1},
            "seed": 42,
        },
    )
    assert resp_port.status_code == 201
    portfolio_data = resp_port.json()
    assert len(portfolio_data["items"]) > 0
    first_item = portfolio_data["items"][0]

    # 5. Examiner Decision Recording via API
    if first_item["finding_id"]:
        resp_dec = client.post(
            f"/api/v1/findings/{first_item['finding_id']}/decisions",
            json={
                "state": "substantiated",
                "rationale": "Verified offline without remote dependency.",
                "cited_evidence_ids": [],
            },
        )
    else:
        resp_dec = client.post(
            f"/api/v1/review-items/{first_item['id']}/decisions",
            json={
                "state": "reviewed_no_concern",
                "rationale": "Control reviewed offline.",
                "cited_evidence_ids": [],
            },
        )
    assert resp_dec.status_code == 201

    # 6. Frozen Report Snapshot & Export via API
    resp_rep = client.post(
        "/api/v1/reports",
        json={
            "run_id": run.id,
            "portfolio_id": portfolio_data["id"],
            "notes": "Verified 100% offline deployment export",
        },
    )
    assert resp_rep.status_code == 201
    report_info = resp_rep.json()
    report_id = report_info["id"]

    # 7. Download artifacts offline
    res_html = client.get(f"/api/v1/reports/{report_id}/html")
    assert res_html.status_code == 200
    assert "Supervisory SOC Assessment Report" in res_html.text

    res_json = client.get(f"/api/v1/reports/{report_id}/json")
    assert res_json.status_code == 200
    snap_data = res_json.json()
    assert snap_data["analysis_run"]["run_id"] == run.id

    res_manifest = client.get(f"/api/v1/reports/{report_id}/manifest")
    assert res_manifest.status_code == 200
    man_data = res_manifest.json()
    assert "components" in man_data
    assert "snapshot_json" in man_data["components"]

    res_bundle = client.get(f"/api/v1/reports/{report_id}/bundle")
    assert res_bundle.status_code == 200
    assert len(res_bundle.content) > 0
