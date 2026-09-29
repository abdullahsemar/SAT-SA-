"""Supervisory API routes: Overview metrics, peer comparisons, longitudinal trends,
unusual pattern hypotheses, and authorized entity/period selectors.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import check_entity_access, get_current_user, permitted_entity_ids
from apps.api.schemas.supervisory import (
    AuthorizedEntityItem,
    EntityPeriodOption,
    PeerCohortResponse,
    PeriodTrendsResponse,
    SupervisoryOverviewResponse,
    UnusualPatternsResponse,
)
from db.models.access import User
from db.models.assessment import AnalysisRun
from db.models.evidence import CSE, Submission
from db.session import get_db
from packages.analytics.peer_comparison import PeerComparisonService
from packages.analytics.supervisory_summary import SupervisorySummaryService
from packages.analytics.trends import PeriodTrendsService
from packages.analytics.unusual_patterns import UnusualPatternService

router = APIRouter(prefix="/supervisory", tags=["Supervisory Analytics"])


@router.get("/entities", response_model=List[AuthorizedEntityItem])
def list_authorized_entities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns entities authorized for the logged-in examiner/administrator.

    Populates dropdown selectors to eliminate manual UUID copy-pasting.
    """
    allowed_ids = permitted_entity_ids(current_user)

    query = select(CSE)
    if allowed_ids is not None:
        query = query.where(CSE.id.in_(allowed_ids))

    cses = db.execute(query.order_by(CSE.name.asc())).scalars().all()

    result = []
    for cse in cses:
        # Get submission counts and latest periods
        subs = (
            db.execute(
                select(Submission)
                .where(Submission.entity_id == cse.id)
                .order_by(Submission.period_start.desc())
            )
            .scalars()
            .all()
        )

        sub_count = len(subs)
        latest_start = subs[0].period_start.isoformat() if subs else None
        latest_end = subs[0].period_end.isoformat() if subs else None

        # Determine sector
        sector = "Banking / Financial Services"
        if "HEALTH" in cse.id or "HEALTH" in cse.code:
            sector = "Healthcare Services"
        elif "ENERGY" in cse.id or "ENERGY" in cse.code:
            sector = "Critical Energy Infrastructure"
        elif "TELECOM" in cse.id or "TELECOM" in cse.code:
            sector = "Telecommunications"

        result.append(
            AuthorizedEntityItem(
                id=cse.id,
                name=cse.name,
                code=cse.code,
                sector=sector,
                submission_count=sub_count,
                latest_period_start=latest_start,
                latest_period_end=latest_end,
            )
        )
    return result


@router.get("/periods", response_model=List[EntityPeriodOption])
def list_entity_periods(
    entity_id: str = Query(..., description="Entity ID to list periods for"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns available reporting periods and assessment runs for an entity."""
    check_entity_access(current_user, entity_id)

    submissions = (
        db.execute(
            select(Submission)
            .where(Submission.entity_id == entity_id)
            .order_by(Submission.period_start.desc())
        )
        .scalars()
        .all()
    )

    results: List[EntityPeriodOption] = []
    for sub in submissions:
        # Check for completed run
        run = (
            db.execute(
                select(AnalysisRun)
                .where(AnalysisRun.submission_id == sub.id, AnalysisRun.status == "completed")
                .order_by(AnalysisRun.created_at.desc())
            )
            .scalars()
            .first()
        )

        # Build readable period label
        p_start = sub.period_start.date()
        p_end = sub.period_end.date()
        if p_start.month == 1 and p_end.month == 3:
            label = f"{p_start.year}-Q1"
        elif p_start.month == 4 and p_end.month == 6:
            label = f"{p_start.year}-Q2"
        elif p_start.month == 7 and p_end.month == 9:
            label = f"{p_start.year}-Q3"
        elif p_start.month == 10 and p_end.month == 12:
            label = f"{p_start.year}-Q4"
        else:
            label = f"{p_start.isoformat()} to {p_end.isoformat()}"

        results.append(
            EntityPeriodOption(
                submission_id=sub.id,
                run_id=run.id if run else None,
                period_start=sub.period_start.isoformat(),
                period_end=sub.period_end.isoformat(),
                period_label=label,
                status=sub.status,
                findings_count=run.findings_count if run else 0,
                has_analysis_run=run is not None,
            )
        )
    return results


@router.get("/overview", response_model=SupervisoryOverviewResponse)
def get_supervisory_overview(
    entity_id: str = Query(..., description="Target CSE entity ID"),
    submission_id: Optional[str] = Query(None, description="Specific submission ID (optional)"),
    run_id: Optional[str] = Query(None, description="Specific analysis run ID (optional)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns comprehensive supervisory overview metrics, execution gaps,
    negative space, contradicted claims, and capability coverage for an entity.
    """
    check_entity_access(current_user, entity_id)

    service = SupervisorySummaryService(db)
    result = service.get_entity_overview(
        entity_id=entity_id,
        run_id=run_id,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No assessment overview available for entity '{entity_id}'",
        )
    return result.to_dict()


@router.get("/peer-comparison", response_model=PeerCohortResponse)
def get_peer_comparison(
    entity_id: str = Query(..., description="Target CSE entity ID"),
    period_start: Optional[str] = Query(None, description="Filter period start (ISO string)"),
    period_end: Optional[str] = Query(None, description="Filter period end (ISO string)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Evaluates peer comparison cohort eligibility, exclusion rules, and normalized
    rate distributions. Target entity is strictly excluded from reference distribution.
    """
    check_entity_access(current_user, entity_id)

    service = PeerComparisonService(db)
    result = service.evaluate_peer_comparison(
        target_entity_id=entity_id,
        period_start=period_start,
        period_end=period_end,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Peer comparison could not be initialized for entity '{entity_id}'",
        )
    return result.to_dict()


@router.get("/trends", response_model=PeriodTrendsResponse)
def get_period_trends(
    entity_id: str = Query(..., description="Target CSE entity ID"),
    limit_periods: int = Query(
        12, ge=1, le=48, description="Maximum historical periods to analyze"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Computes longitudinal performance trajectory across reporting periods.

    Missing periods are explicitly marked as gaps, never fabricated zeros.
    """
    check_entity_access(current_user, entity_id)

    service = PeriodTrendsService(db)
    result = service.compute_trends(entity_id=entity_id, limit_periods=limit_periods)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trends not available for entity '{entity_id}'",
        )
    return result.to_dict()


@router.get("/unusual-patterns", response_model=UnusualPatternsResponse)
def get_unusual_patterns(
    submission_id: str = Query(..., description="Submission ID to analyze"),
    entity_id: Optional[str] = Query(None, description="Entity ID for authorization verification"),
    run_id: Optional[str] = Query(None, description="Optional Analysis Run ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Detects explainable statistical anomalies (rapid closures, caseload surges,
    negative-space telemetry drops, and repeated narratives) using robust Median/MAD metrics.
    """
    sub = db.execute(select(Submission).where(Submission.id == submission_id)).scalar_one_or_none()
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission '{submission_id}' not found",
        )

    check_entity_access(current_user, sub.entity_id)

    service = UnusualPatternService(db)
    result = service.analyze_patterns(submission_id=submission_id, run_id=run_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unusual patterns could not be computed for submission '{submission_id}'",
        )
    return result.to_dict()
