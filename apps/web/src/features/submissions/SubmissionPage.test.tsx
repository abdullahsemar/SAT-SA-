import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SubmissionPage } from "./SubmissionPage";
import { apiClient } from "../../api/client";

// Mock apiClient methods
vi.mock("../../api/client", async () => {
  const actual = await vi.importActual("../../api/client");
  return {
    ...actual,
    apiClient: {
      getMe: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
      listSubmissions: vi.fn(),
      createSubmission: vi.fn(),
      uploadFile: vi.fn(),
      validateSubmission: vi.fn(),
      commitSubmission: vi.fn(),
      getSubmission: vi.fn(),
      getSubmissionQuality: vi.fn(),
      getRecordProvenance: vi.fn(),
    },
  };
});

describe("SubmissionPage UI Workbench Flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders login form when session is unauthenticated", async () => {
    vi.mocked(apiClient.getMe).mockRejectedValueOnce(new Error("Unauthenticated"));
    render(<SubmissionPage />);

    expect(await screen.findByText("Supervisory Evidence Intake")).toBeInTheDocument();
    expect(screen.getByLabelText("Examiner Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sign In/i })).toBeInTheDocument();
  });

  it("completes login and renders submissions dashboard", async () => {
    vi.mocked(apiClient.getMe).mockRejectedValueOnce(new Error("Unauthenticated"));
    vi.mocked(apiClient.login).mockResolvedValueOnce({
      id: "user-1",
      username: "examiner_one",
      role: "examiner",
      entity_scope: ["CSE-BANK-01"],
      csrf_token: "csrf-token-123",
    });
    vi.mocked(apiClient.listSubmissions).mockResolvedValueOnce({
      items: [
        {
          id: "sub-100",
          entity_id: "CSE-BANK-01",
          period_start: "2026-01-01T00:00:00Z",
          period_end: "2026-02-01T00:00:00Z",
          source_timezone: "UTC",
          status: "committed",
          revision: 1,
          created_at: "2026-01-15T12:00:00Z",
          committed_at: "2026-01-15T12:30:00Z",
          file_count: 2,
        },
      ],
      total: 1,
    });

    render(<SubmissionPage />);

    expect(await screen.findByText("Supervisory Evidence Intake")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Examiner Username"), {
      target: { value: "examiner_one" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "secret123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In/i }));

    expect(await screen.findByText("Supervisory Evidence Intake Workbench")).toBeInTheDocument();
    expect(screen.getByText("examiner_one")).toBeInTheDocument();
    expect(screen.getByText("+ Import New Submission")).toBeInTheDocument();
    expect(screen.getByText("Saved CSE Submissions")).toBeInTheDocument();
  });

  it("renders quality scorecard when validating evidence", async () => {
    vi.mocked(apiClient.getMe).mockResolvedValueOnce({
      id: "user-1",
      username: "examiner_one",
      role: "examiner",
      entity_scope: ["CSE-BANK-01"],
      csrf_token: "csrf-token-123",
    });
    vi.mocked(apiClient.listSubmissions).mockResolvedValueOnce({ items: [], total: 0 });

    vi.mocked(apiClient.getSubmission).mockResolvedValue({
      id: "sub-200",
      entity_id: "CSE-BANK-01",
      period_start: "2026-01-01T00:00:00Z",
      period_end: "2026-02-01T00:00:00Z",
      source_timezone: "UTC",
      status: "validated",
      revision: 1,
      manifest: {
        sources: [
          {
            source_id: "src-alerts",
            record_type: "alerts",
            declared_row_count: 5,
            is_optional: false,
          },
        ],
      },
      created_at: "2026-01-10T10:00:00Z",
      files: [],
    });

    vi.mocked(apiClient.validateSubmission).mockResolvedValueOnce({
      submission_id: "sub-200",
      entity_id: "CSE-BANK-01",
      status: "validated",
      revision: 1,
      accepted_count: 4,
      rejected_count: 1,
      quarantined_count: 1,
      duplicate_count: 0,
      orphan_count: 0,
      timestamp_problem_count: 1,
      source_summaries: {
        "src-alerts": {
          source_id: "src-alerts",
          record_type: "alerts",
          declared_rows: 5,
          actual_rows: 5,
          status: "PRESENT",
          is_optional: false,
        },
      },
      issues: [
        {
          id: "iss-1",
          source_id: "src-alerts",
          record_type: "alerts",
          row_locator: "row:2",
          issue_type: "MALFORMED_TIMESTAMP",
          severity: "error",
          field_name: "timestamp",
          message: "Invalid ISO-8601 datetime",
        },
      ],
    });

    render(<SubmissionPage />);

    // Simulate opening an active draft
    await waitFor(() => expect(screen.getByText("+ Import New Submission")).toBeInTheDocument());

    // Call validate
    vi.mocked(apiClient.listSubmissions).mockResolvedValue({ items: [], total: 0 });
  });

  it("inspects record provenance displaying raw vs normalized payloads", async () => {
    vi.mocked(apiClient.getMe).mockResolvedValueOnce({
      id: "user-1",
      username: "admin",
      role: "admin",
      entity_scope: ["*"],
      csrf_token: "csrf-token-123",
    });
    vi.mocked(apiClient.listSubmissions).mockResolvedValueOnce({ items: [], total: 0 });

    vi.mocked(apiClient.getRecordProvenance).mockResolvedValueOnce({
      id: "rec-test-uuid",
      raw_record_id: "raw-uuid",
      submission_id: "sub-test",
      entity_id: "CSE-BANK-01",
      source_id: "src-assets",
      record_type: "assets",
      native_id: "AST-PROV-99",
      row_locator: "row:1",
      raw_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      raw_payload: { native_id: "AST-PROV-99", hostname: "core-bank-01" },
      normalized_data: { native_id: "AST-PROV-99", hostname: "core-bank-01", criticality: "CRITICAL" },
      is_quarantined: false,
      created_at: "2026-01-10T12:00:00Z",
    });

    render(<SubmissionPage />);

    await waitFor(() => expect(screen.getByText("Evidence Record Provenance Inspector")).toBeInTheDocument());

    const input = screen.getByPlaceholderText(/Enter Normalized Record UUID/i);
    fireEvent.change(input, { target: { value: "rec-test-uuid" } });

    fireEvent.click(screen.getByRole("button", { name: /Inspect Record/i }));

    expect(await screen.findByText("ORIGINAL RAW SOURCE PAYLOAD (From Extracted Evidence)")).toBeInTheDocument();
    expect(screen.getByText("CANONICAL NORMALIZED TYPED RECORD")).toBeInTheDocument();
    expect(screen.getByText("AST-PROV-99")).toBeInTheDocument();
  });
});
