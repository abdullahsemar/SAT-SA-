import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from db.models.evidence import NormalizedRecord, RawRecord, Submission
from packages.ingestion.manifest import ManifestDeclaration, SourceDeclaration


@dataclass
class SourceReference:
    source_id: str
    record_id: str
    record_type: str
    locator: str
    native_id: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "record_id": self.record_id,
            "record_type": self.record_type,
            "locator": self.locator,
            "native_id": self.native_id,
            "sha256": self.sha256,
        }


class AssessmentContext:
    def __init__(
        self,
        submission: Submission,
        normalized_records: list[NormalizedRecord] | None = None,
        raw_records: list[RawRecord] | None = None,
        policy_path: str = "config/policies/demo-v1.json",
        rules_path: str = "config/detectors/rules-v1.json",
    ):
        self.submission = submission
        manifest_dict = None
        if submission.manifest_json:
            try:
                parsed = json.loads(submission.manifest_json)
                if isinstance(parsed, dict) and "entity_id" in parsed and "sources" in parsed:
                    manifest_dict = parsed
            except Exception:
                pass

        if manifest_dict:
            self.manifest = ManifestDeclaration.model_validate(manifest_dict)
        else:
            self.manifest = ManifestDeclaration(
                manifest_version="1.0.0",
                entity_id=submission.entity_id,
                period_start=submission.period_start,
                period_end=submission.period_end,
                source_timezone=getattr(submission, "source_timezone", "UTC") or "UTC",
                sources=[
                    SourceDeclaration(
                        source_id="src-cases",
                        record_type="cases",
                        declared_row_count=0,
                        export_scope="Default export scope",
                        lineage="Default Lineage",
                        sampling_method="full_population",
                    )
                ],
            )

        if normalized_records is None:
            normalized_records = list(getattr(submission, "normalized_records", []))
        if raw_records is None:
            raw_records = list(getattr(submission, "raw_records", []))

        # Strictly scope to submission and entity
        sub_id = getattr(submission, "id", None)
        ent_id = getattr(submission, "entity_id", None)
        if sub_id:
            normalized_records = [
                r for r in normalized_records if getattr(r, "submission_id", sub_id) == sub_id
            ]
            raw_records = [r for r in raw_records if getattr(r, "submission_id", sub_id) == sub_id]
        if ent_id:
            normalized_records = [
                r for r in normalized_records if getattr(r, "entity_id", ent_id) == ent_id
            ]
            raw_records = [r for r in raw_records if getattr(r, "entity_id", ent_id) == ent_id]

        # Build lookup tables
        self.raw_by_id: dict[str, RawRecord] = {r.id: r for r in raw_records}
        self.records_by_type: dict[str, list[NormalizedRecord]] = {}
        self.records_by_native_id: dict[tuple[str, str], NormalizedRecord] = {}
        self.collisions_by_native_id: dict[tuple[str, str], list[NormalizedRecord]] = {}

        for r in normalized_records:
            self.records_by_type.setdefault(r.record_type, []).append(r)
            if r.is_quarantined:
                continue
            key = (r.record_type, str(r.native_id))
            if key in self.records_by_native_id:
                self.collisions_by_native_id.setdefault(
                    key, [self.records_by_native_id[key]]
                ).append(r)
            else:
                self.records_by_native_id[key] = r

        # Load configs
        p_path = Path(policy_path)
        self.policy = json.loads(p_path.read_text(encoding="utf-8")) if p_path.exists() else {}

        r_path = Path(rules_path)
        self.rules = json.loads(r_path.read_text(encoding="utf-8")) if r_path.exists() else {}

        # Track excluded claims
        self.excluded_claims: list[dict[str, Any]] = []

        # Cutoff time frozen to submission period_end in UTC
        cutoff = self.manifest.period_end
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=datetime.timezone.utc)
        self.cutoff_time = cutoff

        # Track declared vs submitted sources
        self.declared_sources: dict[str, SourceDeclaration] = {
            s.source_id: s for s in self.manifest.sources
        }
        self.submitted_sources: set[str] = {f.source_id for f in submission.files}

        # Aliases for detectors
        self.submission_id = self.submission.id
        self.period_end = self.cutoff_time

    def get_records(self, record_type: str) -> list[dict[str, Any]]:
        """Returns records of given type from normalized_records or scenario report."""
        type_keys = [record_type]
        if record_type in ("actions", "investigation_actions"):
            type_keys = ["actions", "investigation_actions"]
        elif record_type in ("claims", "reported_claims"):
            type_keys = ["claims", "reported_claims"]
        elif record_type in ("remediations", "remediations_validations"):
            type_keys = ["remediations", "remediations_validations"]

        norm_list = []
        for tk in type_keys:
            norm_list.extend(self.records_by_type.get(tk, []))

        if norm_list:
            res = []
            for r in norm_list:
                if r.is_quarantined:
                    continue
                d = (
                    json.loads(r.normalized_data)
                    if isinstance(r.normalized_data, str)
                    else dict(r.normalized_data)
                )
                nid = str(r.native_id)
                d.setdefault("native_id", nid)
                d.setdefault("id", nid)
                if r.record_type == "cases":
                    d.setdefault("case_id", nid)
                elif r.record_type == "assets":
                    d.setdefault("asset_id", nid)
                elif r.record_type == "alerts":
                    d.setdefault("alert_id", nid)
                elif r.record_type in ("actions", "investigation_actions"):
                    d.setdefault("action_id", nid)
                elif r.record_type in ("claims", "reported_claims"):
                    d.setdefault("claim_id", nid)
                    if "metric_value" in d and "claimed_value" not in d:
                        d["claimed_value"] = d["metric_value"]
                    elif "claimed_value" in d and "metric_value" not in d:
                        d["metric_value"] = d["claimed_value"]
                    if "metric_name" in d and "claim_type" not in d:
                        d["claim_type"] = d["metric_name"]
                    elif "claim_type" in d and "metric_name" not in d:
                        d["metric_name"] = d["claim_type"]
                elif r.record_type in ("remediations", "remediations_validations"):
                    d.setdefault("remediation_id", nid)
                elif r.record_type == "escalations":
                    d.setdefault("escalation_id", nid)

                if "entity_id" not in d:
                    d["entity_id"] = getattr(
                        r, "entity_id", getattr(self.submission, "entity_id", None)
                    )
                d["submission_id"] = getattr(self.submission, "id", None)
                d["_record_id"] = str(r.id)
                d["_source_ref"] = self.get_source_ref(r)
                res.append(d)
            return res

        return []

    def get_source_reference(
        self, record_type: str, id_field: str, val: Any
    ) -> SourceReference | None:
        """Finds or builds a traceable SourceReference for a record."""
        if val is None:
            return None
        val_str = str(val).strip()
        if not val_str or val_str.upper() == "UNKNOWN":
            return None

        rec = self.records_by_native_id.get((record_type, val_str))
        if not rec and record_type == "actions":
            rec = self.records_by_native_id.get(("investigation_actions", val_str))
        elif not rec and record_type == "investigation_actions":
            rec = self.records_by_native_id.get(("actions", val_str))
        elif not rec and record_type == "claims":
            rec = self.records_by_native_id.get(("reported_claims", val_str))
        elif not rec and record_type == "reported_claims":
            rec = self.records_by_native_id.get(("claims", val_str))

        if not rec:
            # Check by NormalizedRecord.id (UUID)
            type_keys = [record_type]
            if record_type in ("actions", "investigation_actions"):
                type_keys = ["actions", "investigation_actions"]
            elif record_type in ("claims", "reported_claims"):
                type_keys = ["claims", "reported_claims"]
            for tk in type_keys:
                for r in self.records_by_type.get(tk, []):
                    if not r.is_quarantined and r.id == val_str:
                        rec = r
                        break
                if rec:
                    break

        if rec:
            raw = self.raw_by_id.get(rec.raw_record_id)
            return SourceReference(
                source_id=rec.source_id,
                record_id=rec.id,
                record_type=rec.record_type,
                locator=raw.row_locator if raw else "unknown",
                native_id=rec.native_id,
                sha256=raw.sha256_hash if raw else "unknown",
            )

        # Disclose the gap; do not invent a synthetic record or constant digest
        return None

    def is_source_available(self, record_type: str) -> bool:
        type_keys = [record_type]
        if record_type in ("actions", "investigation_actions"):
            type_keys = ["actions", "investigation_actions"]
        elif record_type in ("claims", "reported_claims"):
            type_keys = ["claims", "reported_claims"]
        elif record_type in ("remediations", "remediations_validations"):
            type_keys = ["remediations", "remediations_validations"]

        for tk in type_keys:
            if bool(self.records_by_type.get(tk)):
                return True

        for src in self.manifest.sources:
            if src.record_type in type_keys and src.source_id in self.submitted_sources:
                return True
        return False

    def has_declared_claims_source(self) -> bool:
        """Returns True if any claim source was declared in the manifest."""
        return any(s.record_type in ("claims", "reported_claims") for s in self.manifest.sources)

    def get_declared_claims_sources(self) -> list[SourceDeclaration]:
        """Returns list of declared claims sources."""
        return [s for s in self.manifest.sources if s.record_type in ("claims", "reported_claims")]

    def has_declared_escalation_source(self) -> bool:
        """Returns True if an authoritative escalation source was declared."""
        for s in self.manifest.sources:
            if s.record_type == "escalations" or "escalat" in str(s.export_scope or "").lower():
                return True
        return False

    def source_completeness(self, record_type: str) -> tuple[bool, str]:
        """Check every declared source before inferring absence or population rates."""
        aliases = {
            "actions": {"actions", "investigation_actions"},
            "claims": {"claims", "reported_claims"},
        }
        types = aliases.get(record_type, {record_type})
        sources = [s for s in self.manifest.sources if s.record_type in types]
        if not sources:
            return False, f"No {record_type} source declared."
        files = {f.source_id: f for f in self.submission.files}
        records = [r for t in types for r in self.records_by_type.get(t, [])]
        issues = getattr(self.submission, "validation_issues", [])
        for src in sources:
            f = files.get(src.source_id)
            if f is None:
                return False, f"Declared source {src.source_id} was not submitted."
            if src.sampling_method != "full_population":
                return False, f"Source {src.source_id} is sampled ({src.sampling_method})."
            if any(
                w in src.export_scope.lower()
                for w in ("sample", "subset", "partial", "filtered", "incomplete", "selected")
            ):
                return False, f"Source {src.source_id} declares a partial export scope."
            relevant = [r for r in records if r.source_id == src.source_id]
            if f.actual_row_count != src.declared_row_count or len(relevant) != f.actual_row_count:
                return (
                    False,
                    f"Source {src.source_id} has inconsistent declared, parsed or retained counts.",
                )
            if any(r.is_quarantined for r in relevant):
                return False, f"Source {src.source_id} contains quarantined records."
            if len({r.native_id for r in relevant}) != len(relevant):
                return False, f"Source {src.source_id} contains duplicate native identifiers."
            if any(
                i.source_id == src.source_id
                and (
                    i.severity == "error"
                    or i.issue_type in {"ROW_COUNT_MISMATCH", "TIMESTAMP_OUT_OF_PERIOD"}
                )
                for i in issues
            ):
                return False, f"Source {src.source_id} has unresolved quality or coverage issues."
            for boundary, expected in (
                ("period_start", self.manifest.period_start),
                ("period_end", self.manifest.period_end),
            ):
                actual = getattr(src, boundary, None)
                if actual is not None and actual != expected:
                    return False, f"Source {src.source_id} does not cover the assessment period."
        if len({r.native_id for r in records}) != len(records):
            return False, f"Multiple {record_type} sources contain overlapping native identifiers."
        return True, f"All {record_type} sources are complete for the declared assessment scope."

    def is_authoritative_escalation_source_complete(self) -> tuple[bool, str]:
        return self.source_completeness("escalations")

    def get_source_ref(self, record: NormalizedRecord) -> dict[str, Any]:
        raw = self.raw_by_id.get(record.raw_record_id)
        locator = raw.row_locator if raw else "unknown"
        sha256 = raw.sha256_hash if raw else "unknown"
        return SourceReference(
            source_id=record.source_id,
            record_id=record.id,
            record_type=record.record_type,
            locator=locator,
            native_id=record.native_id,
            sha256=sha256,
        ).to_dict()

    def get_investigation_passages(self) -> list[dict[str, Any]]:
        """Extracts candidate narrative passages from cases and investigation actions."""
        passages: list[dict[str, Any]] = []

        # 1. Cases
        for case in self.get_records("cases"):
            c_id = str(case.get("native_id") or case.get("case_id") or case.get("id", ""))
            if not c_id or c_id == "UNKNOWN":
                continue
            s_ref = case.get("_source_ref") or {}
            src_id = s_ref.get("source_id", "src-cases")
            rec_id = s_ref.get("record_id", c_id)

            # Extract narrative fields
            texts = []
            if case.get("disposition"):
                texts.append(f"Disposition: {case['disposition']}")
            if case.get("root_cause") and case.get("root_cause") != "UNKNOWN":
                texts.append(f"Root cause: {case['root_cause']}")
            if case.get("title"):
                texts.append(str(case["title"]))

            for t in texts:
                if t.strip():
                    passages.append(
                        {
                            "record_id": rec_id,
                            "source_id": src_id,
                            "record_type": "cases",
                            "case_id": c_id,
                            "text": t.strip(),
                        }
                    )

        # 2. Investigation Actions
        for act in self.get_records("investigation_actions") or self.get_records("actions"):
            a_id = str(act.get("native_id") or act.get("action_id") or act.get("id", ""))
            if not a_id or a_id == "UNKNOWN":
                continue
            c_id = str(act.get("case_id", ""))
            s_ref = act.get("_source_ref") or {}
            src_id = s_ref.get("source_id", "src-actions")
            rec_id = s_ref.get("record_id", a_id)

            details = act.get("details", {})
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    details = {"raw": details}

            texts = []
            if isinstance(details, dict):
                for k in ("notes", "triage_notes", "description", "summary", "comment"):
                    val = details.get(k)
                    if val and isinstance(val, str) and val.strip():
                        texts.append(val.strip())

            if not texts and act.get("action_type"):
                texts.append(f"Action: {act.get('action_type')}")

            for t in texts:
                passages.append(
                    {
                        "record_id": rec_id,
                        "source_id": src_id,
                        "record_type": "investigation_actions",
                        "case_id": c_id,
                        "text": t,
                    }
                )

        return passages
