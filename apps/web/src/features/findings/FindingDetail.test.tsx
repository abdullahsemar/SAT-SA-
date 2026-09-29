import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { FindingDetail } from "./FindingDetail";
import { apiClient, Finding, EvidenceChain } from "../../api/client";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual("../../api/client");
  return {
    ...actual,
    apiClient: {
      getEvidenceChain: vi.fn(),
    },
  };
});

describe("FindingDetail Component", () => {
  const mockFinding: Finding = {
    finding_id: "find-12345",
    run_id: "run-67890",
    submission_id: "sub-11111",
    cse_id: "CSE-BANK-01",
    rule_id: "POL-ESC-002",
    rule_title: "Escalation Policy Compliance and Timeliness",
    severity: "high",
    evidence_state: "potential_concern",
    primary_object_type: "case",
    primary_object_id: "CASE-OVERDUE-ESCALATION",
    affected_asset_ids: ["SRV-CORE-DB-01"],
    rationale: "Case CASE-OVERDUE-ESCALATION had an escalation SLA of 0.5h before snapshot cutoff, but was overdue.",
    uncertainty_note: "No approved exception matched; missing timely escalation.",
    supporting_records: [
      {
        source_id: "src-cases",
        record_id: "rec-case-01",
        record_type: "cases",
        locator: "case_id:CASE-OVERDUE-ESCALATION",
        native_id: "CASE-OVERDUE-ESCALATION",
        sha256: "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      },
    ],
    peer_comparison_status: "peer_comparison_unavailable",
    finding_metadata: { total_population: 1 },
    created_at: "2026-08-31T23:59:59Z",
  };

  const mockChain: EvidenceChain = {
    object_id: "CASE-OVERDUE-ESCALATION",
    object_type: "case",
    summary: {
      nodes_count: 2,
      edges_count: 1,
      events_count: 2,
      omissions_count: 0,
      uncertainties_count: 0,
    },
    timeline: [
      {
        timestamp: "2026-08-10T08:00:00Z",
        entity_type: "cases",
        entity_id: "CASE-OVERDUE-ESCALATION",
        event: "Case Created: CASE-OVERDUE-ESCALATION",
      },
      {
        timestamp: "2026-08-11T14:00:00Z",
        entity_type: "escalations",
        entity_id: "ACT-OVERDUE-DUP-01",
        event: "Escalated (escalation_attempt -> Security Team)",
      },
    ],
    related_entities: {
      nodes: [
        {
          id: "CASE-OVERDUE-ESCALATION",
          record_type: "cases",
          native_id: "CASE-OVERDUE-ESCALATION",
          label: "Case CASE-OVERDUE-ESCALATION (CRITICAL)",
        },
      ],
      edges: [],
    },
    uncertainties: [],
    omissions: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders finding details, uncertainty note, and peer comparison status", async () => {
    vi.mocked(apiClient.getEvidenceChain).mockResolvedValueOnce(mockChain);
    const onBack = vi.fn();

    render(<FindingDetail finding={mockFinding} onBack={onBack} />);

    expect(screen.getByText("POL-ESC-002")).toBeInTheDocument();
    expect(screen.getByText("Escalation Policy Compliance and Timeliness")).toBeInTheDocument();
    expect(screen.getByText("Potential Concern")).toBeInTheDocument();
    expect(screen.getByText("Peer Comparison: Unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Case CASE-OVERDUE-ESCALATION had an escalation SLA/)).toBeInTheDocument();
    expect(screen.getByText(/No approved exception matched/)).toBeInTheDocument();

    // Check supporting records
    expect(screen.getByText("src-cases")).toBeInTheDocument();
    expect(screen.getByText("case_id:CASE-OVERDUE-ESCALATION")).toBeInTheDocument();
    expect(screen.getByText("4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945")).toBeInTheDocument();

    // Check evidence chain timeline
    await waitFor(() => {
      expect(screen.getByText("Case Created: CASE-OVERDUE-ESCALATION")).toBeInTheDocument();
      expect(screen.getByText(/Escalated \(escalation_attempt/)).toBeInTheDocument();
    });

    // Test Back button
    const backBtn = screen.getByRole("button", { name: /Back to Findings/i });
    fireEvent.click(backBtn);
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
