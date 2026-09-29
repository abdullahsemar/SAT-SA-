"""API endpoints for Evidence Integrity, Signed Custody Events, and Verification."""

from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.auth import check_entity_access, get_current_user
from apps.api.schemas.evidence_integrity import (
    CustodyEventResponse,
    IntegrityStatusResponse,
    VerifyRequest,
    VerifyResponse,
)
from db.models.access import User
from db.models.evidence_integrity import (
    CustodyEvent,
    LedgerOutbox,
    VerificationRun,
)
from db.session import get_db
from packages.evidence_integrity.custody import CustodyLogManager
from packages.evidence_integrity.fabric_client import default_fabric_client
from packages.evidence_integrity.outbox import OutboxProcessor
from packages.evidence_integrity.signatures import default_key_registry, export_public_key_b64
from packages.evidence_integrity.verifier import EvidenceVerifier

router = APIRouter(tags=["Evidence Integrity"])


@router.get("/status", response_model=IntegrityStatusResponse)
def get_integrity_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves operational ledger status, active signing key, and outbox metrics."""
    key_id, _ = default_key_registry.get_service_signer()
    pub = default_key_registry.get_public_key(key_id)
    pub_b64 = export_public_key_b64(pub) if pub else ""

    pending = db.execute(
        select(func.count())
        .select_from(LedgerOutbox)
        .where(LedgerOutbox.status == "pending_anchor")
    ).scalar_one()

    anchored = db.execute(
        select(func.count()).select_from(LedgerOutbox).where(LedgerOutbox.status == "anchored")
    ).scalar_one()

    failed = db.execute(
        select(func.count()).select_from(LedgerOutbox).where(LedgerOutbox.status == "anchor_failed")
    ).scalar_one()

    return IntegrityStatusResponse(
        ledger_mode=default_fabric_client.mode,
        fabric_configured=default_fabric_client.enabled,
        channel_name=default_fabric_client.channel_name,
        chaincode_name=default_fabric_client.chaincode_name,
        service_key_id=key_id,
        service_public_key=pub_b64,
        pending_outbox_count=pending,
        anchored_outbox_count=anchored,
        failed_outbox_count=failed,
    )


@router.get("/custody-log", response_model=List[CustodyEventResponse])
def get_custody_log(
    entity_id: str = Query(..., description="Target Supervised Entity ID"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves the sequential append-only signed custody log for an entity."""
    check_entity_access(current_user, entity_id)

    stmt = (
        select(CustodyEvent)
        .where(CustodyEvent.entity_id == entity_id)
        .order_by(CustodyEvent.sequence_number.asc())
        .limit(limit)
    )
    events = list(db.execute(stmt).scalars().all())

    return [
        CustodyEventResponse(
            id=ev.id,
            entity_id=ev.entity_id,
            event_type=ev.event_type,
            sequence_number=ev.sequence_number,
            previous_event_commitment=ev.previous_event_commitment,
            object_type=ev.object_type,
            object_id=ev.object_id,
            object_version=ev.object_version,
            evidence_commitment=ev.evidence_commitment,
            claimed_event_time=ev.claimed_event_time,
            recorded_at=ev.recorded_at,
            actor_id=ev.actor_id,
            signing_key_id=ev.signing_key_id,
            signature=ev.signature,
            payload_digest=ev.payload_digest,
            metadata=json.loads(ev.metadata_json) if ev.metadata_json else {},
        )
        for ev in events
    ]


@router.post("/verify", response_model=VerifyResponse)
def execute_verification(
    req: VerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Executes read-only cryptographic verification of evidence and persists the audit record."""
    check_entity_access(current_user, req.entity_id)

    verifier = EvidenceVerifier()
    if req.target_type == "submission":
        res = verifier.verify_submission(req.target_id, db)
    elif req.target_type == "custody_log":
        mgr = CustodyLogManager(db)
        ok, issues = mgr.verify_event_chain(req.entity_id)
        res = EvidenceVerifier().verify_submission(req.target_id, db) if ok else None
        if not res:
            from packages.evidence_integrity.verifier import VerificationResult

            res = VerificationResult(
                is_valid=ok,
                status="verified_against_checkpoint" if ok else "verification_failed",
                target_id=req.target_id,
                target_type="custody_log",
                issues=issues,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported verification target type '{req.target_type}'",
        )

    # Persist audit record of this verification execution
    v_record = VerificationRun(
        entity_id=req.entity_id,
        target_type=req.target_type,
        target_id=req.target_id,
        verification_status=res.status,
        mode=default_fabric_client.mode,
        checked_bytes_sha256=None,
        canonical_hash_verified=res.is_valid,
        signature_verified=res.signatures_verified > 0,
        checkpoint_verified=res.status == "verified_against_checkpoint",
        ledger_verified=False,
        details_json=json.dumps(res.details),
        actor_id=current_user.username,
    )
    db.add(v_record)
    db.commit()

    return VerifyResponse(
        is_valid=res.is_valid,
        status=res.status,
        target_id=res.target_id,
        target_type=res.target_type,
        files_checked=res.files_checked,
        records_checked=res.records_checked,
        signatures_verified=res.signatures_verified,
        issues=res.issues,
        details=res.details,
    )


@router.post("/outbox/process")
def process_outbox_queue(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Processes pending outbox jobs (accessible by lead examiner or admin)."""
    if current_user.role not in ("admin", "lead_examiner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Lead examiner access required"
        )

    processor = OutboxProcessor(db)
    results = processor.process_pending_jobs(limit=50)
    return {"processed_count": len(results), "jobs": results}
