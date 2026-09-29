import datetime
from typing import Any

from pydantic import BaseModel, Field


class StandardErrorEnvelope(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserProfileResponse(BaseModel):
    id: str
    username: str
    role: str
    entity_scope: list[str]
    csrf_token: str | None = None


class SubmissionFileResponse(BaseModel):
    id: str
    source_id: str
    record_type: str
    original_filename: str
    sha256_hash: str
    byte_size: int
    declared_row_count: int
    actual_row_count: int
    created_at: datetime.datetime


class SubmissionSummary(BaseModel):
    id: str
    entity_id: str
    period_start: datetime.datetime
    period_end: datetime.datetime
    source_timezone: str
    status: str
    revision: int
    created_at: datetime.datetime
    committed_at: datetime.datetime | None
    file_count: int


class SubmissionDetailResponse(BaseModel):
    id: str
    entity_id: str
    period_start: datetime.datetime
    period_end: datetime.datetime
    source_timezone: str
    status: str
    revision: int
    manifest: dict[str, Any]
    idempotency_key: str | None
    created_at: datetime.datetime
    committed_at: datetime.datetime | None
    files: list[SubmissionFileResponse]


class PaginatedSubmissionsResponse(BaseModel):
    items: list[SubmissionSummary]
    total: int
    page: int
    page_size: int


class QualityIssueResponse(BaseModel):
    id: str
    source_id: str | None
    record_type: str | None
    row_locator: str | None
    issue_type: str
    severity: str
    field_name: str | None
    message: str


class SourceSummaryItem(BaseModel):
    source_id: str
    record_type: str
    declared_rows: int
    actual_rows: int
    status: str  # "PRESENT", "UNKNOWN", "MISSING"
    sha256: str | None
    is_optional: bool


class QualityResponse(BaseModel):
    submission_id: str
    entity_id: str
    status: str
    revision: int
    accepted_count: int
    rejected_count: int
    quarantined_count: int
    duplicate_count: int
    orphan_count: int
    timestamp_problem_count: int
    source_summaries: dict[str, SourceSummaryItem]
    issues: list[QualityIssueResponse]


class CommitRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=128)


class RecordProvenanceResponse(BaseModel):
    id: str
    raw_record_id: str
    submission_id: str
    entity_id: str
    source_id: str
    record_type: str
    native_id: str
    row_locator: str
    raw_sha256: str
    raw_payload: dict[str, Any]
    normalized_data: dict[str, Any]
    is_quarantined: bool
    created_at: datetime.datetime
