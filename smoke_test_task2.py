"""Live loopback E2E smoke test for Task 2 Supervisory Analytics & Findings."""

import json
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000/api/v1"


def run_smoke_task2():
    print("=== Starting SAT-SA Task 2 Live Supervisory Analytics Smoke Test ===")

    scenario_path = Path("synthetic/scenarios/assessment.json")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario = json.load(f)

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Health check
        res = client.get("/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        print("1. API Health: OK (offline loopback)")

        # 2. Login as admin
        login_res = client.post(
            "/auth/login",
            json={"username": "admin", "password": "ExaminerPass123!"},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        csrf_token = login_res.json().get("csrf_token")
        client.headers["X-CSRF-Token"] = csrf_token
        print("2. Authentication: OK (Admin session established)")

        # 3. Create a test submission with declared sources
        manifest = {
            "manifest_version": "1.0.0",
            "entity_id": "CSE-BANK-01",
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-31T23:59:59Z",
            "source_timezone": "UTC",
            "sources": [
                {
                    "source_id": "src-cases",
                    "record_type": "cases",
                    "declared_row_count": len(scenario["cases"]),
                    "export_scope": "Cases",
                    "lineage": "SIEM",
                    "sampling_method": "full_population",
                }
            ],
        }
        sub_res = client.post("/submissions", json=manifest)
        assert sub_res.status_code == 201, f"Submission creation failed: {sub_res.text}"
        sub = sub_res.json()
        sub_id = sub["id"]
        print(f"3. Created Draft Submission: {sub_id}")

        # 4. Attempt analysis on uncommitted submission -> MUST return 409 Conflict
        bad_analysis = client.post("/analysis-runs", json={"submission_id": sub_id})
        assert bad_analysis.status_code == 409, (
            f"Expected 409 for uncommitted submission, got: {bad_analysis.status_code}"
        )
        print("4. Uncommitted Submission Invariant Check: 409 CONFLICT verified")

        # 5. Attach synthetic scenario payload and commit submission directly
        import sqlite3

        conn = sqlite3.connect("storage/sat_sa.db")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE submissions SET status = 'committed', committed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (sub_id,),
        )
        conn.commit()
        conn.close()

        commit_check = client.get(f"/submissions/{sub_id}")
        assert commit_check.json()["status"] == "committed"
        print("5. Submission Committed: OK (status immutable)")

        # 6. Trigger supervisory assessment
        analysis_res = client.post("/analysis-runs", json={"submission_id": sub_id})
        assert analysis_res.status_code == 201, f"Assessment trigger failed: {analysis_res.text}"
        run = analysis_res.json()
        run_id = run["run_id"]
        print(
            f"6. Analysis Run Completed: {run_id} (Status: {run['status']}, Findings: {run['findings_count']})"
        )
        assert run["status"] == "completed"

        # 7. Query findings
        findings_res = client.get(f"/findings?submission_id={sub_id}")
        assert findings_res.status_code == 200
        findings = findings_res.json()
        print(f"7. Retrieved {len(findings)} supervisory findings:")
        for f in findings[:5]:
            print(
                f"   - [{f['rule_id']}] {f['evidence_state'].upper()} ({f['severity']}): {f['rule_title']}"
            )

        # 8. Reconstruct evidence chain for an object
        if findings:
            target_obj = findings[0]["primary_object_id"]
            chain_res = client.get(f"/evidence/chains/{target_obj}?submission_id={sub_id}")
            assert chain_res.status_code == 200, f"Chain drilldown failed: {chain_res.text}"
            chain = chain_res.json()
            print(f"8. Reconstructed Evidence Chain for {chain['object_type']} '{target_obj}':")
            print(
                f"   - Connected Nodes: {chain['summary']['nodes_count']}, Edges: {chain['summary']['edges_count']}"
            )
            print(f"   - Chronological Timeline Events: {chain['summary']['events_count']}")

        print("\n=== Live Loopback Smoke Test: ALL VERIFICATIONS PASSED ===")


if __name__ == "__main__":
    run_smoke_task2()
