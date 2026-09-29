import datetime
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models.evidence import (
    CSE,
    NormalizedRecord,
    RawRecord,
    Submission,
    SubmissionFile,
    ValidationIssue,
)
from packages.ingestion.manifest import ManifestDeclaration
from packages.ingestion.parsers import (
    ParsedRawItem,
    parse_source_file,
    sanitize_filename,
)
from packages.ingestion.quality import QualityReport, evaluate_submission_quality


class IngestionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class IngestionService:
    def __init__(self, storage_dir: str = "storage/raw_files"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def create_draft(self, manifest: ManifestDeclaration, db: Session) -> Submission:
        # Check if CSE exists, or register it
        cse = db.get(CSE, manifest.entity_id)
        if not cse:
            cse = CSE(
                id=manifest.entity_id,
                name=f"Entity {manifest.entity_id}",
                code=manifest.entity_id,
            )
            db.add(cse)
            db.flush()

        # Find latest revision for this entity and period
        stmt = (
            select(func.max(Submission.revision))
            .where(Submission.entity_id == manifest.entity_id)
            .where(Submission.period_start == manifest.period_start)
            .where(Submission.period_end == manifest.period_end)
        )
        max_rev = db.execute(stmt).scalar() or 0
        new_revision = max_rev + 1

        manifest_json_str = manifest.model_dump_json()

        submission = Submission(
            entity_id=manifest.entity_id,
            period_start=manifest.period_start,
            period_end=manifest.period_end,
            source_timezone=manifest.source_timezone,
            status="draft",
            revision=new_revision,
            manifest_json=manifest_json_str,
        )
        db.add(submission)
        db.commit()
        db.refresh(submission)
        return submission

    def save_file(
        self,
        submission_id: str,
        source_id: str,
        filename: str,
        content: bytes,
        db: Session,
    ) -> SubmissionFile:
        submission = db.get(Submission, submission_id)
        if not submission:
            raise IngestionError(
                "SUBMISSION_NOT_FOUND", f"Submission '{submission_id}' not found", 404
            )

        if submission.status == "committed":
            raise IngestionError(
                "SUBMISSION_IMMUTABLE",
                f"Submission '{submission_id}' is committed and cannot be modified",
                409,
            )

        manifest_dict = json.loads(submission.manifest_json)
        manifest = ManifestDeclaration.model_validate(manifest_dict)

        decl = next((s for s in manifest.sources if s.source_id == source_id), None)
        if not decl:
            raise IngestionError(
                "UNDECLARED_SOURCE",
                f"Source '{source_id}' is not declared in the submission manifest",
                422,
            )

        safe_name = sanitize_filename(filename)
        # Parse file to ensure validity and calculate hashes
        try:
            file_sha256, items = parse_source_file(content, safe_name)
        except Exception as e:
            raise IngestionError("FILE_PARSE_ERROR", f"Failed to parse source file: {e}", 422)

        # Store file in dedicated folder
        sub_folder = self.storage_dir / submission_id
        sub_folder.mkdir(parents=True, exist_ok=True)
        stored_path = sub_folder / f"{source_id}.bin"
        stored_path.write_bytes(content)

        # Upsert SubmissionFile
        stmt = select(SubmissionFile).where(
            SubmissionFile.submission_id == submission_id,
            SubmissionFile.source_id == source_id,
        )
        existing_file = db.execute(stmt).scalar_one_or_none()

        if existing_file:
            existing_file.original_filename = safe_name
            existing_file.storage_path = str(stored_path)
            existing_file.sha256_hash = file_sha256
            existing_file.byte_size = len(content)
            existing_file.declared_row_count = decl.declared_row_count
            existing_file.actual_row_count = len(items)
            file_record = existing_file
        else:
            file_record = SubmissionFile(
                submission_id=submission_id,
                source_id=source_id,
                record_type=decl.record_type,
                original_filename=safe_name,
                storage_path=str(stored_path),
                sha256_hash=file_sha256,
                byte_size=len(content),
                declared_row_count=decl.declared_row_count,
                actual_row_count=len(items),
            )
            db.add(file_record)

        db.commit()
        db.refresh(file_record)
        return file_record

    def validate_submission(self, submission_id: str, db: Session) -> QualityReport:
        submission = db.get(Submission, submission_id)
        if not submission:
            raise IngestionError(
                "SUBMISSION_NOT_FOUND", f"Submission '{submission_id}' not found", 404
            )

        if submission.status == "committed":
            raise IngestionError(
                "SUBMISSION_IMMUTABLE",
                f"Submission '{submission_id}' is committed and cannot be re-validated",
                409,
            )

        manifest_dict = json.loads(submission.manifest_json)
        manifest = ManifestDeclaration.model_validate(manifest_dict)

        # Read all files uploaded for this submission
        stmt = select(SubmissionFile).where(SubmissionFile.submission_id == submission_id)
        files = db.execute(stmt).scalars().all()

        parsed_files: dict[str, list[ParsedRawItem]] = {}
        for f in files:
            path = Path(f.storage_path)
            if path.exists():
                content = path.read_bytes()
                _, items = parse_source_file(content, f.original_filename)
                parsed_files[f.source_id] = items

        # Evaluate quality
        report = evaluate_submission_quality(
            manifest=manifest,
            submission_id=submission_id,
            parsed_files=parsed_files,
        )

        # Clear existing raw/normalized records and issues for this submission
        db.query(ValidationIssue).filter(ValidationIssue.submission_id == submission_id).delete()
        db.query(NormalizedRecord).filter(NormalizedRecord.submission_id == submission_id).delete()
        db.query(RawRecord).filter(RawRecord.submission_id == submission_id).delete()
        db.flush()

        # Persist issues
        for issue in report.issues:
            db_issue = ValidationIssue(
                submission_id=submission_id,
                source_id=issue.source_id,
                record_type=issue.record_type,
                row_locator=issue.row_locator,
                issue_type=issue.issue_type,
                severity=issue.severity,
                field_name=issue.field_name,
                message=issue.message,
            )
            db.add(db_issue)

        # Persist raw and normalized records
        for rec in report.normalized_records:
            db_raw = RawRecord(
                submission_id=submission_id,
                source_id=rec.source_id,
                record_type=rec.record_type,
                row_locator=rec.row_locator,
                sha256_hash=rec.raw_hash,
                raw_payload=json.dumps(rec.raw_payload, ensure_ascii=False),
            )
            db.add(db_raw)
            db.flush()

            db_norm = NormalizedRecord(
                raw_record_id=db_raw.id,
                submission_id=submission_id,
                entity_id=manifest.entity_id,
                source_id=rec.source_id,
                record_type=rec.record_type,
                native_id=rec.native_id,
                timestamp=rec.timestamp,
                normalized_data=json.dumps(rec.normalized_data, ensure_ascii=False),
                is_quarantined=rec.is_quarantined,
            )
            db.add(db_norm)

        # Update status to validated
        submission.status = "validated"
        db.commit()
        db.refresh(submission)
        return report

    def commit_submission(
        self,
        submission_id: str,
        idempotency_key: str | None,
        db: Session,
    ) -> Submission:
        submission = db.get(Submission, submission_id)
        if not submission:
            raise IngestionError(
                "SUBMISSION_NOT_FOUND", f"Submission '{submission_id}' not found", 404
            )

        if submission.status == "committed":
            # Check idempotency
            if idempotency_key and submission.idempotency_key == idempotency_key:
                return submission
            if not idempotency_key:
                return submission
            raise IngestionError(
                "IDEMPOTENCY_CONFLICT",
                "Submission is already committed with a different key",
                409,
            )

        if submission.status != "validated":
            raise IngestionError(
                "INVALID_STATE",
                f"Cannot commit submission in '{submission.status}' status; run validation first",
                409,
            )

        # Check if idempotency_key is used elsewhere
        if idempotency_key:
            stmt = select(Submission).where(Submission.idempotency_key == idempotency_key)
            existing = db.execute(stmt).scalar_one_or_none()
            if existing and existing.id != submission_id:
                raise IngestionError(
                    "IDEMPOTENCY_CONFLICT",
                    f"Idempotency key '{idempotency_key}' is already used by submission '{existing.id}'",
                    409,
                )

        submission.status = "committed"
        submission.committed_at = datetime.datetime.now(datetime.timezone.utc)
        submission.idempotency_key = idempotency_key

        # Build cryptographic commitments for files and canonical records
        from db.models.evidence_integrity import EvidenceCommitment
        from packages.evidence_integrity.canonical import build_record_commitment
        from packages.evidence_integrity.custody import CustodyLogManager
        from packages.evidence_integrity.hashing import MerkleTree, generate_record_nonce

        # 1. Commitments for uploaded files
        stmt_files = select(SubmissionFile).where(SubmissionFile.submission_id == submission_id)
        files = list(db.execute(stmt_files).scalars().all())
        file_hashes = []
        for f in files:
            file_hashes.append(f.sha256_hash)
            fc = EvidenceCommitment(
                entity_id=submission.entity_id,
                submission_id=submission_id,
                commitment_type="raw_file",
                record_type=f.record_type,
                record_id=f.source_id,
                raw_file_sha256=f.sha256_hash,
                details_json=json.dumps(
                    {"filename": f.original_filename, "byte_size": f.byte_size}
                ),
            )
            db.add(fc)

        # 2. Canonical commitments for normalized records
        stmt_norm = select(NormalizedRecord).where(NormalizedRecord.submission_id == submission_id)
        norm_records = list(db.execute(stmt_norm).scalars().all())
        record_digests = []
        for nr in norm_records:
            nonce = generate_record_nonce()
            c_json, digest = build_record_commitment(
                entity_id=submission.entity_id,
                record_type=nr.record_type,
                native_id=nr.native_id,
                payload=json.loads(nr.normalized_data),
                nonce=nonce,
            )
            record_digests.append(digest)
            rc = EvidenceCommitment(
                entity_id=submission.entity_id,
                submission_id=submission_id,
                commitment_type="canonical_record",
                record_type=nr.record_type,
                record_id=nr.native_id,
                canonical_digest=digest,
                nonce=nonce,
                details_json=json.dumps({"raw_record_id": nr.raw_record_id}),
            )
            db.add(rc)

        # 3. Merkle tree batch commitment
        all_leaves = file_hashes + record_digests
        merkle_tree = MerkleTree(all_leaves if all_leaves else ["0" * 64])
        batch_root = merkle_tree.get_root_hex()

        bc = EvidenceCommitment(
            entity_id=submission.entity_id,
            submission_id=submission_id,
            commitment_type="merkle_batch",
            merkle_root=batch_root,
            details_json=json.dumps(
                {
                    "leaf_count": len(all_leaves),
                    "file_count": len(files),
                    "record_count": len(norm_records),
                }
            ),
        )
        db.add(bc)

        # 4. Signed custody log event
        event_type = (
            "submission_committed" if submission.revision == 1 else "evidence_revision_registered"
        )
        custody_mgr = CustodyLogManager(db)
        custody_mgr.record_event(
            entity_id=submission.entity_id,
            event_type=event_type,
            object_type="submission",
            object_id=submission.id,
            object_version=submission.revision,
            evidence_commitment=batch_root,
            actor_id="system_ingestion",
            metadata={"source_file_count": len(files), "record_count": len(norm_records)},
        )

        db.commit()
        db.refresh(submission)
        return submission

    def get_quality_summary(self, submission_id: str, db: Session) -> dict[str, Any]:
        submission = db.get(Submission, submission_id)
        if not submission:
            raise IngestionError(
                "SUBMISSION_NOT_FOUND", f"Submission '{submission_id}' not found", 404
            )

        manifest_dict = json.loads(submission.manifest_json)
        manifest = ManifestDeclaration.model_validate(manifest_dict)

        # Aggregate counts
        stmt_issues = select(ValidationIssue).where(ValidationIssue.submission_id == submission_id)
        issues = db.execute(stmt_issues).scalars().all()

        stmt_norm = select(NormalizedRecord).where(NormalizedRecord.submission_id == submission_id)
        records = db.execute(stmt_norm).scalars().all()

        accepted = sum(1 for r in records if not r.is_quarantined)
        quarantined = sum(1 for r in records if r.is_quarantined)
        rejected = quarantined  # rejected/quarantined

        duplicate_count = sum(
            1 for i in issues if i.issue_type in ("DUPLICATE_NATIVE_ID", "CONFLICTING_IDENTITY")
        )
        orphan_count = sum(1 for i in issues if i.issue_type == "ORPHAN_REFERENCE")
        ts_count = sum(
            1 for i in issues if i.issue_type in ("MALFORMED_TIMESTAMP", "TIMESTAMP_OUT_OF_PERIOD")
        )

        # File summaries
        stmt_files = select(SubmissionFile).where(SubmissionFile.submission_id == submission_id)
        files = {f.source_id: f for f in db.execute(stmt_files).scalars().all()}

        source_summaries = {}
        for s in manifest.sources:
            f = files.get(s.source_id)
            if f:
                source_summaries[s.source_id] = {
                    "source_id": s.source_id,
                    "record_type": s.record_type,
                    "declared_rows": s.declared_row_count,
                    "actual_rows": f.actual_row_count,
                    "status": "PRESENT",
                    "sha256": f.sha256_hash,
                    "is_optional": s.is_optional,
                }
            else:
                source_summaries[s.source_id] = {
                    "source_id": s.source_id,
                    "record_type": s.record_type,
                    "declared_rows": s.declared_row_count,
                    "actual_rows": 0,
                    "status": "UNKNOWN" if s.is_optional else "MISSING",
                    "sha256": None,
                    "is_optional": s.is_optional,
                }

        issues_data = [
            {
                "id": i.id,
                "source_id": i.source_id,
                "record_type": i.record_type,
                "row_locator": i.row_locator,
                "issue_type": i.issue_type,
                "severity": i.severity,
                "field_name": i.field_name,
                "message": i.message,
            }
            for i in issues
        ]

        return {
            "submission_id": submission_id,
            "entity_id": submission.entity_id,
            "status": submission.status,
            "revision": submission.revision,
            "accepted_count": accepted,
            "rejected_count": rejected,
            "quarantined_count": quarantined,
            "duplicate_count": duplicate_count,
            "orphan_count": orphan_count,
            "timestamp_problem_count": ts_count,
            "source_summaries": source_summaries,
            "issues": issues_data,
        }
