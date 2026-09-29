"""Database models for cryptographic evidence integrity, signed custody log, and ledger anchoring.

Preserves core architectural invariants:
- Strict immutability of machine findings and historical evidence.
- Exact raw-file SHA-256 hashes separated from canonical record commitments and similarity embeddings.
- Append-only signed custody log with Ed25519 signatures and Merkle checkpoints.
- Transactional outbox pattern for permissioned ledger (Hyperledger Fabric) anchoring.
- Standalone verification independent of database state flags.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class EvidenceCommitment(Base):
    """Cryptographic commitment for submitted raw files, canonical records, or Merkle batches."""

    __tablename__ = "evidence_commitments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    submission_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    commitment_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # "raw_file" | "canonical_record" | "merkle_batch" | "report_snapshot"
    record_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    record_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    raw_file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    canonical_digest: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    merkle_root: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    nonce: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    representation_version: Mapped[str] = mapped_column(
        String(32), default="v1.0-canonical-json", nullable=False
    )
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    submission = relationship("Submission")

    __table_args__ = (
        Index("ix_ev_commit_entity_type", "entity_id", "commitment_type"),
        Index("ix_ev_commit_rec", "entity_id", "record_type", "record_id"),
    )


class CustodyEvent(Base):
    """Signed append-only custody event for critical evidence and assessment milestones."""

    __tablename__ = "custody_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # submission_committed, evidence_revision_registered, assessment_finalized, human_decision_recorded, report_snapshot_finalized
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    previous_event_commitment: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    object_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    evidence_commitment: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    claimed_event_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recorded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    signing_key_id: Mapped[str] = mapped_column(String(100), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)  # Base64 Ed25519 signature
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    outbox_entries = relationship("LedgerOutbox", back_populates="custody_event")

    __table_args__ = (
        UniqueConstraint("entity_id", "sequence_number", name="uq_custody_entity_sequence"),
        Index("ix_custody_obj", "entity_id", "object_type", "object_id"),
    )


class CustodyCheckpoint(Base):
    """Periodic signed tree/log checkpoint to defend against rollback and deletion."""

    __tablename__ = "custody_checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tree_size: Mapped[int] = mapped_column(Integer, nullable=False)
    root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signing_key_id: Mapped[str] = mapped_column(String(100), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)  # Base64 Ed25519 signature
    checkpoint_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("entity_id", "sequence_number", name="uq_checkpoint_entity_seq"),
    )


class LedgerOutbox(Base):
    """Transactional outbox for anchoring custody events into Hyperledger Fabric."""

    __tablename__ = "ledger_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("custody_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_name: Mapped[str] = mapped_column(String(64), default="sat-sa-channel", nullable=False)
    chaincode_name: Mapped[str] = mapped_column(
        String(64), default="sat_sa_custody", nullable=False
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending_anchor", nullable=False, index=True
    )  # pending_anchor, anchored, anchor_failed, not_configured, legacy_unanchored
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    block_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    receipt_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    anchored_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    custody_event = relationship("CustodyEvent", back_populates="outbox_entries")

    def __init__(self, **kwargs: Any):
        import json

        if "payload" in kwargs and "payload_json" not in kwargs:
            kwargs["payload_json"] = json.dumps(kwargs.pop("payload"))
        kwargs.pop("event_type", None)
        if kwargs.get("status") == "pending":
            kwargs["status"] = "pending_anchor"
        super().__init__(**kwargs)

    @property
    def receipt(self) -> Optional[Dict[str, Any]]:
        if not self.receipt_json:
            return None
        import json

        return json.loads(self.receipt_json)

    __table_args__ = (Index("ix_outbox_status_retries", "status", "retry_count"),)


class VerificationRun(Base):
    """Audit record of explicit cryptographic verification executions."""

    __tablename__ = "verification_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # submission, report_snapshot, assessment_run, custody_log
    target_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # verified_against_checkpoint, verification_failed, unverified, stale_verification
    mode: Mapped[str] = mapped_column(
        String(32), default="standalone_signed_log", nullable=False
    )  # standalone_signed_log | fabric_anchored | offline_local
    checked_bytes_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    canonical_hash_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkpoint_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ledger_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    verified_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (Index("ix_verif_target", "entity_id", "target_type", "target_id"),)
