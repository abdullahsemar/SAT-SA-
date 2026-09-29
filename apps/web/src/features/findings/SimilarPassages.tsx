import React, { useEffect, useState } from "react";
import { apiClient, SimilarPassageMatch, SimilarPassagesResponse } from "../../api/client";

interface SimilarPassagesProps {
  findingId: string;
}

export const SimilarPassages: React.FC<SimilarPassagesProps> = ({ findingId }) => {
  const [data, setData] = useState<SimilarPassagesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMatch, setSelectedMatch] = useState<SimilarPassageMatch | null>(null);

  useEffect(() => {
    let isMounted = true;
    async function loadPassages() {
      setLoading(true);
      setError(null);
      try {
        const res = await apiClient.getSimilarPassages(findingId);
        if (isMounted) {
          setData(res);
          if (res.matches && res.matches.length > 0) {
            setSelectedMatch(res.matches[0]);
          }
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || "Failed to load similar passages");
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    loadPassages();
    return () => {
      isMounted = false;
    };
  }, [findingId]);

  const getExplanationBadge = (expl: string) => {
    switch (expl) {
      case "possible_playbook_template":
        return { label: "Possible Playbook Template", bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" };
      case "possible_repeated_benign":
        return { label: "Possible Repeated Benign Condition", bg: "#ecfdf5", color: "#047857", border: "#a7f3d0" };
      case "possible_external_investigation":
        return { label: "Possible External Investigation", bg: "#fdf4ff", color: "#86198f", border: "#f0abfc" };
      default:
        return { label: "Insufficient Evidence", bg: "#f3f4f6", color: "#4b5563", border: "#e5e7eb" };
    }
  };

  if (loading) {
    return (
      <div style={{ padding: "20px", background: "#f9fafb", borderRadius: "8px", border: "1px solid #e5e7eb" }}>
        <p style={{ margin: 0, color: "#6b7280", fontSize: "14px" }}>Loading persisted passage similarity evidence...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: "16px", background: "#fef2f2", borderRadius: "8px", border: "1px solid #fecaca", color: "#991b1b", fontSize: "13px" }}>
        <strong>Passage Evidence Unavailable:</strong> {error}
      </div>
    );
  }

  if (!data) return null;

  if (data.status === "disabled") {
    return (
      <div style={{ padding: "16px", background: "#f9fafb", borderRadius: "8px", border: "1px solid #e5e7eb", color: "#6b7280", fontSize: "13px" }}>
        <span style={{ fontWeight: 600, color: "#374151" }}>Semantic Mode Disabled:</span> Passage similarity analysis was disabled for this run (<code>mode=off</code>).
      </div>
    );
  }

  if (data.status === "not_computed" || !data.target_passage) {
    return (
      <div style={{ padding: "16px", background: "#f9fafb", borderRadius: "8px", border: "1px solid #e5e7eb", color: "#6b7280", fontSize: "13px" }}>
        <span style={{ fontWeight: 600, color: "#374151" }}>No Passage Evaluated:</span> This finding does not contain an eligible investigation narrative or closure disposition for similarity comparison.
      </div>
    );
  }

  const isFallback = data.method_used.includes("fallback");

  return (
    <div
      style={{
        background: "#ffffff",
        borderRadius: "8px",
        border: "1px solid #e5e7eb",
        padding: "24px",
        marginTop: "24px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px", marginBottom: "16px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
            <h2 style={{ fontSize: "16px", fontWeight: 700, margin: 0, color: "#111827" }}>
              Similar Investigation Passages
            </h2>
            <span
              style={{
                fontSize: "12px",
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "4px",
                background: isFallback ? "#fef3c7" : "#e0e7ff",
                color: isFallback ? "#92400e" : "#3730a3",
                border: `1px solid ${isFallback ? "#fde68a" : "#c7d2fe"}`,
              }}
            >
              {isFallback ? "Lexical Fallback" : "Semantic (all-MiniLM-L6-v2)"}
            </span>
          </div>
          <p style={{ margin: 0, color: "#6b7280", fontSize: "13px" }}>
            Side-by-side passage comparison with verified source character spans and provenance.
          </p>
        </div>

        {/* Provenance details */}
        <div style={{ textAlign: "right", fontSize: "12px", color: "#6b7280" }}>
          {data.model_revision && (
            <div>
              Revision: <code>{data.model_revision.slice(0, 10)}...</code>
            </div>
          )}
          {data.manifest_digest && (
            <div>
              Manifest Digest: <code>{data.manifest_digest.slice(0, 8)}...</code>
            </div>
          )}
        </div>
      </div>

      {/* Fallback Notice if applicable */}
      {isFallback && (
        <div
          style={{
            marginBottom: "16px",
            padding: "10px 14px",
            borderRadius: "6px",
            background: "#fffbeb",
            border: "1px solid #fde68a",
            color: "#92400e",
            fontSize: "12px",
          }}
        >
          <strong>Notice:</strong> Lexical fallback was engaged ({data.fallback_reason || "semantic model unavailable"}). Matches are scored using token/keyword overlap rather than dense embeddings.
        </div>
      )}

      {/* Supervisory Notice */}
      <div
        style={{
          marginBottom: "20px",
          padding: "10px 14px",
          borderRadius: "6px",
          background: "#f0fdf4",
          border: "1px solid #bbf7d0",
          color: "#166534",
          fontSize: "12px",
          lineHeight: "1.4",
        }}
      >
        <strong>Supervisory Notice:</strong> {data.disclaimer}
      </div>

      {data.matches.length === 0 ? (
        <p style={{ color: "#6b7280", fontSize: "14px", margin: 0 }}>
          No historical passages exceeded the similarity threshold for this finding.
        </p>
      ) : (
        /* Side-by-side Layout */
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
          {/* Target Finding Passage (Left) */}
          <div style={{ background: "#f9fafb", borderRadius: "8px", border: "1px solid #e5e7eb", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <span style={{ fontSize: "12px", fontWeight: 700, textTransform: "uppercase", color: "#4b5563" }}>
                Target Finding Passage
              </span>
              {data.target_span && (
                <span style={{ fontSize: "11px", color: "#6b7280" }}>
                  Span: <code>[{data.target_span.start_char}:{data.target_span.end_char}]</code> ({data.target_span.record_id})
                </span>
              )}
            </div>
            <div
              style={{
                fontSize: "13px",
                lineHeight: "1.6",
                color: "#111827",
                background: "#ffffff",
                padding: "12px",
                borderRadius: "6px",
                border: "1px solid #e5e7eb",
                fontFamily: "inherit",
              }}
            >
              {data.target_passage}
            </div>
          </div>

          {/* Matched Passages Inspector (Right) */}
          <div style={{ background: "#f9fafb", borderRadius: "8px", border: "1px solid #e5e7eb", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <span style={{ fontSize: "12px", fontWeight: 700, textTransform: "uppercase", color: "#4b5563" }}>
                Matched Passages ({data.matches.length})
              </span>
            </div>

            {/* Candidate Selector Tabs */}
            <div style={{ display: "flex", gap: "8px", marginBottom: "12px", overflowX: "auto" }}>
              {data.matches.map((m, idx) => {
                const isSel = selectedMatch?.match_id === m.match_id;
                return (
                  <button
                    key={m.match_id || idx}
                    onClick={() => setSelectedMatch(m)}
                    style={{
                      background: isSel ? "#4f46e5" : "#ffffff",
                      color: isSel ? "#ffffff" : "#374151",
                      border: `1px solid ${isSel ? "#4f46e5" : "#d1d5db"}`,
                      borderRadius: "6px",
                      padding: "6px 12px",
                      fontSize: "12px",
                      fontWeight: 600,
                      cursor: "pointer",
                      whiteSpace: "nowrap",
                    }}
                  >
                    Match #{idx + 1} ({(m.similarity * 100).toFixed(1)}%)
                  </button>
                );
              })}
            </div>

            {/* Selected Match Details */}
            {selectedMatch && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px", flexWrap: "wrap", gap: "8px" }}>
                  <div>
                    <span
                      style={{
                        fontSize: "12px",
                        fontWeight: 600,
                        padding: "3px 8px",
                        borderRadius: "4px",
                        background: getExplanationBadge(selectedMatch.possible_explanation).bg,
                        color: getExplanationBadge(selectedMatch.possible_explanation).color,
                        border: `1px solid ${getExplanationBadge(selectedMatch.possible_explanation).border}`,
                      }}
                    >
                      {getExplanationBadge(selectedMatch.possible_explanation).label}
                    </span>
                    {selectedMatch.exact_match && (
                      <span
                        style={{
                          marginLeft: "6px",
                          fontSize: "11px",
                          fontWeight: 700,
                          padding: "2px 6px",
                          borderRadius: "4px",
                          background: "#dcfce7",
                          color: "#15803d",
                          border: "1px solid #86efac",
                        }}
                      >
                        EXACT DUPLICATE
                      </span>
                    )}
                  </div>
                  <span style={{ fontSize: "11px", color: "#6b7280" }}>
                    Source: <strong>{selectedMatch.source_id}</strong> &bull; Record: <code>{selectedMatch.record_id}</code> &bull; Span: <code>[{selectedMatch.start_char}:{selectedMatch.end_char}]</code>
                  </span>
                </div>

                {/* Hybrid Score Breakdown */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
                    gap: "8px",
                    marginBottom: "12px",
                    padding: "8px 12px",
                    background: "#f1f5f9",
                    borderRadius: "6px",
                    border: "1px solid #e2e8f0",
                  }}
                >
                  <div>
                    <div style={{ fontSize: "10px", color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>Overall Similarity</div>
                    <div style={{ fontSize: "14px", fontWeight: 700, color: "#1e293b" }}>{(selectedMatch.similarity * 100).toFixed(1)}%</div>
                  </div>
                  <div>
                    <div style={{ fontSize: "10px", color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>Lexical Jaccard</div>
                    <div style={{ fontSize: "14px", fontWeight: 700, color: "#0f766e" }}>
                      {selectedMatch.lexical_score !== undefined ? `${(selectedMatch.lexical_score * 100).toFixed(1)}%` : "N/A"}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: "10px", color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>TLSH Distance</div>
                    <div style={{ fontSize: "14px", fontWeight: 700, color: selectedMatch.tlsh_distance !== null && selectedMatch.tlsh_distance !== undefined && selectedMatch.tlsh_distance < 30 ? "#b91c1c" : "#4338ca" }}>
                      {selectedMatch.tlsh_distance !== null && selectedMatch.tlsh_distance !== undefined ? selectedMatch.tlsh_distance : "Low Complexity"}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: "10px", color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>MiniLM Cosine</div>
                    <div style={{ fontSize: "14px", fontWeight: 700, color: "#7c3aed" }}>
                      {selectedMatch.semantic_score !== undefined ? `${(selectedMatch.semantic_score * 100).toFixed(1)}%` : `${(selectedMatch.similarity * 100).toFixed(1)}%`}
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    fontSize: "13px",
                    lineHeight: "1.6",
                    color: "#111827",
                    background: "#ffffff",
                    padding: "12px",
                    borderRadius: "6px",
                    border: "1px solid #e5e7eb",
                    marginBottom: "12px",
                  }}
                >
                  {selectedMatch.matched_text}
                </div>

                <div style={{ fontSize: "11px", color: "#6b7280", fontStyle: "italic" }}>
                  {selectedMatch.caveats}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
