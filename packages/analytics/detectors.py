"""Supervisory analytics detectors for SAT-SA.

Implements the 5 bounded supervisory rule families:
1. Investigation Evidence (POL-INV-001): Fast closure with required artifacts is not penalized;
   missing investigation export yields insufficient_evidence, not failure.
2. Escalation Evidence (POL-ESC-002): Checks due escalations accounting for policy exceptions,
   actions not-yet-due at cutoff, and duplicate escalations.
3. Monitoring Coverage (POL-COV-003): Critical assets vs dated inventory & coverage;
   quiet well-monitored assets are not flagged; missing coverage yields insufficient_evidence.
4. KPI Reconciliation (POL-KPI-004): Mathematical bounded interval [y/n, (y+u)/n] over distinct cases.
5. Recurrence Context (POL-REC-005): Stable asset recurring condition after closure;
   presents as hypothesis, respects benign exceptions & external owners; marks peer comparison unavailable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from packages.analytics.claims import ClaimReconciler
from packages.analytics.context import AssessmentContext
from packages.analytics.obligations import ObligationEvaluator
from packages.analytics.reconstruction import EvidenceGraphReconstructor
from packages.ingestion.claim_contract import claim_period, metric_kind


class DetectorResult:
    def __init__(
        self,
        rule_id: str,
        rule_title: str,
        severity: str,
        evidence_state: str,
        primary_object_type: str,
        primary_object_id: str,
        affected_asset_ids: List[str],
        rationale: str,
        uncertainty_note: Optional[str] = None,
        supporting_records: Optional[List[Dict[str, Any]]] = None,
        peer_comparison_status: Optional[str] = "peer_comparison_unavailable",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.finding_id = str(uuid.uuid4())
        self.rule_id = rule_id
        self.rule_title = rule_title
        self.severity = severity
        self.evidence_state = evidence_state
        self.primary_object_type = primary_object_type
        self.primary_object_id = primary_object_id
        self.affected_asset_ids = affected_asset_ids or []
        self.rationale = rationale
        self.uncertainty_note = uncertainty_note
        self.supporting_records = supporting_records or []
        self.peer_comparison_status = peer_comparison_status
        self.extra_metadata = extra_metadata or {}

    def to_dict(self, submission_id: str) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "submission_id": submission_id,
            "rule_id": self.rule_id,
            "rule_title": self.rule_title,
            "severity": self.severity,
            "evidence_state": self.evidence_state,
            "primary_object_type": self.primary_object_type,
            "primary_object_id": self.primary_object_id,
            "affected_asset_ids": self.affected_asset_ids,
            "rationale": self.rationale,
            "uncertainty_note": self.uncertainty_note,
            "supporting_records": self.supporting_records,
            "peer_comparison_status": self.peer_comparison_status,
            "finding_metadata": self.extra_metadata,
        }


class BaseDetector:
    def __init__(
        self,
        context: AssessmentContext,
        graph: EvidenceGraphReconstructor,
        evaluator: ObligationEvaluator,
        rule_config: Dict[str, Any],
    ):
        self.ctx = context
        self.graph = graph
        self.evaluator = evaluator
        self.evaluator.add_submitted_exceptions(context.get_records("exceptions"))
        self.config = rule_config

    def run(self) -> List[DetectorResult]:
        raise NotImplementedError


def is_substantive_text(val: Any) -> bool:
    """Returns True if text is non-empty, non-whitespace, and not a placeholder."""
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False
    if s.upper() in (
        "",
        "UNKNOWN",
        "NONE",
        "NULL",
        "N/A",
        "NA",
        "UNDEFINED",
        "PENDING",
        "PLACEHOLDER",
        "-",
    ):
        return False
    return True


class InvestigationEvidenceDetector(BaseDetector):
    """Rule POL-INV-001: Evaluates case investigation quality and closure evidence."""

    def run(self) -> List[DetectorResult]:
        results: List[DetectorResult] = []
        rule_id = self.config.get("rule_id", "POL-INV-001")
        rule_title = self.config.get("title", "Case Investigation Quality and Closure Evidence")

        # Check if cases table is present
        case_records = self.ctx.get_records("cases")
        if not case_records:
            results.append(
                DetectorResult(
                    rule_id=rule_id,
                    rule_title=rule_title,
                    severity="medium",
                    evidence_state="insufficient_evidence",
                    primary_object_type="submission",
                    primary_object_id=self.ctx.submission_id,
                    affected_asset_ids=[],
                    rationale="No case records were exported in this submission. Cannot verify investigation quality.",
                    uncertainty_note="Missing 'cases' table export; supervisory verdict suspended.",
                )
            )
            return results

        min_duration_minutes = float(self.config.get("min_investigation_duration_minutes", 1.0))
        has_action_source, action_source_reason = self.ctx.source_completeness("actions")

        for case in case_records:
            case_id = case.get("native_id") or case.get("case_id") or case.get("id")
            if not case_id or case_id == "UNKNOWN":
                continue
            status = str(case.get("status", "")).upper()
            if not status and case.get("closed_at"):
                status = "CLOSED"
            if status not in ("CLOSED", "RESOLVED"):
                continue

            severity = str(case.get("severity", "MEDIUM")).upper()
            created_at_dt = self.graph._parse_dt(case.get("created_at"))
            closed_at_dt = self.graph._parse_dt(case.get("closed_at") or case.get("updated_at"))

            # Calculate duration
            duration_minutes = None
            if created_at_dt and closed_at_dt:
                duration_minutes = (closed_at_dt - created_at_dt).total_seconds() / 60.0

            # Check if active approved policy exception exists
            exception = self.evaluator.match_exception(
                rule_id, "case", case_id, created_at_dt or self.ctx.cutoff_time
            )
            if exception:
                continue

            # Gather associated actions/artifacts
            actions = self.graph.case_actions.get(case_id, [])

            # Build source refs
            case_ref = self.ctx.get_source_reference("cases", "case_id", case_id)
            supporting_refs = [case_ref.to_dict()] if case_ref else []
            for a in actions:
                a_id = a.get("native_id") or a.get("action_id") or a.get("id")
                if a_id:
                    a_ref = self.ctx.get_source_reference("actions", "action_id", a_id)
                    if a_ref:
                        supporting_refs.append(a_ref.to_dict())

            affected_assets = [
                self.graph.alerts_by_id[al_id].get("asset_id")
                or self.graph.alerts_by_id[al_id].get("affected_asset_id")
                for al_id in self.graph.case_alerts.get(case_id, [])
                if al_id in self.graph.alerts_by_id
                and (
                    self.graph.alerts_by_id[al_id].get("asset_id")
                    or self.graph.alerts_by_id[al_id].get("affected_asset_id")
                )
            ]

            # Substantive closure text check (root cause, disposition, resolution)
            has_substantive_disposition = (
                is_substantive_text(case.get("disposition"))
                or is_substantive_text(case.get("resolution"))
                or is_substantive_text(case.get("closing_notes"))
            )
            has_substantive_root_cause = is_substantive_text(case.get("root_cause"))

            # Check policy required actions/artifacts for this severity
            art_spec = self.evaluator.get_case_artifact_obligation(severity)
            required_actions = [a.lower() for a in art_spec.get("required_actions", [])]
            require_hash = art_spec.get("require_artifact_hash", False)

            missing_requirements: List[str] = []

            # A nonempty root_cause is not sufficient by itself if policy requires other actions/artifacts
            if required_actions:
                for req in required_actions:
                    matching = [a for a in actions if req in str(a.get("action_type", "")).lower()]
                    if not matching:
                        missing_requirements.append(f"required action '{req}'")
                    elif require_hash:
                        has_hash = any(
                            is_substantive_text(
                                a.get("artifact_hash") or a.get("sha256") or a.get("hash")
                            )
                            for a in matching
                        )
                        if not has_hash:
                            missing_requirements.append(f"cryptographic artifact hash for '{req}'")

            # Check general closure evidence if no specific actions were defined
            if not has_substantive_disposition and not has_substantive_root_cause:
                if not any("triage" in str(a.get("action_type", "")).lower() for a in actions):
                    missing_requirements.append(
                        "closure disposition or forensic triage documentation"
                    )

            # Fast closure evaluation
            is_fast_closure = (
                duration_minutes is not None and duration_minutes < min_duration_minutes
            )

            if missing_requirements:
                if not has_action_source:
                    evidence_state = "insufficient_evidence"
                    rationale = (
                        f"Case {case_id} ({severity}) was closed, but required investigation artifacts "
                        f"({', '.join(missing_requirements)}) could not be verified because action logs are missing or incomplete."
                    )
                    uncertainty_note = action_source_reason
                else:
                    evidence_state = "potential_concern"
                    if has_substantive_root_cause:
                        rationale = (
                            f"Case {case_id} ({severity}) recorded root cause '{case.get('root_cause')}', "
                            f"but other policy-required closure artifacts are absent ({', '.join(missing_requirements)})."
                        )
                    elif is_fast_closure:
                        rationale = (
                            f"Case {case_id} ({severity}) was closed in {duration_minutes:.1f} minutes "
                            f"(below threshold of {min_duration_minutes:.0f}m) without required closure artifacts: "
                            f"{', '.join(missing_requirements)}."
                        )
                    else:
                        rationale = (
                            f"Case {case_id} ({severity}) was closed without required closure artifacts: "
                            f"{', '.join(missing_requirements)}."
                        )
                    uncertainty_note = "Action logs provided but required investigation artifacts were not recorded."

                results.append(
                    DetectorResult(
                        rule_id=rule_id,
                        rule_title=rule_title,
                        severity="high" if severity in ("CRITICAL", "HIGH") else "medium",
                        evidence_state=evidence_state,
                        primary_object_type="case",
                        primary_object_id=case_id,
                        affected_asset_ids=list(set(affected_assets)),
                        rationale=rationale,
                        uncertainty_note=uncertainty_note,
                        supporting_records=supporting_refs,
                    )
                )
            else:
                # All applicable closure requirements are supported.
                # A fast closure with adequate evidence: do not penalize it merely for being fast.
                continue

        return results


class EscalationEvidenceDetector(BaseDetector):
    """Rule POL-ESC-002: Verifies escalation timeliness, exceptions, and cutoffs."""

    def run(self) -> List[DetectorResult]:
        results: List[DetectorResult] = []
        rule_id = self.config.get("rule_id", "POL-ESC-002")
        rule_title = self.config.get("title", "Escalation Policy Compliance and Timeliness")

        case_records = self.ctx.get_records("cases")
        if not case_records:
            return results

        cutoff_time = self.ctx.cutoff_time
        is_esc_complete, esc_completeness_reason = (
            self.ctx.is_authoritative_escalation_source_complete()
        )

        for case in case_records:
            case_id = case.get("native_id") or case.get("case_id") or case.get("id")
            if not case_id or case_id == "UNKNOWN":
                continue
            severity = str(case.get("severity", "MEDIUM")).upper()

            # Check eligibility by severity
            eligible_severities = self.evaluator.policy.escalation.get(
                "eligible_severities", ["CRITICAL", "HIGH"]
            )
            if severity not in eligible_severities:
                continue

            created_at = self.graph._parse_dt(case.get("created_at"))
            if not created_at:
                continue

            sla_hours = self.evaluator.get_escalation_sla_hours(severity)
            due_at = self.evaluator.get_due_time(created_at, sla_hours)

            # Check period cutoff: if due_at > cutoff_time, obligation is not yet due at snapshot time
            if not self.evaluator.is_action_due(created_at, sla_hours, cutoff_time):
                # Deadline after cutoff: no adverse escalation finding
                continue

            # If case was already closed/resolved before due_at, escalation was not overdue
            closed_at = self.graph._parse_dt(case.get("closed_at") or case.get("resolved_at"))
            if closed_at and closed_at <= due_at:
                continue

            # Check if active policy exception exists for this case or rule
            exception = self.evaluator.match_exception(rule_id, "case", case_id, created_at)
            if exception:
                # Excused by approved exception: no adverse finding
                continue

            # Check escalations recorded in actions and escalations table
            actions = self.graph.case_actions.get(case_id, [])
            direct_escs = self.graph.case_escalations.get(case_id, [])
            all_raw_escs = direct_escs + [
                a for a in actions if "escalat" in str(a.get("action_type", "")).lower()
            ]

            # Deduplicate escalations by action_id/escalation_id
            seen_actions: Set[str] = set()
            deduped_escalations = []
            for esc in all_raw_escs:
                aid = (
                    esc.get("native_id")
                    or esc.get("action_id")
                    or esc.get("escalation_id")
                    or esc.get("id")
                )
                if aid and aid not in seen_actions:
                    seen_actions.add(aid)
                    deduped_escalations.append(esc)

            case_ref = self.ctx.get_source_reference("cases", "case_id", case_id)
            supporting_refs = [case_ref.to_dict()] if case_ref else []

            # Check for indicated out-of-band escalation in narrative
            notes_text = (
                str(case.get("investigation_notes") or "")
                + " "
                + str(case.get("closing_notes") or "")
                + " "
                + str(case.get("notes") or "")
                + " "
                + str(case.get("disposition") or "")
            ).lower()
            has_oob_indication = any(
                p in notes_text
                for p in [
                    "out-of-band",
                    "out of band",
                    "escalated via phone",
                    "phone escalation",
                    "verbal escalation",
                    "phoned on-call",
                    "called on-call",
                ]
            )

            if not deduped_escalations:
                if has_oob_indication:
                    results.append(
                        DetectorResult(
                            rule_id=rule_id,
                            rule_title=rule_title,
                            severity="medium",
                            evidence_state="insufficient_evidence",
                            primary_object_type="case",
                            primary_object_id=case_id,
                            affected_asset_ids=[],
                            rationale=(
                                f"Case {case_id} ({severity}) narrative indicates an out-of-band escalation occurred, "
                                f"but no official escalation record was submitted to corroborate it."
                            ),
                            uncertainty_note="Out-of-band escalation claimed in case narrative; verification suspended pending supporting escalation records.",
                            supporting_records=supporting_refs,
                        )
                    )
                elif not is_esc_complete:
                    results.append(
                        DetectorResult(
                            rule_id=rule_id,
                            rule_title=rule_title,
                            severity="medium",
                            evidence_state="insufficient_evidence",
                            primary_object_type="case",
                            primary_object_id=case_id,
                            affected_asset_ids=[],
                            rationale=(
                                f"Case {case_id} ({severity}) had an escalation SLA of {sla_hours:.1f}h "
                                f"(due {due_at.isoformat()}), but authoritative escalation evidence was not available "
                                f"or complete ({esc_completeness_reason})."
                            ),
                            uncertainty_note="Authoritative escalation source omitted or incomplete; supervisory verdict suspended.",
                            supporting_records=supporting_refs,
                        )
                    )
                else:
                    results.append(
                        DetectorResult(
                            rule_id=rule_id,
                            rule_title=rule_title,
                            severity="high" if severity in ("HIGH", "CRITICAL") else "medium",
                            evidence_state="potential_concern",
                            primary_object_type="case",
                            primary_object_id=case_id,
                            affected_asset_ids=[],
                            rationale=(
                                f"Case {case_id} ({severity}) had an escalation SLA of {sla_hours:.1f}h "
                                f"(due {due_at.isoformat()}) before snapshot cutoff ({cutoff_time.isoformat()}), "
                                f"but no escalation action was recorded in complete authoritative evidence."
                            ),
                            uncertainty_note="No approved exception matched; verified missing from complete authoritative escalation records.",
                            supporting_records=supporting_refs,
                        )
                    )
            else:
                # Escalations exist; check if timely
                earliest_esc = min(
                    deduped_escalations,
                    key=lambda x: (
                        self.graph._parse_dt(x.get("created_at") or x.get("timestamp"))
                        or datetime.max.replace(tzinfo=timezone.utc)
                    ),
                )
                esc_dt = self.graph._parse_dt(
                    earliest_esc.get("created_at") or earliest_esc.get("timestamp")
                )
                a_id = (
                    earliest_esc.get("action_id")
                    or earliest_esc.get("escalation_id")
                    or earliest_esc.get("id")
                )
                if a_id:
                    a_ref = self.ctx.get_source_reference(
                        "actions", "action_id", a_id
                    ) or self.ctx.get_source_reference("escalations", "escalation_id", a_id)
                    if a_ref:
                        supporting_refs.append(a_ref.to_dict())

                if esc_dt and esc_dt > due_at:
                    delay_hours = (esc_dt - due_at).total_seconds() / 3600.0
                    results.append(
                        DetectorResult(
                            rule_id=rule_id,
                            rule_title=rule_title,
                            severity="medium",
                            evidence_state="potential_concern",
                            primary_object_type="case",
                            primary_object_id=case_id,
                            affected_asset_ids=[],
                            rationale=(
                                f"Case {case_id} was escalated {delay_hours:.1f} hours past the SLA deadline "
                                f"({sla_hours:.1f}h SLA)."
                            ),
                            uncertainty_note=None,
                            supporting_records=supporting_refs,
                        )
                    )

        return results


class MonitoringCoverageDetector(BaseDetector):
    """Rule POL-COV-003: Evaluates asset coverage vs telemetry and silence."""

    def run(self) -> List[DetectorResult]:
        results: List[DetectorResult] = []
        rule_id = self.config.get("rule_id", "POL-COV-003")
        rule_title = self.config.get(
            "title", "Critical Asset Monitoring Coverage and Inventory Freshness"
        )

        assets = self.ctx.get_records("assets")
        if not assets:
            results.append(
                DetectorResult(
                    rule_id=rule_id,
                    rule_title=rule_title,
                    severity="high",
                    evidence_state="insufficient_evidence",
                    primary_object_type="submission",
                    primary_object_id=self.ctx.submission_id,
                    affected_asset_ids=[],
                    rationale="Asset inventory export is missing. Cannot verify monitoring coverage.",
                    uncertainty_note="Missing 'assets' table; monitoring coverage assessment suspended.",
                )
            )
            return results

        for asset in assets:
            asset_id = asset.get("native_id") or asset.get("asset_id") or asset.get("id")
            if not asset_id or asset_id == "UNKNOWN":
                continue
            criticality = str(asset.get("criticality", "MEDIUM")).upper()
            status = str(asset.get("status", "ACTIVE")).upper()

            if criticality not in ("HIGH", "CRITICAL") or status != "ACTIVE":
                continue

            asset_ref = self.ctx.get_source_reference("assets", "asset_id", asset_id)
            supporting_refs = [asset_ref.to_dict()] if asset_ref else []

            last_heartbeat = asset.get("last_heartbeat") or asset.get("last_seen")
            raw_agent_status = asset.get("agent_status")
            agent_status = str(raw_agent_status).upper() if raw_agent_status else ""

            # Telemetry confirms broken sensor / agent
            if agent_status in ("UNHEALTHY", "DISCONNECTED", "MISSING"):
                results.append(
                    DetectorResult(
                        rule_id=rule_id,
                        rule_title=rule_title,
                        severity="high",
                        evidence_state="potential_concern",
                        primary_object_type="asset",
                        primary_object_id=asset_id,
                        affected_asset_ids=[asset_id],
                        rationale=(
                            f"Critical asset {asset_id} has unhealthy telemetry status '{agent_status}'."
                        ),
                        uncertainty_note="Confirmed coverage gap on critical asset.",
                        supporting_records=supporting_refs,
                    )
                )
                continue

            # Missing telemetry proof -> insufficient_evidence
            if not last_heartbeat and not agent_status:
                results.append(
                    DetectorResult(
                        rule_id=rule_id,
                        rule_title=rule_title,
                        severity="medium",
                        evidence_state="insufficient_evidence",
                        primary_object_type="asset",
                        primary_object_id=asset_id,
                        affected_asset_ids=[asset_id],
                        rationale=(
                            f"Critical asset {asset_id} generated 0 telemetry heartbeats or health records."
                        ),
                        uncertainty_note="Telemetry data missing from submission; healthy silence cannot be confirmed.",
                        supporting_records=supporting_refs,
                    )
                )
                continue

            # Healthy silence (0 alerts but healthy agent) or has alerts -> compliant (no finding)

        return results


class KPIReconciliationDetector(BaseDetector):
    """Rule POL-KPI-004: Reconciles self-reported claims using bounded uncertainty math."""

    def run(self) -> List[DetectorResult]:
        results: List[DetectorResult] = []
        rule_id = self.config.get("rule_id", "POL-KPI-004")
        rule_title = self.config.get("title", "Supervisory KPI Claim Reconciliation")

        claims = self.ctx.get_records("claims")
        has_declared_claims = self.ctx.has_declared_claims_source()

        # 1. No claims source declared and no claims provided -> return []
        if not has_declared_claims and not claims:
            return results

        # 2. Claims source declared but missing or incomplete (0 valid records)
        if has_declared_claims and not claims:
            declared_sources = self.ctx.get_declared_claims_sources()
            source_id = declared_sources[0].source_id if declared_sources else "claims_source"
            results.append(
                DetectorResult(
                    rule_id=rule_id,
                    rule_title=rule_title,
                    severity="medium",
                    evidence_state="insufficient_evidence",
                    primary_object_type="source",
                    primary_object_id=source_id,
                    affected_asset_ids=[],
                    rationale=f"Claims source '{source_id}' was declared in submission manifest but no claim records were submitted or available.",
                    uncertainty_note="Cannot perform supervisory KPI claim reconciliation without declared claim records.",
                    supporting_records=[],
                )
            )
            return results

        # 3. Process claims: separate malformed, out-of-scope, and valid claims
        valid_claims = []
        for c in claims:
            claim_obj_id = str(
                c.get("native_id") or c.get("claim_id") or c.get("id") or "CLAIM-UNKNOWN"
            )

            # Metric type check
            claim_type = str(c.get("claim_type", "")).lower()
            metric_name = str(c.get("metric_name", "")).lower()
            if metric_kind(metric_name) is None:
                self.ctx.excluded_claims.append(
                    {
                        "claim_id": claim_obj_id,
                        "reason": "out_of_scope_metric",
                        "claim_type": claim_type,
                        "metric_name": metric_name,
                    }
                )
                continue

            # Scope / entity check
            c_entity = c.get("entity_id")
            if (
                c_entity
                and self.ctx.submission.entity_id
                and str(c_entity) != str(self.ctx.submission.entity_id)
            ):
                self.ctx.excluded_claims.append(
                    {
                        "claim_id": claim_obj_id,
                        "reason": "out_of_scope_entity",
                        "entity_id": c_entity,
                    }
                )
                continue

            try:
                c_start, c_end = claim_period(c)
            except (ValueError, TypeError):
                self.ctx.excluded_claims.append(
                    {"claim_id": claim_obj_id, "reason": "invalid_claim_period"}
                )
                continue
            p_start = self.graph._parse_dt(self.ctx.manifest.period_start)
            if c_end <= p_start or c_start >= self.ctx.cutoff_time:
                self.ctx.excluded_claims.append(
                    {"claim_id": claim_obj_id, "reason": "out_of_scope_period"}
                )
                continue
            if c_start < p_start or c_end > self.ctx.cutoff_time:
                self.ctx.excluded_claims.append(
                    {"claim_id": claim_obj_id, "reason": "claim_period_not_fully_covered"}
                )
                continue
            if str(c.get("unit") or "percent").lower() not in {"percent", "percentage", "%"}:
                self.ctx.excluded_claims.append(
                    {"claim_id": claim_obj_id, "reason": "unsupported_metric_unit"}
                )
                continue

            # Value validation: non-numeric or out-of-range [0, 100]
            val_raw = (
                c.get("claimed_value")
                if c.get("claimed_value") is not None
                else c.get("metric_value")
            )
            if val_raw is None:
                self.ctx.excluded_claims.append(
                    {
                        "claim_id": claim_obj_id,
                        "reason": "malformed_missing_value",
                    }
                )
                continue
            try:
                val = float(val_raw)
            except (ValueError, TypeError):
                self.ctx.excluded_claims.append(
                    {
                        "claim_id": claim_obj_id,
                        "reason": "malformed_non_numeric_value",
                        "raw_value": str(val_raw),
                    }
                )
                continue
            if not (0.0 <= val <= 100.0):
                self.ctx.excluded_claims.append(
                    {
                        "claim_id": claim_obj_id,
                        "reason": "malformed_value_out_of_range",
                        "raw_value": val,
                    }
                )
                continue

            valid_claims.append((c, val, claim_obj_id))

        if not valid_claims:
            return results

        is_denom_complete, denom_reason = self.ctx.source_completeness("cases")

        cases = self.ctx.get_records("cases")

        for claim_dict, claimed_sla_pct, claim_obj_id in valid_claims:
            c_ref = self.ctx.get_source_reference(
                "claims", "claim_id", claim_obj_id
            ) or self.ctx.get_source_reference("reported_claims", "native_id", claim_obj_id)
            claim_refs = [c_ref.to_dict()] if c_ref else []

            if not cases or not is_denom_complete:
                reconciliation = ClaimReconciler.evaluate_sla_claim(
                    claimed_pct=claimed_sla_pct,
                    compliant_case_ids=set(),
                    non_compliant_case_ids=set(),
                    unknown_case_ids=set(),
                    is_denominator_complete=is_denom_complete if cases else False,
                )
                results.append(
                    DetectorResult(
                        rule_id=rule_id,
                        rule_title=rule_title,
                        severity="medium",
                        evidence_state="insufficient_evidence",
                        primary_object_type="claim",
                        primary_object_id=claim_obj_id,
                        affected_asset_ids=[],
                        rationale=reconciliation.explanation
                        if not is_denom_complete
                        else "No case data available to reconcile claimed SLA compliance.",
                        uncertainty_note=denom_reason
                        or "Cases table missing, empty, or incomplete population.",
                        supporting_records=claim_refs,
                        extra_metadata={
                            "claimed_pct": claimed_sla_pct,
                            "is_denominator_complete": is_denom_complete if cases else False,
                        },
                    )
                )
                continue

            # Group distinct cases into compliant, non-compliant, and unknown
            compliant_cases: Set[str] = set()
            non_compliant_cases: Set[str] = set()
            unknown_cases: Set[str] = set()

            cutoff_time = self.ctx.cutoff_time or datetime.now(timezone.utc)

            kind = metric_kind(claim_dict["metric_name"])
            period_start, period_end = claim_period(claim_dict)
            escalation_complete, escalation_reason = self.ctx.source_completeness("escalations")
            for case in cases:
                case_id = str(case.get("native_id") or case.get("case_id") or case.get("id"))
                severity = str(case.get("severity", "MEDIUM")).upper()
                created_at = self.graph._parse_dt(case.get("created_at"))
                if created_at and not period_start <= created_at < period_end:
                    continue
                if kind == "escalation" and severity not in self.evaluator.policy.escalation.get(
                    "eligible_severities", ["CRITICAL", "HIGH"]
                ):
                    continue
                if not created_at:
                    unknown_cases.add(case_id)
                    continue
                rule = "POL-ESC-002" if kind == "escalation" else "POL-INV-001"
                if self.evaluator.match_exception(rule, "case", case_id, created_at):
                    continue
                ref = self.ctx.get_source_reference("cases", "native_id", case_id)
                if ref:
                    claim_refs.append(ref.to_dict())
                sla_hours = (
                    self.evaluator.get_escalation_sla_hours(severity)
                    if kind == "escalation"
                    else self.evaluator.get_case_sla_hours(severity)
                )
                due = self.evaluator.get_due_time(created_at, sla_hours)
                if kind == "escalation":
                    times = []
                    for esc in self.graph.case_escalations.get(case_id, []):
                        when = self.graph._parse_dt(esc.get("timestamp") or esc.get("escalated_at"))
                        if when and created_at <= when < cutoff_time:
                            times.append(when)
                            esc_ref = self.ctx.get_source_reference(
                                "escalations", "native_id", esc.get("native_id")
                            )
                            if esc_ref:
                                claim_refs.append(esc_ref.to_dict())
                    if any(t <= due for t in times):
                        compliant_cases.add(case_id)
                    elif due <= cutoff_time and escalation_complete:
                        non_compliant_cases.add(case_id)
                    else:
                        unknown_cases.add(case_id)
                else:
                    closed_at = self.graph._parse_dt(case.get("closed_at"))
                    if closed_at and closed_at < created_at:
                        unknown_cases.add(case_id)
                    elif closed_at and closed_at <= due and closed_at < cutoff_time:
                        compliant_cases.add(case_id)
                    elif due <= cutoff_time:
                        non_compliant_cases.add(case_id)
                    else:
                        unknown_cases.add(case_id)

            reconciliation = ClaimReconciler.evaluate_sla_claim(
                claimed_pct=claimed_sla_pct,
                compliant_case_ids=compliant_cases,
                non_compliant_case_ids=non_compliant_cases,
                unknown_case_ids=unknown_cases,
                is_denominator_complete=True,
            )

            results.append(
                DetectorResult(
                    rule_id=rule_id,
                    rule_title=rule_title,
                    severity="high" if reconciliation.is_contradicted else "medium",
                    evidence_state=reconciliation.evidence_state,
                    primary_object_type="claim",
                    primary_object_id=claim_obj_id,
                    affected_asset_ids=[],
                    rationale=reconciliation.explanation,
                    uncertainty_note=(
                        f"Bounded interval [{reconciliation.lower_bound_pct:.1f}%, {reconciliation.upper_bound_pct:.1f}%] "
                        f"computed over {reconciliation.total_population} distinct cases "
                        f"({reconciliation.unknown_outcomes} indeterminate outcomes)."
                    ),
                    supporting_records=claim_refs,
                    extra_metadata={
                        "total_population": reconciliation.total_population,
                        "verified_compliant": reconciliation.verified_compliant,
                        "verified_non_compliant": reconciliation.verified_non_compliant,
                        "unknown_outcomes": reconciliation.unknown_outcomes,
                        "lower_bound_pct": reconciliation.lower_bound_pct,
                        "upper_bound_pct": reconciliation.upper_bound_pct,
                        "claimed_pct": reconciliation.claimed_pct,
                        "is_contradicted": reconciliation.is_contradicted,
                    },
                )
            )

        return results


class RecurrenceContextDetector(BaseDetector):
    """Rule POL-REC-005: Recurring alert conditions on assets after remediation."""

    def run(self) -> List[DetectorResult]:
        results: List[DetectorResult] = []
        rule_id = self.config.get("rule_id", "POL-REC-005")
        rule_title = self.config.get("title", "Post-Remediation Recurrence Context")

        # Always explicitly label peer comparison status as unavailable in Task 2
        peer_comparison_status = "peer_comparison_unavailable"

        alerts = self.ctx.get_records("alerts")
        cases = self.ctx.get_records("cases")

        if not alerts or not cases:
            return results

        # Group alerts by asset_id and title/rule_name
        asset_alerts: Dict[str, List[Dict[str, Any]]] = {}
        for a in alerts:
            aid = a.get("affected_asset_id") or a.get("asset_id")
            if aid:
                asset_alerts.setdefault(aid, []).append(a)

        threshold = int(self.config.get("recurrence_threshold_count", 3))

        for asset_id, a_list in asset_alerts.items():
            if len(a_list) < threshold:
                continue

            # Check if an approved exception or external remediation owner applies
            cutoff = self.ctx.cutoff_time or (
                self.ctx.submission.period_end if self.ctx.submission else None
            )
            if not cutoff and a_list:
                latest_ts = max(
                    (a.get("timestamp") for a in a_list if a.get("timestamp")), default=None
                )
                if latest_ts:
                    cutoff = self.graph._parse_dt(latest_ts)
            if not cutoff:
                cutoff = datetime.now(timezone.utc)

            exception = self.evaluator.match_exception(rule_id, "asset", asset_id, cutoff)
            if exception and (exception.remediation_owner or exception.rule_id in (rule_id, "*")):
                # Benign/known condition handled by external owner or covered by approved exception
                continue

            # Find distinct case associations
            associated_cases = set()
            for al in a_list:
                al_id = al.get("native_id") or al.get("alert_id") or al.get("id")
                if al_id in self.graph.alert_cases:
                    associated_cases.update(self.graph.alert_cases[al_id])

            supporting_refs = []
            asset_ref = self.ctx.get_source_reference("assets", "asset_id", asset_id)
            if asset_ref:
                supporting_refs.append(asset_ref.to_dict())

            for c_id in list(associated_cases)[:3]:
                c_ref = self.ctx.get_source_reference("cases", "case_id", c_id)
                if c_ref:
                    supporting_refs.append(c_ref.to_dict())

            # Present as an investigative hypothesis, NOT a causal accusation of "failure to learn"
            results.append(
                DetectorResult(
                    rule_id=rule_id,
                    rule_title=rule_title,
                    severity="medium",
                    evidence_state="potential_concern",
                    primary_object_type="asset",
                    primary_object_id=asset_id,
                    affected_asset_ids=[asset_id],
                    rationale=(
                        f"Hypothesis: Asset {asset_id} exhibited recurring alert conditions ({len(a_list)} alerts across "
                        f"{len(associated_cases)} cases) within the evaluation period. "
                        f"Requires supervisory verification of underlying root-cause remediation."
                    ),
                    uncertainty_note="Presents as operational hypothesis; external maintenance owner records not found.",
                    supporting_records=supporting_refs,
                    peer_comparison_status=peer_comparison_status,
                    extra_metadata={
                        "alert_count": len(a_list),
                        "case_count": len(associated_cases),
                    },
                )
            )

        return results
