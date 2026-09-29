import React, { useState } from "react";
import { SupervisoryOverview } from "./features/overview/SupervisoryOverview";
import { PeerComparisonAndTrends } from "./features/comparison/PeerComparisonAndTrends";
import SubmissionPage from "./features/submissions/SubmissionPage";
import { FindingsPage } from "./features/findings/FindingsPage";
import { ExaminerWorkspace } from "./features/review/ExaminerWorkspace";
import { ReportsPage } from "./features/reports/ReportsPage";
import { EvidenceIntegrityDashboard } from "./features/evidence-integrity/EvidenceIntegrityDashboard";

export const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<
    "overview" | "intake" | "findings" | "comparison" | "review" | "reports" | "integrity"
  >("overview");

  const [activeEntityId, setActiveEntityId] = useState<string>("");
  const [activeSubmissionId, setActiveSubmissionId] = useState<string>("");
  const [activeRunId, setActiveRunId] = useState<string>("");

  const handleNavigate = (view: string, context?: any) => {
    if (context?.entityId) setActiveEntityId(context.entityId);
    if (context?.submissionId) setActiveSubmissionId(context.submissionId);
    if (context?.runId) setActiveRunId(context.runId);

    if (
      ["overview", "intake", "findings", "comparison", "review", "reports", "integrity"].includes(
        view
      )
    ) {
      setCurrentView(view as any);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "#f9fafb" }}>
      {/* Top Application Bar */}
      <header
        style={{
          background: "#111827",
          color: "#ffffff",
          padding: "0 24px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          height: "60px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              width: "28px",
              height: "28px",
              borderRadius: "6px",
              background: "#4f46e5",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 800,
              fontSize: "14px",
            }}
          >
            S
          </div>
          <div>
            <span style={{ fontWeight: 700, fontSize: "16px", letterSpacing: "0.5px" }}>SAT-SA</span>
            <span style={{ color: "#9ca3af", fontSize: "12px", marginLeft: "8px" }}>
              Supervisory Analytics Tool for SOC Assessment
            </span>
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav style={{ display: "flex", gap: "4px" }}>
          <button
            onClick={() => setCurrentView("overview")}
            style={{
              background: currentView === "overview" ? "#1f2937" : "transparent",
              color: currentView === "overview" ? "#ffffff" : "#9ca3af",
              border: "none",
              borderRadius: "6px",
              padding: "8px 14px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            Overview
          </button>
          <button
            onClick={() => setCurrentView("intake")}
            style={{
              background: currentView === "intake" ? "#1f2937" : "transparent",
              color: currentView === "intake" ? "#ffffff" : "#9ca3af",
              border: "none",
              borderRadius: "6px",
              padding: "8px 14px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            Evidence Intake
          </button>
          <button
            onClick={() => setCurrentView("findings")}
            style={{
              background: currentView === "findings" ? "#1f2937" : "transparent",
              color: currentView === "findings" ? "#ffffff" : "#9ca3af",
              border: "none",
              borderRadius: "6px",
              padding: "8px 14px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            Supervisory Findings
          </button>
          <button
            onClick={() => setCurrentView("comparison")}
            style={{
              background: currentView === "comparison" ? "#1f2937" : "transparent",
              color: currentView === "comparison" ? "#ffffff" : "#9ca3af",
              border: "none",
              borderRadius: "6px",
              padding: "8px 14px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            Peer Comparison &amp; Trends
          </button>
          <button
            onClick={() => setCurrentView("review")}
            style={{
              background: currentView === "review" ? "#1f2937" : "transparent",
              color: currentView === "review" ? "#ffffff" : "#9ca3af",
              border: "none",
              borderRadius: "6px",
              padding: "8px 14px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            Examiner Review
          </button>
          <button
            onClick={() => setCurrentView("integrity")}
            style={{
              background: currentView === "integrity" ? "#1f2937" : "transparent",
              color: currentView === "integrity" ? "#ffffff" : "#9ca3af",
              border: "none",
              borderRadius: "6px",
              padding: "8px 14px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            Evidence Custody &amp; Integrity
          </button>
          <button
            onClick={() => setCurrentView("reports")}
            style={{
              background: currentView === "reports" ? "#1f2937" : "transparent",
              color: currentView === "reports" ? "#ffffff" : "#9ca3af",
              border: "none",
              borderRadius: "6px",
              padding: "8px 14px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            Reports &amp; Exports
          </button>
        </nav>
      </header>

      {/* Main Content Area */}
      <main style={{ flex: 1 }}>
        {currentView === "overview" && (
          <SupervisoryOverview
            selectedEntityId={activeEntityId}
            selectedRunId={activeRunId}
            onNavigateToView={handleNavigate}
            onSelectEntity={(eId) => setActiveEntityId(eId)}
            onSelectPeriod={(subId, rId) => {
              setActiveSubmissionId(subId);
              if (rId) setActiveRunId(rId);
            }}
          />
        )}
        {currentView === "intake" && <SubmissionPage />}
        {currentView === "findings" && (
          <FindingsPage initialSubmissionId={activeSubmissionId || undefined} />
        )}
        {currentView === "comparison" && (
          <PeerComparisonAndTrends
            selectedEntityId={activeEntityId}
            selectedSubmissionId={activeSubmissionId}
            onNavigateToView={handleNavigate}
            onSelectEntity={(eId) => setActiveEntityId(eId)}
            onSelectPeriod={(subId, rId) => {
              setActiveSubmissionId(subId);
              if (rId) setActiveRunId(rId);
            }}
          />
        )}
        {currentView === "review" && <ExaminerWorkspace />}
        {currentView === "integrity" && <EvidenceIntegrityDashboard />}
        {currentView === "reports" && <ReportsPage />}
      </main>
    </div>
  );
};

export default App;
