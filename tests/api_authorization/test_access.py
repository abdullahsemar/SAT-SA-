import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.auth import create_user_session
from db.models.evidence import NormalizedRecord
from tests.conftest import authenticate_user


def test_anonymous_access_fails(client: TestClient):
    """Verifies that unauthenticated requests to protected endpoints return 401."""
    # List submissions
    res1 = client.get("/api/v1/submissions")
    assert res1.status_code == 401
    assert res1.json()["code"] == "UNAUTHORIZED"

    # Create submission
    res2 = client.post(
        "/api/v1/submissions",
        json={
            "manifest_version": "1.0.0",
            "entity_id": "CSE-BANK-01",
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-02-01T00:00:00Z",
            "source_timezone": "UTC",
            "sources": [],
        },
    )
    assert res2.status_code == 401

    # Record lookup
    res3 = client.get("/api/v1/evidence/records/rec-dummy-id")
    assert res3.status_code == 401


def test_wrong_entity_access_fails(
    client: TestClient, db_session: Session, bank_examiner, fintech_examiner
):
    """Verifies that an examiner scoped to CSE-BANK-01 cannot access or submit for CSE-FINTECH-02."""
    headers_bank = authenticate_user(client, bank_examiner, db_session)

    # Bank examiner tries to create submission for Fintech
    fintech_manifest = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-FINTECH-02",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-alerts",
                "record_type": "alerts",
                "declared_row_count": 1,
                "export_scope": "Alerts",
                "lineage": "SIEM",
                "sampling_method": "full_population",
                "is_optional": False,
            }
        ],
    }

    res = client.post("/api/v1/submissions", json=fintech_manifest, headers=headers_bank)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert "Access denied to entity 'CSE-FINTECH-02'" in res.json()["message"]


def test_cross_entity_record_inspection_blocked(
    client: TestClient, db_session: Session, bank_examiner, fintech_examiner
):
    """Verifies that an examiner cannot inspect a record belonging to another entity."""
    # Create submission and record for Fintech
    fintech_headers = authenticate_user(client, fintech_examiner, db_session)
    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-FINTECH-02",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-assets",
                "record_type": "assets",
                "declared_row_count": 1,
                "export_scope": "Assets",
                "lineage": "CMDB",
                "sampling_method": "full_population",
                "is_optional": False,
            }
        ],
    }

    sub_res = client.post("/api/v1/submissions", json=manifest, headers=fintech_headers)
    sub_id = sub_res.json()["id"]

    data = "native_id,hostname,ip_address,criticality,owner,environment\nAST-F1,fin-host,10.2.0.1,HIGH,FinSec,PROD\n".encode(
        "utf-8"
    )
    client.post(
        f"/api/v1/submissions/{sub_id}/files",
        data={"source_id": "src-assets"},
        files={"file": ("assets.csv", data, "text/csv")},
        headers=fintech_headers,
    )
    client.post(f"/api/v1/submissions/{sub_id}/validate", headers=fintech_headers)

    # Get created record
    record = (
        db_session.query(NormalizedRecord).filter(NormalizedRecord.submission_id == sub_id).first()
    )
    assert record is not None

    # Authenticate as bank examiner and attempt to access fintech record
    bank_headers = authenticate_user(client, bank_examiner, db_session)
    forbidden_res = client.get(f"/api/v1/evidence/records/{record.id}", headers=bank_headers)
    assert forbidden_res.status_code == 403
    assert "Access denied to entity 'CSE-FINTECH-02'" in forbidden_res.json()["message"]


def test_admin_global_access(client: TestClient, db_session: Session, admin_user, bank_examiner):
    """Verifies that an admin user with wildcard scope can view and interact with any entity."""
    admin_headers = authenticate_user(client, admin_user, db_session)

    # Admin creates submission for CSE-BANK-01
    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-BANK-01",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-alerts",
                "record_type": "alerts",
                "declared_row_count": 0,
                "export_scope": "Empty",
                "lineage": "SIEM",
                "sampling_method": "full_population",
                "is_optional": True,
            }
        ],
    }

    res = client.post("/api/v1/submissions", json=manifest, headers=admin_headers)
    assert res.status_code == 201

    # Admin lists submissions
    list_res = client.get("/api/v1/submissions", headers=admin_headers)
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1


def test_csrf_protection(client: TestClient, db_session: Session, bank_examiner):
    """Verifies that state-changing requests using cookie authentication without a valid CSRF header are rejected."""
    # Authenticate and set cookie only, without providing X-CSRF-Token header
    token, csrf_token, _ = create_user_session(bank_examiner, db_session)
    client.cookies.set("sat_session", token)

    # Safe GET succeeds without CSRF
    get_res = client.get("/api/v1/submissions")
    assert get_res.status_code == 200

    test_manifest = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-BANK-01",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-alerts",
                "record_type": "alerts",
                "declared_row_count": 0,
                "export_scope": "Empty",
                "lineage": "SIEM",
                "sampling_method": "full_population",
                "is_optional": True,
            }
        ],
    }

    # Unsafe POST without CSRF header fails
    post_res_no_csrf = client.post(
        "/api/v1/submissions",
        json=test_manifest,
    )
    assert post_res_no_csrf.status_code == 403
    assert "CSRF validation failed" in post_res_no_csrf.json()["message"]

    # Unsafe POST with incorrect CSRF header fails
    post_res_bad_csrf = client.post(
        "/api/v1/submissions",
        json=test_manifest,
        headers={"X-CSRF-Token": "invalid-csrf-token-12345"},
    )
    assert post_res_bad_csrf.status_code == 403

    # Unsafe POST with correct CSRF header succeeds
    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-BANK-01",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-alerts",
                "record_type": "alerts",
                "declared_row_count": 0,
                "export_scope": "Empty",
                "lineage": "SIEM",
                "sampling_method": "full_population",
                "is_optional": True,
            }
        ],
    }
    post_res_valid = client.post(
        "/api/v1/submissions",
        json=manifest,
        headers={"X-CSRF-Token": csrf_token},
    )
    assert post_res_valid.status_code == 201


def test_auth_login_logout_flow(client: TestClient, db_session: Session, bank_examiner):
    """Verifies user login, session cookie setting, me endpoint, and logout cookie invalidation."""
    # 1. Invalid credentials
    bad_login = client.post(
        "/api/v1/auth/login",
        json={"username": "bank_examiner_test", "password": "WrongPassword!"},
    )
    assert bad_login.status_code == 401

    # 2. Valid credentials
    good_login = client.post(
        "/api/v1/auth/login",
        json={"username": "bank_examiner_test", "password": "ExaminerPass123!"},
    )
    assert good_login.status_code == 200
    login_data = good_login.json()
    assert login_data["username"] == "bank_examiner_test"
    assert "sat_session" in client.cookies
    csrf_token = login_data["csrf_token"]
    assert csrf_token is not None

    # 3. GET /api/v1/auth/me
    me_res = client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "bank_examiner_test"

    # 4. Logout
    logout_res = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert logout_res.status_code == 200

    # 5. Subsequent request should fail (session invalidated)
    after_res = client.get("/api/v1/auth/me")
    assert after_res.status_code == 401


def test_empty_and_malformed_scope_deny_access(
    client: TestClient, db_session: Session, bank_examiner
):
    """Verifies that empty or malformed scopes fail closed and grant zero entity access."""
    # 1. Empty scope []
    bank_examiner.entity_scope = "[]"
    db_session.commit()
    headers_empty = authenticate_user(client, bank_examiner, db_session)

    # List submissions returns empty list
    res_list = client.get("/api/v1/submissions", headers=headers_empty)
    assert res_list.status_code == 200
    assert res_list.json()["items"] == []

    dummy_sources = [
        {
            "source_id": "src-alerts",
            "record_type": "alerts",
            "declared_row_count": 0,
            "export_scope": "Alerts",
            "lineage": "SIEM",
            "sampling_method": "full_population",
            "is_optional": True,
        }
    ]

    # Direct submission creation fails with 403
    res_sub = client.post(
        "/api/v1/submissions",
        json={
            "manifest_version": "1.0.0",
            "entity_id": "CSE-BANK-01",
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-02-01T00:00:00Z",
            "source_timezone": "UTC",
            "sources": dummy_sources,
        },
        headers=headers_empty,
    )
    assert res_sub.status_code == 403
    assert "Access denied to entity" in res_sub.json()["message"]

    # 2. Malformed scope (invalid JSON or non-string array)
    bank_examiner.entity_scope = "{invalid:json}"
    db_session.commit()
    headers_bad = authenticate_user(client, bank_examiner, db_session)

    res_list_bad = client.get("/api/v1/submissions", headers=headers_bad)
    assert res_list_bad.status_code == 200
    assert res_list_bad.json()["items"] == []

    res_sub_bad = client.post(
        "/api/v1/submissions",
        json={
            "manifest_version": "1.0.0",
            "entity_id": "CSE-BANK-01",
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-02-01T00:00:00Z",
            "source_timezone": "UTC",
            "sources": dummy_sources,
        },
        headers=headers_bad,
    )
    assert res_sub_bad.status_code == 403


def test_multiple_authorized_entities_supported(
    client: TestClient, db_session: Session, bank_examiner
):
    """Verifies that an examiner with multiple authorized entities can access all authorized entities, but not third."""
    # Scope includes both ENT-A and ENT-B, but not ENT-C
    bank_examiner.entity_scope = json.dumps(["CSE-BANK-01", "CSE-FINTECH-02"])
    db_session.commit()
    headers = authenticate_user(client, bank_examiner, db_session)

    dummy_sources = [
        {
            "source_id": "src-alerts",
            "record_type": "alerts",
            "declared_row_count": 0,
            "export_scope": "Alerts",
            "lineage": "SIEM",
            "sampling_method": "full_population",
            "is_optional": True,
        }
    ]

    # Can submit for CSE-BANK-01
    res1 = client.post(
        "/api/v1/submissions",
        json={
            "manifest_version": "1.0.0",
            "entity_id": "CSE-BANK-01",
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-02-01T00:00:00Z",
            "source_timezone": "UTC",
            "sources": dummy_sources,
        },
        headers=headers,
    )
    assert res1.status_code == 201

    # Can submit for CSE-FINTECH-02 (never drop second entity)
    res2 = client.post(
        "/api/v1/submissions",
        json={
            "manifest_version": "1.0.0",
            "entity_id": "CSE-FINTECH-02",
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-02-01T00:00:00Z",
            "source_timezone": "UTC",
            "sources": dummy_sources,
        },
        headers=headers,
    )
    assert res2.status_code == 201

    # Cannot submit for CSE-OTHER-03
    res3 = client.post(
        "/api/v1/submissions",
        json={
            "manifest_version": "1.0.0",
            "entity_id": "CSE-OTHER-03",
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-02-01T00:00:00Z",
            "source_timezone": "UTC",
            "sources": dummy_sources,
        },
        headers=headers,
    )
    assert res3.status_code == 403
    assert "Access denied to entity 'CSE-OTHER-03'" in res3.json()["message"]
