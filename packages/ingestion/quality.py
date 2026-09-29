import datetime
import math
from dataclasses import dataclass, field
from typing import Any

from packages.ingestion.claim_contract import claim_period, percentage_metric
from packages.ingestion.manifest import ManifestDeclaration


def parse_iso_datetime(val: Any) -> datetime.datetime | None:
    if val is None or val == "" or val == "UNKNOWN":
        return None
    if isinstance(val, datetime.datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=datetime.timezone.utc)
        return val.astimezone(datetime.timezone.utc)
    if not isinstance(val, str):
        raise ValueError(f"Expected datetime string, got {type(val).__name__}")

    s = val.strip()
    if not s or s == "UNKNOWN":
        return None

    # Replace trailing 'Z' with '+00:00' for standard fromisoformat
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = dt.astimezone(datetime.timezone.utc)
        return dt
    except Exception as e:
        raise ValueError(f"Invalid ISO-8601 datetime: '{val}' ({e})")


def clean_string(val: Any, default: str | None = None) -> str | None:
    if val is None:
        return default
    s = str(val).strip()
    if not s or s == "UNKNOWN":
        return default or "UNKNOWN"
    return s


def parse_float(val: Any, allow_unknown: bool = True) -> float | str | None:
    if val is None or val == "" or val == "UNKNOWN":
        return "UNKNOWN" if allow_unknown else None
    try:
        return float(val)
    except (ValueError, TypeError):
        raise ValueError(f"Cannot parse '{val}' as float")


@dataclass
class QualityIssue:
    source_id: str | None
    record_type: str | None
    row_locator: str | None
    issue_type: str
    severity: str  # "error", "warning", "info"
    field_name: str | None
    message: str


@dataclass
class ValidationResultRecord:
    row_locator: str
    raw_hash: str
    raw_payload: dict[str, Any]
    source_id: str
    record_type: str
    native_id: str
    timestamp: datetime.datetime | None
    normalized_data: dict[str, Any]
    is_quarantined: bool = False


@dataclass
class QualityReport:
    submission_id: str
    entity_id: str
    accepted_count: int = 0
    rejected_count: int = 0
    quarantined_count: int = 0
    duplicate_count: int = 0
    orphan_count: int = 0
    timestamp_problem_count: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
    source_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    normalized_records: list[ValidationResultRecord] = field(default_factory=list)


def normalize_record(
    record_type: str,
    raw_data: dict[str, Any],
    row_locator: str,
    source_id: str,
    manifest: ManifestDeclaration,
) -> tuple[dict[str, Any] | None, list[QualityIssue]]:
    issues: list[QualityIssue] = []
    normalized: dict[str, Any] = {}

    # Extract native_id
    native_id = raw_data.get("native_id")
    if not native_id or str(native_id).strip() == "":
        issues.append(
            QualityIssue(
                source_id=source_id,
                record_type=record_type,
                row_locator=row_locator,
                issue_type="MISSING_REQUIRED_FIELD",
                severity="error",
                field_name="native_id",
                message="Missing required field 'native_id'",
            )
        )
        return None, issues

    native_id = str(native_id).strip()
    normalized["native_id"] = native_id

    # Check for cross-entity reference in native_id or foreign fields
    for k, v in raw_data.items():
        if isinstance(v, str) and ("CSE-" in v or "ENTITY-" in v):
            # If value contains an entity prefix that does not match this entity
            parts = v.split("/")
            for p in parts:
                if (p.startswith("CSE-") or p.startswith("ENTITY-")) and p != manifest.entity_id:
                    issues.append(
                        QualityIssue(
                            source_id=source_id,
                            record_type=record_type,
                            row_locator=row_locator,
                            issue_type="CROSS_ENTITY_REFERENCE",
                            severity="error",
                            field_name=k,
                            message=f"Field '{k}' contains foreign entity reference '{p}', expected '{manifest.entity_id}'",
                        )
                    )

    # Normalize by contract record type
    try:
        if record_type == "assets":
            hostname = raw_data.get("hostname")
            if not hostname or str(hostname).strip() == "":
                issues.append(
                    QualityIssue(
                        source_id=source_id,
                        record_type=record_type,
                        row_locator=row_locator,
                        issue_type="MISSING_REQUIRED_FIELD",
                        severity="error",
                        field_name="hostname",
                        message="Missing required field 'hostname'",
                    )
                )
                return None, issues
            normalized["asset_id"] = native_id
            normalized["hostname"] = str(hostname).strip()
            normalized["ip_address"] = clean_string(raw_data.get("ip_address"), default=None)
            normalized["criticality"] = clean_string(raw_data.get("criticality"), default="UNKNOWN")
            normalized["owner"] = clean_string(raw_data.get("owner"), default=None)
            normalized["environment"] = clean_string(raw_data.get("environment"), default="UNKNOWN")
            for name in ("agent_status", "last_heartbeat", "last_seen"):
                if raw_data.get(name) is not None:
                    normalized[name] = (
                        parse_iso_datetime(raw_data[name]).isoformat()
                        if name != "agent_status"
                        else str(raw_data[name]).strip()
                    )
            ts = raw_data.get("timestamp")
            if ts:
                dt = parse_iso_datetime(ts)
                normalized["timestamp"] = dt.isoformat() if dt else None

        elif record_type == "alerts":
            title = raw_data.get("title")
            severity = raw_data.get("severity")
            source_tool = raw_data.get("source_tool")
            triage_status = raw_data.get("triage_status")
            ts = raw_data.get("timestamp")

            if not title:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "title",
                        "Missing 'title'",
                    )
                )
            if not severity:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "severity",
                        "Missing 'severity'",
                    )
                )
            if not source_tool:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "source_tool",
                        "Missing 'source_tool'",
                    )
                )
            if not triage_status:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "triage_status",
                        "Missing 'triage_status'",
                    )
                )

            dt = None
            if not ts:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "timestamp",
                        "Missing 'timestamp'",
                    )
                )
            else:
                try:
                    dt = parse_iso_datetime(ts)
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "error",
                            "timestamp",
                            str(ve),
                        )
                    )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["alert_id"] = native_id
            normalized["title"] = str(title).strip()
            normalized["severity"] = str(severity).strip()
            normalized["source_tool"] = str(source_tool).strip()
            normalized["triage_status"] = str(triage_status).strip()
            aff_ast = clean_string(
                raw_data.get("affected_asset_id") or raw_data.get("asset_id"), default=None
            )
            normalized["affected_asset_id"] = aff_ast
            normalized["asset_id"] = aff_ast
            normalized["timestamp"] = dt.isoformat() if dt else None

        elif record_type == "cases":
            created_at = raw_data.get("created_at")
            severity = raw_data.get("severity")
            status = raw_data.get("status")

            if not created_at:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "created_at",
                        "Missing 'created_at'",
                    )
                )
            if not severity:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "severity",
                        "Missing 'severity'",
                    )
                )
            if not status:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "status",
                        "Missing 'status'",
                    )
                )

            c_dt = None
            if created_at:
                try:
                    c_dt = parse_iso_datetime(created_at)
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "error",
                            "created_at",
                            str(ve),
                        )
                    )

            closed_at = raw_data.get("closed_at")
            cl_dt = None
            if closed_at:
                try:
                    cl_dt = parse_iso_datetime(closed_at)
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "warning",
                            "closed_at",
                            str(ve),
                        )
                    )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["case_id"] = native_id
            normalized["created_at"] = c_dt.isoformat() if c_dt else None
            normalized["closed_at"] = cl_dt.isoformat() if cl_dt else None
            normalized["severity"] = str(severity).strip()
            normalized["status"] = str(status).strip()
            normalized["assigned_analyst"] = clean_string(
                raw_data.get("assigned_analyst"), default=None
            )
            normalized["root_cause"] = clean_string(raw_data.get("root_cause"), default="UNKNOWN")
            for name in (
                "disposition",
                "resolution",
                "investigation_notes",
                "closing_notes",
                "notes",
                "title",
                "asset_id",
            ):
                if raw_data.get(name) is not None:
                    normalized[name] = str(raw_data[name]).strip()
            normalized["timestamp"] = normalized["created_at"]

        elif record_type == "case_alert_links":
            case_id = raw_data.get("case_id")
            alert_id = raw_data.get("alert_id")
            if not case_id:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "case_id",
                        "Missing 'case_id'",
                    )
                )
            if not alert_id:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "alert_id",
                        "Missing 'alert_id'",
                    )
                )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["case_id"] = str(case_id).strip()
            normalized["alert_id"] = str(alert_id).strip()
            l_ts = raw_data.get("linked_at")
            if l_ts:
                try:
                    l_dt = parse_iso_datetime(l_ts)
                    normalized["linked_at"] = l_dt.isoformat() if l_dt else None
                    normalized["timestamp"] = normalized["linked_at"]
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "warning",
                            "linked_at",
                            str(ve),
                        )
                    )
            else:
                normalized["linked_at"] = None
                normalized["timestamp"] = None

        elif record_type == "investigation_actions":
            case_id = raw_data.get("case_id")
            action_type = raw_data.get("action_type")
            actor = raw_data.get("actor")
            ts = raw_data.get("timestamp")

            if not case_id or not action_type or not actor or not ts:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "action",
                        "Missing mandatory action fields",
                    )
                )

            dt = None
            if ts:
                try:
                    dt = parse_iso_datetime(ts)
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "error",
                            "timestamp",
                            str(ve),
                        )
                    )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["action_id"] = native_id
            normalized["case_id"] = str(case_id).strip()
            normalized["action_type"] = str(action_type).strip()
            normalized["actor"] = str(actor).strip()
            normalized["artifact_hash"] = clean_string(raw_data.get("artifact_hash"), default=None)
            normalized["timestamp"] = dt.isoformat() if dt else None

        elif record_type == "escalations":
            case_id = raw_data.get("case_id")
            escalation_level = raw_data.get("escalation_level")
            notified_party = raw_data.get("notified_party")
            ts = raw_data.get("timestamp")

            if not case_id or not escalation_level or not notified_party or not ts:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "escalation",
                        "Missing mandatory escalation fields",
                    )
                )

            dt = None
            if ts:
                try:
                    dt = parse_iso_datetime(ts)
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "error",
                            "timestamp",
                            str(ve),
                        )
                    )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["escalation_id"] = native_id
            normalized["case_id"] = str(case_id).strip()
            normalized["escalation_level"] = str(escalation_level).strip()
            normalized["notified_party"] = str(notified_party).strip()
            normalized["timestamp"] = dt.isoformat() if dt else None

        elif record_type == "coverage_observations":
            sensor_name = raw_data.get("sensor_name")
            status = raw_data.get("status")
            ts = raw_data.get("timestamp")

            if not sensor_name or not status or not ts:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "coverage",
                        "Missing mandatory coverage fields",
                    )
                )

            dt = None
            if ts:
                try:
                    dt = parse_iso_datetime(ts)
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "error",
                            "timestamp",
                            str(ve),
                        )
                    )

            try:
                exp_eps = parse_float(raw_data.get("expected_eps"))
                obs_eps = parse_float(raw_data.get("observed_eps"))
            except ValueError as ve:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "INVALID_FIELD_TYPE",
                        "error",
                        "eps",
                        str(ve),
                    )
                )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["sensor_name"] = str(sensor_name).strip()
            normalized["status"] = str(status).strip()
            normalized["expected_eps"] = exp_eps
            normalized["observed_eps"] = obs_eps
            normalized["timestamp"] = dt.isoformat() if dt else None

        elif record_type == "ownership":
            asset_id = raw_data.get("asset_id")
            owner_team = raw_data.get("owner_team")
            if not asset_id or not owner_team:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "ownership",
                        "Missing asset_id or owner_team",
                    )
                )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["asset_id"] = str(asset_id).strip()
            normalized["owner_team"] = str(owner_team).strip()
            normalized["contact_email"] = clean_string(raw_data.get("contact_email"), default=None)
            eff_dt = None
            if raw_data.get("effective_date"):
                try:
                    eff_dt = parse_iso_datetime(raw_data.get("effective_date"))
                except ValueError:
                    pass
            normalized["effective_date"] = eff_dt.isoformat() if eff_dt else None
            normalized["timestamp"] = normalized["effective_date"]

        elif record_type == "exceptions":
            policy_ref = raw_data.get("policy_reference")
            scope = raw_data.get("affected_scope")
            approved_by = raw_data.get("approved_by")
            exp_date = raw_data.get("expiry_date")
            status = raw_data.get("status")

            if not policy_ref or not scope or not approved_by or not exp_date or not status:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "exceptions",
                        "Missing exception fields",
                    )
                )

            e_dt = None
            if exp_date:
                try:
                    e_dt = parse_iso_datetime(exp_date)
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "error",
                            "expiry_date",
                            str(ve),
                        )
                    )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["policy_reference"] = str(policy_ref).strip()
            normalized["affected_scope"] = str(scope).strip()
            normalized["approved_by"] = str(approved_by).strip()
            normalized["expiry_date"] = e_dt.isoformat() if e_dt else None
            normalized["status"] = str(status).strip()
            start = parse_iso_datetime(raw_data.get("valid_from") or raw_data.get("effective_date"))
            normalized["valid_from"] = start.isoformat() if start else None
            normalized["valid_to"] = normalized["expiry_date"]
            normalized["target_type"] = raw_data.get("target_type")
            normalized["target_id"] = raw_data.get("target_id")
            normalized["reason"] = raw_data.get("reason")
            normalized["timestamp"] = None  # An expiry outside the evidence period is legitimate.

        elif record_type == "remediations_validations":
            case_id = raw_data.get("case_id")
            action_summary = raw_data.get("action_summary")
            validated_by = raw_data.get("validated_by")
            val_date = raw_data.get("validation_date")
            result = raw_data.get("result")

            if not case_id or not action_summary or not validated_by or not val_date or not result:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "MISSING_REQUIRED_FIELD",
                        "error",
                        "remediations",
                        "Missing remediation fields",
                    )
                )

            v_dt = None
            if val_date:
                try:
                    v_dt = parse_iso_datetime(val_date)
                except ValueError as ve:
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "MALFORMED_TIMESTAMP",
                            "error",
                            "validation_date",
                            str(ve),
                        )
                    )

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["remediation_id"] = native_id
            normalized["case_id"] = str(case_id).strip()
            normalized["action_summary"] = str(action_summary).strip()
            normalized["validated_by"] = str(validated_by).strip()
            normalized["validation_date"] = v_dt.isoformat() if v_dt else None
            normalized["result"] = str(result).strip()
            normalized["timestamp"] = normalized["validation_date"]

        elif record_type == "reported_claims":
            metric_name = raw_data.get("metric_name")
            period = raw_data.get("period")
            val = raw_data.get("metric_value")

            if not metric_name or not period or val is None or val == "":
                issues.append(
                    QualityIssue(
                        source_id=source_id,
                        record_type=record_type,
                        row_locator=row_locator,
                        issue_type="MISSING_REQUIRED_FIELD",
                        severity="error",
                        field_name="claims",
                        message="Missing required claim fields (metric_name, period, or metric_value)",
                    )
                )

            m_val = None
            if val is not None and val != "":
                try:
                    m_val = parse_float(val, allow_unknown=False)
                except (ValueError, TypeError) as ve:
                    issues.append(
                        QualityIssue(
                            source_id=source_id,
                            record_type=record_type,
                            row_locator=row_locator,
                            issue_type="INVALID_FIELD_TYPE",
                            severity="error",
                            field_name="metric_value",
                            message=str(ve),
                        )
                    )

            unit = clean_string(raw_data.get("unit"), default=None)
            if m_val is not None:
                is_pct = percentage_metric(metric_name, unit)
                if not math.isfinite(m_val) or m_val < 0 or (is_pct and m_val > 100):
                    issues.append(
                        QualityIssue(
                            source_id,
                            record_type,
                            row_locator,
                            "VALUE_OUT_OF_RANGE",
                            "error",
                            "metric_value",
                            "Claim value must be finite and nonnegative; percentages must be at most 100.",
                        )
                    )
            try:
                start, end = claim_period(raw_data)
                normalized["period_start"] = start.isoformat()
                normalized["period_end"] = end.isoformat()
            except (ValueError, TypeError) as exc:
                issues.append(
                    QualityIssue(
                        source_id,
                        record_type,
                        row_locator,
                        "INVALID_CLAIM_PERIOD",
                        "error",
                        "period",
                        str(exc),
                    )
                )
            normalized["entity_id"] = str(raw_data.get("entity_id") or manifest.entity_id)
            normalized["unit"] = unit or ("percent" if percentage_metric(metric_name) else None)

            if any(i.severity == "error" for i in issues):
                return None, issues

            normalized["claim_id"] = native_id
            normalized["native_id"] = native_id
            normalized["metric_name"] = str(metric_name).strip()
            normalized["metric_value"] = m_val
            normalized["claimed_value"] = m_val
            normalized["claim_type"] = str(metric_name).strip()
            normalized["period"] = str(period).strip()
            normalized["notes"] = clean_string(raw_data.get("notes"), default=None)
            normalized["timestamp"] = None

    except Exception as e:
        issues.append(
            QualityIssue(
                source_id=source_id,
                record_type=record_type,
                row_locator=row_locator,
                issue_type="RECORD_PARSE_ERROR",
                severity="error",
                field_name=None,
                message=f"Error normalizing record: {e}",
            )
        )
        return None, issues

    # Validate timestamp bounding against manifest [period_start, period_end)
    ts_str = normalized.get("timestamp")
    if ts_str:
        try:
            record_dt = parse_iso_datetime(ts_str)
            if record_dt and (
                record_dt < manifest.period_start or record_dt >= manifest.period_end
            ):
                issues.append(
                    QualityIssue(
                        source_id=source_id,
                        record_type=record_type,
                        row_locator=row_locator,
                        issue_type="TIMESTAMP_OUT_OF_PERIOD",
                        severity="warning",
                        field_name="timestamp",
                        message=f"Event timestamp {ts_str} falls outside declared period [{manifest.period_start.isoformat()}, {manifest.period_end.isoformat()})",
                    )
                )
        except Exception:
            pass

    return normalized, issues


def evaluate_submission_quality(
    manifest: ManifestDeclaration,
    submission_id: str,
    parsed_files: dict[str, list[Any]],  # source_id -> list of ParsedRawItem
) -> QualityReport:
    report = QualityReport(submission_id=submission_id, entity_id=manifest.entity_id)

    # 1. Source completeness and row count reconciliation
    declared_sources = {s.source_id: s for s in manifest.sources}

    for src_id, decl in declared_sources.items():
        actual_items = parsed_files.get(src_id)
        if actual_items is None:
            if decl.is_optional:
                report.issues.append(
                    QualityIssue(
                        source_id=src_id,
                        record_type=decl.record_type,
                        row_locator=None,
                        issue_type="OPTIONAL_SOURCE_MISSING",
                        severity="info",
                        field_name=None,
                        message=f"Optional source '{src_id}' was not provided in this submission; treated as UNKNOWN coverage",
                    )
                )
                report.source_summaries[src_id] = {
                    "record_type": decl.record_type,
                    "declared_rows": decl.declared_row_count,
                    "actual_rows": 0,
                    "status": "UNKNOWN",
                    "is_optional": True,
                }
            else:
                report.issues.append(
                    QualityIssue(
                        source_id=src_id,
                        record_type=decl.record_type,
                        row_locator=None,
                        issue_type="REQUIRED_SOURCE_MISSING",
                        severity="error",
                        field_name=None,
                        message=f"Mandatory source '{src_id}' ({decl.record_type}) was declared but no file was uploaded",
                    )
                )
                report.source_summaries[src_id] = {
                    "record_type": decl.record_type,
                    "declared_rows": decl.declared_row_count,
                    "actual_rows": 0,
                    "status": "MISSING",
                    "is_optional": False,
                }
            continue

        actual_count = len(actual_items)
        if actual_count != decl.declared_row_count:
            report.issues.append(
                QualityIssue(
                    source_id=src_id,
                    record_type=decl.record_type,
                    row_locator=None,
                    issue_type="ROW_COUNT_MISMATCH",
                    severity="warning",
                    field_name=None,
                    message=f"Source '{src_id}' declared {decl.declared_row_count} rows but file contains {actual_count} rows",
                )
            )

        report.source_summaries[src_id] = {
            "record_type": decl.record_type,
            "declared_rows": decl.declared_row_count,
            "actual_rows": actual_count,
            "status": "PRESENT",
            "is_optional": decl.is_optional,
        }

    # 2. Record-by-record normalization & duplicate tracking
    # Key: (record_type, native_id) -> list of (normalized_data, row_locator, source_id)
    seen_identities: dict[tuple[str, str], list[tuple[dict[str, Any], str, str]]] = {}
    valid_cases: set[str] = set()
    valid_alerts: set[str] = set()
    valid_assets: set[str] = set()

    for src_id, items in parsed_files.items():
        decl = declared_sources.get(src_id)
        if not decl:
            continue

        record_type = decl.record_type

        for raw_item in items:
            norm_data, row_issues = normalize_record(
                record_type=record_type,
                raw_data=raw_item.raw_payload,
                row_locator=raw_item.row_locator,
                source_id=src_id,
                manifest=manifest,
            )

            report.issues.extend(row_issues)

            has_errors = any(i.severity == "error" for i in row_issues)
            has_ts_prob = any(
                i.issue_type in ("MALFORMED_TIMESTAMP", "TIMESTAMP_OUT_OF_PERIOD")
                for i in row_issues
            )
            if has_ts_prob:
                report.timestamp_problem_count += 1

            if has_errors or norm_data is None:
                report.rejected_count += 1
                # Still record quarantined record for provenance
                report.normalized_records.append(
                    ValidationResultRecord(
                        row_locator=raw_item.row_locator,
                        raw_hash=raw_item.sha256_hash,
                        raw_payload=raw_item.raw_payload,
                        source_id=src_id,
                        record_type=record_type,
                        native_id=str(raw_item.raw_payload.get("native_id", "UNKNOWN")),
                        timestamp=None,
                        normalized_data={"error": "quarantined", "raw": raw_item.raw_payload},
                        is_quarantined=True,
                    )
                )
                report.quarantined_count += 1
            else:
                native_id = norm_data["native_id"]
                key = (record_type, native_id)

                # Track known IDs for relational link verification
                if record_type == "cases":
                    valid_cases.add(native_id)
                elif record_type == "alerts":
                    valid_alerts.add(native_id)
                elif record_type == "assets":
                    valid_assets.add(native_id)

                # Check duplicates & conflicting identities
                if key in seen_identities:
                    report.duplicate_count += 1
                    # Compare existing with current
                    first_norm, first_loc, first_src = seen_identities[key][0]
                    # Check if conflicting values
                    if first_norm != norm_data:
                        report.issues.append(
                            QualityIssue(
                                source_id=src_id,
                                record_type=record_type,
                                row_locator=raw_item.row_locator,
                                issue_type="CONFLICTING_IDENTITY",
                                severity="error",
                                field_name="native_id",
                                message=f"Conflicting values for {record_type} native_id '{native_id}'. Clashes with {first_src}:{first_loc}",
                            )
                        )
                        report.rejected_count += 1
                        report.quarantined_count += 1
                        report.normalized_records.append(
                            ValidationResultRecord(
                                row_locator=raw_item.row_locator,
                                raw_hash=raw_item.sha256_hash,
                                raw_payload=raw_item.raw_payload,
                                source_id=src_id,
                                record_type=record_type,
                                native_id=native_id,
                                timestamp=None,
                                normalized_data={
                                    "error": "conflicting_identity",
                                    "raw": raw_item.raw_payload,
                                },
                                is_quarantined=True,
                            )
                        )
                        continue
                    else:
                        report.issues.append(
                            QualityIssue(
                                source_id=src_id,
                                record_type=record_type,
                                row_locator=raw_item.row_locator,
                                issue_type="DUPLICATE_NATIVE_ID",
                                severity="warning",
                                field_name="native_id",
                                message=f"Duplicate {record_type} native_id '{native_id}' already observed in {first_src}:{first_loc}",
                            )
                        )
                else:
                    seen_identities[key] = []

                seen_identities[key].append((norm_data, raw_item.row_locator, src_id))

                ts_parsed = None
                if norm_data.get("timestamp"):
                    try:
                        ts_parsed = parse_iso_datetime(norm_data["timestamp"])
                    except Exception:
                        pass

                report.normalized_records.append(
                    ValidationResultRecord(
                        row_locator=raw_item.row_locator,
                        raw_hash=raw_item.sha256_hash,
                        raw_payload=raw_item.raw_payload,
                        source_id=src_id,
                        record_type=record_type,
                        native_id=native_id,
                        timestamp=ts_parsed,
                        normalized_data=norm_data,
                        is_quarantined=False,
                    )
                )
                report.accepted_count += 1

    # 3. Cross-record Relational Integrity / Orphan Link Checks
    # Only verify orphan references if the corresponding source was declared and submitted
    has_cases_source = any(
        d.record_type == "cases" for d in manifest.sources if d.source_id in parsed_files
    )
    has_alerts_source = any(
        d.record_type == "alerts" for d in manifest.sources if d.source_id in parsed_files
    )
    has_assets_source = any(
        d.record_type == "assets" for d in manifest.sources if d.source_id in parsed_files
    )

    for rec in report.normalized_records:
        if rec.is_quarantined:
            continue

        if rec.record_type == "case_alert_links":
            c_id = rec.normalized_data.get("case_id")
            a_id = rec.normalized_data.get("alert_id")
            if has_cases_source and c_id and c_id not in valid_cases:
                report.orphan_count += 1
                report.issues.append(
                    QualityIssue(
                        source_id=rec.source_id,
                        record_type=rec.record_type,
                        row_locator=rec.row_locator,
                        issue_type="ORPHAN_REFERENCE",
                        severity="error",
                        field_name="case_id",
                        message=f"case_alert_link references case_id '{c_id}' not found in submitted cases",
                    )
                )
            if has_alerts_source and a_id and a_id not in valid_alerts:
                report.orphan_count += 1
                report.issues.append(
                    QualityIssue(
                        source_id=rec.source_id,
                        record_type=rec.record_type,
                        row_locator=rec.row_locator,
                        issue_type="ORPHAN_REFERENCE",
                        severity="error",
                        field_name="alert_id",
                        message=f"case_alert_link references alert_id '{a_id}' not found in submitted alerts",
                    )
                )

        elif rec.record_type in (
            "investigation_actions",
            "escalations",
            "remediations_validations",
        ):
            c_id = rec.normalized_data.get("case_id")
            if has_cases_source and c_id and c_id not in valid_cases:
                report.orphan_count += 1
                report.issues.append(
                    QualityIssue(
                        source_id=rec.source_id,
                        record_type=rec.record_type,
                        row_locator=rec.row_locator,
                        issue_type="ORPHAN_REFERENCE",
                        severity="error",
                        field_name="case_id",
                        message=f"{rec.record_type} references case_id '{c_id}' not found in submitted cases",
                    )
                )

        elif rec.record_type == "ownership":
            ass_id = rec.normalized_data.get("asset_id")
            if has_assets_source and ass_id and ass_id not in valid_assets:
                report.orphan_count += 1
                report.issues.append(
                    QualityIssue(
                        source_id=rec.source_id,
                        record_type=rec.record_type,
                        row_locator=rec.row_locator,
                        issue_type="ORPHAN_REFERENCE",
                        severity="warning",
                        field_name="asset_id",
                        message=f"ownership references asset_id '{ass_id}' not found in submitted assets",
                    )
                )

    return report
