"""API endpoints for strictly read-only retrieval of persisted passage similarities."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.auth import check_entity_access, get_current_user
from apps.api.schemas.semantic_evidence import SimilarPassagesResponse
from db.models.access import User
from db.models.assessment import Finding
from db.session import get_db
from packages.analytics.service import AnalysisService

router = APIRouter(tags=["Semantic Similarity"])


@router.get(
    "/findings/{finding_id}/similar-passages",
    response_model=SimilarPassagesResponse,
)
def get_finding_similar_passages(
    finding_id: str,
    limit: int = Query(5, ge=1, le=20, description="Max similar passages to return"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves previously persisted similar passages for a finding.

    STRICTLY READ-ONLY: Never invokes the encoder, calculates embeddings, downloads weights,
    or mutates the analytical cache on GET requests.
    """
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding {finding_id} not found",
        )

    # Enforce role and entity-scoped authorization
    check_entity_access(current_user, finding.entity_id)

    service = AnalysisService(db)
    result = service.get_similar_passages(
        finding_id=finding_id, cse_id=finding.entity_id, limit=limit
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding {finding_id} not found or access denied",
        )

    return result
