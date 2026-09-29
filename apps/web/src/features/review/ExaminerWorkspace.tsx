import React, { useEffect, useState } from "react";
import {
  apiClient,
  Finding,
  ReviewDecision,
  ReviewItem,
  ReviewPortfolio,
} from "../../api/client";
import { SimilarPassages } from "../findings/SimilarPassages";
import { DecisionForm } from "./DecisionForm";
import { ReviewQueue } from "./ReviewQueue";

interface ExaminerWorkspaceProps {
  initialPortfolioId?: string | null;
  onBack?: () => void;
}

export const ExaminerWorkspace: React.FC<ExaminerWorkspaceProps> = ({
  initialPortfolioId,
}) => {
  const [portfolios, setPortfolios] = useState<ReviewPortfolio[]>([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState<ReviewPortfolio | null>(null);
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(null);
  const [associatedFinding, setAssociatedFinding] = useState<Finding | null>(null);
  const [itemDecisions, setItemDecisions] = useState<ReviewDecision[]>([]);
  const [decisionsByItemId, setDecisionsByItemId] = useState<Record<string, ReviewDecision[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Source record inspection drawer
  const [inspectedRecord, setInspectedRecord] = useState<any | null>(null);

  // Load portfolios list
  useEffect(() => {
    let isMounted = true;
    async function loadPortfolios() {
      setLoading(true);
      setError(null);
      try {
        const list = await apiClient.listReviewPortfolios();
        if (!isMounted) return;
        setPortfolios(list);
        if (list.length > 0) {
          const target = initialPortfolioId
            ? list.find((p) => p.id === initialPortfolioId) || list[0]
            : list[0];
          setSelectedPortfolio(target);
          if (target.items && target.items.length > 0) {
            setSelectedItem(target.items[0]);
          }
        }
      } catch (err: any) {
        if (isMounted) setError(err.message || "Failed to load review portfolios");
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    loadPortfolios();
    return () => {
      isMounted = false;
    };
  }, [initialPortfolioId]);

  // When selectedItem changes, load finding (if any) and decision history
  useEffect(() => {
    let isMounted = true;
    async function loadItemData() {
      if (!selectedItem) {
        setAssociatedFinding(null);
        setItemDecisions([]);
        return;
      }

      // 1. Fetch decisions
      try {
        let decs: ReviewDecision[] = [];
        if (selectedItem.finding_id) {
          decs = await apiClient.getFindingDecisions(selectedItem.finding_id);
        } else {
          decs = await apiClient.getItemDecisions(selectedItem.id);
        }
        if (isMounted) {
          setItemDecisions(decs);
          setDecisionsByItemId((prev) => ({ ...prev, [selectedItem.id]: decs }));
        }
      } catch {
        if (isMounted) setItemDecisions([]);
      }

      // 2. Fetch finding if linked
      if (selectedItem.finding_id) {
        try {
          const f = await apiClient.getFinding(selectedItem.finding_id);
          if (isMounted) setAssociatedFinding(f);
        } catch {
          if (isMounted) setAssociatedFinding(null);
        }
      } else {
        if (isMounted) setAssociatedFinding(null);
      }
    }
    loadItemData();
    return () => {
      isMounted = false;
    };
  }, [selectedItem]);

  const handleDecisionSaved = (saved: ReviewDecision) => {
    setItemDecisions((prev) => [...prev, saved]);
    if (selectedItem) {
      setDecisionsByItemId((prev) => ({
        ...prev,
        [selectedItem.id]: [...(prev[selectedItem.id] || []), saved],
      }));
    }
  };

  if (loading && !selectedPortfolio) {
    return (
      <div style={{ padding: "40px", textAlign: "center", color: "#6b7280" }}>
        Loading examiner review workspace...
      </div>
    );
  }

  if (error && !selectedPortfolio) {
    return (
      <div style={{ padding: "30px", maxWidth: "800px", margin: "40px auto" }}>
        <div style={{ padding: "16px", background: "#fee2e2", color: "#991b1b", borderRadius: "8px" }}>
          {error}
        </div>
      </div>
    );
  }

  if (!selectedPortfolio) {
    return (
      <div style={{ padding: "40px", textAlign: "center", color: "#6b7280" }}>
        No review portfolios generated yet. Create an analysis run first to request a review portfolio.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "calc(100vh - 60px)", overflow: "hidden" }}>
      {/* 1. Left Column: Review Queue & Portfolio Switcher */}
      <div style={{ width: "320px", flexShrink: 0, height: "100%", display: "flex", flexDirection: "column" }}>
        {portfolios.length > 1 && (
          <div style={{ padding: "8px 12px", borderBottom: "1px solid #e5e7eb", background: "#f3f4f6" }}>
            <label style={{ fontSize: "11px", fontWeight: 700, color: "#4b5563", display: "block", marginBottom: "4px" }}>
              Portfolio Revision:
            </label>
            <select
              value={selectedPortfolio.id}
              onChange={(e) => {
                const target = portfolios.find((p) => p.id === e.target.value);
                if (target) {
                  setSelectedPortfolio(target);
                  if (target.items && target.items.length > 0) {
                    setSelectedItem(target.items[0]);
                  }
                }
              }}
              style={{ width: "100%", padding: "4px 8px", fontSize: "12px", borderRadius: "4px", border: "1px solid #d1d5db" }}
            >
              {portfolios.map((p) => (
                <option key={p.id} value={p.id}>
                  Rev #{p.revision} ({p.entity_id}) - {p.items?.length || 0} items
                </option>
              ))}
            </select>
          </div>
        )}
        <div style={{ flex: 1, overflow: "hidden" }}>
          <ReviewQueue
            portfolio={selectedPortfolio}
            selectedItemId={selectedItem?.id || null}
            onSelectItem={(it) => setSelectedItem(it)}
            decisionsByItemId={decisionsByItemId}
          />
        </div>
      </div>

      {/* 2. Center Column: Evidence, Explanations & Alternatives */}
      <div style={{ flex: 1, height: "100%", overflowY: "auto", padding: "24px", background: "#f9fafb" }}>
        {selectedItem ? (
          <div style={{ maxWidth: "880px", margin: "0 auto" }}>
            {/* Item Header Card */}
            <div
              style={{
                background: "#ffffff",
                borderRadius: "8px",
                border: "1px solid #e5e7eb",
                padding: "20px 24px",
                marginBottom: "20px",
                boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span
                    style={{
                      fontSize: "12px",
                      fontWeight: 700,
                      color: "#4f46e5",
                      textTransform: "uppercase",
                    }}
                  >
                    Rank #{selectedItem.selection_rank} &bull; {selectedItem.stratum} stratum
                  </span>
                  <span
                    style={{
                      fontSize: "11px",
                      background: "#f3f4f6",
                      color: "#374151",
                      padding: "2px 8px",
                      borderRadius: "4px",
                      fontWeight: 600,
                    }}
                  >
                    Unit: {selectedItem.unit_type}
                  </span>
                </div>

                <span style={{ fontSize: "12px", color: "#6b7280" }}>
                  Est. Review: <strong>{selectedItem.estimated_review_minutes} min</strong>
                </span>
              </div>

              <h2 style={{ margin: "0 0 8px 0", fontSize: "18px", fontWeight: 700, color: "#111827" }}>
                {selectedItem.scope}
              </h2>

              {/* Marginal selection reasons */}
              {selectedItem.marginal_reasons && (
                <div
                  style={{
                    marginTop: "12px",
                    padding: "10px 14px",
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "6px",
                    fontSize: "13px",
                    color: "#334155",
                    lineHeight: "1.5",
                  }}
                >
                  <strong>Why Selected:</strong> {selectedItem.marginal_reasons.why_selected}
                </div>
              )}

              {/* What examiner could learn */}
              <div
                style={{
                  marginTop: "12px",
                  padding: "10px 14px",
                  background: "#eff6ff",
                  border: "1px solid #bfdbfe",
                  borderRadius: "6px",
                  fontSize: "13px",
                  color: "#1e40af",
                  lineHeight: "1.5",
                }}
              >
                <strong>Examiner Learning Objective:</strong> {selectedItem.what_examiner_learns}
              </div>

              {/* Boundary / Uncertainty notes */}
              {selectedItem.unknowns && selectedItem.unknowns.length > 0 && (
                <div style={{ marginTop: "12px" }}>
                  {selectedItem.unknowns.map((unk, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: "8px 12px",
                        background: "#fffbeb",
                        border: "1px solid #fde68a",
                        color: "#92400e",
                        borderRadius: "6px",
                        fontSize: "12px",
                        marginBottom: "6px",
                      }}
                    >
                      <strong>Evidence Boundary / Uncertainty:</strong> {unk}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Finding-Specific Section: rendered ONLY if finding exists */}
            {associatedFinding && (
              <div
                style={{
                  background: "#ffffff",
                  borderRadius: "8px",
                  border: "1px solid #e5e7eb",
                  padding: "20px 24px",
                  marginBottom: "20px",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <span style={{ fontSize: "12px", fontWeight: 700, color: "#991b1b", textTransform: "uppercase" }}>
                    Machine Finding &bull; {associatedFinding.rule_id}
                  </span>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 600,
                      padding: "2px 8px",
                      borderRadius: "4px",
                      background: "#fef2f2",
                      color: "#991b1b",
                    }}
                  >
                    State: {associatedFinding.evidence_state}
                  </span>
                </div>

                <h3 style={{ margin: "0 0 10px 0", fontSize: "16px", fontWeight: 700, color: "#111827" }}>
                  {associatedFinding.rule_title}
                </h3>

                <div
                  style={{
                    padding: "12px 14px",
                    background: "#f9fafb",
                    borderRadius: "6px",
                    fontSize: "13px",
                    lineHeight: "1.6",
                    color: "#1f2937",
                  }}
                >
                  {associatedFinding.rationale}
                </div>
              </div>
            )}

            {/* Supporting Source Records Table */}
            <div
              style={{
                background: "#ffffff",
                borderRadius: "8px",
                border: "1px solid #e5e7eb",
                padding: "20px 24px",
                marginBottom: "20px",
                boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
              }}
            >
              <h3 style={{ margin: "0 0 14px 0", fontSize: "15px", fontWeight: 700, color: "#111827" }}>
                Source Evidence Provenance ({selectedItem.evidence_references?.length || 0})
              </h3>
              {(!selectedItem.evidence_references || selectedItem.evidence_references.length === 0) ? (
                <div style={{ color: "#6b7280", fontSize: "13px" }}>
                  No direct primary records attached (e.g. absence-of-coverage evaluated across telemetry silence).
                </div>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                    <thead>
                      <tr style={{ background: "#f9fafb", borderBottom: "1px solid #e5e7eb", textAlign: "left" }}>
                        <th style={{ padding: "8px 10px", color: "#4b5563" }}>Source ID</th>
                        <th style={{ padding: "8px 10px", color: "#4b5563" }}>Record Type</th>
                        <th style={{ padding: "8px 10px", color: "#4b5563" }}>Locator</th>
                        <th style={{ padding: "8px 10px", color: "#4b5563" }}>Native ID</th>
                        <th style={{ padding: "8px 10px", color: "#4b5563" }}>SHA-256 Hash</th>
                        <th style={{ padding: "8px 10px", color: "#4b5563" }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedItem.evidence_references.map((rec, idx) => (
                        <tr key={idx} style={{ borderBottom: "1px solid #f3f4f6" }}>
                          <td style={{ padding: "8px 10px", fontWeight: 600 }}>{rec.source_id}</td>
                          <td style={{ padding: "8px 10px", color: "#6b7280" }}>{rec.record_type}</td>
                          <td style={{ padding: "8px 10px" }}><code>{rec.locator || rec.row_locator || "N/A"}</code></td>
                          <td style={{ padding: "8px 10px" }}><strong>{rec.native_id || rec.id || "N/A"}</strong></td>
                          <td style={{ padding: "8px 10px" }}>
                            <code style={{ fontSize: "10px", background: "#f3f4f6", padding: "2px 4px", borderRadius: "3px" }}>
                              {rec.sha256 ? rec.sha256.substring(0, 16) + "..." : "verified"}
                            </code>
                          </td>
                          <td style={{ padding: "8px 10px" }}>
                            <button
                              onClick={() => setInspectedRecord(rec)}
                              style={{
                                background: "#f3f4f6",
                                border: "1px solid #d1d5db",
                                borderRadius: "4px",
                                padding: "2px 8px",
                                fontSize: "11px",
                                cursor: "pointer",
                              }}
                            >
                              Inspect
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Semantic Investigation Passages: rendered ONLY if finding exists */}
            {associatedFinding && (
              <div style={{ marginBottom: "20px" }}>
                <SimilarPassages findingId={associatedFinding.finding_id} />
              </div>
            )}

            {/* Immutable Decision History Timeline */}
            <div
              style={{
                background: "#ffffff",
                borderRadius: "8px",
                border: "1px solid #e5e7eb",
                padding: "20px 24px",
                marginBottom: "20px",
                boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
              }}
            >
              <h3 style={{ margin: "0 0 14px 0", fontSize: "15px", fontWeight: 700, color: "#111827" }}>
                Immutable Decision History ({itemDecisions.length})
              </h3>
              {itemDecisions.length === 0 ? (
                <p style={{ color: "#6b7280", fontSize: "13px", margin: 0 }}>
                  No determinations recorded yet for this item. Complete the form to persist an examiner decision.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {itemDecisions.map((dec, idx) => (
                    <div
                      key={dec.id}
                      style={{
                        padding: "12px 16px",
                        borderRadius: "6px",
                        border: "1px solid #e5e7eb",
                        background: idx === itemDecisions.length - 1 ? "#f0fdf4" : "#f9fafb",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                        <span style={{ fontSize: "12px", fontWeight: 700, color: "#111827" }}>
                          Revision #{dec.version} &bull; State: <code>{dec.state}</code>
                        </span>
                        <span style={{ fontSize: "11px", color: "#6b7280" }}>
                          By <strong>{dec.reviewer_username}</strong> on {new Date(dec.created_at).toLocaleString()}
                        </span>
                      </div>
                      <div style={{ fontSize: "13px", color: "#374151", lineHeight: "1.5" }}>
                        {dec.rationale}
                      </div>
                      {dec.cited_evidence_ids && dec.cited_evidence_ids.length > 0 && (
                        <div style={{ marginTop: "6px", fontSize: "11px", color: "#4b5563" }}>
                          <strong>Cited Evidence IDs:</strong> {dec.cited_evidence_ids.join(", ")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div style={{ padding: "40px", textAlign: "center", color: "#6b7280" }}>
            Select an item from the queue on the left to inspect evidence and persist decisions.
          </div>
        )}
      </div>

      {/* 3. Right Column: Decision Form & Raw Record Drawer */}
      <div
        style={{
          width: "380px",
          flexShrink: 0,
          height: "100%",
          borderLeft: "1px solid #e5e7eb",
          background: "#ffffff",
          overflowY: "auto",
          padding: "20px",
        }}
      >
        {selectedItem ? (
          <>
            <DecisionForm
              item={selectedItem}
              existingDecisions={itemDecisions}
              onDecisionSaved={handleDecisionSaved}
            />

            {/* Original Source Record Inspection Drawer Modal/Subpanel */}
            {inspectedRecord && (
              <div
                style={{
                  marginTop: "20px",
                  padding: "16px",
                  borderRadius: "8px",
                  border: "1px solid #d1d5db",
                  background: "#f9fafb",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <h4 style={{ margin: 0, fontSize: "13px", fontWeight: 700, color: "#111827" }}>
                    Source Record Details
                  </h4>
                  <button
                    onClick={() => setInspectedRecord(null)}
                    style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: "12px", color: "#6b7280" }}
                  >
                    &times; Close
                  </button>
                </div>
                <div style={{ fontSize: "11px", display: "flex", flexDirection: "column", gap: "6px" }}>
                  <div><strong>Source ID:</strong> {inspectedRecord.source_id}</div>
                  <div><strong>Record Type:</strong> {inspectedRecord.record_type}</div>
                  <div><strong>Locator:</strong> {inspectedRecord.locator || inspectedRecord.row_locator || "N/A"}</div>
                  <div><strong>Native ID:</strong> {inspectedRecord.native_id || inspectedRecord.id || "N/A"}</div>
                  <div><strong>SHA-256 Hash:</strong></div>
                  <code style={{ wordBreak: "break-all", background: "#e5e7eb", padding: "4px", borderRadius: "4px" }}>
                    {inspectedRecord.sha256 || "N/A"}
                  </code>
                </div>
              </div>
            )}
          </>
        ) : (
          <div style={{ color: "#6b7280", fontSize: "13px", textAlign: "center", marginTop: "40px" }}>
            Select an item to record supervisory determinations.
          </div>
        )}
      </div>
    </div>
  );
};
