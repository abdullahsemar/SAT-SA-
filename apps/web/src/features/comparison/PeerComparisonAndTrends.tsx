import React, { useEffect, useState } from "react";
import {
  apiClient,
  AuthorizedEntityItem,
  EntityPeriodOption,
  MetricComparison,
  PeerCohortResponse,
  PeriodTrendsResponse,
  UnusualPatternsResponse,
} from "../../api/client";

interface PeerComparisonAndTrendsProps {
  selectedEntityId?: string;
  selectedSubmissionId?: string;
  onNavigateToView?: (view: string, context?: any) => void;
  onSelectEntity?: (entityId: string) => void;
  onSelectPeriod?: (submissionId: string, runId?: string | null) => void;
}

export const PeerComparisonAndTrends: React.FC<PeerComparisonAndTrendsProps> = ({
  selectedEntityId,
  selectedSubmissionId,
  onNavigateToView,
  onSelectEntity,
  onSelectPeriod,
}) => {
  const [activeTab, setActiveTab] = useState<"peers" | "trends" | "patterns">("peers");
  const [entities, setEntities] = useState<AuthorizedEntityItem[]>([]);
  const [periods, setPeriods] = useState<EntityPeriodOption[]>([]);
  const [currentEntityId, setCurrentEntityId] = useState<string>(selectedEntityId || "");
  const [currentSubmissionId, setCurrentSubmissionId] = useState<string>(selectedSubmissionId || "");

  // Data states
  const [peerData, setPeerData] = useState<PeerCohortResponse | null>(null);
  const [trendData, setTrendData] = useState<PeriodTrendsResponse | null>(null);
  const [patternsData, setPatternsData] = useState<UnusualPatternsResponse | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Load entities
  useEffect(() => {
    const fetchEntities = async () => {
      try {
        const list = await apiClient.getAuthorizedEntities();
        setEntities(list);
        if (list.length > 0 && !currentEntityId) {
          setCurrentEntityId(list[0].id);
          if (onSelectEntity) onSelectEntity(list[0].id);
        }
      } catch (err: any) {
        setError(err.message || "Failed to load entities");
      }
    };
    fetchEntities();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync prop changes
  useEffect(() => {
    if (selectedEntityId && selectedEntityId !== currentEntityId) {
      setCurrentEntityId(selectedEntityId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEntityId]);

  useEffect(() => {
    if (selectedSubmissionId && selectedSubmissionId !== currentSubmissionId) {
      setCurrentSubmissionId(selectedSubmissionId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSubmissionId]);

  // Load periods whenever entity changes
  useEffect(() => {
    if (!currentEntityId) return;
    const fetchPeriods = async () => {
      try {
        const list = await apiClient.getEntityPeriods(currentEntityId);
        setPeriods(list);
        if (list.length > 0 && !currentSubmissionId) {
          setCurrentSubmissionId(list[0].submission_id);
          if (onSelectPeriod) {
            onSelectPeriod(list[0].submission_id, list[0].run_id);
          }
        }
      } catch (err: any) {
        console.error("Failed to load periods:", err);
      }
    };
    fetchPeriods();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentEntityId]);

  // Load tab-specific data
  useEffect(() => {
    if (!currentEntityId) return;

    const loadData = async () => {
      setLoading(true);
      setError(null);
      try {
        if (activeTab === "peers") {
          const res = await apiClient.getPeerComparison(currentEntityId);
          setPeerData(res);
        } else if (activeTab === "trends") {
          const res = await apiClient.getPeriodTrends(currentEntityId);
          setTrendData(res);
        } else if (activeTab === "patterns") {
          if (currentSubmissionId) {
            const res = await apiClient.getUnusualPatterns(currentSubmissionId, currentEntityId);
            setPatternsData(res);
          }
        }
      } catch (err: any) {
        setError(err.message || "Failed to load comparative analytics");
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [currentEntityId, currentSubmissionId, activeTab]);

  const getStatePill = (state: string) => {
    switch (state) {
      case "FAVORABLE":
        return { bg: "#dcfce7", color: "#166534", text: "Favorable Alignment" };
      case "ALIGNED_WITH_PEERS":
        return { bg: "#e0e7ff", color: "#3730a3", text: "Aligned with Peers" };
      case "OUTLIER_CONCERN":
        return { bg: "#fee2e2", color: "#991b1b", text: "Outlier Concern" };
      case "UNAVAILABLE":
      default:
        return { bg: "#f3f4f6", color: "#4b5563", text: "Peer Comparison Unavailable" };
    }
  };

  const getTrajectoryBadge = (trajectory: string) => {
    switch (trajectory) {
      case "IMPROVING":
        return { bg: "#dcfce7", color: "#166534", label: "Improving Trajectory" };
      case "DETERIORATING":
        return { bg: "#fee2e2", color: "#991b1b", label: "Deteriorating Compliance" };
      case "STABLE":
        return { bg: "#e0e7ff", color: "#3730a3", label: "Stable Operational Posture" };
      case "INSUFFICIENT_HISTORY":
      default:
        return { bg: "#fef3c7", color: "#92400e", label: "Insufficient Historical Quarters" };
    }
  };

  return (
    <div style={{ maxWidth: "1280px", margin: "0 auto", padding: "24px 20px" }}>
      {/* Top Header & Entity Selector */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "8px",
          padding: "16px 20px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
          marginBottom: "20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "16px",
          border: "1px solid #e5e7eb",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" }}>
          <div>
            <label
              htmlFor="comp-entity-select"
              style={{
                display: "block",
                fontSize: "11px",
                fontWeight: 700,
                color: "#6b7280",
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                marginBottom: "4px",
              }}
            >
              Supervised Entity
            </label>
            <select
              id="comp-entity-select"
              value={currentEntityId}
              onChange={(e) => {
                setCurrentEntityId(e.target.value);
                if (onSelectEntity) onSelectEntity(e.target.value);
              }}
              style={{
                padding: "8px 12px",
                fontSize: "13px",
                fontWeight: 600,
                borderRadius: "6px",
                border: "1px solid #d1d5db",
                background: "#f9fafb",
                color: "#111827",
                minWidth: "260px",
              }}
            >
              {entities.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name} ({e.code}) — {e.sector}
                </option>
              ))}
            </select>
          </div>

          {activeTab === "patterns" && (
            <div>
              <label
                htmlFor="comp-period-select"
                style={{
                  display: "block",
                  fontSize: "11px",
                  fontWeight: 700,
                  color: "#6b7280",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                  marginBottom: "4px",
                }}
              >
                Submission Period
              </label>
              <select
                id="comp-period-select"
                value={currentSubmissionId}
                onChange={(e) => {
                  setCurrentSubmissionId(e.target.value);
                  const sel = periods.find((p) => p.submission_id === e.target.value);
                  if (onSelectPeriod) onSelectPeriod(e.target.value, sel?.run_id);
                }}
                style={{
                  padding: "8px 12px",
                  fontSize: "13px",
                  fontWeight: 600,
                  borderRadius: "6px",
                  border: "1px solid #d1d5db",
                  background: "#f9fafb",
                  color: "#111827",
                  minWidth: "220px",
                }}
              >
                {periods.map((p) => (
                  <option key={p.submission_id} value={p.submission_id}>
                    {p.period_label} ({p.has_analysis_run ? "Assessed" : "Pending"})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Tab Switcher */}
        <div style={{ display: "flex", gap: "6px", background: "#f3f4f6", padding: "4px", borderRadius: "8px" }}>
          <button
            onClick={() => setActiveTab("peers")}
            style={{
              padding: "8px 16px",
              fontSize: "13px",
              fontWeight: 600,
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              background: activeTab === "peers" ? "#ffffff" : "transparent",
              color: activeTab === "peers" ? "#111827" : "#6b7280",
              boxShadow: activeTab === "peers" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
            }}
          >
            Peer Comparison
          </button>
          <button
            onClick={() => setActiveTab("trends")}
            style={{
              padding: "8px 16px",
              fontSize: "13px",
              fontWeight: 600,
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              background: activeTab === "trends" ? "#ffffff" : "transparent",
              color: activeTab === "trends" ? "#111827" : "#6b7280",
              boxShadow: activeTab === "trends" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
            }}
          >
            Longitudinal Trends
          </button>
          <button
            onClick={() => setActiveTab("patterns")}
            style={{
              padding: "8px 16px",
              fontSize: "13px",
              fontWeight: 600,
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              background: activeTab === "patterns" ? "#ffffff" : "transparent",
              color: activeTab === "patterns" ? "#111827" : "#6b7280",
              boxShadow: activeTab === "patterns" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
            }}
          >
            Unusual Patterns (MAD)
          </button>
        </div>
      </div>

      {loading && (
        <div
          style={{
            background: "#ffffff",
            padding: "48px",
            textAlign: "center",
            borderRadius: "8px",
            border: "1px solid #e5e7eb",
            color: "#6b7280",
            fontSize: "14px",
          }}
        >
          Computing comparative distributions and statistical hypotheses...
        </div>
      )}

      {error && !loading && (
        <div
          style={{
            background: "#fee2e2",
            border: "1px solid #f87171",
            color: "#991b1b",
            padding: "16px 20px",
            borderRadius: "8px",
            marginBottom: "20px",
            fontSize: "14px",
          }}
        >
          <strong>Notice:</strong> {error}
        </div>
      )}

      {/* TAB 1: PEER COMPARISON */}
      {activeTab === "peers" && peerData && !loading && (
        <div>
          {/* Cohort Eligibility & Status Card */}
          <div
            style={{
              background: "#ffffff",
              borderRadius: "8px",
              padding: "20px",
              border: "1px solid #e5e7eb",
              boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
              marginBottom: "20px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", marginBottom: "12px" }}>
              <div>
                <h3 style={{ margin: "0 0 4px 0", fontSize: "16px", fontWeight: 700, color: "#111827" }}>
                  Cohort Eligibility & Reference Distribution
                </h3>
                <span style={{ fontSize: "13px", color: "#6b7280" }}>
                  Sector: <strong>{peerData.target_sector}</strong> | Criticality Tier: <strong>{peerData.target_tier}</strong> | Eligibility Rule: <strong>{peerData.cohort_version}</strong>
                </span>
              </div>

              <div
                style={{
                  background: peerData.is_cohort_sufficient ? "#dcfce7" : "#fef3c7",
                  color: peerData.is_cohort_sufficient ? "#166534" : "#92400e",
                  border: `1px solid ${peerData.is_cohort_sufficient ? "#86efac" : "#fde68a"}`,
                  padding: "6px 14px",
                  borderRadius: "9999px",
                  fontWeight: 700,
                  fontSize: "13px",
                }}
              >
                {peerData.status === "VALID_COMPARISON" ? "Valid Statistical Cohort" : "Insufficient Peer Cohort"}
              </div>
            </div>

            <p style={{ margin: "0 0 12px 0", fontSize: "13px", color: "#374151" }}>
              {peerData.status_reason}
            </p>

            {/* Target Exclusion & Privacy Disclosures */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div
                style={{
                  background: "#f0fdf4",
                  border: "1px solid #bbf7d0",
                  padding: "10px 14px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  color: "#166534",
                }}
              >
                <strong>Target Entity Exclusion Invariant:</strong> The target entity is strictly excluded from the reference distribution to prevent self-skewing medians and IQRs.
              </div>

              <div
                style={{
                  background: "#eff6ff",
                  border: "1px solid #bfdbfe",
                  padding: "10px 14px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  color: "#1e40af",
                }}
              >
                <strong>Privacy Boundary:</strong> {peerData.privacy_disclosure}
              </div>
            </div>
          </div>

          {/* Metric Comparison Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "20px", marginBottom: "24px" }}>
            {peerData.metric_comparisons.map((m: MetricComparison) => {
              const pill = getStatePill(m.comparison_state);
              return (
                <div
                  key={m.metric_code}
                  style={{
                    background: "#ffffff",
                    borderRadius: "8px",
                    padding: "20px",
                    border: "1px solid #e5e7eb",
                    boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                    <div>
                      <span style={{ fontSize: "11px", fontWeight: 700, color: "#6b7280" }}>{m.metric_code}</span>
                      <h4 style={{ margin: "2px 0 0 0", fontSize: "14px", fontWeight: 700, color: "#111827" }}>
                        {m.metric_name}
                      </h4>
                    </div>
                    <span
                      style={{
                        background: pill.bg,
                        color: pill.color,
                        padding: "3px 8px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: 600,
                      }}
                    >
                      {pill.text}
                    </span>
                  </div>

                  <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "12px" }}>
                    <div>
                      <span style={{ fontSize: "11px", color: "#6b7280", display: "block" }}>Target Value</span>
                      <span style={{ fontSize: "24px", fontWeight: 800, color: "#111827" }}>
                        {m.target_value} {m.unit}
                      </span>
                    </div>

                    {m.peer_distribution && (
                      <div style={{ borderLeft: "1px solid #e5e7eb", paddingLeft: "10px" }}>
                        <span style={{ fontSize: "11px", color: "#6b7280", display: "block" }}>Peer Median</span>
                        <span style={{ fontSize: "18px", fontWeight: 700, color: "#4b5563" }}>
                          {m.peer_distribution.median.toFixed(1)} {m.unit}
                        </span>
                      </div>
                    )}
                  </div>

                  {m.peer_distribution && (
                    <div
                      style={{
                        background: "#f9fafb",
                        borderRadius: "6px",
                        padding: "8px 12px",
                        fontSize: "11px",
                        color: "#4b5563",
                        marginBottom: "10px",
                        display: "flex",
                        justifyContent: "space-between",
                      }}
                    >
                      <span>Min: {m.peer_distribution.min.toFixed(1)}</span>
                      <span>Q1: {m.peer_distribution.q25.toFixed(1)}</span>
                      <span>Q3: {m.peer_distribution.q75.toFixed(1)}</span>
                      <span>Max: {m.peer_distribution.max.toFixed(1)}</span>
                      <span>IQR: {m.peer_distribution.iqr.toFixed(1)}</span>
                    </div>
                  )}

                  <p style={{ margin: 0, fontSize: "12px", color: "#4b5563", lineHeight: 1.4 }}>
                    {m.explanation}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Cohort Membership Audit */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
            <div
              style={{
                background: "#ffffff",
                borderRadius: "8px",
                padding: "20px",
                border: "1px solid #e5e7eb",
              }}
            >
              <h4 style={{ margin: "0 0 12px 0", fontSize: "14px", fontWeight: 700, color: "#111827" }}>
                Qualified Cohort Members ({peerData.eligible_peers.length})
              </h4>
              {peerData.eligible_peers.length === 0 ? (
                <p style={{ fontSize: "13px", color: "#9ca3af" }}>No peers qualified for this reporting window.</p>
              ) : (
                <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "13px", color: "#374151" }}>
                  {peerData.eligible_peers.map((p) => (
                    <li key={p.entity_id} style={{ marginBottom: "6px" }}>
                      <strong>{p.name}</strong> ({p.entity_id}) — <span style={{ color: "#166534" }}>{p.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div
              style={{
                background: "#ffffff",
                borderRadius: "8px",
                padding: "20px",
                border: "1px solid #e5e7eb",
              }}
            >
              <h4 style={{ margin: "0 0 12px 0", fontSize: "14px", fontWeight: 700, color: "#111827" }}>
                Excluded Entities & Audited Disqualification Reasons ({peerData.excluded_peers.length})
              </h4>
              {peerData.excluded_peers.length === 0 ? (
                <p style={{ fontSize: "13px", color: "#9ca3af" }}>No entities were excluded.</p>
              ) : (
                <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "13px", color: "#374151" }}>
                  {peerData.excluded_peers.map((p) => (
                    <li key={p.entity_id} style={{ marginBottom: "6px" }}>
                      <strong>{p.name}</strong> ({p.entity_id}): <span style={{ color: "#991b1b" }}>{p.reason}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: LONGITUDINAL TRENDS */}
      {activeTab === "trends" && trendData && !loading && (
        <div>
          {/* Trajectory Card */}
          {(() => {
            const badge = getTrajectoryBadge(trendData.trajectory);
            return (
              <div
                style={{
                  background: "#ffffff",
                  borderRadius: "8px",
                  padding: "20px",
                  border: "1px solid #e5e7eb",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                  marginBottom: "20px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#111827" }}>
                    Multi-Period Longitudinal Posture Trajectory
                  </h3>
                  <span
                    style={{
                      background: badge.bg,
                      color: badge.color,
                      padding: "4px 12px",
                      borderRadius: "9999px",
                      fontSize: "12px",
                      fontWeight: 700,
                    }}
                  >
                    {badge.label}
                  </span>
                </div>

                <p style={{ margin: "0 0 12px 0", fontSize: "13px", color: "#374151", lineHeight: 1.5 }}>
                  {trendData.trajectory_narrative}
                </p>

                {trendData.scope_annotations.length > 0 && (
                  <div
                    style={{
                      background: "#fffbeb",
                      border: "1px solid #fef3c7",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      color: "#92400e",
                    }}
                  >
                    <strong>Scope & Governance Annotations:</strong>
                    <ul style={{ margin: "4px 0 0 0", paddingLeft: "16px" }}>
                      {trendData.scope_annotations.map((s, idx) => (
                        <li key={idx}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })()}

          {/* Longitudinal Points Table */}
          <div
            style={{
              background: "#ffffff",
              borderRadius: "8px",
              padding: "20px",
              border: "1px solid #e5e7eb",
              boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
            }}
          >
            <h4 style={{ margin: "0 0 14px 0", fontSize: "14px", fontWeight: 700, color: "#111827" }}>
              Quarterly Evidence Points & Canonical Runs
            </h4>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb" }}>
                    <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 700, color: "#4b5563" }}>Period</th>
                    <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 700, color: "#4b5563" }}>Status</th>
                    <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 700, color: "#4b5563" }}>Completeness</th>
                    <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 700, color: "#4b5563" }}>Cases</th>
                    <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 700, color: "#4b5563" }}>Adverse Findings</th>
                    <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 700, color: "#4b5563" }}>Rapid Closure %</th>
                    <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 700, color: "#4b5563" }}>Overdue Escalation %</th>
                    <th style={{ padding: "10px 12px", textAlign: "center", fontWeight: 700, color: "#4b5563" }}>Attention Index</th>
                    <th style={{ padding: "10px 12px", textAlign: "right", fontWeight: 700, color: "#4b5563" }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {trendData.points.map((pt, idx) => {
                    if (!pt.has_data) {
                      return (
                        <tr key={idx} style={{ background: "#fffdf0", borderBottom: "1px solid #fef3c7" }}>
                          <td style={{ padding: "12px", fontWeight: 700, color: "#92400e" }}>
                            {pt.period_label}
                          </td>
                          <td colSpan={7} style={{ padding: "12px", color: "#92400e", fontSize: "12px" }}>
                            <strong>REPORTING GAP PRESERVED:</strong> {pt.gap_reason || "No evidence submitted."}
                          </td>
                          <td style={{ padding: "12px", textAlign: "right" }}>
                            <span style={{ fontSize: "11px", color: "#9ca3af" }}>No Run</span>
                          </td>
                        </tr>
                      );
                    }

                    return (
                      <tr key={idx} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "12px", fontWeight: 600, color: "#111827" }}>
                          {pt.period_label}
                        </td>
                        <td style={{ padding: "12px", textAlign: "center" }}>
                          <span
                            style={{
                              background: "#dcfce7",
                              color: "#166534",
                              padding: "2px 8px",
                              borderRadius: "4px",
                              fontSize: "11px",
                              fontWeight: 600,
                            }}
                          >
                            Assessed
                          </span>
                        </td>
                        <td style={{ padding: "12px", textAlign: "center", fontWeight: 600 }}>
                          {pt.evidence_completeness_pct !== null ? `${pt.evidence_completeness_pct}%` : "—"}
                        </td>
                        <td style={{ padding: "12px", textAlign: "center" }}>
                          {pt.total_cases_evaluated ?? "—"}
                        </td>
                        <td style={{ padding: "12px", textAlign: "center" }}>
                          <span
                            style={{
                              color: (pt.adverse_findings_count || 0) > 0 ? "#991b1b" : "#166534",
                              fontWeight: 700,
                            }}
                          >
                            {pt.adverse_findings_count ?? "—"}
                          </span>
                        </td>
                        <td style={{ padding: "12px", textAlign: "center" }}>
                          {pt.unsubstantiated_closure_rate_pct != null ? `${pt.unsubstantiated_closure_rate_pct}%` : "—"}
                        </td>
                        <td style={{ padding: "12px", textAlign: "center" }}>
                          {pt.overdue_escalation_rate_pct != null ? `${pt.overdue_escalation_rate_pct}%` : "—"}
                        </td>
                        <td style={{ padding: "12px", textAlign: "center", fontWeight: 700 }}>
                          {pt.supervisory_attention_index != null ? pt.supervisory_attention_index.toFixed(1) : "—"}
                        </td>
                        <td style={{ padding: "12px", textAlign: "right" }}>
                          {pt.run_id && (
                            <button
                              onClick={() => onNavigateToView && onNavigateToView("findings", { runId: pt.run_id })}
                              style={{
                                padding: "4px 8px",
                                fontSize: "11px",
                                fontWeight: 600,
                                color: "#4f46e5",
                                background: "#eef2ff",
                                border: "1px solid #c7d2fe",
                                borderRadius: "4px",
                                cursor: "pointer",
                              }}
                            >
                              Inspect Run &rarr;
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: UNUSUAL PATTERNS (ROBUST MAD) */}
      {activeTab === "patterns" && patternsData && !loading && (
        <div>
          {/* Methodology & Disclosure Card */}
          <div
            style={{
              background: "#ffffff",
              borderRadius: "8px",
              padding: "20px",
              border: "1px solid #e5e7eb",
              boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
              marginBottom: "20px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#111827" }}>
                Explainable Statistical Review Hypotheses
              </h3>
              <span
                style={{
                  background: patternsData.hypotheses_count > 0 ? "#fee2e2" : "#dcfce7",
                  color: patternsData.hypotheses_count > 0 ? "#991b1b" : "#166534",
                  padding: "4px 10px",
                  borderRadius: "9999px",
                  fontSize: "12px",
                  fontWeight: 700,
                }}
              >
                {patternsData.hypotheses_count} Hypothesis Leads
              </span>
            </div>

            <p style={{ margin: "0 0 12px 0", fontSize: "13px", color: "#4b5563" }}>
              {patternsData.methodology_disclosure}
            </p>

            {/* Robust Statistics Baseline Snapshot */}
            {patternsData.robust_statistics_summary.investigation_duration_stats && (
              <div
                style={{
                  background: "#f9fafb",
                  padding: "10px 14px",
                  borderRadius: "6px",
                  border: "1px solid #e5e7eb",
                  fontSize: "12px",
                  color: "#374151",
                  display: "flex",
                  gap: "24px",
                  flexWrap: "wrap",
                }}
              >
                <div>
                  Median Duration:{" "}
                  <strong>
                    {patternsData.robust_statistics_summary.investigation_duration_stats.median_minutes} min
                  </strong>
                </div>
                <div>
                  MAD Duration:{" "}
                  <strong>
                    {patternsData.robust_statistics_summary.investigation_duration_stats.mad_minutes} min
                  </strong>
                </div>
                <div>
                  Zero-MAD Detected:{" "}
                  <strong>
                    {patternsData.robust_statistics_summary.investigation_duration_stats.zero_mad ? "Yes (Uniform timestamps)" : "No"}
                  </strong>
                </div>
              </div>
            )}
          </div>

          {/* Hypotheses List */}
          {patternsData.hypotheses.length === 0 ? (
            <div
              style={{
                background: "#ffffff",
                padding: "36px",
                textAlign: "center",
                borderRadius: "8px",
                border: "1px solid #e5e7eb",
                color: "#6b7280",
                fontSize: "14px",
              }}
            >
              No statistically anomalous operational patterns or boilerplate clusters detected for this submission.
            </div>
          ) : (
            <div style={{ display: "grid", gap: "16px" }}>
              {patternsData.hypotheses.map((hyp) => (
                <div
                  key={hyp.hypothesis_id}
                  style={{
                    background: "#ffffff",
                    borderRadius: "8px",
                    padding: "20px",
                    border: "1px solid #e5e7eb",
                    borderLeft: `4px solid ${
                      hyp.severity === "HIGH" ? "#ef4444" : hyp.severity === "ELEVATED" ? "#f59e0b" : "#3b82f6"
                    }`,
                    boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                    <div>
                      <span style={{ fontSize: "11px", fontWeight: 700, color: "#6b7280" }}>{hyp.pattern_code}</span>
                      <h4 style={{ margin: "2px 0 0 0", fontSize: "15px", fontWeight: 700, color: "#111827" }}>
                        {hyp.title}
                      </h4>
                    </div>

                    <span
                      style={{
                        fontSize: "11px",
                        fontWeight: 700,
                        padding: "3px 8px",
                        borderRadius: "4px",
                        background: hyp.severity === "HIGH" ? "#fee2e2" : hyp.severity === "ELEVATED" ? "#fef3c7" : "#e0e7ff",
                        color: hyp.severity === "HIGH" ? "#991b1b" : hyp.severity === "ELEVATED" ? "#92400e" : "#3730a3",
                      }}
                    >
                      {hyp.severity} Priority
                    </span>
                  </div>

                  <p style={{ margin: "0 0 12px 0", fontSize: "13px", color: "#1f2937", lineHeight: 1.4 }}>
                    {hyp.hypothesis_statement}
                  </p>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                      gap: "10px",
                      background: "#f9fafb",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      color: "#4b5563",
                      marginBottom: "12px",
                    }}
                  >
                    <div>
                      Observed: <strong>{hyp.observed_value} {hyp.observed_unit}</strong>
                    </div>
                    <div>
                      Baseline: <strong>{hyp.baseline_value}</strong>
                    </div>
                    <div>
                      Deviation: <strong>{hyp.deviation_factor}</strong>
                    </div>
                    <div>
                      Sample Size: <strong>n={hyp.sample_size}</strong>
                    </div>
                  </div>

                  {hyp.uncertainty_warning && (
                    <div
                      style={{
                        background: "#fffdf0",
                        border: "1px solid #fef3c7",
                        padding: "8px 12px",
                        borderRadius: "6px",
                        fontSize: "12px",
                        color: "#92400e",
                        marginBottom: "12px",
                      }}
                    >
                      <strong>Uncertainty Boundary:</strong> {hyp.uncertainty_warning}
                    </div>
                  )}

                  <div
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      color: "#1e293b",
                    }}
                  >
                    <strong>Suggested Examiner Action:</strong> {hyp.suggested_examiner_action}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
