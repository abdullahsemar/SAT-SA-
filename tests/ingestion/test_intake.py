import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.evidence import NormalizedRecord, RawRecord
from tests.conftest import authenticate_user


def test_csv_json_parity(client: TestClient, db_session: Session, bank_examiner):
    """Criterion 1: A valid CSV and an equivalent JSON submission produce equivalent normalized records and traceable row references."""
    headers = authenticate_user(client, bank_examiner, db_session)

    # 1. Submit with CSV
    manifest_csv = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-BANK-01",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-alerts",
                "record_type": "alerts",
                "declared_row_count": 2,
                "export_scope": "Alerts CSV",
                "lineage": "SIEM",
                "sampling_method": "full_population",
                "is_optional": False,
            }
        ],
    }

    res = client.post("/api/v1/submissions", json=manifest_csv, headers=headers)
    assert res.status_code == 201, res.text
    sub_csv_id = res.json()["id"]

    csv_data = (
        "native_id,timestamp,title,severity,source_tool,affected_asset_id,triage_status\n"
        "ALT-001,2026-01-10T12:00:00Z,Brute Force,HIGH,SIEM,AST-01,CLOSED\n"
        "ALT-002,2026-01-10T12:05:00Z,Port Scan,LOW,SIEM,AST-02,CLOSED\n"
    ).encode("utf-8")

    file_res = client.post(
        f"/api/v1/submissions/{sub_csv_id}/files",
        data={"source_id": "src-alerts"},
        files={"file": ("alerts.csv", csv_data, "text/csv")},
        headers=headers,
    )
    assert file_res.status_code == 200, file_res.text

    val_res = client.post(f"/api/v1/submissions/{sub_csv_id}/validate", headers=headers)
    assert val_res.status_code == 200, val_res.text
    csv_quality = val_res.json()
    assert csv_quality["accepted_count"] == 2
    assert csv_quality["rejected_count"] == 0

    # 2. Submit identical content with JSON
    manifest_json = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-BANK-01",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-alerts",
                "record_type": "alerts",
                "declared_row_count": 2,
                "export_scope": "Alerts JSON",
                "lineage": "SIEM",
                "sampling_method": "full_population",
                "is_optional": False,
            }
        ],
    }

    res2 = client.post("/api/v1/submissions", json=manifest_json, headers=headers)
    assert res2.status_code == 201
    sub_json_id = res2.json()["id"]

    json_data = json.dumps(
        [
            {
                "native_id": "ALT-001",
                "timestamp": "2026-01-10T12:00:00Z",
                "title": "Brute Force",
                "severity": "HIGH",
                "source_tool": "SIEM",
                "affected_asset_id": "AST-01",
                "triage_status": "CLOSED",
            },
            {
                "native_id": "ALT-002",
                "timestamp": "2026-01-10T12:05:00Z",
                "title": "Port Scan",
                "severity": "LOW",
                "source_tool": "SIEM",
                "affected_asset_id": "AST-02",
                "triage_status": "CLOSED",
            },
        ]
    ).encode("utf-8")

    file_res2 = client.post(
        f"/api/v1/submissions/{sub_json_id}/files",
        data={"source_id": "src-alerts"},
        files={"file": ("alerts.json", json_data, "application/json")},
        headers=headers,
    )
    assert file_res2.status_code == 200

    val_res2 = client.post(f"/api/v1/submissions/{sub_json_id}/validate", headers=headers)
    assert val_res2.status_code == 200
    json_quality = val_res2.json()
    assert json_quality["accepted_count"] == 2

    # Verify equivalent normalized records between CSV and JSON submissions
    csv_records = (
        db_session.execute(
            select(NormalizedRecord)
            .where(NormalizedRecord.submission_id == sub_csv_id)
            .order_by(NormalizedRecord.native_id)
        )
        .scalars()
        .all()
    )

    json_records = (
        db_session.execute(
            select(NormalizedRecord)
            .where(NormalizedRecord.submission_id == sub_json_id)
            .order_by(NormalizedRecord.native_id)
        )
        .scalars()
        .all()
    )

    assert len(csv_records) == len(json_records) == 2
    for cr, jr in zip(csv_records, json_records):
        assert cr.native_id == jr.native_id
        assert cr.record_type == jr.record_type
        assert json.loads(cr.normalized_data) == json.loads(jr.normalized_data)

    # Verify traceable row references
    csv_raw = db_session.get(RawRecord, csv_records[0].raw_record_id)
    json_raw = db_session.get(RawRecord, json_records[0].raw_record_id)
    assert csv_raw.row_locator == "row:1"
    assert json_raw.row_locator == "index:0"


def test_malformed_timestamps_duplicates_and_cross_entity_issues(
    client: TestClient, db_session: Session, bank_examiner
):
    """Criterion 2: Malformed timestamps, missing required IDs, conflicting duplicates, path-like filenames and cross-entity references are safely handled with explicit issues."""
    headers = authenticate_user(client, bank_examiner, db_session)

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
                "declared_row_count": 4,
                "export_scope": "Dirty Alerts",
                "lineage": "SIEM",
                "sampling_method": "full_population",
                "is_optional": False,
            }
        ],
    }

    sub_res = client.post("/api/v1/submissions", json=manifest, headers=headers)
    sub_id = sub_res.json()["id"]

    # Alerts data with:
    # 1. Malformed timestamp: "not-a-timestamp"
    # 2. Missing required ID: empty native_id
    # 3. Conflicting duplicate: ALT-999 with different titles
    # 4. Cross-entity reference: mentions CSE-OTHER-99
    csv_dirty = (
        "native_id,timestamp,title,severity,source_tool,affected_asset_id,triage_status\n"
        "ALT-001,not-a-timestamp,Title 1,HIGH,SIEM,AST-1,CLOSED\n"
        ",2026-01-10T12:00:00Z,Missing ID Alert,HIGH,SIEM,AST-1,CLOSED\n"
        "ALT-999,2026-01-10T12:00:00Z,Legitimate Title,HIGH,SIEM,AST-1,CLOSED\n"
        "ALT-999,2026-01-10T12:00:00Z,CONFLICTING DIFFERENT TITLE,LOW,SIEM,AST-1,CLOSED\n"
        "ALT-CROSS,2026-01-10T12:00:00Z,Cross Entity Alert,HIGH,SIEM,CSE-OTHER-99/asset-01,CLOSED\n"
    ).encode("utf-8")

    # Path traversal filename test: should be sanitized safely
    file_res = client.post(
        f"/api/v1/submissions/{sub_id}/files",
        data={"source_id": "src-alerts"},
        files={"file": ("../../etc/passwd.csv", csv_dirty, "text/csv")},
        headers=headers,
    )
    assert file_res.status_code == 200
    saved_filename = file_res.json()["original_filename"]
    assert "/" not in saved_filename and ".." not in saved_filename

    # Validate
    val_res = client.post(f"/api/v1/submissions/{sub_id}/validate", headers=headers)
    assert val_res.status_code == 200
    report = val_res.json()

    issue_types = [i["issue_type"] for i in report["issues"]]
    assert "MALFORMED_TIMESTAMP" in issue_types
    assert "MISSING_REQUIRED_FIELD" in issue_types
    assert "CONFLICTING_IDENTITY" in issue_types
    assert "CROSS_ENTITY_REFERENCE" in issue_types
    assert report["rejected_count"] >= 2


def test_missing_optional_sources_reported_as_unknown(
    client: TestClient, db_session: Session, bank_examiner
):
    """Criterion 3: Missing optional sources are reported as unknown, not healthy or failed."""
    headers = authenticate_user(client, bank_examiner, db_session)

    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-BANK-01",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-mandatory-assets",
                "record_type": "assets",
                "declared_row_count": 1,
                "export_scope": "Assets",
                "lineage": "CMDB",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-optional-coverage",
                "record_type": "coverage_observations",
                "declared_row_count": 2,
                "export_scope": "Coverage",
                "lineage": "Sensors",
                "sampling_method": "full_population",
                "is_optional": True,
            },
        ],
    }

    sub_res = client.post("/api/v1/submissions", json=manifest, headers=headers)
    sub_id = sub_res.json()["id"]

    # Upload only the mandatory assets file
    asset_data = (
        "native_id,hostname,ip_address,criticality,owner,environment,timestamp\n"
        "AST-1,host-1,10.0.0.1,HIGH,SecOps,PROD,2026-01-05T00:00:00Z\n"
    ).encode("utf-8")

    client.post(
        f"/api/v1/submissions/{sub_id}/files",
        data={"source_id": "src-mandatory-assets"},
        files={"file": ("assets.csv", asset_data, "text/csv")},
        headers=headers,
    )

    # Validate
    val_res = client.post(f"/api/v1/submissions/{sub_id}/validate", headers=headers)
    assert val_res.status_code == 200
    report = val_res.json()

    # Verify optional source is classified as UNKNOWN
    opt_summary = report["source_summaries"]["src-optional-coverage"]
    assert opt_summary["status"] == "UNKNOWN"
    assert opt_summary["is_optional"] is True

    # Check that issue raised is INFO severity OPTIONAL_SOURCE_MISSING, not ERROR or FAILED
    opt_issues = [i for i in report["issues"] if i["source_id"] == "src-optional-coverage"]
    assert len(opt_issues) == 1
    assert opt_issues[0]["issue_type"] == "OPTIONAL_SOURCE_MISSING"
    assert opt_issues[0]["severity"] == "info"


def test_commit_idempotency_and_immutability(
    client: TestClient, db_session: Session, bank_examiner
):
    """Criterion 4: Retrying commit does not duplicate data; accepted data survives restart and cannot be edited in place."""
    headers = authenticate_user(client, bank_examiner, db_session)

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
                "declared_row_count": 1,
                "export_scope": "Alerts",
                "lineage": "SIEM",
                "sampling_method": "full_population",
                "is_optional": False,
            }
        ],
    }

    sub_res = client.post("/api/v1/submissions", json=manifest, headers=headers)
    sub_id = sub_res.json()["id"]

    data = (
        "native_id,timestamp,title,severity,source_tool,affected_asset_id,triage_status\n"
        "ALT-IMM-1,2026-01-10T12:00:00Z,Imm Alert,HIGH,SIEM,AST-1,CLOSED\n"
    ).encode("utf-8")

    client.post(
        f"/api/v1/submissions/{sub_id}/files",
        data={"source_id": "src-alerts"},
        files={"file": ("alerts.csv", data, "text/csv")},
        headers=headers,
    )

    client.post(f"/api/v1/submissions/{sub_id}/validate", headers=headers)

    # First commit with idempotency key
    idempotency_key = "idemp-key-test-12345"
    commit1 = client.post(
        f"/api/v1/submissions/{sub_id}/commit",
        json={"idempotency_key": idempotency_key},
        headers=headers,
    )
    assert commit1.status_code == 200
    assert commit1.json()["status"] == "committed"

    # Retry commit with identical idempotency key -> Must succeed without duplicating data
    commit_retry = client.post(
        f"/api/v1/submissions/{sub_id}/commit",
        json={"idempotency_key": idempotency_key},
        headers=headers,
    )
    assert commit_retry.status_code == 200
    assert commit_retry.json()["id"] == sub_id

    # Verify row counts did not duplicate in database
    records = (
        db_session.execute(select(NormalizedRecord).where(NormalizedRecord.submission_id == sub_id))
        .scalars()
        .all()
    )
    assert len(records) == 1

    # Verify committed submission cannot be modified in place
    upload_after_commit = client.post(
        f"/api/v1/submissions/{sub_id}/files",
        data={"source_id": "src-alerts"},
        files={"file": ("alerts.csv", data, "text/csv")},
        headers=headers,
    )
    assert upload_after_commit.status_code == 409

    val_after_commit = client.post(f"/api/v1/submissions/{sub_id}/validate", headers=headers)
    assert val_after_commit.status_code == 409


def test_record_provenance_inspection(client: TestClient, db_session: Session, bank_examiner):
    """Verifies that an authorized user can inspect a normalized record, retrieve original raw record payload, row locator, and SHA-256."""
    headers = authenticate_user(client, bank_examiner, db_session)

    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": "CSE-BANK-01",
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

    sub_id = client.post("/api/v1/submissions", json=manifest, headers=headers).json()["id"]

    asset_csv = (
        "native_id,hostname,ip_address,criticality,owner,environment,timestamp\n"
        "AST-PROV-1,prov-host,10.10.10.10,CRITICAL,Lead Analyst,PROD,2026-01-05T12:00:00Z\n"
    ).encode("utf-8")

    client.post(
        f"/api/v1/submissions/{sub_id}/files",
        data={"source_id": "src-assets"},
        files={"file": ("assets.csv", asset_csv, "text/csv")},
        headers=headers,
    )

    client.post(f"/api/v1/submissions/{sub_id}/validate", headers=headers)
    client.post(f"/api/v1/submissions/{sub_id}/commit", headers=headers)

    # Query normalized record ID
    record = db_session.execute(
        select(NormalizedRecord).where(NormalizedRecord.submission_id == sub_id)
    ).scalar_one()

    # Fetch via API
    res = client.get(f"/api/v1/evidence/records/{record.id}", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == record.id
    assert body["native_id"] == "AST-PROV-1"
    assert body["row_locator"] == "row:1"
    assert body["raw_sha256"] is not None
    assert body["raw_payload"]["hostname"] == "prov-host"
    assert body["normalized_data"]["criticality"] == "CRITICAL"
