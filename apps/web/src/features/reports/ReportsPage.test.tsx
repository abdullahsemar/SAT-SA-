import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ReportsPage } from "./ReportsPage";
import { apiClient, ReportResponse } from "../../api/client";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<any>("../../api/client");
  return {
    ...actual,
    apiClient: {
      listReports: vi.fn(),
      createReport: vi.fn(),
      getReportHtmlUrl: vi.fn((id: string) => `/api/v1/reports/${id}/html`),
      getReportJsonUrl: vi.fn((id: string) => `/api/v1/reports/${id}/json`),
      getReportManifestUrl: vi.fn((id: string) => `/api/v1/reports/${id}/manifest`),
      getReportBundleUrl: vi.fn((id: string) => `/api/v1/reports/${id}/bundle`),
      getReportProofUrl: vi.fn((id: string) => `/api/v1/reports/${id}/proof`),
    },
  };
});

describe("ReportsPage Component", () => {
  const mockReports: ReportResponse[] = [
    {
      id: "rep-12345678-abcd",
      run_id: "run-87654321-wxyz",
      portfolio_id: "port-11112222",
      entity_id: "CSE-BANK-01",
      created_by: "examiner_smith",
      decision_cutoff_time: "2026-09-20T12:00:00Z",
      status: "completed",
      report_schema_version: "v1.0",
      notes: "Annual examination export",
      created_at: "2026-09-20T12:05:00Z",
      completed_at: "2026-09-20T12:05:02Z",
      html_url: "/api/v1/reports/rep-12345678-abcd/html",
      json_url: "/api/v1/reports/rep-12345678-abcd/json",
      manifest_url: "/api/v1/reports/rep-12345678-abcd/manifest",
      bundle_url: "/api/v1/reports/rep-12345678-abcd/bundle",
      error_message: null,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders reports table with report IDs, status, and download links", async () => {
    vi.mocked(apiClient.listReports).mockResolvedValueOnce({
      reports: mockReports,
      total: 1,
    });

    render(<ReportsPage entityId="CSE-BANK-01" />);

    expect(screen.getByText("Loading reports...")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Supervisory Assessment Reports")).toBeInTheDocument();
    });

    expect(screen.getByText("rep-1234")).toBeInTheDocument();
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
    expect(screen.getByText("HTML")).toBeInTheDocument();
    expect(screen.getByText("JSON")).toBeInTheDocument();
    expect(screen.getByText("Manifest")).toBeInTheDocument();
    expect(screen.getByText("Bundle (.zip)")).toBeInTheDocument();
  });

  it("shows empty state when no reports are present", async () => {
    vi.mocked(apiClient.listReports).mockResolvedValueOnce({
      reports: [],
      total: 0,
    });

    render(<ReportsPage entityId="CSE-BANK-01" />);

    await waitFor(() => {
      expect(screen.getByText("No reports generated yet")).toBeInTheDocument();
    });
  });

  it("opens modal and submits new report creation", async () => {
    vi.mocked(apiClient.listReports).mockResolvedValueOnce({
      reports: [],
      total: 0,
    });
    vi.mocked(apiClient.createReport).mockResolvedValueOnce(mockReports[0]);

    render(<ReportsPage entityId="CSE-BANK-01" runId="run-87654321-wxyz" />);

    await waitFor(() => {
      expect(screen.getByText("No reports generated yet")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("+ Generate New Report"));

    expect(screen.getByText("Generate Assessment Report")).toBeInTheDocument();

    const submitBtn = screen.getByText("Generate Snapshot & Report");
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(apiClient.createReport).toHaveBeenCalledWith(
        expect.objectContaining({
          run_id: "run-87654321-wxyz",
        })
      );
    });
  });
});
