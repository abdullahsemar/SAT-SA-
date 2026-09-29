import datetime
import uuid

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


class CSE(Base):
    __tablename__ = "cses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Entity ID e.g. "CSE-BANK-01"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    submissions = relationship("Submission", back_populates="cse", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False, index=True
    )  # "draft" | "validated" | "committed"
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )
    committed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    cse = relationship("CSE", back_populates="submissions")
    files = relationship(
        "SubmissionFile", back_populates="submission", cascade="all, delete-orphan"
    )
    raw_records = relationship(
        "RawRecord", back_populates="submission", cascade="all, delete-orphan"
    )
    normalized_records = relationship(
        "NormalizedRecord", back_populates="submission", cascade="all, delete-orphan"
    )
    validation_issues = relationship(
        "ValidationIssue", back_populates="submission", cascade="all, delete-orphan"
    )


class SubmissionFile(Base):
    __tablename__ = "submission_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    declared_row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    submission = relationship("Submission", back_populates="files")

    __table_args__ = (
        UniqueConstraint("submission_id", "source_id", name="uq_submission_file_source"),
    )

    @property
    def filename(self) -> str:
        return self.original_filename


class RawRecord(Base):
    __tablename__ = "raw_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    row_locator: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # e.g. "row:2" or "index:0"
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # Serialized JSON of raw input record
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    submission = relationship("Submission", back_populates="raw_records")
    normalized_records = relationship(
        "NormalizedRecord", back_populates="raw_record", cascade="all, delete-orphan"
    )


class NormalizedRecord(Base):
    __tablename__ = "normalized_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    raw_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    native_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    timestamp: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    normalized_data: Mapped[str] = mapped_column(Text, nullable=False)  # Validated canonical JSON
    is_quarantined: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    raw_record = relationship("RawRecord", back_populates="normalized_records")
    submission = relationship("Submission", back_populates="normalized_records")

    __table_args__ = (
        Index("ix_normalized_entity_record_native", "entity_id", "record_type", "native_id"),
    )


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    record_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_locator: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # "error", "warning", "info"
    field_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    submission = relationship("Submission", back_populates="validation_issues")
