"""Tests for loader security, path traversal rejection, hash integrity, and offline controls."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from packages.analytics.semantics.registry import (
    ModelSecurityError,
    compute_sha256,
    validate_model_directory,
)


def test_offline_environment_variables_enforced():
    """Confirms offline environment variables are strictly set."""
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("HF_HUB_DISABLE_TELEMETRY") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def test_missing_manifest_rejected(tmp_path: Path):
    """Validation fails if manifest does not exist."""
    res = validate_model_directory(tmp_path, tmp_path / "manifest.json")
    assert not res.is_valid
    assert "not found" in (res.error_reason or "")


def test_missing_model_directory_rejected(tmp_path: Path):
    """Validation fails if model directory does not exist."""
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps({"model_id": "test", "commit_sha": "abc", "files": {}}),
        encoding="utf-8",
    )
    res = validate_model_directory(tmp_path / "nonexistent", manifest_file)
    assert not res.is_valid
    assert "does not exist" in (res.error_reason or "")


def test_forbidden_file_extension_rejected(tmp_path: Path):
    """Presence of forbidden extensions (.pkl, .bin, .pt, .py) triggers ModelSecurityError."""
    m_dir = tmp_path / "model"
    m_dir.mkdir()
    (m_dir / "weights.bin").write_bytes(b"unsafe_pickle_binary")

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "model_id": "test",
                "commit_sha": "abc",
                "files": {"weights.bin": {"size_bytes": 20, "sha256": "abc"}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ModelSecurityError) as exc:
        validate_model_directory(m_dir, manifest_file)
    assert "Forbidden file extension" in str(exc.value)


def test_unexpected_file_rejected(tmp_path: Path):
    """Presence of unallowlisted file triggers ModelSecurityError."""
    m_dir = tmp_path / "model"
    m_dir.mkdir()
    (m_dir / "valid.json").write_text("{}", encoding="utf-8")
    (m_dir / "unexpected.json").write_text("{}", encoding="utf-8")

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "model_id": "test",
                "commit_sha": "abc",
                "files": {
                    "valid.json": {"size_bytes": 2, "sha256": compute_sha256(m_dir / "valid.json")}
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ModelSecurityError) as exc:
        validate_model_directory(m_dir, manifest_file)
    assert "Unexpected unallowlisted file" in str(exc.value)


def test_tampered_file_hash_detected(tmp_path: Path):
    """Altered file content produces hash mismatch error."""
    m_dir = tmp_path / "model"
    m_dir.mkdir()
    target_file = m_dir / "config.json"
    target_file.write_text('{"tampered": true}', encoding="utf-8")

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "model_id": "test",
                "commit_sha": "abc",
                "files": {
                    "config.json": {
                        "size_bytes": len('{"tampered": true}'),
                        "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    res = validate_model_directory(m_dir, manifest_file)
    assert not res.is_valid
    assert "SHA-256 hash mismatch" in (res.error_reason or "")


def test_file_size_mismatch_detected(tmp_path: Path):
    """Truncated or expanded file produces size mismatch error."""
    m_dir = tmp_path / "model"
    m_dir.mkdir()
    target_file = m_dir / "config.json"
    target_file.write_text("{}", encoding="utf-8")

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "model_id": "test",
                "commit_sha": "abc",
                "files": {
                    "config.json": {
                        "size_bytes": 9999,
                        "sha256": compute_sha256(target_file),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    res = validate_model_directory(m_dir, manifest_file)
    assert not res.is_valid
    assert "File size mismatch" in (res.error_reason or "")
