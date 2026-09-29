"""Database models for frozen assessment reports and checksum manifests.

Preserves core architectural invariants:
- Reports are frozen snapshots with explicit decision cutoff times.
- Subsequent changes or additions to decisions or findings never mutate an existing report.
- Contains self-contained printable HTML, structured JSON snapshot, and SHA-256 checksum manifest.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class AssessmentReport(Base):
    __tablename__ = "assessment_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    portfolio_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("review_portfolios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    decision_cutoff_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="completed", nullable=False
    )  # "generating", "completed", "failed"
    report_schema_version: Mapped[str] = mapped_column(String(32), default="v1.0", nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_assessment_reports_entity_created", "entity_id", "created_at"),
        Index("ix_assessment_reports_run", "run_id"),
    )
