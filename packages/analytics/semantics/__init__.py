"""Semantic similarity and text chunking package for SAT-SA."""

from packages.analytics.semantics.chunking import TextChunk, TextChunker
from packages.analytics.semantics.config import SemanticConfig, default_semantic_config
from packages.analytics.semantics.encoder import SemanticEncoder
from packages.analytics.semantics.fallback import compute_lexical_similarity
from packages.analytics.semantics.registry import (
    ModelSecurityError,
    ModelVerificationError,
    validate_model_directory,
)
from packages.analytics.semantics.similarity import SimilarityEngine, SimilarityMatch

__all__ = [
    "SemanticConfig",
    "default_semantic_config",
    "ModelSecurityError",
    "ModelVerificationError",
    "validate_model_directory",
    "SemanticEncoder",
    "TextChunk",
    "TextChunker",
    "compute_lexical_similarity",
    "SimilarityEngine",
    "SimilarityMatch",
]
