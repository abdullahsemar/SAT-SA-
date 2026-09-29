"""API routes for frozen reproducible assessment reports, snapshots, and downloads."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import check_entity_access, get_current_user, permitted_entity_ids
from apps.api.schemas.reports import ReportCreateRequest, ReportListResponse, ReportResponse
from db.models.access import User
from db.models.assessment import AnalysisRun
from db.models.evidence import SubmissionFile
from db.models.reports import AssessmentReport
from db.models.review import ReviewPortfolio
from db.session import get_db
from packages.reporting.manifest import ChecksumManifest
from packages.reporting.render import HTMLReportRenderer
from packages.reporting.snapshot import ReportSnapshotBuilder

router = APIRouter(prefix="/reports", tags=["Assessment Reports & Exports"])


def _serialize_report(r: AssessmentReport) -> ReportResponse:
    base_url = f"/api/v1/reports/{r.id}"
    return ReportResponse(
        id=r.id,
        run_id=r.run_id,
        portfolio_id=r.portfolio_id,
        entity_id=r.entity_id,
        created_by=r.created_by,
        decision_cutoff_time=r.decision_cutoff_time,
        status=r.status,
        report_schema_version=r.report_schema_version,
        notes=r.notes,
        created_at=r.created_at,
        completed_at=r.completed_at,
        html_url=f"{base_url}/html",
        json_url=f"{base_url}/json",
        manifest_url=f"{base_url}/manifest",
        bundle_url=f"{base_url}/bundle",
        error_message=r.error_message,
    )


@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(
    req: ReportCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Creates and persists a frozen assessment snapshot and downloadable report."""
    # 1. Fetch AnalysisRun & verify access
    run = db.execute(select(AnalysisRun).where(AnalysisRun.id == req.run_id)).scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis run '{req.run_id}' not found",
        )

    check_entity_access(current_user, run.entity_id)

    # 2. Check portfolio if specified
    if req.portfolio_id:
        port = db.execute(
            select(ReviewPortfolio).where(ReviewPortfolio.id == req.portfolio_id)
        ).scalar_one_or_none()
        if not port:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Review portfolio '{req.portfolio_id}' not found",
            )
        if port.entity_id != run.entity_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Portfolio entity does not match run entity",
            )

    # 3. Build snapshot before rendering
    cutoff = req.decision_cutoff_time or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)

    snapshot_builder = ReportSnapshotBuilder(db)
    try:
        snapshot = snapshot_builder.build_snapshot(
            run_id=run.id,
            entity_id=run.entity_id,
            portfolio_id=req.portfolio_id,
            decision_cutoff_time=cutoff,
            notes=req.notes,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to build assessment snapshot: {str(e)}",
        )

    snapshot_bytes = json.dumps(snapshot, indent=2, sort_keys=True).encode("utf-8")

    # 4. Gather source submission digests
    sub_files = (
        db.execute(select(SubmissionFile).where(SubmissionFile.submission_id == run.submission_id))
        .scalars()
        .all()
    )
    source_digests = {sf.filename: sf.sha256_hash for sf in sub_files}

    # 5. Build preliminary manifest to render into HTML
    preliminary_manifest = ChecksumManifest.build_manifest(
        snapshot_bytes=snapshot_bytes,
        html_bytes=b"",  # will update after render
        input_file_digests=source_digests,
        rule_version=run.rule_version,
        policy_version=run.policy_version,
    )

    # 6. Render HTML
    renderer = HTMLReportRenderer()
    html_str = renderer.render(snapshot, preliminary_manifest)
    html_bytes = html_str.encode("utf-8")

    # 7. Finalize manifest with actual HTML bytes
    final_manifest = ChecksumManifest.build_manifest(
        snapshot_bytes=snapshot_bytes,
        html_bytes=html_bytes,
        input_file_digests=source_digests,
        rule_version=run.rule_version,
        policy_version=run.policy_version,
    )
    manifest_bytes = json.dumps(final_manifest, indent=2, sort_keys=True).encode("utf-8")

    # 8. Persist AssessmentReport
    report = AssessmentReport(
        run_id=run.id,
        portfolio_id=req.portfolio_id,
        entity_id=run.entity_id,
        created_by=current_user.username,
        decision_cutoff_time=cutoff,
        status="completed",
        report_schema_version="v1.0",
        snapshot_json=snapshot_bytes.decode("utf-8"),
        html_content=html_str,
        checksum_manifest_json=manifest_bytes.decode("utf-8"),
        notes=req.notes,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(report)
    db.flush()

    # Record signed custody event for the immutable finalized report
    import hashlib

    from packages.evidence_integrity.custody import CustodyLogManager

    report_digest = hashlib.sha256(manifest_bytes).hexdigest()
    custody_mgr = CustodyLogManager(db)
    custody_mgr.record_event(
        entity_id=report.entity_id,
        event_type="report_snapshot_finalized",
        object_type="assessment_report",
        object_id=report.id,
        object_version=1,
        evidence_commitment=report_digest,
        actor_id=current_user.username,
        metadata={"decision_cutoff_time": cutoff.isoformat(), "run_id": run.id},
    )

    db.commit()
    db.refresh(report)

    return _serialize_report(report)


@router.get("", response_model=ReportListResponse)
def list_reports(
    entity_id: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lists assessment reports filtered by authorized entity."""
    query = select(AssessmentReport)
    if entity_id:
        check_entity_access(current_user, entity_id)
        query = query.where(AssessmentReport.entity_id == entity_id)
    else:
        allowed = permitted_entity_ids(current_user)
        if allowed is not None:
            query = query.where(AssessmentReport.entity_id.in_(allowed))

    if run_id:
        query = query.where(AssessmentReport.run_id == run_id)

    query = query.order_by(AssessmentReport.created_at.desc())
    reports = db.execute(query).scalars().all()
    return ReportListResponse(
        reports=[_serialize_report(r) for r in reports],
        total=len(reports),
    )


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieves report metadata."""
    report = db.execute(
        select(AssessmentReport).where(AssessmentReport.id == report_id)
    ).scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found",
        )
    check_entity_access(current_user, report.entity_id)
    return _serialize_report(report)


@router.get("/{report_id}/html")
def download_report_html(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Downloads self-contained printable HTML report."""
    report = db.execute(
        select(AssessmentReport).where(AssessmentReport.id == report_id)
    ).scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    check_entity_access(current_user, report.entity_id)

    headers = {
        "Content-Disposition": f'inline; filename="assessment-report-{report.entity_id}-{report.id[:8]}.html"'
    }
    return Response(
        content=report.html_content, media_type="text/html; charset=utf-8", headers=headers
    )


@router.get("/{report_id}/json")
def download_report_json(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Downloads machine-readable frozen snapshot JSON."""
    report = db.execute(
        select(AssessmentReport).where(AssessmentReport.id == report_id)
    ).scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    check_entity_access(current_user, report.entity_id)

    headers = {
        "Content-Disposition": f'attachment; filename="assessment-snapshot-{report.entity_id}-{report.id[:8]}.json"'
    }
    return Response(content=report.snapshot_json, media_type="application/json", headers=headers)


@router.get("/{report_id}/manifest")
def download_report_manifest(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Downloads cryptographic checksum manifest JSON."""
    report = db.execute(
        select(AssessmentReport).where(AssessmentReport.id == report_id)
    ).scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    check_entity_access(current_user, report.entity_id)

    headers = {
        "Content-Disposition": f'attachment; filename="checksum-manifest-{report.entity_id}-{report.id[:8]}.json"'
    }
    return Response(
        content=report.checksum_manifest_json, media_type="application/json", headers=headers
    )


@router.get("/{report_id}/bundle")
def download_report_bundle(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Downloads zip bundle containing HTML, JSON snapshot, and checksum manifest."""
    report = db.execute(
        select(AssessmentReport).where(AssessmentReport.id == report_id)
    ).scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    check_entity_access(current_user, report.entity_id)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("assessment.html", report.html_content)
        zf.writestr("snapshot.json", report.snapshot_json)
        zf.writestr("manifest.json", report.checksum_manifest_json)

        # Build proof sidecar
        import hashlib

        report_digest = hashlib.sha256(report.checksum_manifest_json.encode("utf-8")).hexdigest()
        from db.models.evidence_integrity import CustodyEvent

        ev = (
            db.execute(
                select(CustodyEvent)
                .where(
                    CustodyEvent.object_type == "assessment_report",
                    CustodyEvent.object_id == report.id,
                )
                .order_by(CustodyEvent.sequence_number.desc())
            )
            .scalars()
            .first()
        )

        proof_data = {
            "report_id": report.id,
            "entity_id": report.entity_id,
            "run_id": report.run_id,
            "decision_cutoff_time": report.decision_cutoff_time.isoformat(),
            "report_digest": report_digest,
            "signed_envelope": {
                "report_id": report.id,
                "entity_id": report.entity_id,
                "report_digest": report_digest,
                "decision_cutoff_time": report.decision_cutoff_time.isoformat(),
                "created_by": report.created_by,
            },
            "signature": ev.signature if ev else None,
            "signing_key_id": ev.signing_key_id if ev else None,
            "custody_event_id": ev.id if ev else None,
            "sequence_number": ev.sequence_number if ev else None,
            "trust_basis": "Ed25519 Standalone Signed Log / Local Authority",
        }
        zf.writestr("proof_sidecar.json", json.dumps(proof_data, indent=2))

        zf.writestr(
            "README.txt",
            (
                f"SAT-SA Assessment Export Bundle\n"
                f"Report ID: {report.id}\n"
                f"Entity: {report.entity_id}\n"
                f"Cutoff: {report.decision_cutoff_time}\n"
                f"Created By: {report.created_by}\n"
                f"\nVerify with sha256sum:\n"
                f"sha256sum -c manifest.json\n"
                f"\nVerify cryptographic proof:\n"
                f"python scripts/verify_evidence.py --report assessment.html --proof proof_sidecar.json --public-key config/keys/service_audit_public.b64\n"
            ),
        )

    zip_bytes = zip_buffer.getvalue()
    headers = {
        "Content-Disposition": f'attachment; filename="assessment-bundle-{report.entity_id}-{report.id[:8]}.zip"'
    }
    return Response(content=zip_bytes, media_type="application/zip", headers=headers)


@router.get("/reports/{report_id}/proof")
def get_report_proof(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieves the cryptographic proof sidecar for an immutable assessment report."""
    report = db.execute(
        select(AssessmentReport).where(AssessmentReport.id == report_id)
    ).scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    check_entity_access(current_user, report.entity_id)

    import hashlib

    report_digest = hashlib.sha256(report.checksum_manifest_json.encode("utf-8")).hexdigest()
    from db.models.evidence_integrity import CustodyEvent, LedgerOutbox

    ev = (
        db.execute(
            select(CustodyEvent)
            .where(
                CustodyEvent.object_type == "assessment_report",
                CustodyEvent.object_id == report.id,
            )
            .order_by(CustodyEvent.sequence_number.desc())
        )
        .scalars()
        .first()
    )

    outbox = None
    if ev:
        outbox = (
            db.execute(select(LedgerOutbox).where(LedgerOutbox.event_id == ev.id)).scalars().first()
        )

    return {
        "report_id": report.id,
        "entity_id": report.entity_id,
        "run_id": report.run_id,
        "decision_cutoff_time": report.decision_cutoff_time.isoformat(),
        "report_digest": report_digest,
        "signed_envelope": {
            "report_id": report.id,
            "entity_id": report.entity_id,
            "report_digest": report_digest,
            "decision_cutoff_time": report.decision_cutoff_time.isoformat(),
            "created_by": report.created_by,
        },
        "signature": ev.signature if ev else None,
        "signing_key_id": ev.signing_key_id if ev else None,
        "custody_event_id": ev.id if ev else None,
        "sequence_number": ev.sequence_number if ev else None,
        "ledger_status": outbox.status if outbox else "standalone_signed_log",
        "ledger_receipt": json.loads(outbox.receipt_json)
        if (outbox and outbox.receipt_json)
        else None,
        "trust_basis": "Ed25519 Standalone Signed Log / Fabric Anchored",
    }
