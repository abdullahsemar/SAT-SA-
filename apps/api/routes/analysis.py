"""API endpoints for managing supervisory analysis runs."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.auth import check_entity_access, get_current_user, permitted_entity_ids
from apps.api.schemas.findings import AnalysisRunCreate, AnalysisRunResponse
from db.models.access import User
from db.models.evidence import Submission
from db.session import get_db
from packages.analytics.service import (
    AnalysisService,
    SubmissionNotCommittedError,
    SubmissionNotFoundError,
)

router = APIRouter(prefix="/analysis-runs", tags=["Analysis"])


@router.post("", response_model=AnalysisRunResponse, status_code=status.HTTP_201_CREATED)
def create_analysis_run(
    payload: AnalysisRunCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Triggers a supervisory analysis run on a committed submission."""
    # Lookup submission to find its CSE
    sub = db.get(Submission, payload.submission_id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission {payload.submission_id} not found",
        )

    # Check entity authorization using standardized check
    check_entity_access(current_user, sub.entity_id)

    service = AnalysisService(db)
    try:
        run = service.run_assessment(
            submission_id=payload.submission_id,
            cse_id=sub.entity_id,
            policy_id=payload.policy_id,
            run_name=payload.run_name,
            semantic_mode=payload.semantic_mode or "auto",
        )
        return run
    except SubmissionNotCommittedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except SubmissionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.get("", response_model=List[AnalysisRunResponse])
def list_analysis_runs(
    submission_id: Optional[str] = Query(None, description="Filter by submission ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists completed and active analysis runs scoped to current user."""
    service = AnalysisService(db)
    return service.list_runs(
        entity_ids=permitted_entity_ids(current_user), submission_id=submission_id
    )


@router.get("/{run_id}", response_model=AnalysisRunResponse)
def get_analysis_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetches details and summary metrics for an analysis run."""
    service = AnalysisService(db)
    run = service.get_run(run_id=run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run {run_id} not found",
        )
    check_entity_access(current_user, run.entity_id)
    return run
