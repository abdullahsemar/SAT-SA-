import json
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from apps.api.auth import (
    check_entity_access,
    clear_session_cookie,
    create_user_session,
    get_current_user,
    get_current_user_and_session,
    permitted_entity_ids,
    set_session_cookie,
    verify_password,
)
from apps.api.config import settings
from apps.api.schemas.submissions import (
    CommitRequest,
    LoginRequest,
    PaginatedSubmissionsResponse,
    QualityResponse,
    RecordProvenanceResponse,
    SubmissionDetailResponse,
    SubmissionFileResponse,
    SubmissionSummary,
    UserProfileResponse,
)
from db.models.access import User
from db.models.evidence import (
    NormalizedRecord,
    RawRecord,
    Submission,
    SubmissionFile,
)
from db.session import get_db
from packages.ingestion.manifest import ManifestDeclaration
from packages.ingestion.parsers import FileTooLargeError, InvalidFileFormatError
from packages.ingestion.service import IngestionError, IngestionService

router = APIRouter()
ingestion_service = IngestionService(storage_dir=settings.storage_dir)


# -------------------------------------------------------------------------
# Authentication Routes
# -------------------------------------------------------------------------
def _safe_entity_scope(raw_scope: str | None) -> list[str]:
    try:
        val = json.loads(raw_scope) if raw_scope else []
        return val if isinstance(val, list) and all(isinstance(x, str) for x in val) else []
    except Exception:
        return []


@router.post("/auth/login", response_model=UserProfileResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    stmt = select(User).where(User.username == payload.username)
    user = db.execute(stmt).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    token, csrf_token, expires_at = create_user_session(user, db)
    set_session_cookie(response, token, expires_at)

    return UserProfileResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        entity_scope=_safe_entity_scope(user.entity_scope),
        csrf_token=csrf_token,
    )


@router.post("/auth/logout")
def logout(
    response: Response,
    auth_tuple: tuple[User, Any] = Depends(get_current_user_and_session),
    db: Session = Depends(get_db),
):
    _, sess = auth_tuple
    db.delete(sess)
    db.commit()
    clear_session_cookie(response)
    return {"message": "Logged out successfully"}


@router.get("/auth/me", response_model=UserProfileResponse)
def get_current_profile(
    auth_tuple: tuple[User, Any] = Depends(get_current_user_and_session),
):
    user, sess = auth_tuple
    return UserProfileResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        entity_scope=_safe_entity_scope(user.entity_scope),
        csrf_token=sess.csrf_token,
    )


# -------------------------------------------------------------------------
# Submissions API
# -------------------------------------------------------------------------
@router.post(
    "/submissions", response_model=SubmissionDetailResponse, status_code=status.HTTP_201_CREATED
)
def create_submission(
    manifest: ManifestDeclaration,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Enforce entity-scoped authorization
    check_entity_access(current_user, manifest.entity_id)

    try:
        submission = ingestion_service.create_draft(manifest, db)
    except IngestionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return SubmissionDetailResponse(
        id=submission.id,
        entity_id=submission.entity_id,
        period_start=submission.period_start,
        period_end=submission.period_end,
        source_timezone=submission.source_timezone,
        status=submission.status,
        revision=submission.revision,
        manifest=json.loads(submission.manifest_json),
        idempotency_key=submission.idempotency_key,
        created_at=submission.created_at,
        committed_at=submission.committed_at,
        files=[],
    )


@router.post("/submissions/{id}/files", response_model=SubmissionFileResponse)
async def upload_submission_file(
    id: str,
    source_id: Annotated[str, Form(...)],
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = db.get(Submission, id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Submission '{id}' not found"
        )

    check_entity_access(current_user, submission.entity_id)

    # Read content with byte limit enforcement
    content = await file.read()
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file size ({len(content)} bytes) exceeds maximum limit of {settings.max_upload_size_bytes} bytes",
        )

    try:
        stored_file = ingestion_service.save_file(
            submission_id=id,
            source_id=source_id,
            filename=file.filename or f"{source_id}.dat",
            content=content,
            db=db,
        )
    except IngestionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except FileTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e))
    except InvalidFileFormatError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return SubmissionFileResponse(
        id=stored_file.id,
        source_id=stored_file.source_id,
        record_type=stored_file.record_type,
        original_filename=stored_file.original_filename,
        sha256_hash=stored_file.sha256_hash,
        byte_size=stored_file.byte_size,
        declared_row_count=stored_file.declared_row_count,
        actual_row_count=stored_file.actual_row_count,
        created_at=stored_file.created_at,
    )


@router.post("/submissions/{id}/validate", response_model=QualityResponse)
def validate_submission(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = db.get(Submission, id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Submission '{id}' not found"
        )

    check_entity_access(current_user, submission.entity_id)

    try:
        ingestion_service.validate_submission(id, db)
    except IngestionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    summary = ingestion_service.get_quality_summary(id, db)
    return QualityResponse(**summary)


@router.post("/submissions/{id}/commit", response_model=SubmissionDetailResponse)
def commit_submission(
    id: str,
    body: CommitRequest | None = None,
    idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = db.get(Submission, id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Submission '{id}' not found"
        )

    check_entity_access(current_user, submission.entity_id)

    key = (
        body.idempotency_key if body and body.idempotency_key else None
    ) or idempotency_key_header

    try:
        committed = ingestion_service.commit_submission(id, key, db)
    except IngestionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    stmt = select(SubmissionFile).where(SubmissionFile.submission_id == id)
    files = db.execute(stmt).scalars().all()

    return SubmissionDetailResponse(
        id=committed.id,
        entity_id=committed.entity_id,
        period_start=committed.period_start,
        period_end=committed.period_end,
        source_timezone=committed.source_timezone,
        status=committed.status,
        revision=committed.revision,
        manifest=json.loads(committed.manifest_json),
        idempotency_key=committed.idempotency_key,
        created_at=committed.created_at,
        committed_at=committed.committed_at,
        files=[
            SubmissionFileResponse(
                id=f.id,
                source_id=f.source_id,
                record_type=f.record_type,
                original_filename=f.original_filename,
                sha256_hash=f.sha256_hash,
                byte_size=f.byte_size,
                declared_row_count=f.declared_row_count,
                actual_row_count=f.actual_row_count,
                created_at=f.created_at,
            )
            for f in files
        ],
    )


@router.get("/submissions", response_model=PaginatedSubmissionsResponse)
def list_submissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    entity_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = permitted_entity_ids(current_user)

    if entity_id:
        check_entity_access(current_user, entity_id)

    query = select(Submission)
    count_query = select(func.count(Submission.id))

    if allowed is not None:
        query = query.where(Submission.entity_id.in_(allowed))
        count_query = count_query.where(Submission.entity_id.in_(allowed))

    if entity_id:
        query = query.where(Submission.entity_id == entity_id)
        count_query = count_query.where(Submission.entity_id == entity_id)

    total = db.execute(count_query).scalar() or 0

    query = (
        query.order_by(desc(Submission.created_at)).offset((page - 1) * page_size).limit(page_size)
    )
    submissions = db.execute(query).scalars().all()

    items = []
    for s in submissions:
        file_count = (
            db.execute(
                select(func.count(SubmissionFile.id)).where(SubmissionFile.submission_id == s.id)
            ).scalar()
            or 0
        )
        items.append(
            SubmissionSummary(
                id=s.id,
                entity_id=s.entity_id,
                period_start=s.period_start,
                period_end=s.period_end,
                source_timezone=s.source_timezone,
                status=s.status,
                revision=s.revision,
                created_at=s.created_at,
                committed_at=s.committed_at,
                file_count=file_count,
            )
        )

    return PaginatedSubmissionsResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/submissions/{id}", response_model=SubmissionDetailResponse)
def get_submission_detail(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = db.get(Submission, id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Submission '{id}' not found"
        )

    check_entity_access(current_user, submission.entity_id)

    stmt = select(SubmissionFile).where(SubmissionFile.submission_id == id)
    files = db.execute(stmt).scalars().all()

    return SubmissionDetailResponse(
        id=submission.id,
        entity_id=submission.entity_id,
        period_start=submission.period_start,
        period_end=submission.period_end,
        source_timezone=submission.source_timezone,
        status=submission.status,
        revision=submission.revision,
        manifest=json.loads(submission.manifest_json),
        idempotency_key=submission.idempotency_key,
        created_at=submission.created_at,
        committed_at=submission.committed_at,
        files=[
            SubmissionFileResponse(
                id=f.id,
                source_id=f.source_id,
                record_type=f.record_type,
                original_filename=f.original_filename,
                sha256_hash=f.sha256_hash,
                byte_size=f.byte_size,
                declared_row_count=f.declared_row_count,
                actual_row_count=f.actual_row_count,
                created_at=f.created_at,
            )
            for f in files
        ],
    )


@router.get("/submissions/{id}/quality", response_model=QualityResponse)
def get_submission_quality(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = db.get(Submission, id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Submission '{id}' not found"
        )

    check_entity_access(current_user, submission.entity_id)

    summary = ingestion_service.get_quality_summary(id, db)
    return QualityResponse(**summary)


@router.get("/evidence/records/{id}", response_model=RecordProvenanceResponse)
def get_evidence_record_provenance(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.get(NormalizedRecord, id)
    if not record:
        stmt = select(NormalizedRecord).where(NormalizedRecord.native_id == id)
        stmt = stmt.order_by(NormalizedRecord.is_quarantined.asc())
        candidates = db.scalars(stmt).all()
        allowed = permitted_entity_ids(current_user)
        is_admin = allowed is None
        for c in candidates:
            if is_admin or c.entity_id in allowed:
                record = c
                break

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Evidence record '{id}' not found"
        )

    # Access check on record's entity
    check_entity_access(current_user, record.entity_id)

    raw = db.get(RawRecord, record.raw_record_id)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Associated raw record not found"
        )

    return RecordProvenanceResponse(
        id=record.id,
        raw_record_id=raw.id,
        submission_id=record.submission_id,
        entity_id=record.entity_id,
        source_id=record.source_id,
        record_type=record.record_type,
        native_id=record.native_id,
        row_locator=raw.row_locator,
        raw_sha256=raw.sha256_hash,
        raw_payload=json.loads(raw.raw_payload),
        normalized_data=json.loads(record.normalized_data),
        is_quarantined=record.is_quarantined,
        created_at=record.created_at,
    )
