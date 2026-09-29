import React, { useEffect, useState } from "react";
import { apiClient, EvidenceChain, Finding } from "../../api/client";
import { SimilarPassages } from "./SimilarPassages";

interface FindingDetailProps {
  finding: Finding;
  onBack: () => void;
}

export const FindingDetail: React.FC<FindingDetailProps> = ({ finding, onBack }) => {
  const [chain, setChain] = useState<EvidenceChain | null>(null);
  const [loadingChain, setLoadingChain] = useState(false);
  const [chainError, setChainError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    async function loadChain() {
      if (!finding.primary_object_id || !finding.submission_id) return;
      setLoadingChain(true);
      setChainError(null);
      try {
        const data = await apiClient.getEvidenceChain(finding.primary_object_id, finding.submission_id);
        if (isMounted) setChain(data);
      } catch (err: any) {
        if (isMounted) setChainError(err.message || "Failed to reconstruct evidence chain");
      } finally {
        if (isMounted) setLoadingChain(false);
      }
    }
    loadChain();
    return () => {
      isMounted = false;
    };
  }, [finding]);

  const getStateBadgeStyle = (state: string) => {
    switch (state.toLowerCase()) {
      case "supported":
        return { bg: "#ecfdf5", color: "#065f46", border: "#a7f3d0", label: "Supported" };
      case "potential_concern":
        return { bg: "#fffbeb", color: "#92400e", border: "#fde68a", label: "Potential Concern" };
      case "contradictory":
        return { bg: "#fef2f2", color: "#991b1b", border: "#fecaca", label: "Contradictory" };
      case "insufficient_evidence":
        return { bg: "#f5f3ff", color: "#5b21b6", border: "#ddd6fe", label: "Insufficient Evidence" };
      default:
        return { bg: "#f3f4f6", color: "#374151", border: "#e5e7eb", label: state };
    }
  };

  const badge = getStateBadgeStyle(finding.evidence_state);

  return (
    <div style={{ padding: "24px", maxWidth: "1200px", margin: "0 auto" }}>
      <button
        onClick={onBack}
        style={{
          background: "transparent",
          border: "1px solid #d1d5db",
          borderRadius: "6px",
          padding: "8px 16px",
          cursor: "pointer",
          marginBottom: "16px",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          fontWeight: 500,
        }}
      >
        &larr; Back to Findings
      </button>

      {/* Header card */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "8px",
          border: "1px solid #e5e7eb",
          padding: "24px",
          marginBottom: "24px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
              <span style={{ fontSize: "14px", fontWeight: 700, color: "#4f46e5", letterSpacing: "0.5px" }}>
                {finding.rule_id}
              </span>
              <span
                style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  padding: "3px 8px",
                  borderRadius: "4px",
                  background: finding.severity === "critical" ? "#fee2e2" : finding.severity === "high" ? "#ffedd5" : "#fef9c3",
                  color: finding.severity === "critical" ? "#991b1b" : finding.severity === "high" ? "#9a3412" : "#854d0e",
                }}
              >
                {finding.severity}
              </span>
              <span
                style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  padding: "3px 10px",
                  borderRadius: "9999px",
                  background: badge.bg,
                  color: badge.color,
                  border: `1px solid ${badge.border}`,
                }}
              >
                {badge.label}
              </span>
            </div>
            <h1 style={{ fontSize: "20px", fontWeight: 700, margin: "0 0 8px 0", color: "#111827" }}>
              {finding.rule_title}
            </h1>
            <p style={{ margin: 0, color: "#6b7280", fontSize: "14px" }}>
              Object Scope: <strong>{finding.primary_object_type}</strong> (<code>{finding.primary_object_id}</code>) &bull; Entity: <strong>{finding.cse_id}</strong>
            </p>
          </div>

          <div style={{ textAlign: "right" }}>
            <span
              style={{
                display: "inline-block",
                padding: "4px 8px",
                borderRadius: "4px",
                background: "#f3f4f6",
                color: "#6b7280",
                fontSize: "12px",
                fontWeight: 500,
              }}
            >
              Peer Comparison: Unavailable
            </span>
          </div>
        </div>

        {/* Rationale */}
        <div style={{ marginTop: "20px", paddingTop: "16px", borderTop: "1px solid #f3f4f6" }}>
          <h3 style={{ fontSize: "15px", fontWeight: 600, color: "#374151", margin: "0 0 8px 0" }}>Supervisory Proposition & Rationale</h3>
          <p style={{ margin: 0, fontSize: "14px", lineHeight: "1.6", color: "#1f2937", background: "#f9fafb", padding: "12px 16px", borderRadius: "6px" }}>
            {finding.rationale}
          </p>
        </div>

        {/* Uncertainty Note */}
        {finding.uncertainty_note && (
          <div
            style={{
              marginTop: "16px",
              padding: "12px 16px",
              borderRadius: "6px",
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              color: "#1e40af",
              fontSize: "13px",
              lineHeight: "1.5",
            }}
          >
            <strong>Uncertainty / Evidence Boundaries:</strong> {finding.uncertainty_note}
          </div>
        )}
      </div>

      {/* Supporting Source Records */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "8px",
          border: "1px solid #e5e7eb",
          padding: "24px",
          marginBottom: "24px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}
      >
        <h2 style={{ fontSize: "16px", fontWeight: 700, margin: "0 0 16px 0", color: "#111827" }}>
          Frozen Supporting Source Records ({finding.supporting_records?.length || 0})
        </h2>
        {(!finding.supporting_records || finding.supporting_records.length === 0) ? (
          <p style={{ color: "#6b7280", fontSize: "14px", margin: 0 }}>No direct source records attached to this finding.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb", textAlign: "left" }}>
                  <th style={{ padding: "10px 12px", color: "#4b5563" }}>Source ID</th>
                  <th style={{ padding: "10px 12px", color: "#4b5563" }}>Record Type</th>
                  <th style={{ padding: "10px 12px", color: "#4b5563" }}>Locator</th>
                  <th style={{ padding: "10px 12px", color: "#4b5563" }}>Native ID</th>
                  <th style={{ padding: "10px 12px", color: "#4b5563" }}>SHA-256 Provenance Hash</th>
                </tr>
              </thead>
              <tbody>
                {finding.supporting_records.map((rec, idx) => (
                  <tr key={idx} style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "10px 12px", fontWeight: 600 }}>{rec.source_id}</td>
                    <td style={{ padding: "10px 12px", color: "#6b7280" }}>{rec.record_type}</td>
                    <td style={{ padding: "10px 12px" }}><code>{rec.locator}</code></td>
                    <td style={{ padding: "10px 12px" }}><strong>{rec.native_id}</strong></td>
                    <td style={{ padding: "10px 12px" }}>
                      <code style={{ fontSize: "11px", background: "#f3f4f6", padding: "2px 6px", borderRadius: "4px" }}>
                        {rec.sha256}
                      </code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Similar Investigation Passages (Evidence Analysis) */}
      <SimilarPassages findingId={finding.finding_id} />

      {/* Interactive Evidence Chain Drill-down */}
      <div
        style={{
          background: "#ffffff",
          borderRadius: "8px",
          border: "1px solid #e5e7eb",
          padding: "24px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <h2 style={{ fontSize: "16px", fontWeight: 700, margin: 0, color: "#111827" }}>
            Evidence Chain & Timeline Drill-Down
          </h2>
          {chain && (
            <span style={{ fontSize: "12px", color: "#6b7280" }}>
              {chain.summary.nodes_count} entities &bull; {chain.summary.edges_count} links &bull; {chain.summary.events_count} timeline events
            </span>
          )}
        </div>

        {loadingChain && <p style={{ color: "#6b7280", fontSize: "14px" }}>Reconstructing evidence chain from frozen submission...</p>}
        {chainError && (
          <div style={{ padding: "12px", background: "#fee2e2", color: "#991b1b", borderRadius: "6px", fontSize: "13px" }}>
            {chainError}
          </div>
        )}

        {chain && (
          <div>
            {/* Omissions / Uncertainties in graph */}
            {(chain.omissions?.length > 0 || chain.uncertainties?.length > 0) && (
              <div style={{ marginBottom: "20px", display: "flex", flexDirection: "column", gap: "8px" }}>
                {chain.omissions.map((om, idx) => (
                  <div key={idx} style={{ padding: "8px 12px", background: "#fef2f2", color: "#b91c1c", borderRadius: "4px", fontSize: "12px" }}>
                    <strong>Evidence Omission:</strong> {om}
                  </div>
                ))}
                {chain.uncertainties.map((unc, idx) => (
                  <div key={idx} style={{ padding: "8px 12px", background: "#fffbeb", color: "#b45309", borderRadius: "4px", fontSize: "12px" }}>
                    <strong>Link Uncertainty:</strong> {unc}
                  </div>
                ))}
              </div>
            )}

            {/* Timeline */}
            <h4 style={{ fontSize: "14px", fontWeight: 600, color: "#374151", margin: "0 0 12px 0" }}>Chronological Event Timeline</h4>
            {chain.timeline.length === 0 ? (
              <p style={{ color: "#6b7280", fontSize: "13px" }}>No chronological timestamped events found for this chain.</p>
            ) : (
              <div style={{ borderLeft: "2px solid #e5e7eb", marginLeft: "12px", paddingLeft: "16px", display: "flex", flexDirection: "column", gap: "16px" }}>
                {chain.timeline.map((ev, idx) => (
                  <div key={idx} style={{ position: "relative" }}>
                    <div
                      style={{
                        position: "absolute",
                        left: "-23px",
                        top: "4px",
                        width: "12px",
                        height: "12px",
                        borderRadius: "50%",
                        background: "#4f46e5",
                        border: "2px solid #ffffff",
                      }}
                    />
                    <div style={{ fontSize: "13px", fontWeight: 600, color: "#111827" }}>{ev.event}</div>
                    <div style={{ fontSize: "12px", color: "#6b7280" }}>
                      {ev.timestamp ? new Date(ev.timestamp).toUTCString() : "Timestamp not recorded"} &bull; Type: <code>{ev.entity_type}</code> ({ev.entity_id})
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Related entities list */}
            <div style={{ marginTop: "24px", paddingTop: "16px", borderTop: "1px solid #f3f4f6" }}>
              <h4 style={{ fontSize: "14px", fontWeight: 600, color: "#374151", margin: "0 0 12px 0" }}>Connected Objects</h4>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                {chain.related_entities.nodes.map((node, idx) => (
                  <div
                    key={idx}
                    style={{
                      border: "1px solid #e5e7eb",
                      borderRadius: "6px",
                      padding: "8px 12px",
                      background: "#f9fafb",
                      fontSize: "12px",
                    }}
                  >
                    <span style={{ fontWeight: 600, color: "#4b5563" }}>[{node.record_type}]</span> {node.label}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
