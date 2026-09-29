"""Performance and batch profiling tests for evidence ingestion, assessment analysis, and export.

Measures batch execution time, peak memory utilization, and API endpoint latency
against declared synthetic scenarios.
"""

from __future__ import annotations

import json
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.auth import hash_password
from db.models.access import User
from db.models.evidence import CSE, Submission
from packages.analytics.service import AnalysisService
from tests.conftest import authenticate_user
from tests.scenario_adapter import attach_scenario


def test_batch_ingestion_and_assessment_profile(db_session: Session):
    """Measures batch assessment runtime and peak memory consumption."""
    scenario_path = Path("synthetic/scenarios/assessment.json")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    # 1. Setup entities
    cse = CSE(id="CSE-PERF-01", code="CSE-PERF-01", name="Performance Test CSE")
    db_session.add(cse)
    db_session.commit()

    sub = Submission(
        id="SUB-PERF-01",
        entity_id="CSE-PERF-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario_data)
    db_session.add(sub)
    db_session.commit()

    # 2. Profile Assessment Execution with tracemalloc
    tracemalloc.start()
    start_time = time.perf_counter()

    service = AnalysisService(db_session)
    run = service.run_assessment(
        submission_id="SUB-PERF-01",
        cse_id="CSE-PERF-01",
        semantic_mode="off",
    )

    elapsed_s = time.perf_counter() - start_time
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem / (1024 * 1024)

    assert run.status == "completed"
    assert run.findings_count > 0
    # Performance assertion: assessment on fixture should execute in < 5.0 seconds
    assert elapsed_s < 5.0, f"Assessment exceeded 5.0s budget: {elapsed_s:.3f}s"
    # Memory assertion: memory overhead should be reasonable (< 150 MB)
    assert peak_mb < 150.0, f"Peak memory exceeded 150MB: {peak_mb:.2f}MB"


def test_report_export_api_latency(client: TestClient, db_session: Session):
    """Measures API endpoint response latency for frozen snapshot creation and download."""
    # Create test user
    user = User(
        id="perf_examiner_id",
        username="perf_examiner",
        password_hash=hash_password("ExaminerPass123!"),
        role="examiner",
        entity_scope='["CSE-BANK-01"]',
    )
    db_session.add(user)
    db_session.commit()

    headers = authenticate_user(client, user, db_session)
    client.headers.update(headers)

    scenario_path = Path("synthetic/scenarios/assessment.json")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    sub = Submission(
        id="SUB-PERF-02",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, scenario_data)
    db_session.add(sub)
    db_session.commit()

    service = AnalysisService(db_session)
    run = service.run_assessment(
        submission_id="SUB-PERF-02",
        cse_id="CSE-BANK-01",
        semantic_mode="off",
    )

    # 1. Measure POST /api/v1/reports latency
    t0 = time.perf_counter()
    resp_create = client.post(
        "/api/v1/reports",
        json={"run_id": run.id, "notes": "Latency benchmark"},
    )
    create_latency_ms = (time.perf_counter() - t0) * 1000.0

    assert resp_create.status_code == 201
    report_id = resp_create.json()["id"]
    # Report snapshot generation should complete within 2000ms
    assert create_latency_ms < 2000.0, f"Report creation too slow: {create_latency_ms:.1f}ms"

    # 2. Measure GET /api/v1/reports/{id}/html latency
    t1 = time.perf_counter()
    resp_html = client.get(f"/api/v1/reports/{report_id}/html")
    html_latency_ms = (time.perf_counter() - t1) * 1000.0

    assert resp_html.status_code == 200
    assert "Supervisory SOC Assessment Report" in resp_html.text
    assert html_latency_ms < 500.0, f"HTML retrieval too slow: {html_latency_ms:.1f}ms"

    # 3. Measure GET /api/v1/reports/{id}/bundle latency
    t2 = time.perf_counter()
    resp_bundle = client.get(f"/api/v1/reports/{report_id}/bundle")
    bundle_latency_ms = (time.perf_counter() - t2) * 1000.0

    assert resp_bundle.status_code == 200
    assert len(resp_bundle.content) > 0
    assert bundle_latency_ms < 1000.0, f"Bundle retrieval too slow: {bundle_latency_ms:.1f}ms"
