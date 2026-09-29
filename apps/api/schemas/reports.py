"""Pydantic schemas for assessment reports and exports."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ReportCreateRequest(BaseModel):
    run_id: str = Field(..., description="Target analysis run ID to snapshot")
    portfolio_id: Optional[str] = Field(None, description="Optional review portfolio ID to include")
    decision_cutoff_time: Optional[datetime] = Field(
        None,
        description="Frozen timestamp cutoff for examiner decisions; defaults to current time",
    )
    notes: Optional[str] = Field(
        None, max_length=500, description="Examiner notes or scope remarks"
    )


class ReportResponse(BaseModel):
    id: str
    run_id: str
    portfolio_id: Optional[str] = None
    entity_id: str
    created_by: str
    decision_cutoff_time: datetime
    status: str
    report_schema_version: str
    notes: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    html_url: str
    json_url: str
    manifest_url: str
    bundle_url: str
    error_message: Optional[str] = None


class ReportListResponse(BaseModel):
    reports: List[ReportResponse]
    total: int
