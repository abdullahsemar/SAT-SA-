"""Pydantic DTOs for semantic evidence and passage similarity responses."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class TargetSpan(BaseModel):
    start_char: int
    end_char: int
    record_id: str


class SimilarPassageMatch(BaseModel):
    match_id: str
    source_id: str
    record_type: str
    record_id: str
    start_char: int
    end_char: int
    matched_text: str
    similarity: float
    method: str
    possible_explanation: str
    caveats: str
    exact_match: Optional[bool] = None
    lexical_score: Optional[float] = None
    tlsh_distance: Optional[int] = None
    semantic_score: Optional[float] = None


class SimilarPassagesResponse(BaseModel):
    finding_id: str
    status: str = Field(description="Result status: 'completed', 'disabled', or 'not_computed'")
    semantic_mode: str = Field(description="Configured mode: 'off', 'auto', or 'required'")
    method_used: str = Field(
        description="Method executed: 'semantic_all_minilm_l6_v2', 'lexical_fallback', 'disabled', or 'none'"
    )
    model_revision: Optional[str] = None
    manifest_digest: Optional[str] = None
    fallback_reason: Optional[str] = None
    target_passage: Optional[str] = None
    target_span: Optional[TargetSpan] = None
    matches: List[SimilarPassageMatch] = Field(default_factory=list)
    disclaimer: str = (
        "Similarity evidence is comparative decision support for human examiners. "
        "It does not classify SOC quality, prove superficiality, or replace regulatory judgment."
    )
