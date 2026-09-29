"""Explicit KPI semantics shared by intake and analytics (no model inference)."""

import calendar
import re
from datetime import datetime, timezone

CLOSURE_METRICS = {
    "case_closure_sla_compliance_rate",
    "incident_sla_compliance_pct",
    "incident_sla_compliance",
    "incident_sla_pct",
    "sla_compliance",
}
ESCALATION_METRICS = {"escalation_sla_compliance_rate"}


def metric_kind(name: str) -> str | None:
    name = str(name).strip().lower()
    if name in CLOSURE_METRICS:
        return "closure"
    if name in ESCALATION_METRICS:
        return "escalation"
    return None


def percentage_metric(name: str, unit: str | None = None) -> bool:
    return (
        metric_kind(name) is not None
        or str(unit).lower() in {"percent", "percentage", "%"}
        or any(word in str(name).lower().split("_") for word in ("pct", "percent", "percentage"))
    )


def claim_period(data: dict) -> tuple[datetime, datetime]:
    def timestamp(value):
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

    start, end = data.get("period_start"), data.get("period_end")
    period = str(data.get("period", "")).strip()
    month = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if start or end:
        if not start or not end:
            raise ValueError("Both period_start and period_end are required")
        bounds = timestamp(start), timestamp(end)
    elif month:
        year, number = map(int, month.groups())
        start_dt = datetime(year, number, 1, tzinfo=timezone.utc)
        bounds = start_dt, start_dt.replace(year=year + (number == 12), month=number % 12 + 1)
    else:
        raise ValueError("Claim period must be YYYY-MM or an explicit ISO-8601 interval")
    if bounds[0] >= bounds[1]:
        raise ValueError("Claim period_start must precede period_end")
    if month:
        year, number = map(int, month.groups())
        if bounds[0] != datetime(year, number, 1, tzinfo=timezone.utc):
            raise ValueError("Claim period label contradicts its explicit interval")
        last_day = calendar.monthrange(year, number)[1]
        next_month = datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=timezone.utc)
        # Legacy end-of-month inclusive timestamp is retained, never broadened silently.
        if (
            not datetime(year, number, last_day, 23, 59, 59, tzinfo=timezone.utc)
            <= bounds[1]
            <= next_month
        ):
            raise ValueError("Claim period label contradicts its explicit interval")
    return bounds
