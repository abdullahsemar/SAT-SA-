import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VALID_RECORD_TYPES = {
    "assets",
    "alerts",
    "cases",
    "case_alert_links",
    "investigation_actions",
    "escalations",
    "coverage_observations",
    "ownership",
    "exceptions",
    "remediations_validations",
    "reported_claims",
}

SamplingMethod = Literal["full_population", "random_sample", "risk_targeted"]


class SourceDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(
        ..., min_length=1, max_length=100, description="Unique source identifier within submission"
    )
    record_type: str = Field(..., description="One of the 11 recognized contract record types")
    declared_row_count: int = Field(..., ge=0, description="Declared record count by submitter")
    export_scope: str = Field(
        ..., min_length=1, max_length=500, description="Scope definition of the export"
    )
    lineage: str = Field(
        ..., min_length=1, max_length=500, description="Upstream provenance lineage"
    )
    sampling_method: SamplingMethod = Field(
        "full_population", description="Data sampling technique"
    )
    period_start: datetime.datetime | None = None
    period_end: datetime.datetime | None = None
    is_optional: bool = Field(
        False, description="True if source system is optional for this review cycle"
    )

    @field_validator("record_type")
    @classmethod
    def validate_record_type(cls, v: str) -> str:
        if v not in VALID_RECORD_TYPES:
            raise ValueError(
                f"Invalid record_type '{v}'. Must be one of: {sorted(VALID_RECORD_TYPES)}"
            )
        return v


class ManifestDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field("1.0.0", description="Contract manifest version")
    entity_id: str = Field(
        ..., min_length=1, max_length=64, description="Supervised CSE identifier"
    )
    period_start: datetime.datetime = Field(
        ..., description="Inclusive evaluation period start (UTC)"
    )
    period_end: datetime.datetime = Field(..., description="Exclusive evaluation period end (UTC)")
    source_timezone: str = Field("UTC", description="Declared source timezone")
    sources: list[SourceDeclaration] = Field(
        ..., min_length=1, description="Declared source systems"
    )

    @field_validator("source_timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception:
            raise ValueError(f"Invalid timezone identifier: '{v}'")
        return v

    @model_validator(mode="after")
    def validate_period(self) -> "ManifestDeclaration":
        if self.period_start >= self.period_end:
            raise ValueError("period_start must be strictly before period_end")

        # Ensure unique source_ids
        seen_ids = set()
        for src in self.sources:
            if src.source_id in seen_ids:
                raise ValueError(f"Duplicate source_id declared in manifest: '{src.source_id}'")
            seen_ids.add(src.source_id)

        return self
