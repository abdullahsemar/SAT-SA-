import React, { useCallback, useEffect, useState } from "react";
import { AnalysisRun, apiClient, Finding } from "../../api/client";
import { FindingDetail } from "./FindingDetail";

interface FindingsPageProps {
  initialSubmissionId?: string | null;
}

export const FindingsPage: React.FC<FindingsPageProps> = ({ initialSubmissionId }) => {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [selectedSubmissionId, setSelectedSubmissionId] = useState<string>(initialSubmissionId || "");
  const [selectedState, setSelectedState] = useState<string>("all");
  const [selectedRule, setSelectedRule] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const [runningAnalysis, setRunningAnalysis] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [runsData, findingsData] = await Promise.all([
        apiClient.listAnalysisRuns(selectedSubmissionId || undefined),
        apiClient.listFindings({
          submission_id: selectedSubmissionId || undefined,
          rule_id: selectedRule !== "all" ? selectedRule : undefined,
          evidence_state: selectedState !== "all" ? selectedState : undefined,
        }),
      ]);
      setRuns(runsData);
      setFindings(findingsData);
    } catch (err: any) {
      setError(err.message || "Failed to load findings data");
    } finally {
      setLoading(false);
    }
  }, [selectedSubmissionId, selectedRule, selectedState]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRunAssessment = async () => {
    if (!selectedSubmissionId.trim()) {
      setError("Please provide a Committed Submission ID to analyze.");
      return;
    }
    setRunningAnalysis(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const run = await apiClient.createAnalysisRun(selectedSubmissionId.trim());
      setSuccessMsg(`Analysis run created successfully: ${run.run_id} (${run.findings_count} findings generated)`);
      await loadData();
    } catch (err: any) {
      setError(err.message || "Failed to trigger analysis run");
    } finally {
      setRunningAnalysis(false);
    }
  };

  if (selectedFinding) {
    return (
      <FindingDetail
        finding={selectedFinding}
        onBack={() => {
          setSelectedFinding(null);
          loadData();
        }}
      />
    );
  }

  // Summary counts
  const totalFindings = findings.length;
  const concernsCount = findings.filter((f) => f.evidence_state === "potential_concern").length;
  const contradictoryCount = findings.filter((f) => f.evidence_state === "contradictory").length;
  const insufficientCount = findings.filter((f) => f.evidence_state === "insufficient_evidence").length;

  const getStateBadgeStyle = (state: string) => {
    switch (state.toLowerCase()) {
      case "supported":
        return { bg: "#ecfdf5", color: "#065f46" };
      case "potential_concern":
        return { bg: "#fffbeb", color: "#92400e" };
      case "contradictory":
        return { bg: "#fef2f2", color: "#991b1b" };
      case "insufficient_evidence":
        return { bg: "#f5f3ff", color: "#5b21b6" };
      default:
        return { bg: "#f3f4f6", color: "#374151" };
    }
  };

  return (
    <div style={{ padding: "24px", maxWidth: "1200px", margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h1 style={{ fontSize: "24px", fontWeight: 700, margin: "0 0 6px 0", color: "#111827" }}>
            Supervisory Findings & Evidence Analytics
          </h1>
          <p style={{ margin: 0, color: "#6b7280", fontSize: "14px" }}>
            Offline supervisory assessment against frozen CSE submissions, SLAs, and policy obligations.
          </p>
        </div>
      </div>

      {error && (
        <div style={{ padding: "12px 16px", background: "#fee2e2", color: "#991b1b", borderRadius: "6px", marginBottom: "20px", fontSize: "14px" }}>
          {error}
        </div>
      )}

      {successMsg && (
        <div style={{ padding: "12px 16px", background: "#ecfdf5", color: "#065f46", borderRadius: "6px", marginBottom: "20px", fontSize: "14px" }}>
          {successMsg}
        </div>
      )}

      {/* Analysis Run Trigger Section */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "8px",
          border: "1px solid #e5e7eb",
          padding: "20px",
          marginBottom: "24px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}
      >
        <h3 style={{ fontSize: "15px", fontWeight: 600, margin: "0 0 12px 0", color: "#374151" }}>
          Trigger Supervisory Assessment
        </h3>
        <div style={{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
          <input
            type="text"
            placeholder="Committed Submission ID (e.g. SUB-COMMITTED-01)"
            value={selectedSubmissionId}
            onChange={(e) => setSelectedSubmissionId(e.target.value)}
            style={{
              padding: "8px 12px",
              border: "1px solid #d1d5db",
              borderRadius: "6px",
              fontSize: "14px",
              flex: "1",
              minWidth: "280px",
            }}
          />
          <button
            onClick={handleRunAssessment}
            disabled={runningAnalysis || !selectedSubmissionId}
            style={{
              background: "#4f46e5",
              color: "#ffffff",
              border: "none",
              borderRadius: "6px",
              padding: "9px 18px",
              fontSize: "14px",
              fontWeight: 600,
              cursor: runningAnalysis ? "not-allowed" : "pointer",
              opacity: runningAnalysis || !selectedSubmissionId ? 0.7 : 1,
            }}
          >
            {runningAnalysis ? "Analyzing Submission..." : "Run Assessment"}
          </button>
        </div>
      </div>

      {/* Metric Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "24px" }}>
        <div style={{ background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: "8px", padding: "16px" }}>
          <div style={{ fontSize: "13px", fontWeight: 500, color: "#6b7280" }}>Total Generated Findings</div>
          <div style={{ fontSize: "28px", fontWeight: 700, color: "#111827", marginTop: "4px" }}>{totalFindings}</div>
        </div>
        <div style={{ background: "#ffffff", border: "1px solid #fde68a", borderRadius: "8px", padding: "16px" }}>
          <div style={{ fontSize: "13px", fontWeight: 500, color: "#92400e" }}>Potential Concerns</div>
          <div style={{ fontSize: "28px", fontWeight: 700, color: "#b45309", marginTop: "4px" }}>{concernsCount}</div>
        </div>
        <div style={{ background: "#ffffff", border: "1px solid #fecaca", borderRadius: "8px", padding: "16px" }}>
          <div style={{ fontSize: "13px", fontWeight: 500, color: "#991b1b" }}>Contradictory Outcomes</div>
          <div style={{ fontSize: "28px", fontWeight: 700, color: "#dc2626", marginTop: "4px" }}>{contradictoryCount}</div>
        </div>
        <div style={{ background: "#ffffff", border: "1px solid #ddd6fe", borderRadius: "8px", padding: "16px" }}>
          <div style={{ fontSize: "13px", fontWeight: 500, color: "#5b21b6" }}>Insufficient Evidence</div>
          <div style={{ fontSize: "28px", fontWeight: 700, color: "#7c3aed", marginTop: "4px" }}>{insufficientCount}</div>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: "12px", alignItems: "center", marginBottom: "16px", flexWrap: "wrap" }}>
        <div>
          <label style={{ fontSize: "12px", fontWeight: 600, color: "#4b5563", display: "block", marginBottom: "4px" }}>
            Evidence State
          </label>
          <select
            value={selectedState}
            onChange={(e) => setSelectedState(e.target.value)}
            style={{ padding: "6px 12px", borderRadius: "6px", border: "1px solid #d1d5db", fontSize: "13px" }}
          >
            <option value="all">All States</option>
            <option value="potential_concern">Potential Concern</option>
            <option value="contradictory">Contradictory</option>
            <option value="insufficient_evidence">Insufficient Evidence</option>
            <option value="supported">Supported</option>
          </select>
        </div>

        <div>
          <label style={{ fontSize: "12px", fontWeight: 600, color: "#4b5563", display: "block", marginBottom: "4px" }}>
            Rule Family
          </label>
          <select
            value={selectedRule}
            onChange={(e) => setSelectedRule(e.target.value)}
            style={{ padding: "6px 12px", borderRadius: "6px", border: "1px solid #d1d5db", fontSize: "13px" }}
          >
            <option value="all">All Rule Families</option>
            <option value="POL-INV-001">POL-INV-001: Investigation Rigor</option>
            <option value="POL-ESC-002">POL-ESC-002: Escalation Timeliness</option>
            <option value="POL-COV-003">POL-COV-003: Monitoring Coverage</option>
            <option value="POL-KPI-004">POL-KPI-004: KPI Reconciliation</option>
            <option value="POL-REC-005">POL-REC-005: Recurrence Context</option>
          </select>
        </div>
      </div>

      {/* Findings Table */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "8px",
          border: "1px solid #e5e7eb",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          overflow: "hidden",
        }}
      >
        {loading ? (
          <div style={{ padding: "32px", textAlign: "center", color: "#6b7280" }}>Loading findings...</div>
        ) : findings.length === 0 ? (
          <div style={{ padding: "32px", textAlign: "center", color: "#6b7280" }}>
            No supervisory findings match the current filter criteria.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb", textAlign: "left" }}>
                <th style={{ padding: "12px 16px", color: "#4b5563" }}>Rule</th>
                <th style={{ padding: "12px 16px", color: "#4b5563" }}>Title</th>
                <th style={{ padding: "12px 16px", color: "#4b5563" }}>Severity</th>
                <th style={{ padding: "12px 16px", color: "#4b5563" }}>Evidence State</th>
                <th style={{ padding: "12px 16px", color: "#4b5563" }}>Scope</th>
                <th style={{ padding: "12px 16px", color: "#4b5563" }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((finding) => {
                const badgeStyle = getStateBadgeStyle(finding.evidence_state);
                return (
                  <tr
                    key={finding.finding_id}
                    style={{ borderBottom: "1px solid #f3f4f6", cursor: "pointer" }}
                    onClick={() => setSelectedFinding(finding)}
                  >
                    <td style={{ padding: "12px 16px", fontWeight: 700, color: "#4f46e5" }}>{finding.rule_id}</td>
                    <td style={{ padding: "12px 16px", fontWeight: 600, color: "#111827" }}>{finding.rule_title}</td>
                    <td style={{ padding: "12px 16px" }}>
                      <span
                        style={{
                          fontSize: "11px",
                          fontWeight: 600,
                          textTransform: "uppercase",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          background: finding.severity === "critical" ? "#fee2e2" : finding.severity === "high" ? "#ffedd5" : "#fef9c3",
                          color: finding.severity === "critical" ? "#991b1b" : finding.severity === "high" ? "#9a3412" : "#854d0e",
                        }}
                      >
                        {finding.severity}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span
                        style={{
                          fontSize: "12px",
                          fontWeight: 600,
                          padding: "3px 8px",
                          borderRadius: "9999px",
                          background: badgeStyle.bg,
                          color: badgeStyle.color,
                        }}
                      >
                        {finding.evidence_state}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <code>{finding.primary_object_type}:{finding.primary_object_id}</code>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedFinding(finding);
                        }}
                        style={{
                          background: "#f3f4f6",
                          border: "1px solid #d1d5db",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "12px",
                          fontWeight: 500,
                          cursor: "pointer",
                        }}
                      >
                        Inspect &rarr;
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Completed Analysis Runs list */}
      <div style={{ marginTop: "32px" }}>
        <h3 style={{ fontSize: "16px", fontWeight: 700, margin: "0 0 12px 0", color: "#111827" }}>
          Recent Analysis Runs ({runs.length})
        </h3>
        {runs.length === 0 ? (
          <p style={{ color: "#6b7280", fontSize: "14px" }}>No analysis runs recorded yet.</p>
        ) : (
          <div style={{ background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: "8px", overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb", textAlign: "left" }}>
                  <th style={{ padding: "10px 14px", color: "#4b5563" }}>Run ID</th>
                  <th style={{ padding: "10px 14px", color: "#4b5563" }}>Submission</th>
                  <th style={{ padding: "10px 14px", color: "#4b5563" }}>Status</th>
                  <th style={{ padding: "10px 14px", color: "#4b5563" }}>Findings</th>
                  <th style={{ padding: "10px 14px", color: "#4b5563" }}>Input SHA-256</th>
                  <th style={{ padding: "10px 14px", color: "#4b5563" }}>Created At</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "10px 14px", fontWeight: 600 }}>{r.run_id.slice(0, 8)}...</td>
                    <td style={{ padding: "10px 14px" }}><code>{r.submission_id}</code></td>
                    <td style={{ padding: "10px 14px" }}>
                      <span
                        style={{
                          padding: "2px 6px",
                          borderRadius: "4px",
                          fontSize: "11px",
                          fontWeight: 600,
                          background: r.status === "completed" ? "#ecfdf5" : "#fee2e2",
                          color: r.status === "completed" ? "#065f46" : "#991b1b",
                        }}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td style={{ padding: "10px 14px", fontWeight: 600 }}>{r.findings_count}</td>
                    <td style={{ padding: "10px 14px" }}>
                      <code style={{ fontSize: "11px" }}>{r.input_hash ? `${r.input_hash.slice(0, 12)}...` : "—"}</code>
                    </td>
                    <td style={{ padding: "10px 14px", color: "#6b7280" }}>{new Date(r.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
