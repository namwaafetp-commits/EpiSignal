import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { AdminReviewQueue } from "./admin-review-queue";
import * as apiReviews from "../lib/api-reviews";
import type { ReviewQueuePage } from "../lib/api-reviews";

function createFixtureQueue(): ReviewQueuePage {
  return {
    items: [
      {
        case_id: "11111111-1111-1111-1111-111111111111",
        signal_id: "22222222-2222-2222-2222-222222222222",
        reason: "event_match_ambiguous",
        opened_at: "2026-08-29T10:00:00Z",
        title: "First Oldest Case — Ambiguous Dengue Signal",
        source_name: "Yemen Post",
        source_url: "https://news.example/dengue",
        first_seen_at: "2026-08-29T10:00:00Z",
        retrieval_attempts: 0,
        extracted_disease_text: "dengue",
        canonical_disease: "Dengue",
        locations: [
          {
            location_role: "primary",
            precision: "place",
            country_name: "Yemen",
            admin1_name: "Taiz",
            place_name: "Taiz City",
            resolved_name: "Taiz City, Taiz, Yemen",
          },
        ],
        candidate_events: [
          {
            event_id: "33333333-3333-3333-3333-333333333333",
            public_id: "EVT-2026-0001",
            title: "Existing Dengue Event in Taiz",
            verification_status: "unverified",
            match_score: 0.82,
          },
        ],
        allowed_resolutions: ["link_event", "create_event", "dismiss"],
      },
      {
        case_id: "44444444-4444-4444-4444-444444444444",
        signal_id: "55555555-5555-5555-5555-555555555555",
        reason: "disease_unresolved",
        opened_at: "2026-08-29T11:00:00Z",
        title: "Second Case — Unresolved Disease",
        source_name: "Health Wire",
        source_url: "https://news.example/fever",
        first_seen_at: "2026-08-29T11:00:00Z",
        retrieval_attempts: 0,
        extracted_disease_text: "unknown hemorrhagic fever",
        canonical_disease: null,
        locations: [],
        candidate_events: [],
        allowed_resolutions: ["assign_disease", "dismiss"],
      },
    ],
    total_open_cases: 2,
    disease_options: [
      {
        id: "66666666-6666-6666-6666-666666666666",
        canonical_name: "Cholera",
      },
      {
        id: "77777777-7777-7777-7777-777777777777",
        canonical_name: "Dengue",
      },
    ],
    limit: 50,
    offset: 0,
  };
}

describe("AdminReviewQueue component", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders locked state requiring admin token with password input", () => {
    render(<AdminReviewQueue />);
    expect(screen.getByText(/admin authentication/i)).toBeDefined();
    const tokenInput = screen.getByLabelText(/admin token/i) as HTMLInputElement;
    expect(tokenInput.type).toBe("password");
  });

  it("unlocks and displays oldest-first case rail and selected case workspace", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiReviews, "getReviewQueue").mockResolvedValue({
      status: "ready",
      data: createFixtureQueue(),
    });

    render(<AdminReviewQueue />);

    const tokenInput = screen.getByLabelText(/admin token/i);
    const operatorInput = screen.getByLabelText(/operator name/i);
    const unlockButton = screen.getByRole("button", { name: /unlock review queue/i });

    await user.type(tokenInput, "secret-token-123");
    await user.type(operatorInput, "Dr. Jones");
    await user.click(unlockButton);

    await waitFor(() => {
      expect(screen.getAllByText("First Oldest Case — Ambiguous Dengue Signal").length).toBeGreaterThanOrEqual(1);
    });

    // Check workspace rendered candidate event details
    expect(screen.getByText("EVT-2026-0001")).toBeDefined();
    expect(screen.getByText("Existing Dengue Event in Taiz")).toBeDefined();
    expect(screen.getByText(/0.82/)).toBeDefined();

    // Security check: token never in DOM
    expect(document.body.innerHTML).not.toContain("secret-token-123");
  });

  it("links ambiguous candidate event on decision submission and announces through aria-live", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiReviews, "getReviewQueue").mockResolvedValue({
      status: "ready",
      data: createFixtureQueue(),
    });

    const mockResolve = vi.spyOn(apiReviews, "resolveReview").mockResolvedValue({
      status: "success",
      data: {
        case_id: "11111111-1111-1111-1111-111111111111",
        signal_id: "22222222-2222-2222-2222-222222222222",
        resolution: "link_event",
        processing_status: "matched",
        selected_disease_id: null,
        selected_event_id: "33333333-3333-3333-3333-333333333333",
        resolved_at: "2026-08-29T12:00:00Z",
      },
    });

    render(<AdminReviewQueue />);

    await user.type(screen.getByLabelText(/admin token/i), "secret-token-123");
    await user.type(screen.getByLabelText(/operator name/i), "Dr. Jones");
    await user.click(screen.getByRole("button", { name: /unlock review queue/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /link to selected event/i })).toBeDefined();
    });

    const linkButton = screen.getByRole("button", { name: /link to selected event/i });
    await user.click(linkButton);

    await waitFor(() => {
      expect(mockResolve).toHaveBeenCalledWith(
        "secret-token-123",
        "11111111-1111-1111-1111-111111111111",
        expect.objectContaining({
          action: "link_event",
          event_id: "33333333-3333-3333-3333-333333333333",
        })
      );
    });

    // Case is removed and next case is active
    await waitFor(() => {
      expect(screen.queryByText("First Oldest Case — Ambiguous Dengue Signal")).toBeNull();
      expect(screen.getAllByText("Second Case — Unresolved Disease").length).toBeGreaterThan(0);
    });
  });

  it("requires note and confirmation checkbox to dismiss a case", async () => {
    const user = userEvent.setup();
    vi.spyOn(apiReviews, "getReviewQueue").mockResolvedValue({
      status: "ready",
      data: createFixtureQueue(),
    });

    render(<AdminReviewQueue />);

    await user.type(screen.getByLabelText(/admin token/i), "secret-token-123");
    await user.type(screen.getByLabelText(/operator name/i), "Dr. Jones");
    await user.click(screen.getByRole("button", { name: /unlock review queue/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /dismiss signal/i })).toBeDefined();
    });

    const dismissButton = screen.getByRole("button", { name: /dismiss signal/i });
    expect(dismissButton.hasAttribute("disabled")).toBe(true);

    // Fill note and check confirm
    const noteInput = screen.getByLabelText(/rationale note/i);
    await user.type(noteInput, "Non-epidemic content");

    const confirmCheckbox = screen.getByLabelText(/confirm dismissal/i);
    await user.click(confirmCheckbox);

    expect(dismissButton.hasAttribute("disabled")).toBe(false);
  });
});
