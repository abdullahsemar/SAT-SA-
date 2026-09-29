"""API endpoints for inspecting findings and interactive evidence chains."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.auth import check_entity_access, get_current_user, permitted_entity_ids
from apps.api.schemas.findings import EvidenceChainResponse, FindingResponse
from db.models.access import User
from db.models.evidence import Submission
from db.session import get_db
from packages.analytics.service import AnalysisService, SubmissionNotFoundError

router = APIRouter(tags=["Findings & Evidence Chains"])


@router.get("/findings", response_model=List[FindingResponse])
def list_findings(
    submission_id: Optional[str] = Query(None, description="Filter by submission ID"),
    run_id: Optional[str] = Query(None, description="Filter by analysis run ID"),
    rule_id: Optional[str] = Query(None, description="Filter by supervisory rule ID"),
    evidence_state: Optional[str] = Query(None, description="Filter by evidence state"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists generated supervisory findings with optional rule and state filters."""
    service = AnalysisService(db)
    return service.list_findings(
        entity_ids=permitted_entity_ids(current_user),
        submission_id=submission_id,
        run_id=run_id,
        rule_id=rule_id,
        evidence_state=evidence_state,
    )


@router.get("/findings/{finding_id}", response_model=FindingResponse)
def get_finding(
    finding_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetches full finding details, rationale, uncertainty note, and source records."""
    service = AnalysisService(db)
    finding = service.get_finding(finding_id=finding_id)
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding {finding_id} not found",
        )
    check_entity_access(current_user, finding.entity_id)
    return finding


@router.get("/evidence/chains/{object_id}", response_model=EvidenceChainResponse)
def get_evidence_chain(
    object_id: str,
    submission_id: str = Query(..., description="Submission ID containing the evidence"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reconstructs the full many-to-many evidence chain, timeline, and omissions for an object."""
    sub = db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission {submission_id} not found",
        )

    check_entity_access(current_user, sub.entity_id)

    service = AnalysisService(db)
    try:
        chain = service.get_evidence_chain(
            submission_id=submission_id,
            object_id=object_id,
            cse_id=sub.entity_id,
        )
        return chain
    except SubmissionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
