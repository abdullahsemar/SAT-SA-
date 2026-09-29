"""Database models for examiner review portfolios, decisions, and evidence requests.

Preserves core architectural invariants:
- Machine findings remain strictly immutable; human deliberations are stored in dedicated tables.
- Decisions survive restart and form an immutable append-only revision lineage.
- Supports both finding-level supervisory decisions and item-level control/exploratory reviews.
- Evidence requests are local audit records only (no automated external communications).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ReviewPortfolio(Base):
    __tablename__ = "review_portfolios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, default=42, nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    sampling_frame_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    items = relationship(
        "ReviewItem",
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="ReviewItem.selection_rank",
    )

    __table_args__ = (Index("ix_review_portfolios_entity_run", "entity_id", "run_id"),)


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    portfolio_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_portfolios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    unit_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    finding_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("findings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    stratum: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # targeted, control, exploratory
    selection_rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    marginal_reasons_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    evidence_references_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    unknowns_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    what_examiner_learns: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_review_minutes: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    portfolio = relationship("ReviewPortfolio", back_populates="items")
    decisions = relationship(
        "ReviewDecision",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ReviewDecision.created_at",
    )

    __table_args__ = (Index("ix_review_items_port_rank", "portfolio_id", "selection_rank"),)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    finding_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    review_item_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("review_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_username: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    cited_evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    superseded_decision_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("review_decisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    item = relationship("ReviewItem", back_populates="decisions")

    __table_args__ = (
        Index("ix_review_decisions_finding_created", "finding_id", "created_at"),
        Index("ix_review_decisions_item_created", "review_item_id", "created_at"),
    )


class EvidenceRequest(Base):
    __tablename__ = "evidence_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    finding_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    review_item_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("review_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    missing_artifact: Mapped[str] = mapped_column(Text, nullable=False)
    distinguishing_question: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_owner: Mapped[str] = mapped_column(String(100), nullable=False)
    due_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_evidence_requests_entity_status", "entity_id", "status"),)


class ReviewAuditEvent(Base):
    __tablename__ = "review_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_username: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (Index("ix_review_audit_entity_event", "entity_id", "event_type"),)
