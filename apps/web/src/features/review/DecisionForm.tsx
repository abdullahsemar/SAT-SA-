import React, { useState } from "react";
import { apiClient, ReviewDecision, ReviewItem } from "../../api/client";

interface DecisionFormProps {
  item: ReviewItem;
  existingDecisions: ReviewDecision[];
  onDecisionSaved: (decision: ReviewDecision) => void;
}

export const DecisionForm: React.FC<DecisionFormProps> = ({
  item,
  existingDecisions,
  onDecisionSaved,
}) => {
  const isFindingLevel = !!item.finding_id;

  // Mode: "decision" vs "evidence_request"
  const [activeTab, setActiveTab] = useState<"decision" | "request">("decision");

  // Decision State
  const defaultState = isFindingLevel ? "substantiated" : "reviewed_no_concern";
  const [selectedState, setSelectedState] = useState<string>(defaultState);
  const [rationale, setRationale] = useState<string>("");
  const [citedIds, setCitedIds] = useState<string[]>([]);
  const [savingDecision, setSavingDecision] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  // Evidence Request State
  const [missingArtifact, setMissingArtifact] = useState("");
  const [distinguishingQuestion, setDistinguishingQuestion] = useState("");
  const [responsibleOwner, setResponsibleOwner] = useState("SOC Lead Analyst");
  const [dueDate, setDueDate] = useState("2026-09-30T17:00:00Z");
  const [savingRequest, setSavingRequest] = useState(false);
  const [requestSuccess, setRequestSuccess] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);

  const latestDecision = existingDecisions.length > 0 ? existingDecisions[existingDecisions.length - 1] : null;

  // Toggle cited evidence ID
  const toggleEvidenceId = (id: string) => {
    setCitedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSaveDecision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rationale.trim()) {
      setDecisionError("Rationale is required for supervisory determinations.");
      return;
    }

    setSavingDecision(true);
    setDecisionError(null);

    try {
      let saved: ReviewDecision;
      const supersededId = latestDecision ? latestDecision.id : null;

      if (isFindingLevel && item.finding_id) {
        saved = await apiClient.recordFindingDecision(item.finding_id, {
          state: selectedState,
          rationale: rationale.trim(),
          cited_evidence_ids: citedIds,
          superseded_decision_id: supersededId,
        });
      } else {
        saved = await apiClient.recordItemDecision(item.id, {
          state: selectedState,
          rationale: rationale.trim(),
          cited_evidence_ids: citedIds,
          superseded_decision_id: supersededId,
        });
      }

      setRationale("");
      onDecisionSaved(saved);
    } catch (err: any) {
      setDecisionError(err.message || "Failed to persist supervisory decision");
    } finally {
      setSavingDecision(false);
    }
  };

  const handleSaveEvidenceRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!missingArtifact.trim() || !distinguishingQuestion.trim()) {
      setRequestError("Missing artifact description and distinguishing question are required.");
      return;
    }

    setSavingRequest(true);
    setRequestError(null);
    setRequestSuccess(null);

    try {
      await apiClient.createEvidenceRequest({
        finding_id: item.finding_id,
        review_item_id: item.id,
        missing_artifact: missingArtifact.trim(),
        distinguishing_question: distinguishingQuestion.trim(),
        responsible_owner: responsibleOwner.trim(),
        due_date: dueDate,
      });

      setRequestSuccess("Evidence request logged in local audit registry.");
      setMissingArtifact("");
      setDistinguishingQuestion("");
    } catch (err: any) {
      setRequestError(err.message || "Failed to log evidence request");
    } finally {
      setSavingRequest(false);
    }
  };

  return (
    <div
      style={{
        background: "#ffffff",
        border: "1px solid #e5e7eb",
        borderRadius: "8px",
        padding: "20px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      }}
    >
      {/* Mode Navigation Tabs */}
      <div style={{ display: "flex", gap: "8px", marginBottom: "16px", borderBottom: "1px solid #e5e7eb", paddingBottom: "8px" }}>
        <button
          type="button"
          onClick={() => setActiveTab("decision")}
          style={{
            background: activeTab === "decision" ? "#111827" : "transparent",
            color: activeTab === "decision" ? "#ffffff" : "#4b5563",
            border: "none",
            borderRadius: "6px",
            padding: "6px 14px",
            fontSize: "12px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {isFindingLevel ? "Finding Determination" : "Item Review Decision"}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("request")}
          style={{
            background: activeTab === "request" ? "#111827" : "transparent",
            color: activeTab === "request" ? "#ffffff" : "#4b5563",
            border: "none",
            borderRadius: "6px",
            padding: "6px 14px",
            fontSize: "12px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Request Clarifying Evidence
        </button>
      </div>

      {activeTab === "decision" ? (
        <form onSubmit={handleSaveDecision}>
          <div style={{ marginBottom: "14px" }}>
            <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#374151", marginBottom: "6px" }}>
              Determination State
            </label>
            <select
              value={selectedState}
              onChange={(e) => setSelectedState(e.target.value)}
              style={{
                width: "100%",
                padding: "8px 12px",
                borderRadius: "6px",
                border: "1px solid #d1d5db",
                fontSize: "13px",
                background: "#ffffff",
              }}
            >
              {isFindingLevel ? (
                <>
                  <option value="substantiated">Substantiated (Evidence confirms supervisory proposition)</option>
                  <option value="not_substantiated">Not Substantiated (Disproved by supervisory inspection)</option>
                  <option value="additional_evidence_required">Additional Evidence Required</option>
                  <option value="not_applicable">Not Applicable</option>
                </>
              ) : (
                <>
                  <option value="reviewed_no_concern">Reviewed - No Concern (Control verified compliant)</option>
                  <option value="concern_observed">Concern Observed (Deficiency detected during review)</option>
                  <option value="additional_evidence_required">Additional Evidence Required</option>
                </>
              )}
            </select>
          </div>

          <div style={{ marginBottom: "14px" }}>
            <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#374151", marginBottom: "6px" }}>
              Supervisory Rationale & Notes (Required)
            </label>
            <textarea
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder="Detail observations, reconciliation findings, or grounds for determination..."
              rows={4}
              style={{
                width: "100%",
                padding: "10px 12px",
                borderRadius: "6px",
                border: "1px solid #d1d5db",
                fontSize: "13px",
                fontFamily: "inherit",
                resize: "vertical",
              }}
            />
          </div>

          {/* Evidence Citations Checkbox Selector */}
          {item.evidence_references && item.evidence_references.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#374151", marginBottom: "6px" }}>
                Cite Inspected Evidence Records
              </label>
              <div
                style={{
                  maxHeight: "120px",
                  overflowY: "auto",
                  border: "1px solid #e5e7eb",
                  borderRadius: "6px",
                  padding: "8px",
                  background: "#f9fafb",
                  display: "flex",
                  flexDirection: "column",
                  gap: "6px",
                }}
              >
                {item.evidence_references.map((ref, idx) => {
                  const refId = ref.native_id || ref.id || ref.source_id || `rec-${idx}`;
                  const isChecked = citedIds.includes(refId);
                  return (
                    <label key={idx} style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggleEvidenceId(refId)}
                      />
                      <span>
                        <strong>{ref.source_id}</strong> &bull; <code>{refId}</code> ({ref.locator || "record"})
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {latestDecision && (
            <div
              style={{
                marginBottom: "14px",
                padding: "8px 12px",
                background: "#f3f4f6",
                borderRadius: "6px",
                fontSize: "11px",
                color: "#4b5563",
              }}
            >
              <strong>Notice:</strong> Submitting will create Revision #{latestDecision.version + 1} and supersede Decision {latestDecision.id.substring(0, 8)}. Earlier decisions and machine findings remain preserved.
            </div>
          )}

          {decisionError && (
            <div
              style={{
                marginBottom: "14px",
                padding: "8px 12px",
                background: "#fee2e2",
                color: "#991b1b",
                borderRadius: "6px",
                fontSize: "12px",
              }}
            >
              {decisionError}
            </div>
          )}

          <button
            type="submit"
            disabled={savingDecision}
            style={{
              width: "100%",
              background: "#16a34a",
              color: "#ffffff",
              border: "none",
              borderRadius: "6px",
              padding: "10px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: savingDecision ? "not-allowed" : "pointer",
              opacity: savingDecision ? 0.7 : 1,
            }}
          >
            {savingDecision ? "Persisting Determination..." : latestDecision ? "Persist Superseding Determination" : "Persist Supervisory Determination"}
          </button>
        </form>
      ) : (
        <form onSubmit={handleSaveEvidenceRequest}>
          <div style={{ marginBottom: "12px" }}>
            <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#374151", marginBottom: "4px" }}>
              Missing Artifact Description
            </label>
            <input
              type="text"
              value={missingArtifact}
              onChange={(e) => setMissingArtifact(e.target.value)}
              placeholder="e.g. Sysmon Event ID 1 process tree export for SRV-CORE-DB-01"
              style={{
                width: "100%",
                padding: "8px 12px",
                borderRadius: "6px",
                border: "1px solid #d1d5db",
                fontSize: "13px",
              }}
            />
          </div>

          <div style={{ marginBottom: "12px" }}>
            <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#374151", marginBottom: "4px" }}>
              Distinguishing Supervisory Question
            </label>
            <textarea
              value={distinguishingQuestion}
              onChange={(e) => setDistinguishingQuestion(e.target.value)}
              placeholder="Specify what concrete evidentiary distinction would resolve the competing explanations..."
              rows={3}
              style={{
                width: "100%",
                padding: "8px 12px",
                borderRadius: "6px",
                border: "1px solid #d1d5db",
                fontSize: "13px",
                fontFamily: "inherit",
              }}
            />
          </div>

          <div style={{ display: "flex", gap: "10px", marginBottom: "14px" }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#374151", marginBottom: "4px" }}>
                Responsible Owner / Role
              </label>
              <input
                type="text"
                value={responsibleOwner}
                onChange={(e) => setResponsibleOwner(e.target.value)}
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  borderRadius: "6px",
                  border: "1px solid #d1d5db",
                  fontSize: "13px",
                }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", fontSize: "12px", fontWeight: 700, color: "#374151", marginBottom: "4px" }}>
                Due Date (UTC)
              </label>
              <input
                type="text"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  borderRadius: "6px",
                  border: "1px solid #d1d5db",
                  fontSize: "13px",
                }}
              />
            </div>
          </div>

          <div
            style={{
              marginBottom: "14px",
              padding: "8px 12px",
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              borderRadius: "6px",
              fontSize: "11px",
              color: "#1e40af",
              lineHeight: "1.4",
            }}
          >
            <strong>Local Audit Invariant:</strong> Evidence requests remain local records in the SAT-SA offline database. SAT-SA never dispatches emails or external notifications automatically.
          </div>

          {requestSuccess && (
            <div
              style={{
                marginBottom: "14px",
                padding: "8px 12px",
                background: "#ecfdf5",
                color: "#065f46",
                borderRadius: "6px",
                fontSize: "12px",
              }}
            >
              {requestSuccess}
            </div>
          )}

          {requestError && (
            <div
              style={{
                marginBottom: "14px",
                padding: "8px 12px",
                background: "#fee2e2",
                color: "#991b1b",
                borderRadius: "6px",
                fontSize: "12px",
              }}
            >
              {requestError}
            </div>
          )}

          <button
            type="submit"
            disabled={savingRequest}
            style={{
              width: "100%",
              background: "#4f46e5",
              color: "#ffffff",
              border: "none",
              borderRadius: "6px",
              padding: "10px",
              fontSize: "13px",
              fontWeight: 600,
              cursor: savingRequest ? "not-allowed" : "pointer",
              opacity: savingRequest ? 0.7 : 1,
            }}
          >
            {savingRequest ? "Logging Request..." : "Log Local Evidence Request"}
          </button>
        </form>
      )}
    </div>
  );
};
