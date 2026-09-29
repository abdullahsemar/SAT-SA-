"""Database models for persisted semantic evidence, passage chunks, and similarity matches."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class SemanticPassageChunk(Base):
    __tablename__ = "semantic_passage_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vector_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON array of floats, safe
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    submission = relationship("Submission")
    cse = relationship("CSE")

    __table_args__ = (
        Index("ix_chunks_entity_record", "entity_id", "record_type", "record_id"),
        Index("ix_chunks_submission_hash", "submission_id", "chunk_hash"),
    )


class FindingSimilarPassage(Base):
    __tablename__ = "finding_similar_passages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    finding_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("findings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_passage_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    target_end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    target_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    matched_passage_text: Mapped[str] = mapped_column(Text, nullable=False)
    matched_start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    matched_source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    matched_record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    semantic_mode: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    method_used: Mapped[str] = mapped_column(String(64), nullable=False)
    model_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preprocessing_version: Mapped[str] = mapped_column(
        String(32), default="chunk-v1", nullable=False
    )
    fallback_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    possible_explanation: Mapped[str] = mapped_column(String(128), nullable=False)
    caveats: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    finding = relationship("Finding")
    run = relationship("AnalysisRun")

    __table_args__ = (
        Index("ix_fsp_finding_score", "finding_id", "similarity_score"),
        Index("ix_fsp_run_entity", "run_id", "entity_id"),
    )
