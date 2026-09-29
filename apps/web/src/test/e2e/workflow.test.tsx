import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import App from "../../App";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<any>("../../api/client");
  return {
    ...actual,
    apiClient: {
      getMe: vi.fn().mockResolvedValue({
        id: "user-1",
        username: "lead_examiner",
        role: "examiner",
        entity_scope: ["CSE-BANK-01"],
      }),
      getCurrentUser: vi.fn().mockResolvedValue({
        id: "user-1",
        username: "lead_examiner",
        role: "examiner",
        entity_scope: ["CSE-BANK-01"],
      }),
      listSubmissions: vi.fn().mockResolvedValue([]),
      listFindings: vi.fn().mockResolvedValue([]),
      listReviewPortfolios: vi.fn().mockResolvedValue([
        {
          id: "port-e2e-0001",
          run_id: "run-e2e-0001",
          entity_id: "CSE-BANK-01",
          created_by: "lead_examiner",
          revision: 1,
          seed: 42,
          parameters: {},
          summary: { selected_count: 1, strata_counts: { targeted: 1 } },
          sampling_frame: {},
          items: [],
          created_at: "2026-09-20T12:00:00Z",
        },
      ]),
      listReports: vi.fn().mockResolvedValue({
        reports: [
          {
            id: "rep-e2e-0001",
            run_id: "run-e2e-0001",
            portfolio_id: "port-e2e-0001",
            entity_id: "CSE-BANK-01",
            created_by: "lead_examiner",
            decision_cutoff_time: "2026-09-20T12:00:00Z",
            status: "completed",
            report_schema_version: "v1.0",
            notes: "End-to-end verification report",
            created_at: "2026-09-20T12:05:00Z",
            completed_at: "2026-09-20T12:05:02Z",
            html_url: "/api/v1/reports/rep-e2e-0001/html",
            json_url: "/api/v1/reports/rep-e2e-0001/json",
            manifest_url: "/api/v1/reports/rep-e2e-0001/manifest",
            bundle_url: "/api/v1/reports/rep-e2e-0001/bundle",
            error_message: null,
          },
        ],
        total: 1,
      }),
      createReport: vi.fn().mockResolvedValue({
        id: "rep-e2e-0002",
        run_id: "run-e2e-0001",
        portfolio_id: null,
        entity_id: "CSE-BANK-01",
        created_by: "lead_examiner",
        decision_cutoff_time: "2026-09-20T12:10:00Z",
        status: "completed",
        report_schema_version: "v1.0",
        notes: null,
        created_at: "2026-09-20T12:10:01Z",
        completed_at: "2026-09-20T12:10:03Z",
        html_url: "/api/v1/reports/rep-e2e-0002/html",
        json_url: "/api/v1/reports/rep-e2e-0002/json",
        manifest_url: "/api/v1/reports/rep-e2e-0002/manifest",
        bundle_url: "/api/v1/reports/rep-e2e-0002/bundle",
        error_message: null,
      }),
      getReportHtmlUrl: vi.fn((id: string) => `/api/v1/reports/${id}/html`),
      getReportJsonUrl: vi.fn((id: string) => `/api/v1/reports/${id}/json`),
      getReportManifestUrl: vi.fn((id: string) => `/api/v1/reports/${id}/manifest`),
      getReportBundleUrl: vi.fn((id: string) => `/api/v1/reports/${id}/bundle`),
      getReportProofUrl: vi.fn((id: string) => `/api/v1/reports/${id}/proof`),
    },
  };
});

// Frontend Component & Workflow Tests (Mocked API)
// Note: This suite verifies frontend UI component integration using mocked API responses.
// Real end-to-end acceptance verification is performed against the live backend via test_end_to_end.py
// and browser smoke verification.

describe("Frontend Component/Workflow Test (Mocked API): Intake -> Review -> Reports Export", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("navigates across all application views and verifies reports export workspace", async () => {
    render(<App />);

    // Default view: Evidence Intake
    expect(screen.getByText("Evidence Intake")).toBeInTheDocument();
    expect(screen.getByText("Supervisory Findings")).toBeInTheDocument();
    expect(screen.getByText("Examiner Review")).toBeInTheDocument();
    expect(screen.getByText("Reports & Exports")).toBeInTheDocument();

    // Click Examiner Review tab
    fireEvent.click(screen.getByText("Examiner Review"));
    await waitFor(() => {
      expect(screen.getByText(/Review Portfolio/i)).toBeInTheDocument();
    });


    // Click Reports & Exports tab
    fireEvent.click(screen.getByText("Reports & Exports"));
    await waitFor(() => {
      expect(screen.getByText("Supervisory Assessment Reports")).toBeInTheDocument();
    });

    // Check report listed
    expect(screen.getByText("rep-e2e-")).toBeInTheDocument();
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
    expect(screen.getByText("Bundle (.zip)")).toBeInTheDocument();
  });
});
