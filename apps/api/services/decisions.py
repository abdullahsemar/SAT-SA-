"""Decision and portfolio service for SAT-SA supervisory review.

Enforces all supervisory invariants:
- Machine findings are strictly immutable and never altered by supervisory determinations.
- Human decisions are stored in dedicated audit tables with append-only versioning.
- Optimistic concurrency control raises HTTP 409 CONFLICT on concurrent/stale superseding.
- Validates cited evidence references against entity/submission scope (rejects foreign IDs).
- Reopening a saved portfolio reads frozen database records without resampling.
- Evidence requests are stored as local records without outbound external communication.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from db.models.access import User
from db.models.assessment import AnalysisRun, Finding
from db.models.evidence import NormalizedRecord, RawRecord, Submission
from db.models.review import (
    EvidenceRequest,
    ReviewAuditEvent,
    ReviewDecision,
    ReviewItem,
    ReviewPortfolio,
)
from packages.analytics.context import AssessmentContext
from packages.analytics.selection.candidates import CandidateGenerator
from packages.analytics.selection.explanations import ExplanationGenerator
from packages.analytics.selection.objective import ObjectiveWeights
from packages.analytics.selection.optimizer import (
    InvalidAllocationError,
    InvalidBudgetError,
    ReviewPortfolioOptimizer,
)


class DecisionService:
    VALID_FINDING_STATES = {
        "substantiated",
        "not_substantiated",
        "additional_evidence_required",
        "not_applicable",
    }

    VALID_ITEM_STATES = {
        "reviewed_no_concern",
        "concern_observed",
        "additional_evidence_required",
    }

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # 1. Portfolio Management
    # ------------------------------------------------------------------

    def create_portfolio(
        self,
        run_id: str,
        current_user: User,
        max_items: int = 20,
        max_minutes: Optional[float] = None,
        strata_allocation: Optional[Dict[str, int]] = None,
        duplication_caps: Optional[Dict[str, int]] = None,
        seed: int = 42,
    ) -> ReviewPortfolio:
        run = self.db.get(AnalysisRun, run_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"AnalysisRun '{run_id}' not found",
            )

        sub = self.db.get(Submission, run.submission_id)
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Submission '{run.submission_id}' for run '{run_id}' not found",
            )

        # 1. Load context and findings
        ctx = AssessmentContext(sub)
        findings_stmt = select(Finding).where(Finding.run_id == run_id)
        findings = list(self.db.scalars(findings_stmt).all())

        # 2. Extract candidate units
        cand_gen = CandidateGenerator(ctx)
        population = cand_gen.generate_candidates(run_id=run_id, findings=findings)

        # 3. Optimize portfolio selection
        optimizer = ReviewPortfolioOptimizer(
            weights=ObjectiveWeights(),
            duplication_caps=duplication_caps,
        )
        try:
            opt_result = optimizer.optimize(
                population=population,
                max_items=max_items,
                max_minutes=max_minutes,
                strata_allocation=strata_allocation,
                seed=seed,
            )
        except (InvalidBudgetError, InvalidAllocationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )

        # 4. Generate structured explanations
        portfolio_summary = ExplanationGenerator.generate_portfolio_summary(opt_result)

        # Check existing revision count for this run
        count_stmt = select(ReviewPortfolio).where(ReviewPortfolio.run_id == run_id)
        existing_portfolios = list(self.db.scalars(count_stmt).all())
        revision = len(existing_portfolios) + 1

        parameters_data = {
            "max_items": max_items,
            "max_minutes": max_minutes,
            "strata_allocation": strata_allocation,
            "duplication_caps": duplication_caps,
            "seed": seed,
            "weights_version": opt_result.weights_version,
        }

        portfolio = ReviewPortfolio(
            run_id=run_id,
            entity_id=run.entity_id,
            created_by=current_user.username,
            revision=revision,
            seed=seed,
            parameters_json=json.dumps(parameters_data),
            summary_json=json.dumps(portfolio_summary),
            sampling_frame_json=json.dumps(population.sampling_frame_summary),
        )
        self.db.add(portfolio)
        self.db.flush()

        # 5. Persist selected items
        log_by_unit = {entry["unit_id"]: entry for entry in opt_result.selection_log}
        for rank_idx, item_cand in enumerate(opt_result.selected_items, start=1):
            log_entry = log_by_unit.get(item_cand.unit_id)
            item_expl = ExplanationGenerator.generate_item_explanation(
                item=item_cand,
                rank=rank_idx,
                log_entry=log_entry,
            )

            rev_item = ReviewItem(
                portfolio_id=portfolio.id,
                unit_id=item_cand.unit_id,
                unit_type=item_cand.unit_type,
                finding_id=item_cand.finding_id,
                scope=item_cand.scope,
                stratum=item_cand.stratum,
                selection_rank=rank_idx,
                marginal_reasons_json=json.dumps(item_expl),
                evidence_references_json=json.dumps(item_cand.evidence_references),
                unknowns_json=json.dumps(item_cand.unknowns),
                what_examiner_learns=item_cand.what_examiner_could_learn,
                estimated_review_minutes=item_cand.estimated_review_minutes,
            )
            self.db.add(rev_item)

        # 6. Record audit event
        audit_event = ReviewAuditEvent(
            entity_id=run.entity_id,
            event_type="portfolio_created",
            actor_id=current_user.id,
            actor_username=current_user.username,
            target_type="review_portfolio",
            target_id=portfolio.id,
            details_json=json.dumps(
                {
                    "revision": revision,
                    "items_count": len(opt_result.selected_items),
                    "total_minutes": opt_result.total_minutes,
                    "seed": seed,
                }
            ),
        )
        self.db.add(audit_event)
        self.db.commit()
        self.db.refresh(portfolio)
        return portfolio

    def get_portfolio(self, portfolio_id: str, cse_id: Optional[str] = None) -> ReviewPortfolio:
        portfolio = self.db.get(ReviewPortfolio, portfolio_id)
        if not portfolio:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ReviewPortfolio '{portfolio_id}' not found",
            )
        if cse_id and portfolio.entity_id != cse_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to portfolio '{portfolio_id}' for entity '{cse_id}'",
            )
        return portfolio

    def list_portfolios(
        self,
        cse_id: Optional[str] = None,
        run_id: Optional[str] = None,
        entity_ids: list[str] | None = None,
    ) -> List[ReviewPortfolio]:
        stmt = select(ReviewPortfolio).order_by(desc(ReviewPortfolio.created_at))
        if entity_ids is not None:
            stmt = stmt.where(ReviewPortfolio.entity_id.in_(entity_ids))
        if cse_id:
            stmt = stmt.where(ReviewPortfolio.entity_id == cse_id)
        if run_id:
            stmt = stmt.where(ReviewPortfolio.run_id == run_id)
        return list(self.db.scalars(stmt).all())

    # ------------------------------------------------------------------
    # 2. Scope-Checked Evidence Verification
    # ------------------------------------------------------------------

    def validate_cited_evidence_scope(
        self,
        cited_ids: List[str],
        entity_id: str,
        submission_id: Optional[str] = None,
    ) -> None:
        """Validates that cited evidence IDs belong to this entity/submission."""
        if not cited_ids:
            return

        for cid in cited_ids:
            # Check normalized records
            norm_stmt = select(NormalizedRecord).where(
                (NormalizedRecord.id == cid) | (NormalizedRecord.native_id == cid)
            )
            if entity_id:
                norm_stmt = norm_stmt.where(NormalizedRecord.entity_id == entity_id)
            norm_rec = self.db.scalars(norm_stmt).first()

            if norm_rec:
                continue

            # Check raw records
            raw_stmt = select(RawRecord).where(
                (RawRecord.id == cid) | (RawRecord.sha256_hash == cid)
            )
            raw_rec = self.db.scalars(raw_stmt).first()
            if raw_rec:
                # verify submission entity
                sub = self.db.get(Submission, raw_rec.submission_id)
                if sub and sub.entity_id == entity_id:
                    continue

            # Check if it matches a known source ID or native ID within submission
            if submission_id:
                sub_check = self.db.get(Submission, submission_id)
                if sub_check:
                    report_data = getattr(sub_check, "evidence_quality_report", None) or json.loads(
                        sub_check.manifest_json or "{}"
                    )
                    # Check in tables
                    found_in_payload = False
                    for tbl, rows in report_data.items():
                        if isinstance(rows, list):
                            for r in rows:
                                if isinstance(r, dict):
                                    if cid in (
                                        r.get("id"),
                                        r.get("case_id"),
                                        r.get("asset_id"),
                                        r.get("alert_id"),
                                        r.get("action_id"),
                                        r.get("claim_id"),
                                        r.get("native_id"),
                                    ):
                                        found_in_payload = True
                                        break
                        if found_in_payload:
                            break
                    if found_in_payload:
                        continue

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Out-of-scope or unverified cited evidence ID '{cid}' for entity '{entity_id}'",
            )

    # ------------------------------------------------------------------
    # 3. Finding-Level Supervisory Decisions
    # ------------------------------------------------------------------

    def record_finding_decision(
        self,
        finding_id: str,
        state: str,
        rationale: str,
        cited_evidence_ids: List[str],
        current_user: User,
        superseded_decision_id: Optional[str] = None,
        cse_id: Optional[str] = None,
    ) -> ReviewDecision:
        if state not in self.VALID_FINDING_STATES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid finding decision state '{state}'. Expected one of {sorted(self.VALID_FINDING_STATES)}",
            )

        finding = self.db.get(Finding, finding_id)
        if not finding:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Finding '{finding_id}' not found",
            )

        if cse_id and finding.entity_id != cse_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to finding '{finding_id}' for entity '{cse_id}'",
            )

        # Validate cited evidence IDs
        self.validate_cited_evidence_scope(
            cited_ids=cited_evidence_ids,
            entity_id=finding.entity_id,
            submission_id=finding.submission_id,
        )

        # Optimistic concurrency check if superseding
        version = 1
        if superseded_decision_id:
            prior = self.db.get(ReviewDecision, superseded_decision_id)
            if not prior or prior.finding_id != finding_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Prior decision '{superseded_decision_id}' not found on finding '{finding_id}'",
                )

            # Check if this prior decision was already superseded by an existing newer decision
            superseder_check = self.db.scalars(
                select(ReviewDecision).where(
                    ReviewDecision.superseded_decision_id == superseded_decision_id
                )
            ).first()
            if superseder_check:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Version conflict: Decision '{superseded_decision_id}' has already been superseded "
                        f"by decision '{superseder_check.id}'"
                    ),
                )
            version = prior.version + 1

        decision = ReviewDecision(
            finding_id=finding_id,
            review_item_id=None,
            entity_id=finding.entity_id,
            reviewer_id=current_user.id,
            reviewer_username=current_user.username,
            state=state,
            rationale=rationale,
            cited_evidence_ids_json=json.dumps(cited_evidence_ids),
            superseded_decision_id=superseded_decision_id,
            version=version,
        )
        self.db.add(decision)
        self.db.flush()

        # Audit event
        audit_event = ReviewAuditEvent(
            entity_id=finding.entity_id,
            event_type="finding_decision_recorded"
            if not superseded_decision_id
            else "finding_decision_superseded",
            actor_id=current_user.id,
            actor_username=current_user.username,
            target_type="finding",
            target_id=finding_id,
            details_json=json.dumps(
                {
                    "decision_id": decision.id,
                    "state": state,
                    "version": version,
                    "superseded_decision_id": superseded_decision_id,
                }
            ),
        )
        self.db.add(audit_event)

        # Record signed custody event
        import hashlib

        from packages.evidence_integrity.custody import CustodyLogManager

        decision_commitment = hashlib.sha256(f"{state}:{rationale}:{version}".encode()).hexdigest()
        custody_mgr = CustodyLogManager(self.db)
        custody_mgr.record_event(
            entity_id=finding.entity_id,
            event_type="human_decision_recorded",
            object_type="review_decision",
            object_id=decision.id,
            object_version=version,
            evidence_commitment=decision_commitment,
            actor_id=current_user.username,
            metadata={
                "finding_id": finding_id,
                "state": state,
                "superseded_decision_id": superseded_decision_id,
            },
        )

        self.db.commit()
        self.db.refresh(decision)
        return decision

    def get_finding_decisions(
        self, finding_id: str, cse_id: Optional[str] = None
    ) -> List[ReviewDecision]:
        finding = self.db.get(Finding, finding_id)
        if not finding:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Finding '{finding_id}' not found",
            )
        if cse_id and finding.entity_id != cse_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to finding '{finding_id}' for entity '{cse_id}'",
            )

        stmt = (
            select(ReviewDecision)
            .where(ReviewDecision.finding_id == finding_id)
            .order_by(ReviewDecision.created_at)
        )
        return list(self.db.scalars(stmt).all())

    # ------------------------------------------------------------------
    # 4. Item-Level Review Decisions (Controls & Exploratory Units)
    # ------------------------------------------------------------------

    def record_item_decision(
        self,
        review_item_id: str,
        state: str,
        rationale: str,
        cited_evidence_ids: List[str],
        current_user: User,
        superseded_decision_id: Optional[str] = None,
        cse_id: Optional[str] = None,
    ) -> ReviewDecision:
        if state not in self.VALID_ITEM_STATES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid item decision state '{state}'. Expected one of {sorted(self.VALID_ITEM_STATES)}",
            )

        item = self.db.get(ReviewItem, review_item_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ReviewItem '{review_item_id}' not found",
            )

        portfolio = item.portfolio
        if cse_id and portfolio.entity_id != cse_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to review item '{review_item_id}' for entity '{cse_id}'",
            )

        # Validate cited evidence IDs against portfolio entity
        self.validate_cited_evidence_scope(
            cited_ids=cited_evidence_ids,
            entity_id=portfolio.entity_id,
        )

        version = 1
        if superseded_decision_id:
            prior = self.db.get(ReviewDecision, superseded_decision_id)
            if not prior or prior.review_item_id != review_item_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Prior decision '{superseded_decision_id}' not found on review item '{review_item_id}'",
                )

            superseder_check = self.db.scalars(
                select(ReviewDecision).where(
                    ReviewDecision.superseded_decision_id == superseded_decision_id
                )
            ).first()
            if superseder_check:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Version conflict: Decision '{superseded_decision_id}' has already been superseded "
                        f"by decision '{superseder_check.id}'"
                    ),
                )
            version = prior.version + 1

        decision = ReviewDecision(
            finding_id=item.finding_id,
            review_item_id=review_item_id,
            entity_id=portfolio.entity_id,
            reviewer_id=current_user.id,
            reviewer_username=current_user.username,
            state=state,
            rationale=rationale,
            cited_evidence_ids_json=json.dumps(cited_evidence_ids),
            superseded_decision_id=superseded_decision_id,
            version=version,
        )
        self.db.add(decision)
        self.db.flush()

        audit_event = ReviewAuditEvent(
            entity_id=portfolio.entity_id,
            event_type="item_decision_recorded"
            if not superseded_decision_id
            else "item_decision_superseded",
            actor_id=current_user.id,
            actor_username=current_user.username,
            target_type="review_item",
            target_id=review_item_id,
            details_json=json.dumps(
                {
                    "decision_id": decision.id,
                    "state": state,
                    "version": version,
                    "unit_id": item.unit_id,
                    "stratum": item.stratum,
                }
            ),
        )
        self.db.add(audit_event)

        # Record signed custody event
        import hashlib

        from packages.evidence_integrity.custody import CustodyLogManager

        item_decision_commitment = hashlib.sha256(
            f"{state}:{rationale}:{version}".encode()
        ).hexdigest()
        custody_mgr = CustodyLogManager(self.db)
        custody_mgr.record_event(
            entity_id=portfolio.entity_id,
            event_type="human_decision_recorded",
            object_type="review_decision",
            object_id=decision.id,
            object_version=version,
            evidence_commitment=item_decision_commitment,
            actor_id=current_user.username,
            metadata={
                "review_item_id": review_item_id,
                "state": state,
                "superseded_decision_id": superseded_decision_id,
            },
        )

        self.db.commit()
        self.db.refresh(decision)
        return decision

    def get_item_decisions(
        self, review_item_id: str, cse_id: Optional[str] = None
    ) -> List[ReviewDecision]:
        item = self.db.get(ReviewItem, review_item_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ReviewItem '{review_item_id}' not found",
            )
        if cse_id and item.portfolio.entity_id != cse_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to review item '{review_item_id}' for entity '{cse_id}'",
            )

        stmt = (
            select(ReviewDecision)
            .where(ReviewDecision.review_item_id == review_item_id)
            .order_by(ReviewDecision.created_at)
        )
        return list(self.db.scalars(stmt).all())

    # ------------------------------------------------------------------
    # 5. Local Evidence Requests
    # ------------------------------------------------------------------

    def create_evidence_request(
        self,
        missing_artifact: str,
        distinguishing_question: str,
        responsible_owner: str,
        due_date: datetime,
        current_user: User,
        finding_id: Optional[str] = None,
        review_item_id: Optional[str] = None,
        cse_id: Optional[str] = None,
    ) -> EvidenceRequest:
        if not finding_id and not review_item_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Evidence request requires either a finding_id or a review_item_id",
            )

        target_entity_id: Optional[str] = None

        if finding_id:
            finding = self.db.get(Finding, finding_id)
            if not finding:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Finding '{finding_id}' not found",
                )
            target_entity_id = finding.entity_id

        if review_item_id:
            item = self.db.get(ReviewItem, review_item_id)
            if not item:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"ReviewItem '{review_item_id}' not found",
                )
            target_entity_id = item.portfolio.entity_id

        assert target_entity_id is not None
        if cse_id and target_entity_id != cse_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to target entity '{target_entity_id}'",
            )

        ev_req = EvidenceRequest(
            finding_id=finding_id,
            review_item_id=review_item_id,
            entity_id=target_entity_id,
            requester_id=current_user.id,
            missing_artifact=missing_artifact,
            distinguishing_question=distinguishing_question,
            responsible_owner=responsible_owner,
            due_date=due_date,
            status="open",
        )
        self.db.add(ev_req)
        self.db.flush()

        audit_event = ReviewAuditEvent(
            entity_id=target_entity_id,
            event_type="evidence_request_created",
            actor_id=current_user.id,
            actor_username=current_user.username,
            target_type="evidence_request",
            target_id=ev_req.id,
            details_json=json.dumps(
                {
                    "missing_artifact": missing_artifact,
                    "responsible_owner": responsible_owner,
                    "finding_id": finding_id,
                    "review_item_id": review_item_id,
                }
            ),
        )
        self.db.add(audit_event)
        self.db.commit()
        self.db.refresh(ev_req)
        return ev_req

    def list_evidence_requests(
        self,
        cse_id: Optional[str] = None,
        finding_id: Optional[str] = None,
        review_item_id: Optional[str] = None,
        entity_ids: list[str] | None = None,
    ) -> List[EvidenceRequest]:
        stmt = select(EvidenceRequest).order_by(desc(EvidenceRequest.created_at))
        if entity_ids is not None:
            stmt = stmt.where(EvidenceRequest.entity_id.in_(entity_ids))
        if cse_id:
            stmt = stmt.where(EvidenceRequest.entity_id == cse_id)
        if finding_id:
            stmt = stmt.where(EvidenceRequest.finding_id == finding_id)
        if review_item_id:
            stmt = stmt.where(EvidenceRequest.review_item_id == review_item_id)
        return list(self.db.scalars(stmt).all())
