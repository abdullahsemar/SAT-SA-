"""Pydantic schemas for supervisory analysis runs, findings, and evidence chains."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AnalysisRunCreate(BaseModel):
    submission_id: str
    policy_id: Optional[str] = "POL-CSE-DEMO-V1"
    run_name: Optional[str] = None
    semantic_mode: Optional[str] = "auto"


class AnalysisRunResponse(BaseModel):
    run_id: str
    submission_id: str
    cse_id: str
    run_name: str
    status: str
    input_hash: Optional[str] = None
    policy_version: Optional[str] = None
    rule_set_version: Optional[str] = None
    findings_count: int
    summary: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FindingResponse(BaseModel):
    finding_id: str
    run_id: str
    submission_id: str
    cse_id: str
    rule_id: str
    rule_title: str
    severity: str
    evidence_state: str
    primary_object_type: str
    primary_object_id: str
    affected_asset_ids: List[str] = Field(default_factory=list)
    rationale: str
    uncertainty_note: Optional[str] = None
    supporting_records: List[Dict[str, Any]] = Field(default_factory=list)
    peer_comparison_status: Optional[str] = "peer_comparison_unavailable"
    finding_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceTimelineEvent(BaseModel):
    timestamp: Optional[str] = None
    entity_type: str
    entity_id: str
    event: str
    source_reference: Optional[Dict[str, Any]] = None


class EvidenceChainResponse(BaseModel):
    object_id: str
    object_type: str
    summary: Dict[str, Any] = Field(default_factory=dict)
    timeline: List[EvidenceTimelineEvent] = Field(default_factory=list)
    related_entities: Dict[str, Any] = Field(default_factory=dict)
    uncertainties: List[str] = Field(default_factory=list)
    omissions: List[str] = Field(default_factory=list)
