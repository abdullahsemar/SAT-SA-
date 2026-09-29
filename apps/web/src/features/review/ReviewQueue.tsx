import React, { useState } from "react";
import { ReviewItem, ReviewPortfolio, ReviewDecision } from "../../api/client";

interface ReviewQueueProps {
  portfolio: ReviewPortfolio;
  selectedItemId: string | null;
  onSelectItem: (item: ReviewItem) => void;
  decisionsByItemId?: Record<string, ReviewDecision[]>;
}

export const ReviewQueue: React.FC<ReviewQueueProps> = ({
  portfolio,
  selectedItemId,
  onSelectItem,
  decisionsByItemId = {},
}) => {
  const [stratumFilter, setStratumFilter] = useState<string>("all");

  const items = portfolio.items || [];
  const filteredItems = items.filter((it) => {
    if (stratumFilter === "all") return true;
    return it.stratum.toLowerCase() === stratumFilter.toLowerCase();
  });

  const shortfalls = portfolio.summary?.shortfalls || {};
  const hasShortfalls = Object.values(shortfalls).some((v) => Number(v) > 0);

  const getStratumBadge = (stratum: string) => {
    switch (stratum.toLowerCase()) {
      case "control":
        return { bg: "#ecfdf5", color: "#065f46", border: "#a7f3d0", label: "Control Sample" };
      case "exploratory":
        return { bg: "#faf5ff", color: "#6b21a8", border: "#e9d5ff", label: "Exploratory" };
      case "targeted":
      default:
        return { bg: "#eff6ff", color: "#1e40af", border: "#bfdbfe", label: "Targeted" };
    }
  };

  const getItemDecisionState = (item: ReviewItem) => {
    const itemDecs = decisionsByItemId[item.id];
    if (itemDecs && itemDecs.length > 0) {
      const latest = itemDecs[itemDecs.length - 1];
      return latest.state;
    }
    return "pending";
  };

  const getDecisionBadge = (state: string) => {
    switch (state.toLowerCase()) {
      case "substantiated":
        return { bg: "#fee2e2", color: "#991b1b", label: "Substantiated" };
      case "not_substantiated":
        return { bg: "#ecfdf5", color: "#065f46", label: "Not Substantiated" };
      case "reviewed_no_concern":
        return { bg: "#ecfdf5", color: "#065f46", label: "No Concern" };
      case "concern_observed":
        return { bg: "#fee2e2", color: "#991b1b", label: "Concern Observed" };
      case "additional_evidence_required":
        return { bg: "#fef3c7", color: "#92400e", label: "Evidence Needed" };
      case "not_applicable":
        return { bg: "#f3f4f6", color: "#4b5563", label: "N/A" };
      case "pending":
      default:
        return { bg: "#f3f4f6", color: "#6b7280", label: "Pending" };
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        borderRight: "1px solid #e5e7eb",
        background: "#ffffff",
        overflowY: "auto",
      }}
    >
      {/* Portfolio Header */}
      <div style={{ padding: "16px 20px", borderBottom: "1px solid #e5e7eb", background: "#f9fafb" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
          <h2 style={{ margin: 0, fontSize: "15px", fontWeight: 700, color: "#111827" }}>
            Review Portfolio (Rev #{portfolio.revision})
          </h2>
          <span
            style={{
              fontSize: "11px",
              background: "#e0e7ff",
              color: "#3730a3",
              padding: "2px 8px",
              borderRadius: "12px",
              fontWeight: 600,
            }}
          >
            Seed: {portfolio.seed}
          </span>
        </div>
        <div style={{ fontSize: "12px", color: "#6b7280" }}>
          {items.length} items &bull; {portfolio.summary?.total_review_minutes || 0} est. minutes &bull;{" "}
          {portfolio.summary?.hypotheses_covered_count || 0} hypotheses covered
        </div>

        {/* Shortfall Alert */}
        {hasShortfalls && (
          <div
            style={{
              marginTop: "10px",
              padding: "8px 10px",
              background: "#fffbeb",
              border: "1px solid #fde68a",
              borderRadius: "6px",
              fontSize: "11px",
              color: "#92400e",
              lineHeight: "1.4",
            }}
          >
            <strong>Quota Shortfall:</strong>{" "}
            {Object.entries(shortfalls)
              .filter(([, v]) => Number(v) > 0)
              .map(([k, v]) => `${k}: -${v}`)
              .join(", ")}
            . Fewer items returned to prevent synthetic padding.
          </div>
        )}
      </div>

      {/* Filter Tabs */}
      <div
        style={{
          display: "flex",
          borderBottom: "1px solid #e5e7eb",
          background: "#ffffff",
          padding: "6px 12px",
          gap: "4px",
        }}
      >
        {["all", "targeted", "control", "exploratory"].map((tab) => {
          const count =
            tab === "all" ? items.length : items.filter((i) => i.stratum.toLowerCase() === tab).length;
          const isActive = stratumFilter === tab;
          return (
            <button
              key={tab}
              onClick={() => setStratumFilter(tab)}
              style={{
                background: isActive ? "#111827" : "transparent",
                color: isActive ? "#ffffff" : "#4b5563",
                border: "none",
                borderRadius: "4px",
                padding: "4px 8px",
                fontSize: "11px",
                fontWeight: 600,
                cursor: "pointer",
                textTransform: "capitalize",
              }}
            >
              {tab} ({count})
            </button>
          );
        })}
      </div>

      {/* Items List */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {filteredItems.length === 0 ? (
          <div style={{ padding: "24px 16px", textAlign: "center", color: "#6b7280", fontSize: "13px" }}>
            No review items in this filter stratum.
          </div>
        ) : (
          filteredItems.map((item) => {
            const isSelected = item.id === selectedItemId;
            const stratumBadge = getStratumBadge(item.stratum);
            const decState = getItemDecisionState(item);
            const decBadge = getDecisionBadge(decState);

            return (
              <div
                key={item.id}
                onClick={() => onSelectItem(item)}
                style={{
                  padding: "12px 16px",
                  borderBottom: "1px solid #f3f4f6",
                  background: isSelected ? "#f0fdf4" : "#ffffff",
                  borderLeft: isSelected ? "4px solid #16a34a" : "4px solid transparent",
                  cursor: "pointer",
                  transition: "background 0.1s ease",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span
                      style={{
                        fontSize: "11px",
                        fontWeight: 700,
                        color: "#6b7280",
                      }}
                    >
                      #{item.selection_rank}
                    </span>
                    <span
                      style={{
                        fontSize: "10px",
                        fontWeight: 700,
                        padding: "1px 6px",
                        borderRadius: "4px",
                        background: stratumBadge.bg,
                        color: stratumBadge.color,
                        border: `1px solid ${stratumBadge.border}`,
                        textTransform: "uppercase",
                      }}
                    >
                      {stratumBadge.label}
                    </span>
                    <span
                      style={{
                        fontSize: "10px",
                        fontWeight: 600,
                        padding: "1px 6px",
                        borderRadius: "4px",
                        background: "#f3f4f6",
                        color: "#4b5563",
                      }}
                    >
                      {item.unit_type}
                    </span>
                  </div>

                  <span
                    style={{
                      fontSize: "10px",
                      fontWeight: 600,
                      padding: "2px 6px",
                      borderRadius: "4px",
                      background: decBadge.bg,
                      color: decBadge.color,
                    }}
                  >
                    {decBadge.label}
                  </span>
                </div>

                <div
                  style={{
                    fontSize: "13px",
                    fontWeight: 600,
                    color: "#111827",
                    marginBottom: "4px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {item.scope}
                </div>

                <div
                  style={{
                    fontSize: "11px",
                    color: "#6b7280",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span>{item.estimated_review_minutes} min est.</span>
                  {item.finding_id && <span style={{ color: "#4f46e5" }}>Finding linked</span>}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
