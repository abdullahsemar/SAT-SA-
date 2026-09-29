import React, { useEffect, useState } from "react";
import { apiClient, CustodyEvent, IntegrityStatusResponse, VerifyResponse } from "../../api/client";

export const EvidenceIntegrityDashboard: React.FC = () => {
  const [status, setStatus] = useState<IntegrityStatusResponse | null>(null);
  const [events, setEvents] = useState<CustodyEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [entityFilter, setEntityFilter] = useState<string>("");
  const [selectedEvent, setSelectedEvent] = useState<CustodyEvent | null>(null);

  // Verification state
  const [verifyType, setVerifyType] = useState<"submission" | "report_snapshot" | "custody_log">("custody_log");
  const [verifyTargetId, setVerifyTargetId] = useState<string>("");
  const [verifyEntityId, setVerifyEntityId] = useState<string>("E-101");
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [verifyResult, setVerifyResult] = useState<VerifyResponse | null>(null);

  // Outbox trigger state
  const [outboxProcessing, setOutboxProcessing] = useState(false);
  const [outboxMsg, setOutboxMsg] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [statusRes, eventsRes] = await Promise.all([
        apiClient.getIntegrityStatus(),
        apiClient.getCustodyLog({ entity_id: entityFilter || undefined, limit: 50 }),
      ]);
      setStatus(statusRes);
      setEvents(eventsRes);
    } catch (err: any) {
      setError(err.message || "Failed to load evidence integrity data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityFilter]);

  const handleProcessOutbox = async () => {
    setOutboxProcessing(true);
    setOutboxMsg(null);
    try {
      const res = await apiClient.triggerOutboxProcess();
      setOutboxMsg(`Processed ${res.processed} outbox entries (${res.errors} errors). Status: ${res.status}`);
      await loadData();
    } catch (err: any) {
      setOutboxMsg(`Outbox processing failed: ${err.message}`);
    } finally {
      setOutboxProcessing(false);
    }
  };

  const handleRunVerification = async () => {
    if (!verifyEntityId) {
      alert("Entity ID is required for verification");
      return;
    }
    setVerifyLoading(true);
    setVerifyResult(null);
    try {
      const res = await apiClient.verifyEvidence({
        target_type: verifyType,
        target_id: verifyTargetId,
        entity_id: verifyEntityId,
      });
      setVerifyResult(res);
    } catch (err: any) {
      alert(`Verification failed: ${err.message}`);
    } finally {
      setVerifyLoading(false);
    }
  };

  const getEventTypeBadge = (type: string) => {
    switch (type) {
      case "submission_committed":
        return { label: "Submission Committed", bg: "#dbeafe", color: "#1e40af" };
      case "evidence_revision_registered":
        return { label: "Evidence Revision", bg: "#fef3c7", color: "#92400e" };
      case "assessment_finalized":
        return { label: "Assessment Finalized", bg: "#e0e7ff", color: "#3730a3" };
      case "human_decision_recorded":
        return { label: "Examiner Decision", bg: "#fce7f3", color: "#9d174d" };
      case "report_snapshot_finalized":
        return { label: "Report Snapshot Finalized", bg: "#dcfce7", color: "#166534" };
      default:
        return { label: type, bg: "#f3f4f6", color: "#374151" };
    }
  };

  return (
    <div style={{ maxWidth: "1280px", margin: "0 auto", padding: "24px 16px" }}>
      {/* Top Header */}
      <div style={{ marginBottom: "24px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "16px" }}>
          <div>
            <h1 style={{ fontSize: "24px", fontWeight: 700, color: "#111827", margin: "0 0 6px 0" }}>
              Evidence Integrity &amp; Verifiable Custody
            </h1>
            <p style={{ margin: 0, color: "#6b7280", fontSize: "14px" }}>
              Cryptographic evidence commitments, Ed25519 signed append-only logs, and permissioned ledger anchors.
            </p>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button
              onClick={loadData}
              disabled={loading}
              style={{
                background: "#f3f4f6",
                border: "1px solid #d1d5db",
                borderRadius: "6px",
                padding: "8px 14px",
                fontSize: "13px",
                fontWeight: 600,
                color: "#374151",
                cursor: "pointer",
              }}
            >
              Refresh
            </button>
            <button
              onClick={handleProcessOutbox}
              disabled={outboxProcessing}
              style={{
                background: "#4f46e5",
                border: "none",
                borderRadius: "6px",
                padding: "8px 14px",
                fontSize: "13px",
                fontWeight: 600,
                color: "#ffffff",
                cursor: "pointer",
              }}
            >
              {outboxProcessing ? "Processing..." : "Flush Outbox"}
            </button>
          </div>
        </div>

        {outboxMsg && (
          <div style={{ marginTop: "12px", padding: "8px 14px", borderRadius: "6px", background: "#f0fdf4", color: "#166534", fontSize: "12px", border: "1px solid #bbf7d0" }}>
            {outboxMsg}
          </div>
        )}
      </div>

      {error && (
        <div style={{ padding: "16px", background: "#fef2f2", borderRadius: "8px", border: "1px solid #fecaca", color: "#991b1b", marginBottom: "20px" }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Trust Basis & Mode Banner */}
      {status && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: "16px",
            marginBottom: "24px",
          }}
        >
          {/* Mode Card */}
          <div style={{ background: "#ffffff", borderRadius: "8px", border: "1px solid #e5e7eb", padding: "18px", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
            <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", color: "#6b7280", marginBottom: "6px" }}>
              Active Custody Mode
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
              <span
                style={{
                  fontSize: "14px",
                  fontWeight: 700,
                  padding: "3px 10px",
                  borderRadius: "6px",
                  background: status.ledger_mode === "fabric_anchored" ? "#e0e7ff" : "#fef3c7",
                  color: status.ledger_mode === "fabric_anchored" ? "#3730a3" : "#92400e",
                  border: `1px solid ${status.ledger_mode === "fabric_anchored" ? "#c7d2fe" : "#fde68a"}`,
                }}
              >
                {status.ledger_mode === "fabric_anchored" ? "Hyperledger Fabric Anchored" : "Standalone Signed Log"}
              </span>
            </div>
            <div style={{ fontSize: "12px", color: "#4b5563" }}>
              {status.ledger_mode === "fabric_anchored"
                ? `Channel: ${status.channel_name} | Chaincode: ${status.chaincode_name}`
                : "Local Ed25519 signatures & RFC 6962 Merkle checkpoints enabled. Ledger offline/unconfigured."}
            </div>
          </div>

          {/* Key Card */}
          <div style={{ background: "#ffffff", borderRadius: "8px", border: "1px solid #e5e7eb", padding: "18px", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
            <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", color: "#6b7280", marginBottom: "6px" }}>
              Signing Key Authority
            </div>
            <div style={{ fontSize: "13px", fontWeight: 600, color: "#111827", marginBottom: "4px" }}>
              Key ID: <code>{status.service_key_id}</code>
            </div>
            <div style={{ fontSize: "11px", color: "#6b7280", wordBreak: "break-all" }}>
              Pubkey: <code>{status.service_public_key.slice(0, 32)}...</code>
            </div>
          </div>

          {/* Outbox Pipeline Card */}
          <div style={{ background: "#ffffff", borderRadius: "8px", border: "1px solid #e5e7eb", padding: "18px", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
            <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", color: "#6b7280", marginBottom: "6px" }}>
              Transactional Outbox Pipeline
            </div>
            <div style={{ display: "flex", gap: "16px", marginTop: "8px" }}>
              <div>
                <span style={{ fontSize: "10px", color: "#6b7280", textTransform: "uppercase", display: "block" }}>Pending</span>
                <span style={{ fontSize: "18px", fontWeight: 700, color: status.pending_outbox_count > 0 ? "#d97706" : "#111827" }}>
                  {status.pending_outbox_count}
                </span>
              </div>
              <div>
                <span style={{ fontSize: "10px", color: "#6b7280", textTransform: "uppercase", display: "block" }}>Anchored</span>
                <span style={{ fontSize: "18px", fontWeight: 700, color: "#166534" }}>{status.anchored_outbox_count}</span>
              </div>
              <div>
                <span style={{ fontSize: "10px", color: "#6b7280", textTransform: "uppercase", display: "block" }}>Failed</span>
                <span style={{ fontSize: "18px", fontWeight: 700, color: status.failed_outbox_count > 0 ? "#dc2626" : "#111827" }}>
                  {status.failed_outbox_count}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Supervisory Scope & Verification Boundary Note */}
      <div
        style={{
          background: "#f8fafc",
          borderRadius: "8px",
          border: "1px solid #e2e8f0",
          padding: "14px 18px",
          marginBottom: "24px",
          fontSize: "12px",
          color: "#475569",
          lineHeight: "1.5",
        }}
      >
        <strong>What This Proof Establishes:</strong> Verifies that original submission files match exact-byte SHA-256 hashes, structured records conform to canonical JSON serialization with nonces, and supervisory milestones follow an unbroken sequence signed by an authorized key.
        <br />
        <strong>What This Proof Does NOT Establish:</strong> A valid signature or ledger receipt does not establish that the audited organization's internal SOC controls are effective, nor does it guarantee that uncommitted offline logs were unaltered prior to transmission.
      </div>

      {/* Verification Runner Section */}
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
        <h2 style={{ fontSize: "16px", fontWeight: 700, color: "#111827", margin: "0 0 12px 0" }}>
          On-Demand Cryptographic Verification
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", alignItems: "flex-end" }}>
          <div>
            <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#374151", marginBottom: "4px" }}>
              Target Type
            </label>
            <select
              value={verifyType}
              onChange={(e) => setVerifyType(e.target.value as any)}
              style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #d1d5db", fontSize: "13px" }}
            >
              <option value="custody_log">Full Entity Custody Log</option>
              <option value="submission">Submission Evidence &amp; Batch Merkle</option>
              <option value="report_snapshot">Report Snapshot &amp; Sidecar</option>
            </select>
          </div>

          <div>
            <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#374151", marginBottom: "4px" }}>
              Entity ID
            </label>
            <input
              type="text"
              value={verifyEntityId}
              onChange={(e) => setVerifyEntityId(e.target.value)}
              placeholder="e.g. E-101"
              style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #d1d5db", fontSize: "13px", boxSizing: "border-box" }}
            />
          </div>

          <div>
            <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#374151", marginBottom: "4px" }}>
              Target ID (Optional for Log)
            </label>
            <input
              type="text"
              value={verifyTargetId}
              onChange={(e) => setVerifyTargetId(e.target.value)}
              placeholder="submission_id / report_id"
              style={{ width: "100%", padding: "7px 10px", borderRadius: "6px", border: "1px solid #d1d5db", fontSize: "13px", boxSizing: "border-box" }}
            />
          </div>

          <div>
            <button
              onClick={handleRunVerification}
              disabled={verifyLoading}
              style={{
                width: "100%",
                background: "#047857",
                border: "none",
                borderRadius: "6px",
                padding: "8px 14px",
                fontSize: "13px",
                fontWeight: 600,
                color: "#ffffff",
                cursor: "pointer",
              }}
            >
              {verifyLoading ? "Verifying..." : "Run Cryptographic Verification"}
            </button>
          </div>
        </div>

        {/* Verification Result Display */}
        {verifyResult && (
          <div
            style={{
              marginTop: "16px",
              padding: "16px",
              borderRadius: "6px",
              border: `1px solid ${verifyResult.is_valid ? "#86efac" : "#fca5a5"}`,
              background: verifyResult.is_valid ? "#f0fdf4" : "#fef2f2",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <span
                style={{
                  fontSize: "13px",
                  fontWeight: 700,
                  color: verifyResult.is_valid ? "#166534" : "#991b1b",
                  textTransform: "uppercase",
                }}
              >
                Verification Result: {verifyResult.status.toUpperCase()}
              </span>
              <span style={{ fontSize: "12px", color: "#6b7280" }}>
                Signatures Verified: {verifyResult.signatures_verified} | Files: {verifyResult.files_checked} | Records: {verifyResult.records_checked}
              </span>
            </div>

            {verifyResult.issues.length > 0 && (
              <ul style={{ margin: "8px 0 0 0", paddingLeft: "20px", color: "#991b1b", fontSize: "12px" }}>
                {verifyResult.issues.map((iss, i) => (
                  <li key={i}>{iss}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Custody Log Event Timeline */}
      <div style={{ background: "#ffffff", borderRadius: "8px", border: "1px solid #e5e7eb", padding: "20px", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <h2 style={{ fontSize: "16px", fontWeight: 700, color: "#111827", margin: "0 0 4px 0" }}>
              Append-Only Custody Event Timeline
            </h2>
            <p style={{ margin: 0, fontSize: "12px", color: "#6b7280" }}>
              Displaying {events.length} signed cryptographic custody events.
            </p>
          </div>
          <div>
            <input
              type="text"
              placeholder="Filter by Entity ID..."
              value={entityFilter}
              onChange={(e) => setEntityFilter(e.target.value)}
              style={{ padding: "6px 12px", borderRadius: "6px", border: "1px solid #d1d5db", fontSize: "12px" }}
            />
          </div>
        </div>

        {events.length === 0 ? (
          <p style={{ color: "#6b7280", fontSize: "13px", margin: "20px 0" }}>
            No custody events recorded yet. Commit a submission, run an assessment, record a decision, or generate a report to produce signed events.
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "12px" }}>
              <thead>
                <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb" }}>
                  <th style={{ padding: "10px 12px", fontWeight: 600, color: "#4b5563" }}>Seq</th>
                  <th style={{ padding: "10px 12px", fontWeight: 600, color: "#4b5563" }}>Event Type</th>
                  <th style={{ padding: "10px 12px", fontWeight: 600, color: "#4b5563" }}>Entity</th>
                  <th style={{ padding: "10px 12px", fontWeight: 600, color: "#4b5563" }}>Target Ref</th>
                  <th style={{ padding: "10px 12px", fontWeight: 600, color: "#4b5563" }}>Signing Key</th>
                  <th style={{ padding: "10px 12px", fontWeight: 600, color: "#4b5563" }}>Recorded At</th>
                  <th style={{ padding: "10px 12px", fontWeight: 600, color: "#4b5563" }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => {
                  const badge = getEventTypeBadge(ev.event_type);
                  return (
                    <tr key={ev.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "10px 12px", fontWeight: 700, color: "#111827" }}>#{ev.sequence_number}</td>
                      <td style={{ padding: "10px 12px" }}>
                        <span
                          style={{
                            padding: "2px 8px",
                            borderRadius: "4px",
                            fontSize: "11px",
                            fontWeight: 600,
                            background: badge.bg,
                            color: badge.color,
                          }}
                        >
                          {badge.label}
                        </span>
                      </td>
                      <td style={{ padding: "10px 12px", color: "#374151" }}>{ev.entity_id}</td>
                      <td style={{ padding: "10px 12px", color: "#4b5563" }}>
                        <code>{ev.object_type}</code>: {ev.object_id.slice(0, 10)}... (v{ev.object_version})
                      </td>
                      <td style={{ padding: "10px 12px", color: "#6b7280" }}>
                        <code>{ev.signing_key_id}</code>
                      </td>
                      <td style={{ padding: "10px 12px", color: "#6b7280" }}>
                        {new Date(ev.recorded_at).toLocaleString()}
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        <button
                          onClick={() => setSelectedEvent(ev)}
                          style={{
                            background: "#f3f4f6",
                            border: "1px solid #d1d5db",
                            borderRadius: "4px",
                            padding: "3px 8px",
                            fontSize: "11px",
                            cursor: "pointer",
                            fontWeight: 600,
                          }}
                        >
                          Inspect Proof
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Event Details Modal / Drawer */}
      {selectedEvent && (
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
            zIndex: 100,
            padding: "16px",
          }}
          onClick={() => setSelectedEvent(null)}
        >
          <div
            style={{
              background: "#ffffff",
              borderRadius: "8px",
              maxWidth: "680px",
              width: "100%",
              maxHeight: "85vh",
              overflowY: "auto",
              padding: "24px",
              boxShadow: "0 20px 25px -5px rgba(0,0,0,0.1)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#111827" }}>
                Custody Event #{selectedEvent.sequence_number} Proof Details
              </h3>
              <button
                onClick={() => setSelectedEvent(null)}
                style={{ background: "none", border: "none", fontSize: "18px", cursor: "pointer", color: "#6b7280" }}
              >
                &times;
              </button>
            </div>

            <div style={{ fontSize: "12px", color: "#374151", display: "grid", gap: "10px" }}>
              <div>
                <strong>Event ID:</strong> <code>{selectedEvent.id}</code>
              </div>
              <div>
                <strong>Entity ID:</strong> {selectedEvent.entity_id}
              </div>
              <div>
                <strong>Event Type:</strong> <code>{selectedEvent.event_type}</code>
              </div>
              <div>
                <strong>Previous Event Commitment:</strong>
                <pre style={{ background: "#f8fafc", padding: "8px", borderRadius: "4px", margin: "4px 0", fontSize: "11px", wordBreak: "break-all" }}>
                  {selectedEvent.previous_event_commitment}
                </pre>
              </div>
              <div>
                <strong>Evidence Commitment (Merkle Root / Artifact Digest):</strong>
                <pre style={{ background: "#f8fafc", padding: "8px", borderRadius: "4px", margin: "4px 0", fontSize: "11px", wordBreak: "break-all" }}>
                  {selectedEvent.evidence_commitment}
                </pre>
              </div>
              <div>
                <strong>Payload Digest:</strong>
                <pre style={{ background: "#f8fafc", padding: "8px", borderRadius: "4px", margin: "4px 0", fontSize: "11px", wordBreak: "break-all" }}>
                  {selectedEvent.payload_digest}
                </pre>
              </div>
              <div>
                <strong>Ed25519 Signature:</strong>
                <pre style={{ background: "#f8fafc", padding: "8px", borderRadius: "4px", margin: "4px 0", fontSize: "11px", wordBreak: "break-all" }}>
                  {selectedEvent.signature}
                </pre>
              </div>
              <div>
                <strong>Claimed Event Time:</strong> {new Date(selectedEvent.claimed_event_time).toISOString()}
              </div>
              <div>
                <strong>Recorded System Time:</strong> {new Date(selectedEvent.recorded_at).toISOString()}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default EvidenceIntegrityDashboard;
