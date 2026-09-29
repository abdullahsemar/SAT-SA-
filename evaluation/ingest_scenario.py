"""Convert explicit synthetic evidence to intake files; never pass truth labels to analytics."""

import json
from copy import deepcopy

from packages.ingestion.manifest import ManifestDeclaration
from packages.ingestion.service import IngestionService


def ingest_scenario(scenario, db, storage_dir):
    aliases = {"claims": "reported_claims", "actions": "investigation_actions"}
    identity = {
        "assets": "asset_id",
        "alerts": "alert_id",
        "cases": "case_id",
        "claims": "claim_id",
        "actions": "action_id",
        "escalations": "escalation_id",
        "exceptions": "exception_id",
    }
    datasets = {}
    for key in (
        "assets",
        "alerts",
        "cases",
        "claims",
        "actions",
        "escalations",
        "case_alert_links",
        "exceptions",
        "coverage_observations",
    ):
        if key not in scenario:
            continue
        rows = deepcopy(scenario[key])
        for i, row in enumerate(rows):
            row.setdefault("native_id", row.get(identity.get(key, "native_id")) or f"{key}-{i}")
            if key == "claims":
                row.setdefault("metric_value", row.get("claimed_value"))
                row.setdefault("period", scenario["period_start"][:7])
                row.setdefault("period_start", scenario["period_start"])
                row.setdefault("period_end", scenario["period_end"])
            elif key == "cases":
                row.setdefault("status", "CLOSED" if row.get("closed_at") else "OPEN")
            elif key == "alerts":
                row.setdefault("title", row.get("rule_id") or "Synthetic alert")
                row.setdefault("source_tool", "synthetic_export")
                row.setdefault("triage_status", row.get("status", "UNKNOWN"))
                row.setdefault("affected_asset_id", row.get("asset_id"))
            elif key == "actions":
                row.setdefault("actor", row.get("created_by") or "synthetic_actor")
                row.setdefault("timestamp", row.get("created_at"))
            elif key == "escalations":
                row.setdefault("escalation_level", row.get("level") or "UNSPECIFIED")
                row.setdefault("notified_party", row.get("escalated_to") or "synthetic_recipient")
                row.setdefault("timestamp", row.get("escalated_at"))
        datasets[aliases.get(key, key)] = rows
    manifest = {
        "manifest_version": "1.0.0",
        "entity_id": scenario.get("cse_id", "CSE-BANK-01"),
        "period_start": scenario["period_start"],
        "period_end": scenario["period_end"],
        "source_timezone": "UTC",
        "sources": [],
    }
    for kind, rows in datasets.items():
        manifest["sources"].append(
            {
                "source_id": "src-" + kind,
                "record_type": kind,
                "declared_row_count": len(rows),
                "export_scope": "Full synthetic period export",
                "lineage": "Synthetic operational source",
                "sampling_method": "full_population",
            }
        )
    supplied = deepcopy(scenario.get("manifest", {}))
    if supplied:
        if "sources" in supplied:
            for source in supplied["sources"]:
                source["record_type"] = aliases.get(source["record_type"], source["record_type"])
        manifest.update(supplied)
    service = IngestionService(str(storage_dir))
    sub = service.create_draft(ManifestDeclaration.model_validate(manifest), db)
    for source in manifest["sources"]:
        kind = source["record_type"]
        if kind in datasets:
            service.save_file(
                sub.id, source["source_id"], kind + ".json", json.dumps(datasets[kind]).encode(), db
            )
    quality = service.validate_submission(sub.id, db)
    service.commit_submission(sub.id, sub.id, db)
    db.expire_all()
    return sub, quality
