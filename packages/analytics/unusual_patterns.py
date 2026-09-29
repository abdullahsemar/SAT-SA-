"""Unusual pattern analytics: Robust statistical anomaly detection and explainable review hypotheses.

Architectural Invariants:
- An unusual pattern is an exploratory review hypothesis for an examiner, NOT an autonomous finding of guilt.
- Uses robust statistics: Median and Median Absolute Deviation (MAD), not fragile mean/stddev.
- Handles small samples (n < 5), zero-MAD baselines, and sparse observations explicitly with uncertainty warnings.
- Each hypothesis reports observed value, baseline definition, sample size, denominator, deviation, and uncertainty.
- Integrates with text similarity and lifecycle evidence to highlight meaningful review leads.
"""

from __future__ import annotations

import datetime
import json
import statistics
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.assessment import AnalysisRun
from db.models.evidence import NormalizedRecord, Submission


@dataclass
class ReviewHypothesis:
    hypothesis_id: str
    pattern_code: str
    title: str
    severity: str  # "INFORMATIONAL", "ELEVATED", "HIGH"
    hypothesis_statement: str
    observed_value: float
    observed_unit: str
    baseline_value: float
    baseline_definition: str
    deviation_factor: str
    sample_size: int
    denominator_description: str
    uncertainty_warning: Optional[str]
    contributing_records: List[Dict[str, Any]]
    suggested_examiner_action: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UnusualPatternsResult:
    entity_id: str
    submission_id: str
    run_id: str
    hypotheses_count: int
    hypotheses: List[ReviewHypothesis]
    robust_statistics_summary: Dict[str, Any]
    methodology_disclosure: str = (
        "Statistical review hypotheses are generated using robust distribution metrics (Median and Median "
        "Absolute Deviation - MAD). They indicate operational deviations warranting examiner verification "
        "and do not constitute automated regulatory findings."
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class UnusualPatternService:
    """Detects explainable statistical anomalies and operational outliers."""

    def __init__(self, db: Session):
        self.db = db

    def analyze_patterns(
        self,
        submission_id: str,
        run_id: Optional[str] = None,
    ) -> Optional[UnusualPatternsResult]:
        sub = self.db.execute(
            select(Submission).where(Submission.id == submission_id)
        ).scalar_one_or_none()
        if not sub:
            return None

        # Fetch completed run
        run_query = select(AnalysisRun).where(AnalysisRun.submission_id == submission_id)
        if run_id:
            run_query = run_query.where(AnalysisRun.id == run_id)
        else:
            run_query = run_query.where(AnalysisRun.status == "completed").order_by(
                AnalysisRun.created_at.desc()
            )
        run = self.db.execute(run_query).scalars().first()

        actual_run_id = run.id if run else "none"

        # Fetch normalized records
        records = (
            self.db.execute(
                select(NormalizedRecord).where(
                    NormalizedRecord.submission_id == submission_id,
                    NormalizedRecord.is_quarantined.is_(False),
                )
            )
            .scalars()
            .all()
        )

        case_records: List[Dict[str, Any]] = []
        alert_records: List[Dict[str, Any]] = []
        for r in records:
            try:
                data = json.loads(r.normalized_data)
                data["_native_id"] = r.native_id
                data["_record_type"] = r.record_type
                if r.record_type in ("case", "incident"):
                    case_records.append(data)
                elif r.record_type == "alert":
                    alert_records.append(data)
            except Exception:
                continue

        hypotheses: List[ReviewHypothesis] = []
        stats_summary: Dict[str, Any] = {}

        # 1. Pattern: Concentrated Rapid Closures (< 60s without substantive investigation)
        rapid_closure_hyp = self._detect_rapid_closures(case_records)
        if rapid_closure_hyp:
            hypotheses.append(rapid_closure_hyp)

        # 2. Pattern: Investigation Duration Anomaly (Robust MAD)
        duration_hyp, duration_stats = self._detect_duration_anomalies(case_records)
        if duration_hyp:
            hypotheses.append(duration_hyp)
        stats_summary["investigation_duration_stats"] = duration_stats

        # 3. Pattern: Daily Workload / Caseload Spikes
        workload_hyp, workload_stats = self._detect_workload_spikes(case_records)
        if workload_hyp:
            hypotheses.append(workload_hyp)
        stats_summary["daily_caseload_stats"] = workload_stats

        # 4. Pattern: Activity Drop Despite Monitored Critical Assets
        drop_hyp = self._detect_activity_drop(case_records, alert_records, records)
        if drop_hyp:
            hypotheses.append(drop_hyp)

        # 5. Pattern: Repeated Closure Narrative Clusters
        narrative_hyp = self._detect_repeated_narratives(case_records)
        if narrative_hyp:
            hypotheses.append(narrative_hyp)

        # 6. Pattern: Recurrence Post-Remediation
        recurrence_hyp = self._detect_post_remediation_recurrence(case_records, alert_records)
        if recurrence_hyp:
            hypotheses.append(recurrence_hyp)

        return UnusualPatternsResult(
            entity_id=sub.entity_id,
            submission_id=sub.id,
            run_id=actual_run_id,
            hypotheses_count=len(hypotheses),
            hypotheses=hypotheses,
            robust_statistics_summary=stats_summary,
        )

    def _detect_rapid_closures(self, cases: List[Dict[str, Any]]) -> Optional[ReviewHypothesis]:
        rapid_cases = []
        durations = []
        for c in cases:
            # Check duration field or calculate from timestamps
            dur_sec = c.get("duration_seconds")
            if dur_sec is None and c.get("created_at") and c.get("closed_at"):
                try:
                    t1 = datetime.datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
                    t2 = datetime.datetime.fromisoformat(c["closed_at"].replace("Z", "+00:00"))
                    dur_sec = (t2 - t1).total_seconds()
                except Exception:
                    pass

            if dur_sec is not None:
                durations.append(dur_sec)
                # Rapid closure: closed in <= 120 seconds
                if dur_sec <= 120:
                    notes = str(
                        c.get("closure_notes", "") or c.get("investigation_notes", "")
                    ).strip()
                    rapid_cases.append(
                        {
                            "case_id": c.get("_native_id", "unknown"),
                            "duration_seconds": dur_sec,
                            "notes_length": len(notes),
                            "snippet": notes[:80] if notes else "No notes recorded",
                            "analyst": c.get("assigned_to", "unassigned"),
                        }
                    )

        if len(rapid_cases) >= 2:
            pct_rapid = round((len(rapid_cases) / max(len(cases), 1)) * 100.0, 1)
            uncertainty = None
            if len(cases) < 10:
                uncertainty = (
                    f"Limited case population (n={len(cases)}). Interpret as sampling priority."
                )

            return ReviewHypothesis(
                hypothesis_id=str(uuid.uuid4()),
                pattern_code="PAT-RAPID-CLOSURE",
                title="Concentrated Rapid Closures (< 120s)",
                severity="HIGH" if pct_rapid >= 20.0 else "ELEVATED",
                hypothesis_statement=(
                    f"{len(rapid_cases)} cases ({pct_rapid}% of closed cases) were closed within 2 minutes of "
                    "ingestion with minimal or templated investigation notes."
                ),
                observed_value=float(len(rapid_cases)),
                observed_unit="cases",
                baseline_value=0.0,
                baseline_definition="Supervisory expectation: Substantive triage and logging requires > 120s",
                deviation_factor=f"{pct_rapid}% of cohort",
                sample_size=len(cases),
                denominator_description="Total closed cases with duration metadata",
                uncertainty_warning=uncertainty,
                contributing_records=rapid_cases[:10],
                suggested_examiner_action=(
                    "Sample the listed rapid-closure cases into the Review Portfolio to verify if triage was "
                    "legitimate automated suppression or unsubstantiated manual closure."
                ),
            )
        return None

    def _detect_duration_anomalies(
        self, cases: List[Dict[str, Any]]
    ) -> tuple[Optional[ReviewHypothesis], Dict[str, Any]]:
        durations: List[float] = []
        for c in cases:
            dur = c.get("duration_seconds")
            if dur is not None and dur > 0:
                durations.append(float(dur))

        stats: Dict[str, Any] = {
            "count": len(durations),
            "median_minutes": 0.0,
            "mad_minutes": 0.0,
            "zero_mad": False,
            "small_sample": len(durations) < 5,
        }

        if len(durations) < 5:
            if durations:
                stats["median_minutes"] = round(statistics.median(durations) / 60.0, 1)
            return None, stats

        durations_min = [d / 60.0 for d in durations]
        med = statistics.median(durations_min)
        deviations = [abs(d - med) for d in durations_min]
        mad = statistics.median(deviations)

        stats["median_minutes"] = round(med, 1)
        stats["mad_minutes"] = round(mad, 1)

        if mad == 0.0:
            stats["zero_mad"] = True
            # Zero-MAD: majority of cases have identical duration
            identical_count = sum(1 for d in durations_min if abs(d - med) < 0.01)
            if identical_count >= (len(durations_min) * 0.6):
                return (
                    ReviewHypothesis(
                        hypothesis_id=str(uuid.uuid4()),
                        pattern_code="PAT-DURATION-ZERO-MAD",
                        title="Uniform Duration Artifact (Zero-MAD)",
                        severity="ELEVATED",
                        hypothesis_statement=(
                            f"{identical_count} of {len(durations_min)} cases ({round(identical_count / len(durations_min) * 100)}%) "
                            f"have identical duration of {med:.1f} minutes, indicating synthetic or automated timestamp batching."
                        ),
                        observed_value=float(identical_count),
                        observed_unit="cases with identical duration",
                        baseline_value=float(len(durations_min) * 0.1),
                        baseline_definition="Natural operational variation expected across analysts",
                        deviation_factor="Zero-MAD collapse",
                        sample_size=len(durations_min),
                        denominator_description="Cases with duration timestamps",
                        uncertainty_warning="Zero-MAD baseline confirms lack of variance rather than standard bell-curve distribution.",
                        contributing_records=[
                            {"duration_minutes": med, "affected_cases": identical_count}
                        ],
                        suggested_examiner_action="Verify if timestamps represent batch-job automated ingestion rather than analyst actions.",
                    ),
                    stats,
                )
            return None, stats

        # Check for significant duration outliers (> 3 * MAD from median)
        outliers = []
        for c in cases:
            dur = c.get("duration_seconds")
            if dur:
                dur_m = dur / 60.0
                if abs(dur_m - med) > (3.0 * mad):
                    outliers.append(
                        {
                            "case_id": c.get("_native_id", "unknown"),
                            "duration_minutes": round(dur_m, 1),
                            "median_minutes": round(med, 1),
                            "mad_distance": round(abs(dur_m - med) / mad, 1),
                        }
                    )

        if len(outliers) >= 2:
            return (
                ReviewHypothesis(
                    hypothesis_id=str(uuid.uuid4()),
                    pattern_code="PAT-DURATION-OUTLIERS",
                    title="Investigation Duration Statistical Outliers",
                    severity="INFORMATIONAL",
                    hypothesis_statement=(
                        f"{len(outliers)} cases deviate by more than 3.0x MAD from median duration "
                        f"({med:.1f} min, MAD={mad:.1f} min)."
                    ),
                    observed_value=float(len(outliers)),
                    observed_unit="outlier cases",
                    baseline_value=med,
                    baseline_definition="Median case investigation duration",
                    deviation_factor=f"> 3x MAD ({mad:.1f} min)",
                    sample_size=len(durations_min),
                    denominator_description="Total closed cases with duration",
                    uncertainty_warning=None,
                    contributing_records=outliers[:10],
                    suggested_examiner_action="Inspect outlier cases to understand extended triage or dormant ticket delays.",
                ),
                stats,
            )

        return None, stats

    def _detect_workload_spikes(
        self, cases: List[Dict[str, Any]]
    ) -> tuple[Optional[ReviewHypothesis], Dict[str, Any]]:
        # Count cases per calendar date
        date_counts: Dict[str, int] = {}
        for c in cases:
            ts_str = c.get("created_at") or c.get("timestamp")
            if ts_str:
                try:
                    dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date()
                    k = dt.isoformat()
                    date_counts[k] = date_counts.get(k, 0) + 1
                except Exception:
                    pass

        stats: Dict[str, Any] = {
            "days_active": len(date_counts),
            "median_daily_cases": 0.0,
            "mad_daily_cases": 0.0,
        }

        if len(date_counts) < 4:
            return None, stats

        counts = list(date_counts.values())
        med = statistics.median(counts)
        deviations = [abs(x - med) for x in counts]
        mad = statistics.median(deviations) or 1.0

        stats["median_daily_cases"] = round(med, 1)
        stats["mad_daily_cases"] = round(mad, 1)

        # Flag days with > median + 3.0 * MAD
        spike_days = []
        for day, cnt in date_counts.items():
            if cnt > (med + (3.0 * mad)) and cnt >= 5:
                spike_days.append(
                    {
                        "date": day,
                        "case_count": cnt,
                        "baseline_median": med,
                        "mad_distance": round((cnt - med) / mad, 1),
                    }
                )

        if spike_days:
            return (
                ReviewHypothesis(
                    hypothesis_id=str(uuid.uuid4()),
                    pattern_code="PAT-WORKLOAD-SPIKE",
                    title="Anomalous Daily Case Surge",
                    severity="ELEVATED",
                    hypothesis_statement=(
                        f"Detected {len(spike_days)} day(s) with caseload exceeding 3.0x MAD above daily median "
                        f"(Median: {med:.1f} cases/day, MAD: {mad:.1f})."
                    ),
                    observed_value=float(max(s["case_count"] for s in spike_days)),
                    observed_unit="cases/day",
                    baseline_value=med,
                    baseline_definition="Median daily caseload across reporting period",
                    deviation_factor=f"{spike_days[0]['mad_distance']}x MAD above median",
                    sample_size=len(date_counts),
                    denominator_description="Total active operating days in period",
                    uncertainty_warning=None,
                    contributing_records=spike_days,
                    suggested_examiner_action="Correlate spike dates with major security events, sensor reconfigurations, or flood testing.",
                ),
                stats,
            )

        return None, stats

    def _detect_activity_drop(
        self,
        cases: List[Dict[str, Any]],
        alerts: List[Dict[str, Any]],
        all_records: List[NormalizedRecord],
    ) -> Optional[ReviewHypothesis]:
        # Count critical assets declared in assets or inventory records
        asset_count = sum(
            1 for r in all_records if r.record_type in ("asset", "inventory", "endpoint")
        )
        total_activity = len(cases) + len(alerts)

        if asset_count >= 5 and total_activity <= 1:
            return ReviewHypothesis(
                hypothesis_id=str(uuid.uuid4()),
                pattern_code="PAT-ACTIVITY-DROP",
                title="Negative-Space Telemetry Silence",
                severity="HIGH",
                hypothesis_statement=(
                    f"Entity declares {asset_count} critical assets/endpoints, but only {total_activity} "
                    "alerts/cases were submitted across the reporting period. Possible sensor failure or export filter omission."
                ),
                observed_value=float(total_activity),
                observed_unit="events",
                baseline_value=float(asset_count * 2),
                baseline_definition="Expected minimum baseline supervisory telemetry for enterprise scope",
                deviation_factor="> 90% below expected baseline",
                sample_size=asset_count,
                denominator_description="Declared enterprise critical assets",
                uncertainty_warning="Operational silence may reflect flawless defenses, but requires sensor heartbeat proof.",
                contributing_records=[
                    {"declared_assets": asset_count, "recorded_activity": total_activity}
                ],
                suggested_examiner_action="Request SIEM pipeline ingestion health logs and sensor heartbeat verifications.",
            )
        return None

    def _detect_repeated_narratives(
        self, cases: List[Dict[str, Any]]
    ) -> Optional[ReviewHypothesis]:
        # Exact or near-identical text clustering
        text_buckets: Dict[str, List[str]] = {}
        for c in cases:
            notes = (
                str(c.get("closure_notes", "") or c.get("investigation_notes", "")).strip().lower()
            )
            if len(notes) >= 20:  # meaningful length
                # Normalize spaces
                norm = " ".join(notes.split())
                text_buckets.setdefault(norm, []).append(c.get("_native_id", "unknown"))

        # Find any bucket with 3+ occurrences
        repeated = [
            {"text_snippet": k[:100], "count": len(v), "case_ids": v[:5]}
            for k, v in text_buckets.items()
            if len(v) >= 3
        ]

        if repeated:
            total_affected = sum(r["count"] for r in repeated)
            return ReviewHypothesis(
                hypothesis_id=str(uuid.uuid4()),
                pattern_code="PAT-REPEATED-NARRATIVE",
                title="Clustered Repetitive Closure Narratives",
                severity="ELEVATED",
                hypothesis_statement=(
                    f"Identified {len(repeated)} verbatim text cluster(s) covering {total_affected} cases. "
                    "Identical closure rationales repeated across multiple incidents indicate potential boilerplate review."
                ),
                observed_value=float(total_affected),
                observed_unit="templated cases",
                baseline_value=0.0,
                baseline_definition="Investigative hypothesis: Individual cases warrant case-specific closure rationale",
                deviation_factor=f"{total_affected} cases sharing verbatim notes",
                sample_size=len(cases),
                denominator_description="Total closed cases with text notes",
                uncertainty_warning="Boilerplate language may be standard operating procedure for known false positive rules.",
                contributing_records=repeated,
                suggested_examiner_action="Cross-check whether the repeated narrative corresponds to an approved triage rule or superficial analysis.",
            )
        return None

    def _detect_post_remediation_recurrence(
        self, cases: List[Dict[str, Any]], alerts: List[Dict[str, Any]]
    ) -> Optional[ReviewHypothesis]:
        # Track remediated assets
        remediated_assets: Dict[str, datetime.datetime] = {}
        for c in cases:
            disp = str(c.get("disposition", "")).lower()
            notes = str(c.get("closure_notes", "")).lower()
            if "remediat" in disp or "remediat" in notes or "resolved" in disp:
                asset = c.get("asset_id") or c.get("host")
                closed_at = c.get("closed_at")
                if asset and closed_at:
                    try:
                        dt = datetime.datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                        remediated_assets[asset] = dt
                    except Exception:
                        pass

        # Check subsequent alerts on those assets
        recurrences = []
        for a in alerts:
            asset = a.get("asset_id") or a.get("host")
            ts = a.get("timestamp")
            if asset in remediated_assets and ts:
                try:
                    alert_dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if alert_dt > remediated_assets[asset]:
                        recurrences.append(
                            {
                                "asset_id": asset,
                                "remediated_at": remediated_assets[asset].isoformat(),
                                "recurrence_at": alert_dt.isoformat(),
                                "alert_name": a.get("rule_name")
                                or a.get("alert_type", "Security Alert"),
                            }
                        )
                except Exception:
                    pass

        if recurrences:
            return ReviewHypothesis(
                hypothesis_id=str(uuid.uuid4()),
                pattern_code="PAT-RECURRENCE-POST-REMEDIATION",
                title="Post-Remediation Threat Recurrence",
                severity="HIGH",
                hypothesis_statement=(
                    f"Detected {len(recurrences)} new alert(s) on asset(s) previously marked as remediated. "
                    "Indicates incomplete remediation or persistent vulnerability."
                ),
                observed_value=float(len(recurrences)),
                observed_unit="recurrent alerts",
                baseline_value=0.0,
                baseline_definition="Supervisory standard: Remediation validation should prevent immediate recurrence",
                deviation_factor=f"{len(recurrences)} alerts post-fix",
                sample_size=len(remediated_assets),
                denominator_description="Assets with recorded remediation actions",
                uncertainty_warning=None,
                contributing_records=recurrences[:10],
                suggested_examiner_action="Verify root cause analysis and request remediation re-validation test results.",
            )
        return None
