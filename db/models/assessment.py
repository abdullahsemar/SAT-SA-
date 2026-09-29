import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    policy_version: Mapped[str] = mapped_column(String(64), default="demo-v1", nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), default="rules-v1", nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    seed: Mapped[int] = mapped_column(Integer, default=42, nullable=False)
    cutoff_time: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    findings_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary_counts_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    findings = relationship("Finding", back_populates="run", cascade="all, delete-orphan")

    @property
    def run_id(self) -> str:
        return self.id

    @property
    def cse_id(self) -> str:
        return self.entity_id

    @property
    def run_name(self) -> str:
        return f"Assessment-{self.id[:8]}"

    @property
    def rule_set_version(self) -> str:
        return self.rule_version

    @property
    def finished_at(self) -> datetime.datetime | None:
        return self.completed_at

    @property
    def summary(self) -> dict:
        import json

        try:
            return json.loads(self.summary_counts_json) if self.summary_counts_json else {}
        except Exception:
            return {}


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    proposition: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    family: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(32), default="neutral", nullable=False)
    evidence_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    applicable_obligation: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    contradicting_sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    lineage_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    unknowns_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    alternative_explanations_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    additional_evidence_needed_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    run = relationship("AnalysisRun", back_populates="findings")

    @property
    def finding_id(self) -> str:
        return self.id

    @property
    def cse_id(self) -> str:
        return self.entity_id

    @property
    def rule_id(self) -> str:
        return self.family

    @property
    def rule_title(self) -> str:
        return self.applicable_obligation

    @property
    def rationale(self) -> str:
        return self.proposition

    @property
    def severity(self) -> str:
        import json

        try:
            return json.loads(self.metrics_json).get("severity", "medium")
        except Exception:
            return "medium"

    @property
    def uncertainty_note(self) -> str | None:
        import json

        try:
            unk = json.loads(self.unknowns_json)
            return unk[0] if unk else None
        except Exception:
            return None

    @property
    def supporting_records(self) -> list:
        import json

        try:
            return json.loads(self.supporting_sources_json)
        except Exception:
            return []

    @property
    def peer_comparison_status(self) -> str:
        import json

        try:
            return json.loads(self.metrics_json).get(
                "peer_comparison_status", "peer_comparison_unavailable"
            )
        except Exception:
            return "peer_comparison_unavailable"

    @property
    def primary_object_type(self) -> str:
        return self.scope.split(":")[0] if ":" in self.scope else "object"

    @property
    def primary_object_id(self) -> str:
        return self.scope.split(":")[-1] if ":" in self.scope else self.scope

    @property
    def affected_asset_ids(self) -> list:
        import json

        try:
            return json.loads(self.metrics_json).get("affected_asset_ids", [])
        except Exception:
            return []

    @property
    def finding_metadata(self) -> dict:
        import json

        try:
            return json.loads(self.metrics_json)
        except Exception:
            return {}

    __table_args__ = (
        Index("ix_findings_run_family", "run_id", "family"),
        Index("ix_findings_run_state", "run_id", "evidence_state"),
    )
