"""Secure local model registry and integrity verification for SAT-SA.

Enforces:
- Offline environment: sets HF_HUB_OFFLINE=1 and HF_HUB_DISABLE_TELEMETRY=1.
- Path canonicalization: rejects directory traversal and symlinks.
- Manifest cryptographic validation: checks SHA-256, sizes, and file inventory.
- Rejection of forbidden formats (.bin, .pt, .pkl, .py, etc.).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

# Enforce offline mode in environment before any HF libraries load
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

FORBIDDEN_EXTENSIONS = {
    ".py",
    ".sh",
    ".bat",
    ".ps1",
    ".exe",
    ".bin",
    ".pt",
    ".pth",
    ".pkl",
    ".joblib",
    ".h5",
    ".msgpack",
}


class ModelSecurityError(Exception):
    """Raised when an active security violation (symlink escape, traversal, forbidden file) is detected."""

    pass


class ModelVerificationError(Exception):
    """Raised when model weights/manifest are missing, altered, or failed hash verification."""

    pass


@dataclass
class ModelValidationResult:
    is_valid: bool
    model_id: str
    commit_sha: str
    manifest_digest: str
    files_count: int
    error_reason: str | None = None


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest_digest(manifest_dict: Dict[str, Any]) -> str:
    canonical = json.dumps(manifest_dict, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_model_directory(
    model_dir: Path | str,
    manifest_path: Path | str,
) -> ModelValidationResult:
    """Validates the local model directory against the release manifest.

    Raises ModelSecurityError on security violations (traversal, symlinks, forbidden extensions).
    Returns ModelValidationResult with is_valid=False and error_reason on hash mismatches or missing files.
    """
    m_path = Path(manifest_path).resolve()
    if not m_path.exists():
        return ModelValidationResult(
            is_valid=False,
            model_id="unknown",
            commit_sha="unknown",
            manifest_digest="unknown",
            files_count=0,
            error_reason=f"Manifest file not found: {m_path}",
        )

    try:
        with open(m_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as exc:
        return ModelValidationResult(
            is_valid=False,
            model_id="unknown",
            commit_sha="unknown",
            manifest_digest="unknown",
            files_count=0,
            error_reason=f"Failed to parse manifest JSON: {exc}",
        )

    model_id = manifest.get("model_id", "unknown")
    commit_sha = manifest.get("commit_sha", "unknown")
    manifest_digest = compute_manifest_digest(manifest)
    declared_files = manifest.get("files", {})

    target_dir = Path(model_dir).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        return ModelValidationResult(
            is_valid=False,
            model_id=model_id,
            commit_sha=commit_sha,
            manifest_digest=manifest_digest,
            files_count=0,
            error_reason=f"Model directory does not exist: {target_dir}",
        )

    # 1. Scan actual files on disk for security violations
    actual_files: set[str] = set()
    for p in target_dir.rglob("*"):
        if p.is_symlink():
            raise ModelSecurityError(f"Symlink detected in model directory: {p}")

        # Check path traversal
        if not p.resolve().is_relative_to(target_dir):
            raise ModelSecurityError(f"Path escape detected: {p} resolves outside {target_dir}")

        if p.is_file():
            rel_str = str(p.relative_to(target_dir)).replace("\\", "/")
            actual_files.add(rel_str)

            # Check forbidden extensions
            if p.suffix.lower() in FORBIDDEN_EXTENSIONS:
                raise ModelSecurityError(
                    f"Forbidden file extension '{p.suffix}' found in model directory: {rel_str}"
                )

            # Check unexpected file not in manifest
            if rel_str not in declared_files:
                raise ModelSecurityError(
                    f"Unexpected unallowlisted file '{rel_str}' found in model directory"
                )

    # 2. Check all declared files in manifest exist and verify hashes
    for rel_str, file_meta in declared_files.items():
        file_path = target_dir / rel_str
        if not file_path.exists():
            return ModelValidationResult(
                is_valid=False,
                model_id=model_id,
                commit_sha=commit_sha,
                manifest_digest=manifest_digest,
                files_count=len(actual_files),
                error_reason=f"Missing model file declared in manifest: {rel_str}",
            )

        expected_size = file_meta.get("size_bytes")
        actual_size = file_path.stat().st_size
        if expected_size is not None and actual_size != expected_size:
            return ModelValidationResult(
                is_valid=False,
                model_id=model_id,
                commit_sha=commit_sha,
                manifest_digest=manifest_digest,
                files_count=len(actual_files),
                error_reason=f"File size mismatch for '{rel_str}': expected {expected_size}, got {actual_size}",
            )

        expected_sha = file_meta.get("sha256")
        actual_sha = compute_sha256(file_path)
        if expected_sha and actual_sha.lower() != expected_sha.lower():
            return ModelValidationResult(
                is_valid=False,
                model_id=model_id,
                commit_sha=commit_sha,
                manifest_digest=manifest_digest,
                files_count=len(actual_files),
                error_reason=f"SHA-256 hash mismatch for '{rel_str}': expected {expected_sha}, got {actual_sha}",
            )

    return ModelValidationResult(
        is_valid=True,
        model_id=model_id,
        commit_sha=commit_sha,
        manifest_digest=manifest_digest,
        files_count=len(declared_files),
        error_reason=None,
    )
