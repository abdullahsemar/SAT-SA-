"""Resolve every citation against persisted records and the actual uploaded bytes."""

from pathlib import Path

from db.models.evidence import NormalizedRecord, RawRecord
from packages.ingestion.parsers import parse_source_file


def validate_citations(findings, db, submission):
    broken = []
    files = {f.source_id: f for f in submission.files}
    parsed = {}
    for source, file in files.items():
        content = Path(file.storage_path).read_bytes()
        import hashlib

        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != file.sha256_hash or len(content) != file.byte_size:
            broken.append({"source_id": source, "reason": "uploaded_file_digest_mismatch"})
        try:
            digest, rows = parse_source_file(content, file.original_filename)
            parsed[source] = {row.row_locator: row.sha256_hash for row in rows}
        except Exception:
            broken.append({"source_id": source, "reason": "unparseable_or_tampered_source_file"})
            parsed[source] = {}
    for finding in findings:
        refs = finding.supporting_records
        if not refs and finding.evidence_state in {
            "supported",
            "potential_concern",
            "contradictory",
        }:
            # Permit explicit source/submission-level missing-evidence observations
            if finding.primary_object_type in {"source", "submission"}:
                continue
            broken.append({"finding_id": finding.id, "reason": "missing_required_citations"})
        for ref in refs:
            rec_id = ref.get("record_id")
            if not rec_id or str(rec_id).lower() in (
                "placeholder",
                "dummy",
                "fabricated",
                "null",
                "none",
            ):
                broken.append(
                    {"finding_id": finding.id, "reason": "fabricated_or_placeholder_record_id"}
                )
                continue

            sha = ref.get("sha256")
            if (
                not isinstance(sha, str)
                or len(sha) != 64
                or sha == "0" * 64
                or len(set(sha.lower())) <= 1
            ):
                broken.append(
                    {"finding_id": finding.id, "reason": "constant_placeholder_or_invalid_hash"}
                )
                continue

            record = db.get(NormalizedRecord, rec_id)
            raw = db.get(RawRecord, record.raw_record_id) if record else None
            if (
                not record
                or not raw
                or record.submission_id != submission.id
                or record.entity_id != submission.entity_id
            ):
                broken.append(
                    {"finding_id": finding.id, "reason": "unresolvable_or_cross_scope_record"}
                )
                continue
            if any(
                (
                    ref.get("source_id") != record.source_id,
                    ref.get("record_type") != record.record_type,
                    ref.get("native_id") != record.native_id,
                    ref.get("locator") != raw.row_locator,
                    ref.get("sha256") != raw.sha256_hash,
                    parsed.get(record.source_id, {}).get(raw.row_locator) != raw.sha256_hash,
                )
            ):
                broken.append({"finding_id": finding.id, "reason": "citation_provenance_mismatch"})
    return broken
