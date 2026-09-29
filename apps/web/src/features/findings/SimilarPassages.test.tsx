import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SimilarPassages } from "./SimilarPassages";
import { apiClient, SimilarPassagesResponse } from "../../api/client";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual("../../api/client");
  return {
    ...actual,
    apiClient: {
      getSimilarPassages: vi.fn(),
    },
  };
});

describe("SimilarPassages Component", () => {
  const mockCompletedResponse: SimilarPassagesResponse = {
    finding_id: "find-12345",
    status: "completed",
    semantic_mode: "auto",
    method_used: "semantic_all_minilm_l6_v2",
    model_revision: "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    manifest_digest: "a1b2c3d4e5f6",
    target_passage: "Verified source IP belongs to authorized external scanner.",
    target_span: {
      start_char: 0,
      end_char: 58,
      record_id: "CASE-FAST-WITH-ARTIFACTS",
    },
    matches: [
      {
        match_id: "match-001",
        source_id: "src-cases",
        record_type: "cases",
        record_id: "CASE-PREV-SCANNER",
        start_char: 12,
        end_char: 70,
        matched_text: "Source IP verified as approved vulnerability scanner activity.",
        similarity: 0.892,
        method: "semantic_all_minilm_l6_v2",
        possible_explanation: "possible_playbook_template",
        caveats: "Comparative semantic similarity evidence for human examiner review.",
      },
    ],
    disclaimer: "Similarity evidence is comparative decision support for human examiners.",
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders side-by-side passages with character spans and supervisory notice", async () => {
    (apiClient.getSimilarPassages as any).mockResolvedValue(mockCompletedResponse);

    render(<SimilarPassages findingId="find-12345" />);

    expect(screen.getByText(/Loading persisted passage similarity evidence/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Similar Investigation Passages")).toBeInTheDocument();
    });

    // Check method badge
    expect(screen.getByText("Semantic (all-MiniLM-L6-v2)")).toBeInTheDocument();

    // Check target passage
    expect(
      screen.getByText("Verified source IP belongs to authorized external scanner.")
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Span:/i).length).toBeGreaterThanOrEqual(1);

    // Check matched passage
    expect(
      screen.getByText("Source IP verified as approved vulnerability scanner activity.")
    ).toBeInTheDocument();

    // Check explanation badge
    expect(screen.getByText("Possible Playbook Template")).toBeInTheDocument();

    // Check supervisory notice
    expect(screen.getByText(/Supervisory Notice:/i)).toBeInTheDocument();
  });

  it("renders lexical fallback badge and notice when fallback is engaged", async () => {
    const fallbackResponse: SimilarPassagesResponse = {
      ...mockCompletedResponse,
      method_used: "lexical_fallback",
      fallback_reason: "model_offline_unverified",
      matches: [
        {
          ...mockCompletedResponse.matches[0],
          method: "lexical_fallback",
        },
      ],
    };
    (apiClient.getSimilarPassages as any).mockResolvedValue(fallbackResponse);

    render(<SimilarPassages findingId="find-12345" />);

    await waitFor(() => {
      expect(screen.getByText("Lexical Fallback")).toBeInTheDocument();
    });
    expect(screen.getByText(/model_offline_unverified/i)).toBeInTheDocument();
  });

  it("displays informative message when semantic mode is disabled", async () => {
    const disabledResponse: SimilarPassagesResponse = {
      finding_id: "find-12345",
      status: "disabled",
      semantic_mode: "off",
      method_used: "disabled",
      matches: [],
      disclaimer: "Similarity evidence is comparative decision support for human examiners.",
    };
    (apiClient.getSimilarPassages as any).mockResolvedValue(disabledResponse);

    render(<SimilarPassages findingId="find-12345" />);

    await waitFor(() => {
      expect(screen.getByText(/Semantic Mode Disabled:/i)).toBeInTheDocument();
    });
  });

  it("displays informative message when no passage was evaluated", async () => {
    const notComputedResponse: SimilarPassagesResponse = {
      finding_id: "find-12345",
      status: "not_computed",
      semantic_mode: "auto",
      method_used: "none",
      matches: [],
      disclaimer: "Similarity evidence is comparative decision support for human examiners.",
    };
    (apiClient.getSimilarPassages as any).mockResolvedValue(notComputedResponse);

    render(<SimilarPassages findingId="find-12345" />);

    await waitFor(() => {
      expect(screen.getByText(/No Passage Evaluated:/i)).toBeInTheDocument();
    });
  });
});
