"""Configuration for semantic similarity and model execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SemanticConfig:
    model_dir: Path = field(
        default_factory=lambda: (
            Path(__file__).resolve().parent.parent.parent.parent / "models" / "all-MiniLM-L6-v2"
        )
    )
    manifest_path: Path = field(
        default_factory=lambda: (
            Path(__file__).resolve().parent.parent.parent.parent / "models" / "manifest.json"
        )
    )
    default_mode: str = "auto"  # "off" | "auto" | "required"
    max_seq_length: int = 256
    chunk_overlap: int = 32
    candidate_pool_limit: int = 200
    top_k: int = 5
    min_similarity_threshold: float = 0.15
    preprocessing_version: str = "chunk-v1"


default_semantic_config = SemanticConfig()
