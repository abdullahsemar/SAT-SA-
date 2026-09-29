"""API routes for examiner review portfolios, decisions, and evidence requests."""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.auth import check_entity_access, get_current_user, permitted_entity_ids
from apps.api.schemas.review import (
    DecisionResponse,
    EvidenceRequestCreate,
    EvidenceRequestResponse,
    FindingDecisionCreate,
    ItemDecisionCreate,
    PortfolioCreateRequest,
    PortfolioResponse,
    ReviewItemResponse,
)
from apps.api.services.decisions import DecisionService
from db.models.access import User
from db.models.assessment import AnalysisRun, Finding
from db.models.review import ReviewDecision, ReviewItem, ReviewPortfolio
from db.session import get_db

router = APIRouter(tags=["Examiner Review Portfolios & Decisions"])


def _serialize_portfolio(p: ReviewPortfolio) -> PortfolioResponse:
    items_dto = []
    for it in p.items:
        items_dto.append(
            ReviewItemResponse(
                id=it.id,
                portfolio_id=it.portfolio_id,
                unit_id=it.unit_id,
                unit_type=it.unit_type,
                finding_id=it.finding_id,
                scope=it.scope,
                stratum=it.stratum,
                selection_rank=it.selection_rank,
                marginal_reasons=json.loads(it.marginal_reasons_json or "{}"),
                evidence_references=json.loads(it.evidence_references_json or "[]"),
                unknowns=json.loads(it.unknowns_json or "[]"),
                what_examiner_learns=it.what_examiner_learns,
                estimated_review_minutes=it.estimated_review_minutes,
                created_at=it.created_at,
            )
        )
    return PortfolioResponse(
        id=p.id,
        run_id=p.run_id,
        entity_id=p.entity_id,
        created_by=p.created_by,
        revision=p.revision,
        seed=p.seed,
        parameters=json.loads(p.parameters_json or "{}"),
        summary=json.loads(p.summary_json or "{}"),
        sampling_frame=json.loads(p.sampling_frame_json or "{}"),
        items=items_dto,
        created_at=p.created_at,
    )


def _serialize_decision(d: ReviewDecision) -> DecisionResponse:
    return DecisionResponse(
        id=d.id,
        finding_id=d.finding_id,
        review_item_id=d.review_item_id,
        entity_id=d.entity_id,
        reviewer_id=d.reviewer_id,
        reviewer_username=d.reviewer_username,
        state=d.state,
        rationale=d.rationale,
        cited_evidence_ids=json.loads(d.cited_evidence_ids_json or "[]"),
        superseded_decision_id=d.superseded_decision_id,
        version=d.version,
        created_at=d.created_at,
    )


# ----------------------------------------------------------------------
# 1. Review Portfolios Endpoints
# ----------------------------------------------------------------------


@router.post(
    "/review-portfolios",
    response_model=PortfolioResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_review_portfolio(
    req: PortfolioCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generates and persists a frozen, budget-bounded supervisory review portfolio."""
    run = db.get(AnalysisRun, req.run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AnalysisRun '{req.run_id}' not found",
        )

    check_entity_access(current_user, run.entity_id)

    service = DecisionService(db)
    portfolio = service.create_portfolio(
        run_id=req.run_id,
        current_user=current_user,
        max_items=req.max_items,
        max_minutes=req.max_minutes,
        strata_allocation=req.strata_allocation,
        duplication_caps=req.duplication_caps,
        seed=req.seed,
    )
    return _serialize_portfolio(portfolio)


@router.get(
    "/review-portfolios/{portfolio_id}",
    response_model=PortfolioResponse,
)
def get_review_portfolio(
    portfolio_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetches a saved review portfolio, its items, reasons, and budget summary without resampling."""
    service = DecisionService(db)
    portfolio = service.get_portfolio(portfolio_id)
    check_entity_access(current_user, portfolio.entity_id)
    return _serialize_portfolio(portfolio)


@router.get(
    "/review-portfolios",
    response_model=List[PortfolioResponse],
)
def list_review_portfolios(
    run_id: Optional[str] = Query(None, description="Filter by analysis run ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists saved review portfolios for the authorized entity."""
    allowed = permitted_entity_ids(current_user)
    if allowed is not None and not allowed:
        return []

    service = DecisionService(db)
    portfolios = service.list_portfolios(entity_ids=allowed, run_id=run_id)
    return [_serialize_portfolio(p) for p in portfolios]


# ----------------------------------------------------------------------
# 2. Finding-Level Supervisory Decisions
# ----------------------------------------------------------------------


@router.post(
    "/findings/{finding_id}/decisions",
    response_model=DecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_finding_decision(
    finding_id: str,
    req: FindingDecisionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Records an immutable supervisory decision on a machine finding without mutating the finding."""
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{finding_id}' not found",
        )
    check_entity_access(current_user, finding.entity_id)

    service = DecisionService(db)
    decision = service.record_finding_decision(
        finding_id=finding_id,
        state=req.state,
        rationale=req.rationale,
        cited_evidence_ids=req.cited_evidence_ids,
        current_user=current_user,
        superseded_decision_id=req.superseded_decision_id,
        cse_id=None,
    )
    return _serialize_decision(decision)


@router.get(
    "/findings/{finding_id}/decisions",
    response_model=List[DecisionResponse],
)
def get_finding_decisions(
    finding_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves immutable chronological decision history for a machine finding."""
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding '{finding_id}' not found",
        )
    check_entity_access(current_user, finding.entity_id)

    service = DecisionService(db)
    decisions = service.get_finding_decisions(finding_id=finding_id, cse_id=None)
    return [_serialize_decision(d) for d in decisions]


# ----------------------------------------------------------------------
# 3. Item-Level Review Decisions (Controls & Exploratory Items)
# ----------------------------------------------------------------------


@router.post(
    "/review-items/{item_id}/decisions",
    response_model=DecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_item_decision(
    item_id: str,
    req: ItemDecisionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Records an examiner review decision on a portfolio item (e.g. unflagged control)."""
    item = db.get(ReviewItem, item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ReviewItem '{item_id}' not found",
        )
    check_entity_access(current_user, item.portfolio.entity_id)

    service = DecisionService(db)
    decision = service.record_item_decision(
        review_item_id=item_id,
        state=req.state,
        rationale=req.rationale,
        cited_evidence_ids=req.cited_evidence_ids,
        current_user=current_user,
        superseded_decision_id=req.superseded_decision_id,
        cse_id=None,
    )
    return _serialize_decision(decision)


@router.get(
    "/review-items/{item_id}/decisions",
    response_model=List[DecisionResponse],
)
def get_item_decisions(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves chronological decision history for a portfolio review item."""
    item = db.get(ReviewItem, item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ReviewItem '{item_id}' not found",
        )
    check_entity_access(current_user, item.portfolio.entity_id)

    service = DecisionService(db)
    decisions = service.get_item_decisions(review_item_id=item_id, cse_id=None)
    return [_serialize_decision(d) for d in decisions]


# ----------------------------------------------------------------------
# 4. Evidence Requests Endpoints
# ----------------------------------------------------------------------


@router.post(
    "/evidence-requests",
    response_model=EvidenceRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_evidence_request(
    req: EvidenceRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Files a local supervisory evidence request specifying what resolves competing explanations."""
    if not req.finding_id and not req.review_item_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Evidence request requires either a finding_id or a review_item_id",
        )

    target_entity_id: Optional[str] = None
    if req.finding_id:
        finding = db.get(Finding, req.finding_id)
        if not finding:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Finding '{req.finding_id}' not found",
            )
        target_entity_id = finding.entity_id
    elif req.review_item_id:
        item = db.get(ReviewItem, req.review_item_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ReviewItem '{req.review_item_id}' not found",
            )
        target_entity_id = item.portfolio.entity_id

    if target_entity_id is not None:
        check_entity_access(current_user, target_entity_id)

    service = DecisionService(db)
    ev_req = service.create_evidence_request(
        missing_artifact=req.missing_artifact,
        distinguishing_question=req.distinguishing_question,
        responsible_owner=req.responsible_owner,
        due_date=req.due_date,
        current_user=current_user,
        finding_id=req.finding_id,
        review_item_id=req.review_item_id,
        cse_id=None,
    )
    return EvidenceRequestResponse.model_validate(ev_req)


@router.get(
    "/evidence-requests",
    response_model=List[EvidenceRequestResponse],
)
def list_evidence_requests(
    finding_id: Optional[str] = Query(None, description="Filter by finding ID"),
    review_item_id: Optional[str] = Query(None, description="Filter by review item ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists local supervisory evidence requests."""
    allowed = permitted_entity_ids(current_user)
    if allowed is not None and not allowed:
        return []

    service = DecisionService(db)
    requests = service.list_evidence_requests(
        entity_ids=allowed,
        finding_id=finding_id,
        review_item_id=review_item_id,
    )
    return [EvidenceRequestResponse.model_validate(r) for r in requests]
