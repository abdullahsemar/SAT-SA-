import React, { useEffect, useState } from "react";
import {
  apiClient,
  AuthorizedEntityItem,
  EntityPeriodOption,
  SupervisoryOverviewResponse,
} from "../../api/client";

interface SupervisoryOverviewProps {
  selectedEntityId?: string;
  selectedRunId?: string;
  onNavigateToView?: (view: string, context?: any) => void;
  onSelectEntity?: (entityId: string) => void;
  onSelectPeriod?: (submissionId: string, runId?: string | null) => void;
}

export const SupervisoryOverview: React.FC<SupervisoryOverviewProps> = ({
  selectedEntityId,
  selectedRunId,
  onNavigateToView,
  onSelectEntity,
  onSelectPeriod,
}) => {
  const [entities, setEntities] = useState<AuthorizedEntityItem[]>([]);
  const [periods, setPeriods] = useState<EntityPeriodOption[]>([]);
  const [currentEntityId, setCurrentEntityId] = useState<string>(selectedEntityId || "");
  const [currentRunId, setCurrentRunId] = useState<string>(selectedRunId || "");
  const [overview, setOverview] = useState<SupervisoryOverviewResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Load authorized entities on mount
  useEffect(() => {
    const fetchEntities = async () => {
      try {
        const list = await apiClient.getAuthorizedEntities();
        setEntities(list);
        if (list.length > 0 && !currentEntityId) {
          const initialId = list[0].id;
          setCurrentEntityId(initialId);
          if (onSelectEntity) onSelectEntity(initialId);
        }
      } catch (err: any) {
        setError(err.message || "Failed to load authorized entities");
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
    if (selectedRunId && selectedRunId !== currentRunId) {
      setCurrentRunId(selectedRunId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId]);

  // Load periods whenever entity changes
  useEffect(() => {
    if (!currentEntityId) return;
    const fetchPeriods = async () => {
      try {
        const periodList = await apiClient.getEntityPeriods(currentEntityId);
        setPeriods(periodList);
        if (periodList.length > 0 && !currentRunId) {
          const firstWithRun = periodList.find((p) => p.run_id);
          const chosenRun = firstWithRun ? firstWithRun.run_id || "" : "";
          setCurrentRunId(chosenRun);
          if (onSelectPeriod) {
            onSelectPeriod(periodList[0].submission_id, chosenRun);
          }
        }
      } catch (err: any) {
        console.error("Failed to load periods:", err);
      }
    };
    fetchPeriods();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentEntityId]);

  // Fetch overview whenever entity or run changes
  useEffect(() => {
    if (!currentEntityId) return;
    const fetchOverview = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiClient.getSupervisoryOverview(
          currentEntityId,
          currentRunId || undefined
        );
        setOverview(data);
      } catch (err: any) {
        setError(err.message || "Unable to load supervisory overview for the selected entity");
        setOverview(null);
      } finally {
        setLoading(false);
      }
    };
    fetchOverview();
  }, [currentEntityId, currentRunId]);

  const handleEntityChange = (newEntityId: string) => {
    setCurrentEntityId(newEntityId);
    setCurrentRunId("");
    if (onSelectEntity) onSelectEntity(newEntityId);
  };

  const handlePeriodChange = (subId: string) => {
    const selected = periods.find((p) => p.submission_id === subId);
    const newRunId = selected?.run_id || "";
    setCurrentRunId(newRunId);
    if (onSelectPeriod) onSelectPeriod(subId, newRunId);
  };

  const getPriorityBadge = (priority: string) => {
    switch (priority) {
      case "CRITICAL_ATTENTION":
        return {
          bg: "#fee2e2",
          color: "#991b1b",
          border: "#f87171",
          label: "Critical Attention Required",
        };
      case "ELEVATED":
        return {
          bg: "#fef3c7",
          color: "#92400e",
          border: "#fbbf24",
          label: "Elevated Supervisory Priority",
        };
      default:
        return {
          bg: "#dcfce7",
          color: "#166534",
          border: "#86efac",
          label: "Routine Supervisory Monitoring",
        };
    }
  };

  const getStatusPill = (status: string) => {
    switch (status) {
      case "supported":
        return { bg: "#dcfce7", color: "#166534", text: "Supported" };
      case "potential_concern":
        return { bg: "#fee2e2", color: "#991b1b", text: "Potential Concern" };
      case "insufficient_evidence":
        return { bg: "#fef3c7", color: "#92400e", text: "Insufficient Evidence" };
      case "not_assessed":
      default:
        return { bg: "#f3f4f6", color: "#4b5563", text: "Not Assessed" };
    }
  };

  return (
    <div style={{ maxWidth: "1280px", margin: "0 auto", padding: "24px 20px" }}>
      {/* Context Selector Bar */}
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
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
          <div>
            <label
              htmlFor="overview-entity-select"
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
              id="overview-entity-select"
              value={currentEntityId}
              onChange={(e) => handleEntityChange(e.target.value)}
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

          <div>
            <label
              htmlFor="overview-period-select"
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
              Reporting Period & Run
            </label>
            <select
              id="overview-period-select"
              value={
                periods.find((p) => p.run_id === currentRunId)?.submission_id ||
                periods[0]?.submission_id ||
                ""
              }
              onChange={(e) => handlePeriodChange(e.target.value)}
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
        </div>

        {overview && (
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <span
              style={{
                fontSize: "12px",
                color: "#6b7280",
                background: "#f3f4f6",
                padding: "6px 12px",
                borderRadius: "6px",
                border: "1px solid #e5e7eb",
              }}
            >
              Cutoff: <strong>{new Date(overview.cutoff_time).toLocaleDateString()}</strong>
            </span>
            <span
              style={{
                fontSize: "12px",
                color: "#6b7280",
                background: "#f3f4f6",
                padding: "6px 12px",
                borderRadius: "6px",
                border: "1px solid #e5e7eb",
              }}
            >
              Run: <strong>{overview.run_id.slice(0, 8)}...</strong>
            </span>
          </div>
        )}
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
          Calculating supervisory indicators and evidence metrics...
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

      {overview && !loading && (
        <>
          {/* Attention Index Hero Section */}
          {(() => {
            const badge = getPriorityBadge(overview.attention_priority);
            return (
              <div
                style={{
                  background: "#ffffff",
                  borderRadius: "8px",
                  padding: "24px",
                  border: `1px solid #e5e7eb`,
                  boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                  marginBottom: "24px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    flexWrap: "wrap",
                    gap: "16px",
                    marginBottom: "16px",
                  }}
                >
                  <div>
                    <h2
                      style={{
                        fontSize: "20px",
                        fontWeight: 700,
                        color: "#111827",
                        margin: "0 0 6px 0",
                      }}
                    >
                      {overview.entity_name} ({overview.entity_code})
                    </h2>
                    <p style={{ margin: 0, fontSize: "13px", color: "#6b7280" }}>
                      Supervisory Assessment Period:{" "}
                      <strong>
                        {overview.period_start} to {overview.period_end}
                      </strong>
                    </p>
                  </div>

                  <div
                    style={{
                      background: badge.bg,
                      color: badge.color,
                      border: `1px solid ${badge.border}`,
                      padding: "6px 14px",
                      borderRadius: "9999px",
                      fontWeight: 700,
                      fontSize: "13px",
                    }}
                  >
                    {badge.label}
                  </div>
                </div>

                {/* Score & Meter */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "auto 1fr",
                    gap: "24px",
                    alignItems: "center",
                    background: "#f9fafb",
                    padding: "16px 20px",
                    borderRadius: "6px",
                    border: "1px solid #e5e7eb",
                  }}
                >
                  <div>
                    <span style={{ fontSize: "11px", fontWeight: 700, color: "#6b7280", textTransform: "uppercase" }}>
                      Supervisory Attention Index
                    </span>
                    <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
                      <span style={{ fontSize: "36px", fontWeight: 800, color: "#111827" }}>
                        {overview.supervisory_attention_index.toFixed(1)}
                      </span>
                      <span style={{ fontSize: "14px", color: "#6b7280", fontWeight: 600 }}>/ 100</span>
                    </div>
                  </div>

                  <div>
                    <div
                      style={{
                        height: "10px",
                        background: "#e5e7eb",
                        borderRadius: "5px",
                        overflow: "hidden",
                        marginBottom: "6px",
                      }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: `${Math.min(100, Math.max(0, overview.supervisory_attention_index))}%`,
                          background:
                            overview.supervisory_attention_index > 65
                              ? "#ef4444"
                              : overview.supervisory_attention_index > 35
                              ? "#f59e0b"
                              : "#10b981",
                          borderRadius: "5px",
                          transition: "width 0.3s ease",
                        }}
                      />
                    </div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: "11px",
                        color: "#9ca3af",
                      }}
                    >
                      <span>0.0 (Routine Monitoring)</span>
                      <span>35.0 (Elevated Threshold)</span>
                      <span>65.0+ (Critical Attention)</span>
                    </div>
                  </div>
                </div>

                {/* Governance and Triage Disclaimer */}
                <div
                  style={{
                    marginTop: "14px",
                    fontSize: "12px",
                    color: "#6b7280",
                    background: "#f8fafc",
                    padding: "10px 14px",
                    borderRadius: "6px",
                    borderLeft: "3px solid #3b82f6",
                  }}
                >
                  <strong>Analytical Boundary:</strong> {overview.disclaimer}
                </div>
              </div>
            );
          })()}

          {/* 4 Core Indicator Cards */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
              gap: "20px",
              marginBottom: "24px",
            }}
          >
            {/* Card 1: Evidence Completeness */}
            <div
              style={{
                background: "#ffffff",
                padding: "20px",
                borderRadius: "8px",
                border: "1px solid #e5e7eb",
                boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <span style={{ fontSize: "12px", fontWeight: 700, color: "#4b5563", textTransform: "uppercase" }}>
                  Evidence Completeness
                </span>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    padding: "3px 8px",
                    borderRadius: "4px",
                    background:
                      overview.evidence_completeness.sufficiency_verdict === "SUFFICIENT"
                        ? "#dcfce7"
                        : overview.evidence_completeness.sufficiency_verdict === "PARTIALLY_SUFFICIENT"
                        ? "#fef3c7"
                        : "#fee2e2",
                    color:
                      overview.evidence_completeness.sufficiency_verdict === "SUFFICIENT"
                        ? "#166534"
                        : overview.evidence_completeness.sufficiency_verdict === "PARTIALLY_SUFFICIENT"
                        ? "#92400e"
                        : "#991b1b",
                  }}
                >
                  {overview.evidence_completeness.sufficiency_verdict}
                </span>
              </div>

              <div style={{ fontSize: "28px", fontWeight: 800, color: "#111827", marginBottom: "8px" }}>
                {overview.evidence_completeness.completeness_percentage.toFixed(1)}%
              </div>

              <ul style={{ margin: "0 0 14px 0", paddingLeft: "18px", fontSize: "13px", color: "#4b5563" }}>
                <li>
                  Sources Received: <strong>{overview.evidence_completeness.received_sources_count}</strong> of{" "}
                  <strong>{overview.evidence_completeness.declared_sources_count}</strong> declared
                </li>
                <li>
                  Quarantined Records: <strong>{overview.evidence_completeness.quarantined_records_count}</strong>
                </li>
                <li>
                  Total Parsed Records: <strong>{overview.evidence_completeness.total_parsed_records}</strong>
                </li>
              </ul>

              <button
                onClick={() => onNavigateToView && onNavigateToView("intake")}
                style={{
                  width: "100%",
                  padding: "8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "#4f46e5",
                  background: "#eef2ff",
                  border: "1px solid #c7d2fe",
                  borderRadius: "6px",
                  cursor: "pointer",
                }}
              >
                Inspect Intake & Files &rarr;
              </button>
            </div>

            {/* Card 2: Execution Gaps */}
            <div
              style={{
                background: "#ffffff",
                padding: "20px",
                borderRadius: "8px",
                border: "1px solid #e5e7eb",
                boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <span style={{ fontSize: "12px", fontWeight: 700, color: "#4b5563", textTransform: "uppercase" }}>
                  Execution Gaps
                </span>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    padding: "3px 8px",
                    borderRadius: "4px",
                    background: overview.execution_gaps.adverse_findings_count > 0 ? "#fee2e2" : "#dcfce7",
                    color: overview.execution_gaps.adverse_findings_count > 0 ? "#991b1b" : "#166534",
                  }}
                >
                  {overview.execution_gaps.adverse_findings_count} Adverse Findings
                </span>
              </div>

              <div style={{ fontSize: "28px", fontWeight: 800, color: "#111827", marginBottom: "8px" }}>
                {overview.execution_gaps.gap_score.toFixed(1)} <span style={{ fontSize: "13px", fontWeight: 500, color: "#6b7280" }}>/ 100 Gap Score</span>
              </div>

              <ul style={{ margin: "0 0 14px 0", paddingLeft: "18px", fontSize: "13px", color: "#4b5563" }}>
                <li>
                  Unsubstantiated Closures: <strong>{overview.execution_gaps.unsubstantiated_closures}</strong>
                </li>
                <li>
                  Overdue Escalations: <strong>{overview.execution_gaps.overdue_escalations}</strong>
                </li>
                <li>
                  Unlinked Lifecycle Cases: <strong>{overview.execution_gaps.unlinked_lifecycle_cases}</strong>
                </li>
              </ul>

              <button
                onClick={() => onNavigateToView && onNavigateToView("findings")}
                style={{
                  width: "100%",
                  padding: "8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "#4f46e5",
                  background: "#eef2ff",
                  border: "1px solid #c7d2fe",
                  borderRadius: "6px",
                  cursor: "pointer",
                }}
              >
                Inspect Findings & Evidence &rarr;
              </button>
            </div>

            {/* Card 3: Negative Space */}
            <div
              style={{
                background: "#ffffff",
                padding: "20px",
                borderRadius: "8px",
                border: "1px solid #e5e7eb",
                boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <span style={{ fontSize: "12px", fontWeight: 700, color: "#4b5563", textTransform: "uppercase" }}>
                  Negative Space
                </span>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    padding: "3px 8px",
                    borderRadius: "4px",
                    background: overview.negative_space.blind_spot_warning ? "#fee2e2" : "#dcfce7",
                    color: overview.negative_space.blind_spot_warning ? "#991b1b" : "#166534",
                  }}
                >
                  {overview.negative_space.blind_spot_warning ? "Blind Spot Warning" : "Coverage Verified"}
                </span>
              </div>

              <div style={{ fontSize: "28px", fontWeight: 800, color: "#111827", marginBottom: "8px" }}>
                {overview.negative_space.coverage_percentage.toFixed(1)}% <span style={{ fontSize: "13px", fontWeight: 500, color: "#6b7280" }}>Monitored</span>
              </div>

              <ul style={{ margin: "0 0 14px 0", paddingLeft: "18px", fontSize: "13px", color: "#4b5563" }}>
                <li>
                  Total Critical Assets: <strong>{overview.negative_space.total_critical_assets}</strong>
                </li>
                <li>
                  Healthy Quiet Assets: <strong>{overview.negative_space.healthy_quiet_assets}</strong>
                </li>
                <li>
                  Broken Sensor / Silence: <strong>{overview.negative_space.broken_sensor_assets}</strong>
                </li>
              </ul>

              <button
                onClick={() => onNavigateToView && onNavigateToView("comparison")}
                style={{
                  width: "100%",
                  padding: "8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "#4f46e5",
                  background: "#eef2ff",
                  border: "1px solid #c7d2fe",
                  borderRadius: "6px",
                  cursor: "pointer",
                }}
              >
                Inspect Telemetry Patterns &rarr;
              </button>
            </div>

            {/* Card 4: Contradicted Claims & Examiner Activity */}
            <div
              style={{
                background: "#ffffff",
                padding: "20px",
                borderRadius: "8px",
                border: "1px solid #e5e7eb",
                boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <span style={{ fontSize: "12px", fontWeight: 700, color: "#4b5563", textTransform: "uppercase" }}>
                  Claims & Review Workload
                </span>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    padding: "3px 8px",
                    borderRadius: "4px",
                    background: overview.contradicted_claims.mathematically_contradicted_claims > 0 ? "#fee2e2" : "#f3f4f6",
                    color: overview.contradicted_claims.mathematically_contradicted_claims > 0 ? "#991b1b" : "#4b5563",
                  }}
                >
                  {overview.contradicted_claims.mathematically_contradicted_claims} Contradicted
                </span>
              </div>

              <div style={{ fontSize: "28px", fontWeight: 800, color: "#111827", marginBottom: "8px" }}>
                {overview.active_portfolio_items_count} <span style={{ fontSize: "13px", fontWeight: 500, color: "#6b7280" }}>Portfolio Items</span>
              </div>

              <ul style={{ margin: "0 0 14px 0", paddingLeft: "18px", fontSize: "13px", color: "#4b5563" }}>
                <li>
                  Open Evidence Requests: <strong>{overview.open_evidence_requests_count}</strong>
                </li>
                <li>
                  Recorded Human Decisions: <strong>{overview.human_decisions_count}</strong>
                </li>
                <li>
                  Reconciled Claims: <strong>{overview.contradicted_claims.supported_claims}</strong> Supported
                </li>
              </ul>

              <button
                onClick={() => onNavigateToView && onNavigateToView("review")}
                style={{
                  width: "100%",
                  padding: "8px",
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "#4f46e5",
                  background: "#eef2ff",
                  border: "1px solid #c7d2fe",
                  borderRadius: "6px",
                  cursor: "pointer",
                }}
              >
                Open Examiner Workspace &rarr;
              </button>
            </div>
          </div>

          {/* Capability Coverage Dimension Matrix */}
          <div
            style={{
              background: "#ffffff",
              borderRadius: "8px",
              padding: "24px",
              border: "1px solid #e5e7eb",
              boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
            }}
          >
            <div style={{ marginBottom: "16px" }}>
              <h3 style={{ fontSize: "16px", fontWeight: 700, color: "#111827", margin: "0 0 4px 0" }}>
                Security Operations Capability Coverage Matrix
              </h3>
              <p style={{ margin: 0, fontSize: "13px", color: "#6b7280" }}>
                Traceable mapping across 8 operational dimensions backed by verified evidence records and explicit rule definitions.
              </p>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb" }}>
                    <th style={{ padding: "10px 14px", textAlign: "left", fontWeight: 700, color: "#4b5563" }}>Dimension</th>
                    <th style={{ padding: "10px 14px", textAlign: "left", fontWeight: 700, color: "#4b5563" }}>Evidence Status</th>
                    <th style={{ padding: "10px 14px", textAlign: "center", fontWeight: 700, color: "#4b5563" }}>Confidence</th>
                    <th style={{ padding: "10px 14px", textAlign: "left", fontWeight: 700, color: "#4b5563" }}>Governing Rule</th>
                    <th style={{ padding: "10px 14px", textAlign: "left", fontWeight: 700, color: "#4b5563" }}>Evidence Basis</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.capabilities.map((cap) => {
                    const pill = getStatusPill(cap.status);
                    return (
                      <tr key={cap.code} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "12px 14px", fontWeight: 600, color: "#111827" }}>
                          <div>{cap.name}</div>
                          <span style={{ fontSize: "11px", color: "#9ca3af" }}>{cap.code}</span>
                        </td>
                        <td style={{ padding: "12px 14px" }}>
                          <span
                            style={{
                              background: pill.bg,
                              color: pill.color,
                              padding: "4px 10px",
                              borderRadius: "4px",
                              fontSize: "12px",
                              fontWeight: 600,
                            }}
                          >
                            {pill.text}
                          </span>
                        </td>
                        <td style={{ padding: "12px 14px", textAlign: "center", color: "#374151", fontWeight: 600 }}>
                          {(cap.confidence * 100).toFixed(0)}%
                        </td>
                        <td style={{ padding: "12px 14px", color: "#6b7280" }}>
                          {cap.primary_rule || <span style={{ color: "#9ca3af" }}>—</span>}
                        </td>
                        <td style={{ padding: "12px 14px", color: "#4b5563", maxWidth: "380px" }}>
                          {cap.evidence_basis}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
