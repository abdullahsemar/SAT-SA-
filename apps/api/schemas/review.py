"""Pydantic schemas for examiner review portfolios, decisions, and evidence requests."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PortfolioCreateRequest(BaseModel):
    run_id: str = Field(..., description="Frozen analysis run ID to generate candidate units from")
    max_items: int = Field(20, ge=1, le=100, description="Maximum total items in the portfolio")
    max_minutes: Optional[float] = Field(
        None, gt=0, description="Optional total examiner review minute budget"
    )
    strata_allocation: Optional[Dict[str, int]] = Field(
        None, description="Optional custom capacity per stratum (targeted, control, exploratory)"
    )
    duplication_caps: Optional[Dict[str, int]] = Field(
        None, description="Optional duplication caps by group (e.g. {'asset': 3, 'category': 4})"
    )
    seed: int = Field(42, description="Deterministic seed for control sampling and tie-breaking")


class ReviewItemResponse(BaseModel):
    id: str
    portfolio_id: str
    unit_id: str
    unit_type: str
    finding_id: Optional[str] = None
    scope: str
    stratum: str
    selection_rank: int
    marginal_reasons: Dict[str, Any] = Field(default_factory=dict)
    evidence_references: List[Dict[str, Any]] = Field(default_factory=list)
    unknowns: List[str] = Field(default_factory=list)
    what_examiner_learns: str
    estimated_review_minutes: float
    created_at: datetime

    model_config = {"from_attributes": True}


class PortfolioResponse(BaseModel):
    id: str
    run_id: str
    entity_id: str
    created_by: str
    revision: int
    seed: int
    parameters: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    sampling_frame: Dict[str, Any] = Field(default_factory=dict)
    items: List[ReviewItemResponse] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


class FindingDecisionCreate(BaseModel):
    state: str = Field(
        ...,
        description="Decision state: substantiated | not_substantiated | additional_evidence_required | not_applicable",
    )
    rationale: str = Field(
        ..., min_length=5, description="Supervisory rationale for the finding determination"
    )
    cited_evidence_ids: List[str] = Field(
        default_factory=list,
        description="Scope-checked cited raw or normalized evidence record IDs",
    )
    superseded_decision_id: Optional[str] = Field(
        None, description="Optional ID of previous decision to supersede"
    )


class ItemDecisionCreate(BaseModel):
    state: str = Field(
        ...,
        description="Decision state: reviewed_no_concern | concern_observed | additional_evidence_required",
    )
    rationale: str = Field(..., min_length=5, description="Examiner rationale for the review item")
    cited_evidence_ids: List[str] = Field(
        default_factory=list,
        description="Scope-checked cited raw or normalized evidence record IDs",
    )
    superseded_decision_id: Optional[str] = Field(
        None, description="Optional ID of previous decision to supersede"
    )


class DecisionResponse(BaseModel):
    id: str
    finding_id: Optional[str] = None
    review_item_id: Optional[str] = None
    entity_id: str
    reviewer_id: str
    reviewer_username: str
    state: str
    rationale: str
    cited_evidence_ids: List[str] = Field(default_factory=list)
    superseded_decision_id: Optional[str] = None
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceRequestCreate(BaseModel):
    finding_id: Optional[str] = Field(None, description="Optional target finding ID")
    review_item_id: Optional[str] = Field(
        None, description="Optional target portfolio review item ID"
    )
    missing_artifact: str = Field(
        ..., min_length=3, description="Exact description of missing evidence artifact"
    )
    distinguishing_question: str = Field(
        ...,
        min_length=10,
        description="Question that resolves competing explanations (not generic 'send more data')",
    )
    responsible_owner: str = Field(..., min_length=2, description="Responsible entity role/owner")
    due_date: datetime = Field(..., description="Due timestamp in ISO-8601 UTC")


class EvidenceRequestResponse(BaseModel):
    id: str
    finding_id: Optional[str] = None
    review_item_id: Optional[str] = None
    entity_id: str
    requester_id: str
    missing_artifact: str
    distinguishing_question: str
    responsible_owner: str
    due_date: datetime
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
