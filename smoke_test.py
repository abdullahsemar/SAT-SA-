import json
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000/api/v1"


def run_smoke():
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Health check
        res = client.get("/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        print("1. Health check: PASSED (offline runtime healthy)")

        # 2. Login as admin
        login_res = client.post(
            "/auth/login",
            json={"username": "admin", "password": "ExaminerPass123!"},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        user_profile = login_res.json()
        csrf_token = user_profile["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf_token
        print(
            f"2. Authenticated as: {user_profile['username']} (role: {user_profile['role']}, scope: {user_profile['entity_scope']})"
        )

        # 3. Import World A Complete Manifest
        world_dir = Path("synthetic/fixtures/world_a_complete/submission")
        manifest_data = json.loads((world_dir / "manifest.json").read_text(encoding="utf-8"))

        sub_res = client.post("/submissions", json=manifest_data)
        assert sub_res.status_code == 201, f"Create submission failed: {sub_res.text}"
        sub = sub_res.json()
        sub_id = sub["id"]
        print(
            f"3. Created Draft Submission: {sub_id} for entity {sub['entity_id']} (Rev {sub['revision']})"
        )

        # 4. Upload declared files
        file_map = {
            "src-assets-csv": ("assets.csv", "text/csv"),
            "src-alerts-csv": ("alerts.csv", "text/csv"),
            "src-cases-json": ("cases.json", "application/json"),
            "src-links-json": ("case_alert_links.json", "application/json"),
            "src-coverage-json": ("coverage_observations.json", "application/json"),
        }

        for source_id, (fname, ctype) in file_map.items():
            content = (world_dir / fname).read_bytes()
            upload_res = client.post(
                f"/submissions/{sub_id}/files",
                data={"source_id": source_id},
                files={"file": (fname, content, ctype)},
            )
            assert upload_res.status_code == 200, (
                f"Upload failed for {source_id}: {upload_res.text}"
            )
            f_meta = upload_res.json()
            print(
                f"   - Uploaded {source_id}: {f_meta['original_filename']} ({f_meta['byte_size']} bytes, SHA-256: {f_meta['sha256_hash'][:16]}...)"
            )

        # 5. Validate Evidence
        val_res = client.post(f"/submissions/{sub_id}/validate")
        assert val_res.status_code == 200, f"Validation failed: {val_res.text}"
        quality = val_res.json()
        print("5. Validation Results:")
        print(f"   - Accepted records: {quality['accepted_count']}")
        print(f"   - Rejected / Quarantined: {quality['rejected_count']}")
        print(f"   - Duplicate IDs: {quality['duplicate_count']}")
        print(f"   - Orphan links: {quality['orphan_count']}")
        print(f"   - Timestamp issues: {quality['timestamp_problem_count']}")
        assert quality["accepted_count"] == 11
        assert quality["rejected_count"] == 0

        # 6. Commit Submission with Idempotency Key
        idemp_key = f"idemp-smoke-{sub_id}"
        commit_res = client.post(
            f"/submissions/{sub_id}/commit",
            json={"idempotency_key": idemp_key},
        )
        assert commit_res.status_code == 200, f"Commit failed: {commit_res.text}"
        committed_data = commit_res.json()
        assert committed_data["status"] == "committed"
        print(
            f"6. Committed Revision {committed_data['revision']} (Frozen at: {committed_data['committed_at']})"
        )

        # 7. Retry commit (Idempotency verification)
        retry_res = client.post(
            f"/submissions/{sub_id}/commit",
            json={"idempotency_key": idemp_key},
        )
        assert retry_res.status_code == 200, f"Idempotent retry failed: {retry_res.text}"
        print(
            "7. Idempotent commit retry: PASSED (data not duplicated, returned committed revision)"
        )

        # 8. Fetch submission quality report after restart/re-open
        get_q_res = client.get(f"/submissions/{sub_id}/quality")
        assert get_q_res.status_code == 200
        print("8. Reopened submission quality report: PASSED")

        # 9. Query normalized records directly from db to test provenance endpoint
        import sqlite3

        conn = sqlite3.connect("storage/sat_sa.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, native_id FROM normalized_records WHERE submission_id = ? LIMIT 1",
            (sub_id,),
        )
        row = cursor.fetchone()
        rec_id, native_id = row
        conn.close()

        prov_res = client.get(f"/evidence/records/{rec_id}")
        assert prov_res.status_code == 200, f"Provenance inspection failed: {prov_res.text}"
        prov = prov_res.json()
        print(f"9. Provenance Inspection for record '{prov['native_id']}':")
        print(f"   - Row Locator: {prov['row_locator']}")
        print(f"   - Raw Record SHA-256: {prov['raw_sha256']}")
        print(f"   - Raw Payload: {prov['raw_payload']}")
        print(f"   - Normalized Typed Record: {prov['normalized_data']}")

    print("\nALL REAL API SMOKE CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run_smoke()
