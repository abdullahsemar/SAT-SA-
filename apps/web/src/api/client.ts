export interface ApiError {
  code: string;
  message: string;
  details?: any;
  request_id?: string;
}

export interface UserProfile {
  id: string;
  username: string;
  role: string;
  entity_scope: string[];
  csrf_token?: string;
}

export interface SubmissionSummary {
  id: string;
  entity_id: string;
  period_start: string;
  period_end: string;
  source_timezone: string;
  status: "draft" | "validated" | "committed";
  revision: number;
  created_at: string;
  committed_at?: string | null;
  file_count: number;
}

export interface SubmissionFile {
  id: string;
  source_id: string;
  record_type: string;
  original_filename: string;
  sha256_hash: string;
  byte_size: number;
  declared_row_count: number;
  actual_row_count: number;
  created_at: string;
}

export interface SubmissionDetail {
  id: string;
  entity_id: string;
  period_start: string;
  period_end: string;
  source_timezone: string;
  status: "draft" | "validated" | "committed";
  revision: number;
  manifest: any;
  idempotency_key?: string | null;
  created_at: string;
  committed_at?: string | null;
  files: SubmissionFile[];
}

export interface QualityIssue {
  id: string;
  source_id?: string | null;
  record_type?: string | null;
  row_locator?: string | null;
  issue_type: string;
  severity: "error" | "warning" | "info";
  field_name?: string | null;
  message: string;
}

export interface SourceSummary {
  source_id: string;
  record_type: string;
  declared_rows: number;
  actual_rows: number;
  status: "PRESENT" | "UNKNOWN" | "MISSING";
  sha256?: string | null;
  is_optional: boolean;
}

export interface QualityReport {
  submission_id: string;
  entity_id: string;
  status: string;
  revision: number;
  accepted_count: number;
  rejected_count: number;
  quarantined_count: number;
  duplicate_count: number;
  orphan_count: number;
  timestamp_problem_count: number;
  source_summaries: Record<string, SourceSummary>;
  issues: QualityIssue[];
}

export interface RecordProvenance {
  id: string;
  raw_record_id: string;
  submission_id: string;
  entity_id: string;
  source_id: string;
  record_type: string;
  native_id: string;
  row_locator: string;
  raw_sha256: string;
  raw_payload: any;
  normalized_data: any;
  is_quarantined: boolean;
  created_at: string;
}

export interface AnalysisRun {
  run_id: string;
  submission_id: string;
  cse_id: string;
  run_name: string;
  status: string;
  input_hash?: string;
  policy_version?: string;
  rule_set_version?: string;
  findings_count: number;
  summary: Record<string, any>;
  created_at: string;
  finished_at?: string | null;
}

export interface SupportingRecord {
  source_id: string;
  record_id: string;
  record_type: string;
  locator: string;
  native_id: string;
  sha256: string;
}

export interface Finding {
  finding_id: string;
  run_id: string;
  submission_id: string;
  cse_id: string;
  rule_id: string;
  rule_title: string;
  severity: "low" | "medium" | "high" | "critical" | string;
  evidence_state: "supported" | "potential_concern" | "contradictory" | "insufficient_evidence" | "not_applicable" | string;
  primary_object_type: string;
  primary_object_id: string;
  affected_asset_ids: string[];
  rationale: string;
  uncertainty_note?: string | null;
  supporting_records: SupportingRecord[];
  peer_comparison_status?: string;
  finding_metadata: Record<string, any>;
  created_at: string;
}

export interface EvidenceTimelineEvent {
  timestamp?: string | null;
  entity_type: string;
  entity_id: string;
  event: string;
  source_reference?: any;
}

export interface EvidenceChain {
  object_id: string;
  object_type: string;
  summary: Record<string, any>;
  timeline: EvidenceTimelineEvent[];
  related_entities: {
    nodes: Array<{ id: string; record_type: string; native_id: string; label: string; timestamp?: string; details?: any }>;
    edges: Array<{ source_id: string; target_id: string; link_type: string }>;
  };
  uncertainties: string[];
  omissions: string[];
}

class ApiClient {
  private csrfToken: string | null = null;

  setCsrfToken(token: string | null) {
    this.csrfToken = token;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };

    if (this.csrfToken && ["POST", "PUT", "PATCH", "DELETE"].includes(options.method?.toUpperCase() || "")) {
      headers["X-CSRF-Token"] = this.csrfToken;
    }

    const res = await fetch(endpoint, {
      ...options,
      headers,
      credentials: "include",
    });

    if (!res.ok) {
      let err: ApiError;
      try {
        err = await res.json();
      } catch {
        err = {
          code: `HTTP_${res.status}`,
          message: res.statusText || "Server error occurred",
        };
      }
      throw err;
    }

    return res.json();
  }

  async login(username: string, password: string): Promise<UserProfile> {
    const data = await this.request<UserProfile>("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (data.csrf_token) {
      this.csrfToken = data.csrf_token;
    }
    return data;
  }

  async logout(): Promise<void> {
    await this.request("/api/v1/auth/logout", { method: "POST" });
    this.csrfToken = null;
  }

  async getMe(): Promise<UserProfile> {
    const data = await this.request<UserProfile>("/api/v1/auth/me");
    if (data.csrf_token) {
      this.csrfToken = data.csrf_token;
    }
    return data;
  }

  async createSubmission(manifest: any): Promise<SubmissionDetail> {
    return this.request<SubmissionDetail>("/api/v1/submissions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(manifest),
    });
  }

  async uploadFile(submissionId: string, sourceId: string, file: File): Promise<SubmissionFile> {
    const formData = new FormData();
    formData.append("source_id", sourceId);
    formData.append("file", file);

    return this.request<SubmissionFile>(`/api/v1/submissions/${submissionId}/files`, {
      method: "POST",
      body: formData,
    });
  }

  async validateSubmission(submissionId: string): Promise<QualityReport> {
    return this.request<QualityReport>(`/api/v1/submissions/${submissionId}/validate`, {
      method: "POST",
    });
  }

  async commitSubmission(submissionId: string, idempotencyKey?: string): Promise<SubmissionDetail> {
    return this.request<SubmissionDetail>(`/api/v1/submissions/${submissionId}/commit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: idempotencyKey || null }),
    });
  }

  async listSubmissions(page = 1, pageSize = 20, entityId?: string): Promise<{ items: SubmissionSummary[]; total: number }> {
    const params = new URLSearchParams({ page: page.toString(), page_size: pageSize.toString() });
    if (entityId) params.set("entity_id", entityId);
    return this.request(`/api/v1/submissions?${params.toString()}`);
  }

  async getSubmission(id: string): Promise<SubmissionDetail> {
    return this.request<SubmissionDetail>(`/api/v1/submissions/${id}`);
  }

  async getSubmissionQuality(id: string): Promise<QualityReport> {
    return this.request<QualityReport>(`/api/v1/submissions/${id}/quality`);
  }

  async getRecordProvenance(id: string): Promise<RecordProvenance> {
    return this.request<RecordProvenance>(`/api/v1/evidence/records/${id}`);
  }

  async createAnalysisRun(submissionId: string, policyId = "POL-CSE-DEMO-V1", runName?: string): Promise<AnalysisRun> {
    return this.request<AnalysisRun>("/api/v1/analysis-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ submission_id: submissionId, policy_id: policyId, run_name: runName }),
    });
  }

  async listAnalysisRuns(submissionId?: string): Promise<AnalysisRun[]> {
    const endpoint = submissionId ? `/api/v1/analysis-runs?submission_id=${encodeURIComponent(submissionId)}` : "/api/v1/analysis-runs";
    return this.request<AnalysisRun[]>(endpoint);
  }

  async getAnalysisRun(runId: string): Promise<AnalysisRun> {
    return this.request<AnalysisRun>(`/api/v1/analysis-runs/${runId}`);
  }

  async listFindings(params?: { submission_id?: string; run_id?: string; rule_id?: string; evidence_state?: string }): Promise<Finding[]> {
    const query = new URLSearchParams();
    if (params?.submission_id) query.set("submission_id", params.submission_id);
    if (params?.run_id) query.set("run_id", params.run_id);
    if (params?.rule_id) query.set("rule_id", params.rule_id);
    if (params?.evidence_state) query.set("evidence_state", params.evidence_state);
    const qs = query.toString();
    return this.request<Finding[]>(qs ? `/api/v1/findings?${qs}` : "/api/v1/findings");
  }

  async getFinding(findingId: string): Promise<Finding> {
    return this.request<Finding>(`/api/v1/findings/${findingId}`);
  }

  async getEvidenceChain(objectId: string, submissionId: string): Promise<EvidenceChain> {
    return this.request<EvidenceChain>(`/api/v1/evidence/chains/${encodeURIComponent(objectId)}?submission_id=${encodeURIComponent(submissionId)}`);
  }

  async getSimilarPassages(findingId: string, limit = 5): Promise<SimilarPassagesResponse> {
    return this.request<SimilarPassagesResponse>(`/api/v1/findings/${encodeURIComponent(findingId)}/similar-passages?limit=${limit}`);
  }

  async createReviewPortfolio(params: {
    run_id: string;
    max_items?: number;
    max_minutes?: number;
    strata_allocation?: Record<string, number>;
    duplication_caps?: Record<string, number>;
    seed?: number;
  }): Promise<ReviewPortfolio> {
    return this.request<ReviewPortfolio>("/api/v1/review-portfolios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  }

  async getReviewPortfolio(id: string): Promise<ReviewPortfolio> {
    return this.request<ReviewPortfolio>(`/api/v1/review-portfolios/${encodeURIComponent(id)}`);
  }

  async listReviewPortfolios(runId?: string): Promise<ReviewPortfolio[]> {
    const ep = runId ? `/api/v1/review-portfolios?run_id=${encodeURIComponent(runId)}` : "/api/v1/review-portfolios";
    return this.request<ReviewPortfolio[]>(ep);
  }

  async recordFindingDecision(
    findingId: string,
    payload: { state: string; rationale: string; cited_evidence_ids: string[]; superseded_decision_id?: string | null }
  ): Promise<ReviewDecision> {
    return this.request<ReviewDecision>(`/api/v1/findings/${encodeURIComponent(findingId)}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async getFindingDecisions(findingId: string): Promise<ReviewDecision[]> {
    return this.request<ReviewDecision[]>(`/api/v1/findings/${encodeURIComponent(findingId)}/decisions`);
  }

  async recordItemDecision(
    itemId: string,
    payload: { state: string; rationale: string; cited_evidence_ids: string[]; superseded_decision_id?: string | null }
  ): Promise<ReviewDecision> {
    return this.request<ReviewDecision>(`/api/v1/review-items/${encodeURIComponent(itemId)}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async getItemDecisions(itemId: string): Promise<ReviewDecision[]> {
    return this.request<ReviewDecision[]>(`/api/v1/review-items/${encodeURIComponent(itemId)}/decisions`);
  }

  async createEvidenceRequest(payload: {
    missing_artifact: string;
    distinguishing_question: string;
    responsible_owner: string;
    due_date: string;
    finding_id?: string | null;
    review_item_id?: string | null;
  }): Promise<EvidenceRequest> {
    return this.request<EvidenceRequest>("/api/v1/evidence-requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async listEvidenceRequests(params?: { finding_id?: string; review_item_id?: string }): Promise<EvidenceRequest[]> {
    const query = new URLSearchParams();
    if (params?.finding_id) query.set("finding_id", params.finding_id);
    if (params?.review_item_id) query.set("review_item_id", params.review_item_id);
    const qs = query.toString();
    return this.request<EvidenceRequest[]>(qs ? `/api/v1/evidence-requests?${qs}` : "/api/v1/evidence-requests");
  }

  async createReport(payload: {
    run_id: string;
    portfolio_id?: string | null;
    decision_cutoff_time?: string | null;
    notes?: string | null;
  }): Promise<ReportResponse> {
    return this.request<ReportResponse>("/api/v1/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async listReports(params?: { entity_id?: string; run_id?: string }): Promise<ReportListResponse> {
    const query = new URLSearchParams();
    if (params?.entity_id) query.set("entity_id", params.entity_id);
    if (params?.run_id) query.set("run_id", params.run_id);
    const qs = query.toString();
    return this.request<ReportListResponse>(qs ? `/api/v1/reports?${qs}` : "/api/v1/reports");
  }

  async getReport(reportId: string): Promise<ReportResponse> {
    return this.request<ReportResponse>(`/api/v1/reports/${reportId}`);
  }

  getReportHtmlUrl(reportId: string): string {
    return `/api/v1/reports/${reportId}/html`;
  }

  getReportJsonUrl(reportId: string): string {
    return `/api/v1/reports/${reportId}/json`;
  }

  getReportManifestUrl(reportId: string): string {
    return `/api/v1/reports/${reportId}/manifest`;
  }

  getReportBundleUrl(reportId: string): string {
    return `/api/v1/reports/${reportId}/bundle`;
  }

  getReportProofUrl(reportId: string): string {
    return `/api/v1/reports/${reportId}/proof`;
  }

  async getReportProof(reportId: string): Promise<any> {
    return this.request<any>(`/api/v1/reports/${reportId}/proof`);
  }

  async getIntegrityStatus(): Promise<IntegrityStatusResponse> {
    return this.request<IntegrityStatusResponse>("/api/v1/evidence-integrity/status");
  }

  async getCustodyLog(params?: { entity_id?: string; limit?: number }): Promise<CustodyEvent[]> {
    const query = new URLSearchParams();
    if (params?.entity_id) query.set("entity_id", params.entity_id);
    if (params?.limit) query.set("limit", params.limit.toString());
    const qs = query.toString();
    return this.request<CustodyEvent[]>(qs ? `/api/v1/evidence-integrity/custody-log?${qs}` : "/api/v1/evidence-integrity/custody-log");
  }

  async verifyEvidence(payload: VerifyRequest): Promise<VerifyResponse> {
    return this.request<VerifyResponse>("/api/v1/evidence-integrity/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async triggerOutboxProcess(): Promise<{ processed: number; errors: number; status: string }> {
    return this.request<{ processed: number; errors: number; status: string }>("/api/v1/evidence-integrity/outbox/process", {
      method: "POST",
    });
  }

  async getAuthorizedEntities(): Promise<AuthorizedEntityItem[]> {
    return this.request<AuthorizedEntityItem[]>("/api/v1/supervisory/entities");
  }

  async getEntityPeriods(entityId: string): Promise<EntityPeriodOption[]> {
    return this.request<EntityPeriodOption[]>(`/api/v1/supervisory/periods?entity_id=${encodeURIComponent(entityId)}`);
  }

  async getSupervisoryOverview(entityId: string, runId?: string): Promise<SupervisoryOverviewResponse> {
    const qs = runId ? `?entity_id=${encodeURIComponent(entityId)}&run_id=${encodeURIComponent(runId)}` : `?entity_id=${encodeURIComponent(entityId)}`;
    return this.request<SupervisoryOverviewResponse>(`/api/v1/supervisory/overview${qs}`);
  }

  async getPeerComparison(entityId: string, periodStart?: string, periodEnd?: string): Promise<PeerCohortResponse> {
    const params = new URLSearchParams({ entity_id: entityId });
    if (periodStart) params.set("period_start", periodStart);
    if (periodEnd) params.set("period_end", periodEnd);
    return this.request<PeerCohortResponse>(`/api/v1/supervisory/peer-comparison?${params.toString()}`);
  }

  async getPeriodTrends(entityId: string, limitPeriods: number = 12): Promise<PeriodTrendsResponse> {
    return this.request<PeriodTrendsResponse>(`/api/v1/supervisory/trends?entity_id=${encodeURIComponent(entityId)}&limit_periods=${limitPeriods}`);
  }

  async getUnusualPatterns(submissionId: string, entityId?: string, runId?: string): Promise<UnusualPatternsResponse> {
    const params = new URLSearchParams({ submission_id: submissionId });
    if (entityId) params.set("entity_id", entityId);
    if (runId) params.set("run_id", runId);
    return this.request<UnusualPatternsResponse>(`/api/v1/supervisory/unusual-patterns?${params.toString()}`);
  }
}


export interface ReviewItem {
  id: string;
  portfolio_id: string;
  unit_id: string;
  unit_type: string;
  finding_id: string | null;
  scope: string;
  stratum: "targeted" | "control" | "exploratory";
  selection_rank: number;
  marginal_reasons: any;
  evidence_references: any[];
  unknowns: string[];
  what_examiner_learns: string;
  estimated_review_minutes: number;
  created_at: string;
}

export interface ReviewPortfolio {
  id: string;
  run_id: string;
  entity_id: string;
  created_by: string;
  revision: number;
  seed: number;
  parameters: any;
  summary: any;
  sampling_frame: any;
  items: ReviewItem[];
  created_at: string;
}

export interface ReviewDecision {
  id: string;
  finding_id: string | null;
  review_item_id: string | null;
  entity_id: string;
  reviewer_id: string;
  reviewer_username: string;
  state: string;
  rationale: string;
  cited_evidence_ids: string[];
  superseded_decision_id: string | null;
  version: number;
  created_at: string;
}

export interface EvidenceRequest {
  id: string;
  finding_id: string | null;
  review_item_id: string | null;
  entity_id: string;
  requester_id: string;
  missing_artifact: string;
  distinguishing_question: string;
  responsible_owner: string;
  due_date: string;
  status: string;
  created_at: string;
}

export interface TargetSpan {
  start_char: number;
  end_char: number;
  record_id: string;
}

export interface SimilarPassageMatch {
  match_id: string;
  source_id: string;
  record_type: string;
  record_id: string;
  start_char: number;
  end_char: number;
  matched_text: string;
  similarity: number;
  method: string;
  possible_explanation: string;
  caveats: string;
  exact_match?: boolean;
  lexical_score?: number;
  tlsh_distance?: number | null;
  semantic_score?: number;
}

export interface IntegrityStatusResponse {
  ledger_mode: string;
  fabric_configured: boolean;
  channel_name: string;
  chaincode_name: string;
  service_key_id: string;
  service_public_key: string;
  pending_outbox_count: number;
  anchored_outbox_count: number;
  failed_outbox_count: number;
}

export interface CustodyEvent {
  id: string;
  entity_id: string;
  event_type: string;
  sequence_number: number;
  previous_event_commitment: string;
  object_type: string;
  object_id: string;
  object_version: number;
  evidence_commitment: string;
  claimed_event_time: string;
  recorded_at: string;
  actor_id: string;
  signing_key_id: string;
  signature: string;
  payload_digest: string;
  metadata?: Record<string, any>;
}

export interface VerifyRequest {
  target_type: "submission" | "report_snapshot" | "custody_log";
  target_id: string;
  entity_id: string;
}

export interface VerifyResponse {
  is_valid: boolean;
  status: string;
  target_id: string;
  target_type: string;
  files_checked: number;
  records_checked: number;
  signatures_verified: number;
  issues: string[];
  details: Record<string, any>;
}

export interface SimilarPassagesResponse {
  finding_id: string;
  status: "completed" | "disabled" | "not_computed" | "no_passages";
  semantic_mode: "off" | "auto" | "required";
  method_used: string;
  model_revision?: string | null;
  manifest_digest?: string | null;
  fallback_reason?: string | null;
  target_passage?: string | null;
  target_span?: TargetSpan | null;
  matches: SimilarPassageMatch[];
  disclaimer: string;
}

export interface ReportResponse {
  id: string;
  run_id: string;
  portfolio_id: string | null;
  entity_id: string;
  created_by: string;
  decision_cutoff_time: string;
  status: string;
  report_schema_version: string;
  notes: string | null;
  created_at: string;
  completed_at: string | null;
  html_url: string;
  json_url: string;
  manifest_url: string;
  bundle_url: string;
  error_message: string | null;
}

export interface ReportListResponse {
  reports: ReportResponse[];
  total: number;
}

export const apiClient = new ApiClient();

export interface AuthorizedEntityItem {
  id: string;
  name: string;
  code: string;
  sector: string;
  submission_count: number;
  latest_period_start?: string | null;
  latest_period_end?: string | null;
}

export interface EntityPeriodOption {
  submission_id: string;
  run_id?: string | null;
  period_start: string;
  period_end: string;
  period_label: string;
  status: string;
  findings_count: number;
  has_analysis_run: boolean;
}

export interface EvidenceCompletenessSummary {
  declared_sources_count: number;
  received_sources_count: number;
  missing_sources_count: number;
  quarantined_records_count: number;
  total_parsed_records: number;
  completeness_percentage: number;
  sufficiency_verdict: string;
  details: Record<string, any>;
}

export interface ExecutionGapSummary {
  unsubstantiated_closures: number;
  overdue_escalations: number;
  unlinked_lifecycle_cases: number;
  adverse_findings_count: number;
  gap_score: number;
  severity_distribution: Record<string, number>;
  contributing_finding_ids: string[];
}

export interface NegativeSpaceSummary {
  total_critical_assets: number;
  healthy_monitored_assets: number;
  broken_sensor_assets: number;
  healthy_quiet_assets: number;
  missing_telemetry_assets: number;
  coverage_percentage: number;
  blind_spot_warning: boolean;
  contributing_asset_ids: string[];
}

export interface ContradictedClaimsSummary {
  total_declared_claims: number;
  mathematically_contradicted_claims: number;
  compatible_with_unknowns: number;
  supported_claims: number;
  unreconciled_claims: number;
  details: any[];
}

export interface CapabilityDimension {
  code: string;
  name: string;
  status: string;
  confidence: number;
  findings_count: number;
  primary_rule?: string | null;
  evidence_basis: string;
}

export interface SupervisoryOverviewResponse {
  entity_id: string;
  entity_name: string;
  entity_code: string;
  submission_id: string;
  period_start: string;
  period_end: string;
  run_id: string;
  analysis_status: string;
  cutoff_time: string;
  supervisory_attention_index: number;
  attention_priority: string;
  evidence_completeness: EvidenceCompletenessSummary;
  execution_gaps: ExecutionGapSummary;
  negative_space: NegativeSpaceSummary;
  contradicted_claims: ContradictedClaimsSummary;
  open_evidence_requests_count: number;
  active_portfolio_items_count: number;
  human_decisions_count: number;
  capabilities: CapabilityDimension[];
  disclaimer: string;
}

export interface DistributionStats {
  count: number;
  min: number;
  q25: number;
  median: number;
  q75: number;
  max: number;
  iqr: number;
}

export interface MetricComparison {
  metric_code: string;
  metric_name: string;
  target_value: number;
  peer_distribution?: DistributionStats | null;
  target_percentile_rank?: number | null;
  comparison_state: string;
  unit: string;
  explanation: string;
}

export interface PeerCohortResponse {
  target_entity_id: string;
  target_sector: string;
  target_tier: string;
  cohort_version: string;
  period_start: string;
  period_end: string;
  eligible_peer_count: number;
  minimum_peers_required: number;
  is_cohort_sufficient: boolean;
  status: string;
  status_reason: string;
  eligible_peers: Array<{ entity_id: string; name: string; status: string }>;
  excluded_peers: Array<{ entity_id: string; name: string; reason: string }>;
  metric_comparisons: MetricComparison[];
  privacy_disclosure: string;
}

export interface TrendPoint {
  period_label: string;
  period_start: string;
  period_end: string;
  has_data: boolean;
  gap_reason?: string | null;
  run_id?: string | null;
  submission_id?: string | null;
  policy_version?: string | null;
  rule_version?: string | null;
  scope_summary?: string | null;
  evidence_completeness_pct?: number | null;
  total_cases_evaluated?: number | null;
  adverse_findings_count?: number | null;
  concern_density_per_100?: number | null;
  unsubstantiated_closure_rate_pct?: number | null;
  overdue_escalation_rate_pct?: number | null;
  monitoring_coverage_pct?: number | null;
  supervisory_attention_index?: number | null;
  examiner_decisions_count?: number | null;
  open_evidence_requests_count?: number | null;
}

export interface PeriodTrendsResponse {
  entity_id: string;
  entity_name: string;
  entity_code: string;
  sector: string;
  period_count: number;
  missing_period_count: number;
  trajectory: string;
  trajectory_narrative: string;
  points: TrendPoint[];
  scope_annotations: string[];
}

export interface ReviewHypothesis {
  hypothesis_id: string;
  pattern_code: string;
  title: string;
  severity: string;
  hypothesis_statement: string;
  observed_value: number;
  observed_unit: string;
  baseline_value: number;
  baseline_definition: string;
  deviation_factor: string;
  sample_size: number;
  denominator_description: string;
  uncertainty_warning?: string | null;
  contributing_records: any[];
  suggested_examiner_action: string;
}

export interface UnusualPatternsResponse {
  entity_id: string;
  submission_id: string;
  run_id: string;
  hypotheses_count: number;
  hypotheses: ReviewHypothesis[];
  robust_statistics_summary: Record<string, any>;
  methodology_disclosure: string;
}



