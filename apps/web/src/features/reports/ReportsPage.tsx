import React, { useCallback, useEffect, useState } from "react";
import { apiClient, ReportResponse } from "../../api/client";

interface ReportsPageProps {
  entityId?: string;
  runId?: string;
  onSelectRun?: (runId: string) => void;
}

export const ReportsPage: React.FC<ReportsPageProps> = ({ entityId = "CSE-BANK-01", runId }) => {
  const [reports, setReports] = useState<ReportResponse[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [targetRunId, setTargetRunId] = useState<string>(runId || "");
  const [portfolioId, setPortfolioId] = useState<string>("");
  const [decisionCutoff, setDecisionCutoff] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Preview state
  const [previewReportId, setPreviewReportId] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiClient.listReports({ entity_id: entityId });
      setReports(resp.reports);
    } catch (err: any) {
      setError(err.message || "Failed to load reports");
    } finally {
      setLoading(false);
    }
  }, [entityId]);

  useEffect(() => {
    loadReports();
    if (runId) {
      setTargetRunId(runId);
    }
  }, [loadReports, runId]);

  const handleCreateReport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetRunId.trim()) {
      setCreateError("Run ID is required");
      return;
    }

    setIsGenerating(true);
    setCreateError(null);
    try {
      await apiClient.createReport({
        run_id: targetRunId.trim(),
        portfolio_id: portfolioId.trim() || undefined,
        decision_cutoff_time: decisionCutoff ? new Date(decisionCutoff).toISOString() : undefined,
        notes: notes.trim() || undefined,
      });
      setShowCreateModal(false);
      setNotes("");
      setPortfolioId("");
      await loadReports();
    } catch (err: any) {
      setCreateError(err.message || "Failed to generate report");
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div style={{ padding: "24px", maxWidth: "1200px", margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <div>
          <h1 style={{ fontSize: "22px", fontWeight: 700, margin: 0, color: "#0f172a" }}>
            Supervisory Assessment Reports
          </h1>
          <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: "#64748b" }}>
            Entity: <strong>{entityId}</strong> | Frozen snapshots with evidence provenance, decisions, and checksum manifests
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          style={{
            background: "#2563eb",
            color: "#ffffff",
            border: "none",
            borderRadius: "6px",
            padding: "8px 16px",
            fontSize: "13px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          + Generate New Report
        </button>
      </div>

      {/* Supervisory Notice */}
      <div
        style={{
          background: "#f0fdf4",
          borderLeft: "4px solid #16a34a",
          padding: "12px 16px",
          marginBottom: "24px",
          borderRadius: "0 6px 6px 0",
          fontSize: "12px",
          color: "#166534",
        }}
      >
        <strong>SUPERVISORY ARCHIVAL INVARIANT:</strong> Each generated report is an immutable snapshot tied to a frozen decision cutoff time.
        Subsequent supervisory decisions or new submission revisions will not mutate existing generated reports.
      </div>

      {error && (
        <div style={{ background: "#fee2e2", color: "#991b1b", padding: "12px", borderRadius: "6px", marginBottom: "16px", fontSize: "13px" }}>
          {error}
        </div>
      )}

      {/* Reports Table */}
      {loading ? (
        <div style={{ padding: "40px", textAlign: "center", color: "#64748b" }}>Loading reports...</div>
      ) : reports.length === 0 ? (
        <div
          style={{
            padding: "48px",
            textAlign: "center",
            background: "#ffffff",
            border: "1px dashed #cbd5e1",
            borderRadius: "8px",
            color: "#64748b",
          }}
        >
          <p style={{ fontSize: "15px", fontWeight: 600, marginBottom: "8px" }}>No reports generated yet</p>
          <p style={{ fontSize: "13px", marginBottom: "16px" }}>
            Generate a frozen assessment report to export a printable HTML document, machine-readable snapshot, and cryptographic checksum manifest.
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            style={{
              background: "#1e293b",
              color: "#ffffff",
              border: "none",
              borderRadius: "6px",
              padding: "8px 16px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Generate Report
          </button>
        </div>
      ) : (
        <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "8px", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0", textAlign: "left" }}>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569" }}>Report ID</th>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569" }}>Run / Portfolio</th>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569" }}>Decision Cutoff</th>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569" }}>Created At</th>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569" }}>Status</th>
                <th style={{ padding: "12px 16px", fontWeight: 600, color: "#475569", textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "12px 16px", fontFamily: "monospace" }}>
                    <strong>{r.id.slice(0, 8)}</strong>
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <div>Run: <code style={{ fontSize: "11px" }}>{r.run_id.slice(0, 8)}</code></div>
                    {r.portfolio_id && (
                      <div style={{ fontSize: "11px", color: "#64748b" }}>
                        Portfolio: <code>{r.portfolio_id.slice(0, 8)}</code>
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "12px 16px", fontSize: "12px", color: "#475569" }}>
                    {new Date(r.decision_cutoff_time).toLocaleString()}
                  </td>
                  <td style={{ padding: "12px 16px", fontSize: "12px", color: "#475569" }}>
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <span
                      style={{
                        padding: "3px 8px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: 600,
                        background: r.status === "completed" ? "#dcfce7" : "#fee2e2",
                        color: r.status === "completed" ? "#166534" : "#991b1b",
                      }}
                    >
                      {r.status.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px", textAlign: "right" }}>
                    <div style={{ display: "flex", gap: "6px", justifyContent: "flex-end" }}>
                      <button
                        onClick={() => setPreviewReportId(r.id)}
                        style={{
                          background: "#f1f5f9",
                          border: "1px solid #cbd5e1",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "11px",
                          cursor: "pointer",
                          fontWeight: 500,
                        }}
                      >
                        Preview
                      </button>
                      <a
                        href={apiClient.getReportHtmlUrl(r.id)}
                        target="_blank"
                        rel="noreferrer"
                        download
                        style={{
                          background: "#e0e7ff",
                          color: "#3730a3",
                          border: "1px solid #c7d2fe",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "11px",
                          textDecoration: "none",
                          fontWeight: 600,
                        }}
                      >
                        HTML
                      </a>
                      <a
                        href={apiClient.getReportJsonUrl(r.id)}
                        download
                        style={{
                          background: "#fef3c7",
                          color: "#92400e",
                          border: "1px solid #fde68a",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "11px",
                          textDecoration: "none",
                          fontWeight: 600,
                        }}
                      >
                        JSON
                      </a>
                      <a
                        href={apiClient.getReportManifestUrl(r.id)}
                        download
                        style={{
                          background: "#f3e8ff",
                          color: "#6b21a8",
                          border: "1px solid #e9d5ff",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "11px",
                          textDecoration: "none",
                          fontWeight: 600,
                        }}
                      >
                        Manifest
                      </a>
                      <a
                        href={apiClient.getReportBundleUrl(r.id)}
                        download
                        style={{
                          background: "#1e293b",
                          color: "#ffffff",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "11px",
                          textDecoration: "none",
                          fontWeight: 600,
                        }}
                      >
                        Bundle (.zip)
                      </a>
                      <a
                        href={apiClient.getReportProofUrl(r.id)}
                        download
                        style={{
                          background: "#047857",
                          color: "#ffffff",
                          borderRadius: "4px",
                          padding: "4px 8px",
                          fontSize: "11px",
                          textDecoration: "none",
                          fontWeight: 600,
                        }}
                        title="Cryptographic Proof Sidecar (standalone verifiable)"
                      >
                        Proof Sidecar
                      </a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Report Modal */}
      {showCreateModal && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div
            style={{
              background: "#ffffff",
              borderRadius: "8px",
              padding: "24px",
              width: "100%",
              maxWidth: "500px",
              boxShadow: "0 10px 25px rgba(0,0,0,0.1)",
            }}
          >
            <h2 style={{ fontSize: "18px", fontWeight: 700, margin: "0 0 16px 0" }}>
              Generate Assessment Report
            </h2>

            {createError && (
              <div style={{ background: "#fee2e2", color: "#991b1b", padding: "8px 12px", borderRadius: "4px", marginBottom: "14px", fontSize: "12px" }}>
                {createError}
              </div>
            )}

            <form onSubmit={handleCreateReport}>
              <div style={{ marginBottom: "14px" }}>
                <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: "4px", color: "#334155" }}>
                  Analysis Run ID *
                </label>
                <input
                  type="text"
                  value={targetRunId}
                  onChange={(e) => setTargetRunId(e.target.value)}
                  placeholder="e.g. 1a2b3c4d-..."
                  required
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>

              <div style={{ marginBottom: "14px" }}>
                <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: "4px", color: "#334155" }}>
                  Review Portfolio ID (Optional)
                </label>
                <input
                  type="text"
                  value={portfolioId}
                  onChange={(e) => setPortfolioId(e.target.value)}
                  placeholder="Leave empty to use latest portfolio for run"
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>

              <div style={{ marginBottom: "14px" }}>
                <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: "4px", color: "#334155" }}>
                  Decision Cutoff Time (Optional)
                </label>
                <input
                  type="datetime-local"
                  value={decisionCutoff}
                  onChange={(e) => setDecisionCutoff(e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
                <span style={{ fontSize: "11px", color: "#64748b" }}>
                  Decisions recorded after this timestamp will be excluded. Defaults to current time.
                </span>
              </div>

              <div style={{ marginBottom: "20px" }}>
                <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: "4px", color: "#334155" }}>
                  Notes / Scope Remarks (Optional)
                </label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                  placeholder="e.g. Q3 annual examination assessment export"
                  style={{ width: "100%", padding: "8px 10px", borderRadius: "4px", border: "1px solid #cbd5e1", fontSize: "13px" }}
                />
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  disabled={isGenerating}
                  style={{
                    background: "#f1f5f9",
                    border: "1px solid #cbd5e1",
                    borderRadius: "6px",
                    padding: "8px 14px",
                    fontSize: "13px",
                    cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isGenerating}
                  style={{
                    background: "#2563eb",
                    color: "#ffffff",
                    border: "none",
                    borderRadius: "6px",
                    padding: "8px 16px",
                    fontSize: "13px",
                    fontWeight: 600,
                    cursor: isGenerating ? "not-allowed" : "pointer",
                    opacity: isGenerating ? 0.7 : 1,
                  }}
                >
                  {isGenerating ? "Generating Snapshot..." : "Generate Snapshot & Report"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Preview Modal / Drawer */}
      {previewReportId && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.6)",
            display: "flex",
            flexDirection: "column",
            zIndex: 1100,
          }}
        >
          <div
            style={{
              background: "#1e293b",
              color: "#ffffff",
              padding: "12px 20px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <span style={{ fontWeight: 600, fontSize: "14px" }}>Report Preview: {previewReportId.slice(0, 8)}</span>
              <a
                href={apiClient.getReportHtmlUrl(previewReportId)}
                target="_blank"
                rel="noreferrer"
                style={{ color: "#93c5fd", fontSize: "12px", textDecoration: "underline" }}
              >
                Open in new tab
              </a>
            </div>
            <button
              onClick={() => setPreviewReportId(null)}
              style={{
                background: "transparent",
                border: "1px solid #475569",
                color: "#ffffff",
                borderRadius: "4px",
                padding: "4px 10px",
                cursor: "pointer",
                fontSize: "12px",
              }}
            >
              Close
            </button>
          </div>
          <iframe
            src={apiClient.getReportHtmlUrl(previewReportId)}
            title="Assessment Report Preview"
            style={{ flex: 1, border: "none", background: "#ffffff" }}
          />
        </div>
      )}
    </div>
  );
};
