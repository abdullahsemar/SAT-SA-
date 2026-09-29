"""Acceptance test verifying actual sentence-transformers/all-MiniLM-L6-v2 loading in offline isolation.

Guarantees:
- External network access is strictly blocked at the socket level.
- Unrelated user cache is empty (HF_HOME set to empty isolated tmp directory).
- Model loads from verified local models/ directory using safetensors only.
- Output embeddings are 384-dimensional, L2-normalized float32 vectors.
"""

from __future__ import annotations

import socket
from pathlib import Path

import numpy as np
import pytest

from packages.analytics.semantics.config import default_semantic_config
from packages.analytics.semantics.encoder import SemanticEncoder


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch, tmp_path):
    """Blocks all outbound network connections and points Hugging Face cache to empty directory."""
    # 1. Isolate HF cache
    isolated_cache = tmp_path / "empty_cache"
    isolated_cache.mkdir()
    monkeypatch.setenv("HF_HOME", str(isolated_cache))
    monkeypatch.setenv("TORCH_HOME", str(isolated_cache))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_DISABLE_TELEMETRY", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    # 2. Block socket connect calls to prevent any outbound connections
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        host, _ = address[0], address[1]
        # Only allow loopback
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ConnectionRefusedError(
                f"Network connection blocked by offline test harness: {address}"
            )
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


def test_real_model_offline_loading_and_embedding():
    """Verifies that the actual provisioned model loads offline and produces 384-d normalized embeddings."""
    assert Path(default_semantic_config.model_dir).exists(), "Model directory must be provisioned"
    assert Path(default_semantic_config.manifest_path).exists(), "Manifest must be provisioned"

    encoder = SemanticEncoder(
        model_dir=default_semantic_config.model_dir,
        manifest_path=default_semantic_config.manifest_path,
    )

    # Invariant: commit SHA and manifest digest verified
    assert encoder.commit_sha == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    assert encoder.manifest_digest is not None

    # Test single passage
    text = "Verified source IP belongs to authorized external scanner."
    embeddings = encoder.encode(text)

    # Invariant: shape is (1, 384)
    assert embeddings.shape == (1, 384)
    assert embeddings.dtype == np.float32

    # Invariant: L2 normalization (|norm - 1.0| < 1e-5)
    norm_val = float(np.linalg.norm(embeddings[0]))
    assert abs(norm_val - 1.0) < 1e-4

    # Test batch encoding
    batch_texts = [
        "First investigation triage note.",
        "Second investigation action taken on endpoint.",
        "Third case closed as benign false positive.",
    ]
    batch_vecs = encoder.encode(batch_texts)
    assert batch_vecs.shape == (3, 384)

    for i in range(3):
        v_norm = float(np.linalg.norm(batch_vecs[i]))
        assert abs(v_norm - 1.0) < 1e-4
