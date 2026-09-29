"""Pydantic schemas for supervisory overview, peer comparison, and longitudinal trends."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AuthorizedEntityItem(BaseModel):
    id: str
    name: str
    code: str
    sector: str
    submission_count: int
    latest_period_start: Optional[str] = None
    latest_period_end: Optional[str] = None


class EntityPeriodOption(BaseModel):
    submission_id: str
    run_id: Optional[str] = None
    period_start: str
    period_end: str
    period_label: str
    status: str
    findings_count: int
    has_analysis_run: bool


class EvidenceCompletenessSchema(BaseModel):
    declared_sources_count: int
    received_sources_count: int
    missing_sources_count: int
    quarantined_records_count: int
    total_parsed_records: int
    completeness_percentage: float
    sufficiency_verdict: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ExecutionGapSchema(BaseModel):
    unsubstantiated_closures: int
    overdue_escalations: int
    unlinked_lifecycle_cases: int
    adverse_findings_count: int
    gap_score: float
    severity_distribution: Dict[str, int] = Field(default_factory=dict)
    contributing_finding_ids: List[str] = Field(default_factory=list)


class NegativeSpaceSchema(BaseModel):
    total_critical_assets: int
    healthy_monitored_assets: int
    broken_sensor_assets: int
    healthy_quiet_assets: int
    missing_telemetry_assets: int
    coverage_percentage: float
    blind_spot_warning: bool
    contributing_asset_ids: List[str] = Field(default_factory=list)


class ContradictedClaimsSchema(BaseModel):
    total_declared_claims: int
    mathematically_contradicted_claims: int
    compatible_with_unknowns: int
    supported_claims: int
    unreconciled_claims: int
    details: List[Dict[str, Any]] = Field(default_factory=list)


class CapabilityDimensionSchema(BaseModel):
    code: str
    name: str
    status: str
    confidence: float
    findings_count: int
    primary_rule: Optional[str] = None
    evidence_basis: str = ""


class SupervisoryOverviewResponse(BaseModel):
    entity_id: str
    entity_name: str
    entity_code: str
    submission_id: str
    period_start: str
    period_end: str
    run_id: str
    analysis_status: str
    cutoff_time: str
    supervisory_attention_index: float
    attention_priority: str
    evidence_completeness: EvidenceCompletenessSchema
    execution_gaps: ExecutionGapSchema
    negative_space: NegativeSpaceSchema
    contradicted_claims: ContradictedClaimsSchema
    open_evidence_requests_count: int
    active_portfolio_items_count: int
    human_decisions_count: int = 0
    capabilities: List[CapabilityDimensionSchema] = Field(default_factory=list)
    disclaimer: str = ""


class DistributionStatsSchema(BaseModel):
    count: int
    min: float
    q25: float
    median: float
    q75: float
    max: float
    iqr: float


class MetricComparisonSchema(BaseModel):
    metric_code: str
    metric_name: str
    target_value: float
    peer_distribution: Optional[DistributionStatsSchema] = None
    target_percentile_rank: Optional[float] = None
    comparison_state: str
    unit: str
    explanation: str


class PeerCohortResponse(BaseModel):
    target_entity_id: str
    target_sector: str
    target_tier: str
    cohort_version: str
    period_start: str
    period_end: str
    eligible_peer_count: int
    minimum_peers_required: int
    is_cohort_sufficient: bool
    status: str
    status_reason: str
    eligible_peers: List[Dict[str, str]] = Field(default_factory=list)
    excluded_peers: List[Dict[str, str]] = Field(default_factory=list)
    metric_comparisons: List[MetricComparisonSchema] = Field(default_factory=list)
    privacy_disclosure: str


class TrendPointSchema(BaseModel):
    period_label: str
    period_start: str
    period_end: str
    has_data: bool
    gap_reason: Optional[str] = None
    run_id: Optional[str] = None
    submission_id: Optional[str] = None
    policy_version: Optional[str] = None
    rule_version: Optional[str] = None
    scope_summary: Optional[str] = None
    evidence_completeness_pct: Optional[float] = None
    total_cases_evaluated: Optional[int] = None
    adverse_findings_count: Optional[int] = None
    concern_density_per_100: Optional[float] = None
    unsubstantiated_closure_rate_pct: Optional[float] = None
    overdue_escalation_rate_pct: Optional[float] = None
    monitoring_coverage_pct: Optional[float] = None
    supervisory_attention_index: Optional[float] = None
    examiner_decisions_count: Optional[int] = None
    open_evidence_requests_count: Optional[int] = None


class PeriodTrendsResponse(BaseModel):
    entity_id: str
    entity_name: str
    entity_code: str
    sector: str
    period_count: int
    missing_period_count: int
    trajectory: str
    trajectory_narrative: str
    points: List[TrendPointSchema] = Field(default_factory=list)
    scope_annotations: List[str] = Field(default_factory=list)


class ReviewHypothesisSchema(BaseModel):
    hypothesis_id: str
    pattern_code: str
    title: str
    severity: str
    hypothesis_statement: str
    observed_value: float
    observed_unit: str
    baseline_value: float
    baseline_definition: str
    deviation_factor: str
    sample_size: int
    denominator_description: str
    uncertainty_warning: Optional[str] = None
    contributing_records: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_examiner_action: str


class UnusualPatternsResponse(BaseModel):
    entity_id: str
    submission_id: str
    run_id: str
    hypotheses_count: int
    hypotheses: List[ReviewHypothesisSchema] = Field(default_factory=list)
    robust_statistics_summary: Dict[str, Any] = Field(default_factory=dict)
    methodology_disclosure: str
