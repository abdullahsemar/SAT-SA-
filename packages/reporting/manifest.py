"""Cryptographic checksum manifest generator and verifier for assessment reports.

Preserves core architectural invariants:
- Every exported report artifact carries an explicit SHA-256 digest.
- Source submissions and model files are tied to cryptographic hashes.
- Disclaims administrative infallibility: copying a manifest proves file integrity,
  not an administrator-proof immutable audit log.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def compute_sha256_bytes(data: bytes) -> str:
    """Computes hexadecimal SHA-256 digest of arbitrary bytes."""
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def compute_sha256_str(text: str, encoding: str = "utf-8") -> str:
    """Computes hexadecimal SHA-256 digest of a string."""
    return compute_sha256_bytes(text.encode(encoding))


class ChecksumManifest:
    """Generates and verifies cryptographic SHA-256 manifests for report exports."""

    @staticmethod
    def build_manifest(
        snapshot_bytes: bytes,
        html_bytes: bytes,
        input_file_digests: Dict[str, str],
        rule_version: str,
        policy_version: str,
        model_manifest_digest: Optional[str] = None,
        model_mode: str = "offline",
    ) -> Dict[str, Any]:
        """Builds a complete checksum manifest dictionary."""
        snapshot_hash = compute_sha256_bytes(snapshot_bytes)
        html_hash = compute_sha256_bytes(html_bytes)

        components = {
            "snapshot_json": {
                "sha256": snapshot_hash,
                "size_bytes": len(snapshot_bytes),
                "format": "application/json",
            },
            "assessment_html": {
                "sha256": html_hash,
                "size_bytes": len(html_bytes),
                "format": "text/html; charset=utf-8",
            },
        }

        return {
            "manifest_version": "1.0",
            "algorithm": "SHA-256",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rule_version": rule_version,
            "policy_version": policy_version,
            "semantic_encoder": {
                "mode": model_mode,
                "manifest_sha256": model_manifest_digest,
            },
            "components": components,
            "source_submissions": input_file_digests,
            "verification_instructions": (
                "To verify artifact integrity independently:\n"
                "1. sha256sum snapshot.json -> must match components.snapshot_json.sha256\n"
                "2. sha256sum assessment.html -> must match components.assessment_html.sha256\n"
            ),
            "integrity_disclaimer": (
                "NOTICE: This cryptographic manifest certifies file integrity against corruption "
                "or post-export tampering. It does not represent an administrator-proof immutable "
                "blockchain or hardware security module signature."
            ),
        }

    @staticmethod
    def verify_artifact(data: bytes, expected_hash: str) -> bool:
        """Verifies data bytes against expected SHA-256 hex string."""
        computed = compute_sha256_bytes(data)
        return computed.lower() == expected_hash.lower()
