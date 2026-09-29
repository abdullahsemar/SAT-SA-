import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ReviewQueue } from "./ReviewQueue";
import { ReviewPortfolio, ReviewItem } from "../../api/client";

describe("ReviewQueue Component", () => {
  const mockItems: ReviewItem[] = [
    {
      id: "item-1",
      portfolio_id: "port-1",
      unit_id: "unit-tgt-1",
      unit_type: "case",
      finding_id: "find-1",
      scope: "case:CASE-OVERDUE-01",
      stratum: "targeted",
      selection_rank: 1,
      marginal_reasons: { why_selected: "High marginal gain for escalation timeliness" },
      evidence_references: [],
      unknowns: [],
      what_examiner_learns: "Verify escalation notes",
      estimated_review_minutes: 15.0,
      created_at: "2026-08-31T23:59:59Z",
    },
    {
      id: "item-2",
      portfolio_id: "port-1",
      unit_id: "unit-ctrl-1",
      unit_type: "case",
      finding_id: null,
      scope: "case:CASE-NORMAL-01",
      stratum: "control",
      selection_rank: 2,
      marginal_reasons: { why_selected: "Drawn from unflagged eligible control population" },
      evidence_references: [],
      unknowns: [],
      what_examiner_learns: "Audit baseline SOP compliance",
      estimated_review_minutes: 7.0,
      created_at: "2026-08-31T23:59:59Z",
    },
    {
      id: "item-3",
      portfolio_id: "port-1",
      unit_id: "unit-exp-1",
      unit_type: "asset_period",
      finding_id: null,
      scope: "asset:SRV-UNHEALTHY-01:2026-08",
      stratum: "exploratory",
      selection_rank: 3,
      marginal_reasons: { why_selected: "Absence-of-coverage exploratory evaluation" },
      evidence_references: [],
      unknowns: ["Sensor disconnected"],
      what_examiner_learns: "Inspect silence vs telemetry failure",
      estimated_review_minutes: 12.0,
      created_at: "2026-08-31T23:59:59Z",
    },
  ];

  const mockPortfolio: ReviewPortfolio = {
    id: "port-1",
    run_id: "run-1",
    entity_id: "CSE-BANK-01",
    created_by: "examiner1",
    revision: 1,
    seed: 42,
    parameters: { max_items: 20, seed: 42 },
    summary: {
      total_review_minutes: 34.0,
      hypotheses_covered_count: 3,
      shortfalls: { targeted: 0, control: 1, exploratory: 0 },
    },
    sampling_frame: { eligible_control_cases_count: 5 },
    items: mockItems,
    created_at: "2026-08-31T23:59:59Z",
  };

  it("renders portfolio header, seed, and shortfall alert", () => {
    const onSelect = vi.fn();
    render(
      <ReviewQueue
        portfolio={mockPortfolio}
        selectedItemId="item-1"
        onSelectItem={onSelect}
      />
    );

    expect(screen.getByText(/Review Portfolio \(Rev #1\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Seed: 42/i)).toBeInTheDocument();
    expect(screen.getByText(/Quota Shortfall:/i)).toBeInTheDocument();
    expect(screen.getByText(/control: -1/i)).toBeInTheDocument();
  });

  it("renders review items with correct stratum labels and ranks", () => {
    const onSelect = vi.fn();
    render(
      <ReviewQueue
        portfolio={mockPortfolio}
        selectedItemId="item-1"
        onSelectItem={onSelect}
      />
    );

    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("case:CASE-OVERDUE-01")).toBeInTheDocument();
    expect(screen.getByText("Targeted")).toBeInTheDocument();

    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(screen.getByText("case:CASE-NORMAL-01")).toBeInTheDocument();
    expect(screen.getByText("Control Sample")).toBeInTheDocument();

    expect(screen.getByText("#3")).toBeInTheDocument();
    expect(screen.getByText("asset:SRV-UNHEALTHY-01:2026-08")).toBeInTheDocument();
    expect(screen.getByText("Exploratory")).toBeInTheDocument();
  });

  it("filters items by stratum when tabs are clicked", () => {
    const onSelect = vi.fn();
    render(
      <ReviewQueue
        portfolio={mockPortfolio}
        selectedItemId="item-1"
        onSelectItem={onSelect}
      />
    );

    const controlTab = screen.getByRole("button", { name: /Control \(1\)/i });
    fireEvent.click(controlTab);

    expect(screen.getByText("case:CASE-NORMAL-01")).toBeInTheDocument();
    expect(screen.queryByText("case:CASE-OVERDUE-01")).not.toBeInTheDocument();
  });

  it("calls onSelectItem when an item row is clicked", () => {
    const onSelect = vi.fn();
    render(
      <ReviewQueue
        portfolio={mockPortfolio}
        selectedItemId="item-1"
        onSelectItem={onSelect}
      />
    );

    const controlItem = screen.getByText("case:CASE-NORMAL-01");
    fireEvent.click(controlItem);

    expect(onSelect).toHaveBeenCalledWith(mockItems[1]);
  });
});
