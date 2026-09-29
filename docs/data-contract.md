# SAT-SA Data Contract Specification

This document defines the schemas, types, manifest structure, and quality rules for periodic supervisory evidence submissions imported into SAT-SA.

## 1. Submission Manifest Specification

A submission must include a root `manifest.json` declaring the scope and metadata for the evidence package:

```json
{
  "manifest_version": "1.0.0",
  "entity_id": "CSE-BANK-01",
  "period_start": "2026-01-01T00:00:00Z",
  "period_end": "2026-02-01T00:00:00Z",
  "source_timezone": "UTC",
  "sources": [
    {
      "source_id": "src-siem-alerts",
      "record_type": "alerts",
      "declared_row_count": 1420,
      "export_scope": "All alerts generated within evaluation period",
      "lineage": "Splunk Enterprise Cluster -> S3 Export -> CSV",
      "sampling_method": "full_population",
      "is_optional": false
    }
  ]
}
```

### Manifest Fields
| Field | Type | Description |
|---|---|---|
| `manifest_version` | string | Contract version (must be `"1.0.0"`). |
| `entity_id` | string | Unique identifier of the supervised Cyber Security Entity (CSE). |
| `period_start` | ISO-8601 string | Inclusive start timestamp of the observation period (UTC). |
| `period_end` | ISO-8601 string | Exclusive end timestamp of the observation period (UTC). |
| `source_timezone` | string | Declared timezone of the originating systems (e.g. `"UTC"`). |
| `sources` | array | List of declared sources. |

### Source Object Fields
| Field | Type | Description |
|---|---|---|
| `source_id` | string | Unique identifier for the source system within the submission. |
| `record_type` | string | One of the 11 recognized record types (see Section 2). |
| `declared_row_count`| integer | Number of records declared by the submitter. |
| `export_scope` | string | Scope description of the export. |
| `lineage` | string | Provenance/lineage summary from tool of origin. |
| `sampling_method` | string | `"full_population"`, `"random_sample"`, or `"risk_targeted"`. |
| `is_optional` | boolean | True if the source is optional. Missing optional sources evaluate to `UNKNOWN`. |

---

## 2. Recognized Record Types & Schemas

The 11 evidence schemas are strictly typed. Missing values must be `"UNKNOWN"` or `null`—never coerced to `0` or blank strings.

### 2.1 `assets` (IT/OT Asset Inventory)
- `native_id` (string, required): Primary key in source asset management system.
- `hostname` (string, required)
- `ip_address` (string, optional)
- `criticality` (string, required): `"CRITICAL"`, `"HIGH"`, `"MEDIUM"`, `"LOW"`, or `"UNKNOWN"`.
- `owner` (string, optional): Assigned owner or team.
- `environment` (string, optional): `"PROD"`, `"STAGE"`, `"DEV"`, or `"UNKNOWN"`.
- `timestamp` (ISO-8601 string, optional): Snapshot or last-seen timestamp.

### 2.2 `alerts` (Security Monitoring Alerts)
- `native_id` (string, required): Unique alert ID in SIEM/EDR.
- `timestamp` (ISO-8601 string, required): Trigger time. Must fall in `[period_start, period_end)`.
- `title` (string, required): Alert rule/signature name.
- `severity` (string, required): `"CRITICAL"`, `"HIGH"`, `"MEDIUM"`, `"LOW"`, or `"INFORMATIONAL"`.
- `source_tool` (string, required): E.g. `"EDR"`, `"SIEM"`, `"NDR"`.
- `affected_asset_id` (string, optional): References asset `native_id`.
- `triage_status` (string, required): `"CLOSED"`, `"ESCALATED"`, `"IN_PROGRESS"`, or `"UNREVIEWED"`.

### 2.3 `cases` (Incident Response / Investigation Cases)
- `native_id` (string, required): Unique case or ticket number (e.g. `"INC-2026-0042"`).
- `created_at` (ISO-8601 string, required): Case creation time.
- `closed_at` (ISO-8601 string, optional): Case closure time.
- `severity` (string, required): Severity level.
- `status` (string, required): `"OPEN"`, `"CONTAINED"`, `"RESOLVED"`, `"CLOSED"`.
- `assigned_analyst` (string, optional): Lead handler name/ID.
- `root_cause` (string, optional): Documented root cause or `"UNKNOWN"`.

### 2.4 `case_alert_links` (Bipartite Mapping)
- `native_id` (string, required): Mapping identifier.
- `case_id` (string, required): Foreign reference to `cases.native_id`.
- `alert_id` (string, required): Foreign reference to `alerts.native_id`.
- `linked_at` (ISO-8601 string, optional): Time link was established.

### 2.5 `investigation_actions` (Analyst Actions & Artifacts)
- `native_id` (string, required): Action record ID.
- `case_id` (string, required): Foreign reference to `cases.native_id`.
- `action_type` (string, required): E.g. `"HOST_ISOLATION"`, `"MEMORY_DUMP"`, `"FIREWALL_BLOCK"`, `"NOTE"`.
- `timestamp` (ISO-8601 string, required): Execution timestamp.
- `actor` (string, required): Analyst ID or automated playbook ID.
- `artifact_hash` (string, optional): SHA-256 hash of collected forensic artifact.

### 2.6 `escalations` (Notification & Escalation Records)
- `native_id` (string, required): Escalation record ID.
- `case_id` (string, required): Foreign reference to `cases.native_id`.
- `escalation_level` (string, required): `"L1_TO_L2"`, `"L2_TO_L3"`, `"MGMT_NOTIFY"`, `"REGULATOR_NOTIFY"`.
- `timestamp` (ISO-8601 string, required): Escalation timestamp.
- `notified_party` (string, required): Name/role/authority notified.

### 2.7 `coverage_observations` (Sensor / Rule Coverage)
- `native_id` (string, required): Sensor or log source ID.
- `sensor_name` (string, required): Name of sensor/feed.
- `expected_eps` (float, optional): Expected events-per-second.
- `observed_eps` (float, optional): Actual observed events-per-second.
- `status` (string, required): `"ONLINE"`, `"DEGRADED"`, `"OFFLINE"`, or `"UNKNOWN"`.
- `timestamp` (ISO-8601 string, required): Observation timestamp.

### 2.8 `ownership` (Asset & System Ownership Assignments)
- `native_id` (string, required): Ownership record ID.
- `asset_id` (string, required): Foreign reference to `assets.native_id`.
- `owner_team` (string, required): Team or business unit.
- `contact_email` (string, optional): Contact email or role mailbox.
- `effective_date` (ISO-8601 string, optional): Date assigned.

### 2.9 `exceptions` (Approved Security Exceptions & Policy Waivers)
- `native_id` (string, required): Exception ID.
- `policy_reference` (string, required): Policy control ID waived.
- `affected_scope` (string, required): Asset, subnet, or team covered.
- `approved_by` (string, required): Approving authority / CISO.
- `expiry_date` (ISO-8601 string, required): Expiration date.
- `status` (string, required): `"ACTIVE"`, `"EXPIRED"`, `"REVOKED"`.

### 2.10 `remediations_validations` (Post-Incident Remediation & Verification)
- `native_id` (string, required): Remediation record ID.
- `case_id` (string, required): Foreign reference to `cases.native_id`.
- `action_summary` (string, required): Remediation action performed.
- `validated_by` (string, required): Independent validator/auditor ID.
- `validation_date` (ISO-8601 string, required): Date verified effective.
- `result` (string, required): `"VERIFIED_EFFECTIVE"`, `"INCOMPLETE"`, or `"FAILED"`.

### 2.11 `reported_claims` (Supervised Entity Self-Reported Metrics)
- `native_id` (string, required): Claim record ID.
- `metric_name` (string, required): E.g. `"MTTD"`, `"MTTR"`, `"TOTAL_CRITICAL_ALERTS"`.
- `metric_value` (float, required): Reported value.
- `period` (string, required): Reporting cycle name.
- `notes` (string, optional): Contextual notes.

---

## 3. Evidence Quality Issue Taxonomy

The validation engine categorizes issues into standard severities:
- `ERROR`: Reject or quarantine record.
- `WARNING`: Discrepancy observed; record accepted but flagged.
- `INFO`: Neutral observation (e.g. missing optional source).

Standard `issue_type` identifiers:
- `ROW_COUNT_MISMATCH`: Declared rows in manifest != parsed rows in file.
- `MALFORMED_TIMESTAMP`: Unparseable ISO-8601 string.
- `TIMESTAMP_OUT_OF_PERIOD`: Event timestamp falls outside `[period_start, period_end)`.
- `MISSING_REQUIRED_FIELD`: Missing mandatory field (e.g. `native_id`).
- `DUPLICATE_NATIVE_ID`: Same `native_id` repeated within the same entity and source.
- `CONFLICTING_IDENTITY`: Same `native_id` has contradictory field values.
- `ORPHAN_REFERENCE`: Link references a parent (`case_id`, `alert_id`, `asset_id`) not present in submission.
- `CROSS_ENTITY_REFERENCE`: Reference contains an unauthorized or foreign entity ID.
- `OPTIONAL_SOURCE_MISSING`: An optional declared source was not provided (`INFO`).

---

## 4. Cryptographic Evidence Commitment & Custody Contract

### 4.1 Canonical Record Commitment (`v1.0-canonical-json`)
Every ingested and committed record produces a deterministic cryptographic commitment envelope:
- `entity_id` (string, required): Supervised entity scope.
- `submission_id` (string, required): Ingestion batch scope.
- `record_id` (string, required): Record identifier.
- `record_type` (string, required): Declared schema type.
- `representation_version` (string, required): `"v1.0-canonical-json"`.
- `nonce` (hex string, required): 128-bit cryptographically secure per-record salt.
- `canonical_content` (object, required): Strictly normalized primitives with alphabetical key sorting, Unicode NFC normalization, null preservation, and float normalization.

Commitment Hash: `SHA256(CanonicalJSON(Envelope))`.

### 4.2 Batch Merkle Commitment (RFC 6962)
- Leaf nodes: `SHA256(0x00 || record_commitment)`
- Internal nodes: `SHA256(0x01 || left_child || right_child)`
- Preserves deterministic record sequence; supports zero-knowledge inclusion proofs.

### 4.3 Signed Custody Event Record
- `id` (UUID string, required): Unique event ID.
- `entity_id` (string, required): Supervised entity ID.
- `event_type` (string, required): `submission_committed`, `evidence_revision_registered`, `assessment_finalized`, `human_decision_recorded`, `report_snapshot_finalized`.
- `sequence_number` (integer, required): Monotonically increasing counter per entity.
- `previous_event_commitment` (SHA-256 hex, required): Hash of preceding event envelope (genesis: `0*64`).
- `evidence_commitment` (SHA-256 hex, required): Merkle root or artifact manifest digest.
- `claimed_event_time` (ISO-8601 UTC, required): Operational boundary time.
- `recorded_at` (ISO-8601 UTC, required): Local system commit time.
- `actor_id` (string, required): Authenticated user ID.
- `signing_key_id` (string, required): Authority key identifier.
- `signature` (Base64 string, required): Ed25519 digital signature over canonical payload digest.

