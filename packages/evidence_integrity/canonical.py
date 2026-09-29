"""Versioned canonical serialization and deterministic structured commitment hashing.

Specification: v1.0-canonical-json
Invariants:
- Deterministic key ordering (strictly alphabetical recursion).
- Unicode NFC normalization.
- Strict type representation:
  - Nulls preserved explicitly as 'null' (never coerced to empty string or omitted).
  - Booleans preserved as 'true' / 'false'.
  - Numbers: Integers formatted without leading zeros; floats formatted deterministically.
  - Timestamps: ISO-8601 UTC (ending in 'Z').
  - Arrays / Lists: Exact item ordering preserved (domain meaningful).
- Bound to entity_id, record_type, native_id, representation version, and evidence content.
- Supports optional cryptographically secure per-record nonces.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import unicodedata
from typing import Any, Dict, Optional, Tuple


def normalize_value(val: Any) -> Any:
    """Recursively normalizes Python objects into deterministic canonical primitives."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(
                f"Non-finite float value '{val}' is not permit in canonical commitment."
            )
        # Canonical float: round to 8 decimal places and remove trailing zeros
        formatted = f"{val:.8f}".rstrip("0").rstrip(".")
        return float(formatted) if "." in formatted else int(formatted)
    if isinstance(val, (datetime.datetime, datetime.date)):
        if isinstance(val, datetime.datetime):
            if val.tzinfo is None:
                dt_utc = val.replace(tzinfo=datetime.timezone.utc)
            else:
                dt_utc = val.astimezone(datetime.timezone.utc)
            return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        return val.isoformat()
    if isinstance(val, str):
        return unicodedata.normalize("NFC", val)
    if isinstance(val, dict):
        return {
            unicodedata.normalize("NFC", str(k)): normalize_value(v)
            for k, v in sorted(val.items(), key=lambda item: str(item[0]))
        }
    if isinstance(val, (list, tuple)):
        return [normalize_value(item) for item in val]
    # Fallback for custom objects or types with dict/isoformat
    if hasattr(val, "to_dict"):
        return normalize_value(val.to_dict())
    if hasattr(val, "model_dump"):
        return normalize_value(val.model_dump(mode="json"))
    return unicodedata.normalize("NFC", str(val))


def canonical_json_dumps(data: Any) -> str:
    """Serializes canonical representation to deterministic compact UTF-8 JSON."""
    normalized = normalize_value(data)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_bytes(data: Any) -> bytes:
    """Returns UTF-8 encoded canonical compact JSON bytes."""
    return canonical_json_dumps(data).encode("utf-8")


def compute_canonical_digest(data: Any) -> Tuple[str, str]:
    """Returns canonical JSON string and its SHA-256 hex digest."""
    c_json = canonical_json_dumps(data)
    digest = hashlib.sha256(c_json.encode("utf-8")).hexdigest()
    return c_json, digest


def build_record_commitment(
    entity_id: str,
    record_type: str,
    native_id: str,
    payload: Dict[str, Any],
    version: str = "v1.0-canonical-json",
    nonce: Optional[str] = None,
) -> Tuple[str, str]:
    """Constructs a deterministic canonical commitment envelope for a structured record.

    Binds:
    - entity_id (Supervised entity scope)
    - record_type (Evidence domain schema)
    - native_id (Source system record identifier)
    - representation_version (e.g. v1.0-canonical-json)
    - nonce (Optional per-record salt for privacy/guessing resistance)
    - payload (Canonicalized data fields)

    Returns:
    - (canonical_envelope_json, sha256_commitment_digest)
    """
    envelope = {
        "entity_id": entity_id,
        "record_type": record_type,
        "native_id": native_id,
        "version": version,
        "nonce": nonce or "",
        "payload": payload,
    }
    return compute_canonical_digest(envelope)


def create_record_commitment(
    entity_id: str,
    submission_id: str,
    record_id: str,
    record_type: str,
    canonical_content: Dict[str, Any],
    nonce: Optional[str] = None,
    representation_version: str = "v1.0-canonical-json",
) -> Dict[str, Any]:
    """Creates a structured record commitment envelope and returns digest and metadata."""
    envelope = {
        "entity_id": entity_id,
        "submission_id": submission_id,
        "record_id": record_id,
        "record_type": record_type,
        "representation_version": representation_version,
        "nonce": nonce or "",
        "canonical_content": canonical_content,
    }
    c_json, digest = compute_canonical_digest(envelope)
    return {
        "envelope_json": c_json,
        "commitment": digest,
        "entity_id": entity_id,
        "submission_id": submission_id,
        "record_id": record_id,
        "record_type": record_type,
        "representation_version": representation_version,
        "nonce": nonce or "",
        "canonical_content": canonical_content,
    }


def verify_record_commitment(envelope_dict: Dict[str, Any], expected_commitment: str) -> bool:
    """Verifies that an envelope matches its expected commitment digest."""
    envelope = {
        "entity_id": envelope_dict.get("entity_id", ""),
        "submission_id": envelope_dict.get("submission_id", ""),
        "record_id": envelope_dict.get("record_id", ""),
        "record_type": envelope_dict.get("record_type", ""),
        "representation_version": envelope_dict.get(
            "representation_version", "v1.0-canonical-json"
        ),
        "nonce": envelope_dict.get("nonce", ""),
        "canonical_content": envelope_dict.get("canonical_content", {}),
    }
    _, computed_digest = compute_canonical_digest(envelope)
    return computed_digest.lower() == expected_commitment.lower()
