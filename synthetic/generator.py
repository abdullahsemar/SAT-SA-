import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any


def make_iso_ts(year=2026, month=1, day=10, hour=12, minute=0, second=0) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


def write_csv_file(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_json_file(path: Path, data: Any):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_world_a_complete(output_dir: Path, seed: int = 42):
    random.seed(seed)
    world_dir = output_dir / "world_a_complete"
    submission_dir = world_dir / "submission"
    truth_dir = world_dir / "ground_truth"
    submission_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    entity_id = "CSE-BANK-01"
    period_start = "2026-01-01T00:00:00Z"
    period_end = "2026-02-01T00:00:00Z"

    # Assets
    assets = [
        {
            "native_id": "AST-001",
            "hostname": "core-banking-01",
            "ip_address": "10.0.1.15",
            "criticality": "CRITICAL",
            "owner": "Core Banking Team",
            "environment": "PROD",
            "timestamp": make_iso_ts(day=2),
        },
        {
            "native_id": "AST-002",
            "hostname": "auth-gateway-01",
            "ip_address": "10.0.1.20",
            "criticality": "HIGH",
            "owner": "IAM Operations",
            "environment": "PROD",
            "timestamp": make_iso_ts(day=2),
        },
        {
            "native_id": "AST-003",
            "hostname": "vpn-concentrator-02",
            "ip_address": "10.0.2.5",
            "criticality": "HIGH",
            "owner": "Network Ops",
            "environment": "PROD",
            "timestamp": make_iso_ts(day=3),
        },
    ]

    # Alerts
    alerts = [
        {
            "native_id": "ALT-1001",
            "timestamp": make_iso_ts(day=5, hour=8),
            "title": "Multiple Failed Authentication Attempts",
            "severity": "HIGH",
            "source_tool": "SIEM",
            "affected_asset_id": "AST-002",
            "triage_status": "ESCALATED",
        },
        {
            "native_id": "ALT-1002",
            "timestamp": make_iso_ts(day=5, hour=8, minute=15),
            "title": "Suspicious PowerShell Execution",
            "severity": "CRITICAL",
            "source_tool": "EDR",
            "affected_asset_id": "AST-001",
            "triage_status": "ESCALATED",
        },
        {
            "native_id": "ALT-1003",
            "timestamp": make_iso_ts(day=12, hour=14),
            "title": "Anomalous Outbound Data Transfer",
            "severity": "MEDIUM",
            "source_tool": "NDR",
            "affected_asset_id": "AST-003",
            "triage_status": "CLOSED",
        },
    ]

    # Cases
    cases = [
        {
            "native_id": "CAS-501",
            "created_at": make_iso_ts(day=5, hour=8, minute=30),
            "closed_at": make_iso_ts(day=6, hour=10),
            "severity": "HIGH",
            "status": "CLOSED",
            "assigned_analyst": "analyst-42",
            "root_cause": "Credential stuffing attack neutralized",
        },
    ]

    # Links
    links = [
        {
            "native_id": "LNK-01",
            "case_id": "CAS-501",
            "alert_id": "ALT-1001",
            "linked_at": make_iso_ts(day=5, hour=8, minute=35),
        },
        {
            "native_id": "LNK-02",
            "case_id": "CAS-501",
            "alert_id": "ALT-1002",
            "linked_at": make_iso_ts(day=5, hour=8, minute=36),
        },
    ]

    # Coverage Observations
    coverage = [
        {
            "native_id": "COV-01",
            "sensor_name": "Endpoint-CrowdStrike-Agent",
            "expected_eps": 500.0,
            "observed_eps": 485.5,
            "status": "ONLINE",
            "timestamp": make_iso_ts(day=15),
        },
        {
            "native_id": "COV-02",
            "sensor_name": "Network-CoreSwitch-NetFlow",
            "expected_eps": 2500.0,
            "observed_eps": 2480.0,
            "status": "ONLINE",
            "timestamp": make_iso_ts(day=15),
        },
    ]

    # Write evidence files
    write_csv_file(submission_dir / "assets.csv", list(assets[0].keys()), assets)
    write_csv_file(submission_dir / "alerts.csv", list(alerts[0].keys()), alerts)
    write_json_file(submission_dir / "cases.json", cases)
    write_json_file(submission_dir / "case_alert_links.json", links)
    write_json_file(submission_dir / "coverage_observations.json", coverage)

    # Parity check files (JSON version of assets and alerts for parity testing)
    write_json_file(submission_dir / "assets.json", assets)
    write_json_file(submission_dir / "alerts.json", alerts)

    # Manifest
    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": entity_id,
        "period_start": period_start,
        "period_end": period_end,
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-assets-csv",
                "record_type": "assets",
                "declared_row_count": len(assets),
                "export_scope": "Full IT Assets",
                "lineage": "CMDB -> CSV Export",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-alerts-csv",
                "record_type": "alerts",
                "declared_row_count": len(alerts),
                "export_scope": "All Security Alerts",
                "lineage": "SIEM Cluster -> CSV Export",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-cases-json",
                "record_type": "cases",
                "declared_row_count": len(cases),
                "export_scope": "All Investigated Cases",
                "lineage": "SOAR -> JSON Export",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-links-json",
                "record_type": "case_alert_links",
                "declared_row_count": len(links),
                "export_scope": "Case-Alert Relational Links",
                "lineage": "SOAR Link Table -> JSON",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-coverage-json",
                "record_type": "coverage_observations",
                "declared_row_count": len(coverage),
                "export_scope": "Sensor EPS Observations",
                "lineage": "Health Monitor -> JSON",
                "sampling_method": "full_population",
                "is_optional": False,
            },
        ],
    }
    write_json_file(submission_dir / "manifest.json", manifest)

    # Ground truth (kept completely separate from submission files)
    ground_truth = {
        "scenario": "complete_operations",
        "entity_id": entity_id,
        "expected_findings": [],
        "expected_issue_counts": {
            "rejected_count": 0,
            "duplicate_count": 0,
            "orphan_count": 0,
            "timestamp_problem_count": 0,
        },
        "operational_notes": "All telemetry consistent, zero anomalies.",
    }
    write_json_file(truth_dir / "ground_truth.json", ground_truth)


def generate_world_b_incomplete(output_dir: Path, seed: int = 101):
    random.seed(seed)
    world_dir = output_dir / "world_b_incomplete"
    submission_dir = world_dir / "submission"
    truth_dir = world_dir / "ground_truth"
    submission_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    entity_id = "CSE-BANK-01"
    period_start = "2026-01-01T00:00:00Z"
    period_end = "2026-02-01T00:00:00Z"

    # Assets
    assets = [
        {
            "native_id": "AST-101",
            "hostname": "db-prod-01",
            "ip_address": "10.1.0.4",
            "criticality": "CRITICAL",
            "owner": "DBA Team",
            "environment": "PROD",
            "timestamp": make_iso_ts(day=3),
        },
    ]

    # Alerts with intentional timestamp errors
    alerts = [
        {
            "native_id": "ALT-201",
            "timestamp": make_iso_ts(day=5),
            "title": "SQL Injection Attempt",
            "severity": "HIGH",
            "source_tool": "WAF",
            "affected_asset_id": "AST-101",
            "triage_status": "CLOSED",
        },
        {
            "native_id": "ALT-202",
            "timestamp": "2026-99-99T99:99:99Z",
            "title": "Malformed Timestamp Alert",
            "severity": "MEDIUM",
            "source_tool": "SIEM",
            "affected_asset_id": "AST-101",
            "triage_status": "UNREVIEWED",
        },
        {
            "native_id": "ALT-203",
            "timestamp": "2025-11-15T10:00:00Z",
            "title": "Out of Period Alert",
            "severity": "LOW",
            "source_tool": "SIEM",
            "affected_asset_id": "AST-101",
            "triage_status": "CLOSED",
        },
    ]

    # Cases
    cases = [
        {
            "native_id": "CAS-801",
            "created_at": make_iso_ts(day=5),
            "closed_at": make_iso_ts(day=6),
            "severity": "HIGH",
            "status": "CLOSED",
            "assigned_analyst": "analyst-12",
            "root_cause": "SQL injection blocked",
        },
    ]

    # Case-Alert Links with intentional orphan link
    links = [
        {
            "native_id": "LNK-201",
            "case_id": "CAS-801",
            "alert_id": "ALT-201",
            "linked_at": make_iso_ts(day=5),
        },
        {
            "native_id": "LNK-202",
            "case_id": "CAS-NONEXISTENT-999",
            "alert_id": "ALT-201",
            "linked_at": make_iso_ts(day=5),
        },  # Orphan case
    ]

    write_csv_file(submission_dir / "assets.csv", list(assets[0].keys()), assets)
    write_csv_file(submission_dir / "alerts.csv", list(alerts[0].keys()), alerts)
    write_json_file(submission_dir / "cases.json", cases)
    write_json_file(submission_dir / "case_alert_links.json", links)

    # Manifest intentionally declaring 10 rows for cases (actual: 1), and declaring an optional coverage source that is not uploaded
    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": entity_id,
        "period_start": period_start,
        "period_end": period_end,
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-assets-csv",
                "record_type": "assets",
                "declared_row_count": len(assets),
                "export_scope": "Assets",
                "lineage": "CMDB",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-alerts-csv",
                "record_type": "alerts",
                "declared_row_count": len(alerts),
                "export_scope": "Alerts",
                "lineage": "WAF/SIEM",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-cases-json",
                "record_type": "cases",
                "declared_row_count": 10,
                "export_scope": "Cases",
                "lineage": "SOAR",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-links-json",
                "record_type": "case_alert_links",
                "declared_row_count": len(links),
                "export_scope": "Links",
                "lineage": "SOAR",
                "sampling_method": "full_population",
                "is_optional": False,
            },
            {
                "source_id": "src-optional-coverage",
                "record_type": "coverage_observations",
                "declared_row_count": 5,
                "export_scope": "Coverage",
                "lineage": "Monitor",
                "sampling_method": "full_population",
                "is_optional": True,
            },
        ],
    }
    write_json_file(submission_dir / "manifest.json", manifest)

    ground_truth = {
        "scenario": "incomplete_export",
        "entity_id": entity_id,
        "expected_issues": [
            "MALFORMED_TIMESTAMP",
            "TIMESTAMP_OUT_OF_PERIOD",
            "ORPHAN_REFERENCE",
            "ROW_COUNT_MISMATCH",
            "OPTIONAL_SOURCE_MISSING",
        ],
    }
    write_json_file(truth_dir / "ground_truth.json", ground_truth)


def generate_world_c_reused_ids(output_dir: Path, seed: int = 202):
    random.seed(seed)
    world_dir = output_dir / "world_c_reused_ids"
    world_dir.mkdir(parents=True, exist_ok=True)

    # Generate two distinct entity packages: Entity 1 and Entity 2
    for entity_id, folder_name in [("CSE-BANK-01", "entity_1"), ("CSE-FINTECH-02", "entity_2")]:
        sub_dir = world_dir / folder_name / "submission"
        sub_dir.mkdir(parents=True, exist_ok=True)

        alerts = [
            {
                "native_id": "ALT-SHARED-001",
                "timestamp": make_iso_ts(day=10),
                "title": f"Brute force attempt on {entity_id}",
                "severity": "HIGH",
                "source_tool": "SIEM",
                "affected_asset_id": "UNKNOWN",
                "triage_status": "CLOSED",
            },
            {
                "native_id": "ALT-SHARED-002",
                "timestamp": make_iso_ts(day=11),
                "title": f"Malware beacon on {entity_id}",
                "severity": "CRITICAL",
                "source_tool": "EDR",
                "affected_asset_id": "UNKNOWN",
                "triage_status": "CLOSED",
            },
        ]

        # For entity 1, inject a conflicting duplicate to verify conflicting identity detection
        if entity_id == "CSE-BANK-01":
            alerts.append(
                {
                    "native_id": "ALT-SHARED-001",
                    "timestamp": make_iso_ts(day=10),
                    "title": "DIFFERENT TITLE CONFLICTING",
                    "severity": "LOW",
                    "source_tool": "SIEM",
                    "affected_asset_id": "UNKNOWN",
                    "triage_status": "OPEN",
                }
            )

        write_csv_file(sub_dir / "alerts.csv", list(alerts[0].keys()), alerts)

        manifest = {
            "manifest_version": "1.0.0",
            "entity_id": entity_id,
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-02-01T00:00:00Z",
            "source_timezone": "UTC",
            "sources": [
                {
                    "source_id": "src-alerts-csv",
                    "record_type": "alerts",
                    "declared_row_count": len(alerts),
                    "export_scope": "Alerts",
                    "lineage": "SIEM",
                    "sampling_method": "full_population",
                    "is_optional": False,
                },
            ],
        }
        write_json_file(sub_dir / "manifest.json", manifest)


def generate_synthetic_worlds(output_dir: str = "synthetic/fixtures"):
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    generate_world_a_complete(out_path)
    generate_world_b_incomplete(out_path)
    generate_world_c_reused_ids(out_path)
    print(f"Synthetic worlds generated under: {out_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic evidence worlds for SAT-SA")
    parser.add_argument("--output-dir", default="synthetic/fixtures", help="Output directory")
    args = parser.parse_args()
    generate_synthetic_worlds(args.output_dir)


if __name__ == "__main__":
    main()
