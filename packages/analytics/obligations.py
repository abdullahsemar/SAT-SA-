"""Policy obligation evaluator for SAT-SA.

Evaluates operational obligations against policy requirements:
- Case SLA calculations (by severity and submission cutoff time).
- Escalation SLAs (from policy config sla_seconds).
- Policy exceptions matching (by affected entity/asset, rule, and validity window).
- Period cutoffs (actions due after submission period cutoff are NOT considered overdue).
- Required artifact definitions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PolicyException(BaseModel):
    exception_id: str
    rule_id: str
    target_type: str  # "asset", "case", "system"
    target_id: str
    valid_from: datetime
    valid_to: datetime
    approved_by: str
    reason: str
    remediation_owner: Optional[str] = None


class ObligationPolicy(BaseModel):
    policy_version: str = "demo-v1"
    name: str = "Supervisory Policy"
    description: Optional[str] = None
    investigation: Dict[str, Any] = Field(default_factory=dict)
    escalation: Dict[str, Any] = Field(default_factory=dict)
    monitoring_coverage: Dict[str, Any] = Field(default_factory=dict)
    kpi_claims: Dict[str, Any] = Field(default_factory=dict)
    recurrence: Dict[str, Any] = Field(default_factory=dict)
    exceptions: List[PolicyException] = Field(default_factory=list)


class ObligationEvaluator:
    """Evaluates whether actions, escalations, or closures met policy obligations."""

    def __init__(self, policy_config: Dict[str, Any]):
        self.raw_config = policy_config or {}
        # Support both formats (legacy and demo-v1)
        self.policy = ObligationPolicy.model_validate(policy_config)

    def add_submitted_exceptions(self, records: list[dict[str, Any]]) -> None:
        """Accept only explicit, approved, dated exception records with source provenance."""
        known = {e.exception_id for e in self.policy.exceptions}
        for record in records:
            if str(record.get("status", "")).upper() not in {
                "APPROVED",
                "ACTIVE",
            } or not record.get("_source_ref"):
                continue
            try:
                scope = str(record.get("affected_scope", "")).split(":", 1)
                exception = PolicyException.model_validate(
                    {
                        "exception_id": record["native_id"],
                        "rule_id": record.get("policy_reference"),
                        "target_type": record.get("target_type")
                        or (scope[0] if len(scope) == 2 else None),
                        "target_id": record.get("target_id")
                        or (scope[1] if len(scope) == 2 else None),
                        "valid_from": record.get("valid_from"),
                        "valid_to": record.get("valid_to") or record.get("expiry_date"),
                        "approved_by": record.get("approved_by"),
                        "reason": record.get("reason"),
                        "remediation_owner": record.get("remediation_owner"),
                    }
                )
            except (ValueError, TypeError, KeyError):
                continue
            if (
                exception.exception_id not in known
                and exception.approved_by.strip()
                and exception.reason.strip()
            ):
                self.policy.exceptions.append(exception)
                known.add(exception.exception_id)

    def get_case_sla_hours(self, severity: str) -> float:
        """Returns required investigation SLA in hours for a given severity."""
        sev = (severity or "").upper()
        # Default SLAs: CRITICAL: 4h, HIGH: 12h, MEDIUM: 24h, LOW: 72h
        defaults = {"CRITICAL": 4.0, "HIGH": 12.0, "MEDIUM": 24.0, "LOW": 72.0}
        return defaults.get(sev, 24.0)

    def get_escalation_sla_hours(self, severity: str) -> float:
        """Returns required escalation SLA in hours for a given severity."""
        sev = (severity or "").upper()
        # Check policy escalation.sla_seconds
        sla_seconds_map = self.policy.escalation.get("sla_seconds", {})
        if sev in sla_seconds_map:
            return sla_seconds_map[sev] / 3600.0
        defaults = {"CRITICAL": 0.5, "HIGH": 2.0, "MEDIUM": 24.0, "LOW": 168.0}
        return defaults.get(sev, 4.0)

    def get_case_artifact_obligation(self, severity: str) -> dict[str, Any]:
        """Returns specific artifact obligation dict for a severity."""
        sev = (severity or "").upper()
        art_map = self.policy.investigation.get("artifact_obligations", {})
        return art_map.get(sev, {})

    def get_required_artifacts(self, severity: Optional[str] = None) -> List[str]:
        """Returns list of required artifact names/types for case closure."""
        reqs = []
        art_map = self.policy.investigation.get("artifact_obligations", {})
        if severity:
            sev = severity.upper()
            spec = art_map.get(sev, {})
            for action in spec.get("required_actions", []):
                reqs.append(action.lower())
        else:
            for sev, spec in art_map.items():
                for action in spec.get("required_actions", []):
                    reqs.append(action.lower())
        # Default expected closure artifacts
        if not reqs:
            reqs = ["triage_notes", "root_cause", "disposition"]
        return list(set(reqs))

    def is_action_due(
        self,
        created_at: datetime,
        sla_hours: float,
        cutoff_time: datetime,
    ) -> bool:
        """Determines if an action was due on or before the period cutoff time.

        If created_at + sla_hours > cutoff_time, the obligation is not yet due
        at the snapshot cutoff, so it cannot be declared overdue.
        """
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if cutoff_time.tzinfo is None:
            cutoff_time = cutoff_time.replace(tzinfo=timezone.utc)

        due_time = created_at.timestamp() + (sla_hours * 3600.0)
        return due_time <= cutoff_time.timestamp()

    def get_due_time(self, created_at: datetime, sla_hours: float) -> datetime:
        """Calculates expected due timestamp."""
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        due_ts = created_at.timestamp() + (sla_hours * 3600.0)
        return datetime.fromtimestamp(due_ts, tz=timezone.utc)

    def match_exception(
        self,
        rule_id: str,
        target_type: str,
        target_id: str,
        event_time: datetime,
    ) -> Optional[PolicyException]:
        """Finds any valid approved policy exception covering this rule and target at event_time."""
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        for exc in self.policy.exceptions:
            if exc.rule_id != rule_id and exc.rule_id != "*":
                continue
            if exc.target_type != target_type and exc.target_type != "*":
                continue
            if exc.target_id != target_id and exc.target_id != "*":
                continue

            valid_from = (
                exc.valid_from
                if exc.valid_from.tzinfo
                else exc.valid_from.replace(tzinfo=timezone.utc)
            )
            valid_to = (
                exc.valid_to if exc.valid_to.tzinfo else exc.valid_to.replace(tzinfo=timezone.utc)
            )

            if valid_from <= event_time <= valid_to:
                return exc

        return None
