"""Explicit unit-test record adapter; production analytics has no scenario-data bypass.

This creates detached ORM fixtures, not an ingestion acceptance test. End-to-end
coverage is in test_audit_regressions and the real-ingestion evaluation harness.
"""

import hashlib
import json
import uuid

from db.models.evidence import NormalizedRecord, RawRecord, SubmissionFile


def attach_scenario(sub, scenario):
    aliases = {
        "actions": "investigation_actions",
        "claims": "reported_claims",
        "remediations": "remediations_validations",
    }
    kinds = {
        "assets",
        "alerts",
        "cases",
        "case_alert_links",
        "actions",
        "investigation_actions",
        "claims",
        "reported_claims",
        "escalations",
        "coverage_observations",
        "exceptions",
        "ownership",
        "remediations",
        "remediations_validations",
    }
    manifest = json.loads(sub.manifest_json or "{}")
    manifest = (
        manifest
        if "sources" in manifest
        else {
            "manifest_version": "1.0.0",
            "entity_id": sub.entity_id,
            "period_start": sub.period_start.isoformat(),
            "period_end": sub.period_end.isoformat(),
            "source_timezone": "UTC",
            "sources": [],
        }
    )
    manifest.setdefault("entity_id", sub.entity_id)
    manifest.setdefault("manifest_version", "1.0.0")
    manifest.setdefault("period_start", sub.period_start.isoformat())
    manifest.setdefault("period_end", sub.period_end.isoformat())
    manifest.setdefault("source_timezone", "UTC")
    supplied_manifest = scenario.get("manifest")
    if supplied_manifest:
        manifest.update(supplied_manifest)
    sources = {aliases.get(s["record_type"], s["record_type"]): s for s in manifest["sources"]}
    sub.files, sub.raw_records, sub.normalized_records = [], [], []
    for key, rows in scenario.items():
        if key not in kinds or not isinstance(rows, list):
            continue
        kind = aliases.get(key, key)
        src = sources.setdefault(
            kind,
            {
                "source_id": "src-" + kind,
                "record_type": kind,
                "declared_row_count": len(rows),
                "export_scope": "Full fixture export",
                "lineage": "Unit fixture",
                "sampling_method": "full_population",
            },
        )
        src["record_type"] = kind
        payload = json.dumps(rows, sort_keys=True).encode()
        sub.files.append(
            SubmissionFile(
                id=str(uuid.uuid4()),
                submission_id=sub.id,
                source_id=src["source_id"],
                record_type=kind,
                original_filename=kind + ".json",
                storage_path="unit-fixture/" + kind + ".json",
                sha256_hash=hashlib.sha256(payload).hexdigest(),
                byte_size=len(payload),
                declared_row_count=src["declared_row_count"],
                actual_row_count=len(rows),
            )
        )
        for i, row in enumerate(rows):
            data = dict(row)
            native = next(
                (
                    str(row[k])
                    for k in (
                        "native_id",
                        "case_id"
                        if kind == "cases"
                        else "asset_id"
                        if kind == "assets"
                        else "alert_id"
                        if kind == "alerts"
                        else "claim_id"
                        if kind == "reported_claims"
                        else "action_id"
                        if kind == "investigation_actions"
                        else "escalation_id"
                        if kind == "escalations"
                        else "id",
                    )
                    if row.get(k)
                ),
                f"{kind}-{i}",
            )
            data["native_id"] = native
            if kind == "reported_claims":
                data.setdefault("metric_value", data.get("claimed_value"))
                data.setdefault("period", str(sub.period_start)[:7])
                data.setdefault("period_start", sub.period_start.isoformat())
                data.setdefault("period_end", sub.period_end.isoformat())
            raw_text = json.dumps(row, sort_keys=True)
            raw = RawRecord(
                id=str(uuid.uuid4()),
                submission_id=sub.id,
                source_id=src["source_id"],
                record_type=kind,
                row_locator=f"index:{i}",
                raw_payload=raw_text,
                sha256_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
            )
            sub.raw_records.append(raw)
            sub.normalized_records.append(
                NormalizedRecord(
                    id=str(uuid.uuid4()),
                    raw_record_id=raw.id,
                    submission_id=sub.id,
                    entity_id=sub.entity_id,
                    source_id=src["source_id"],
                    record_type=kind,
                    native_id=native,
                    normalized_data=json.dumps(data),
                    is_quarantined=False,
                )
            )
    manifest["sources"] = list(sources.values())
    sub.manifest_json = json.dumps(manifest)
    return sub
