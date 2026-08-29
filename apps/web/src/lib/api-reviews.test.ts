import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  isReviewQueuePage,
  isReviewCaseResult,
  getReviewQueue,
  resolveReview,
  type ReviewQueuePage,
  type ReviewCaseResult,
} from "./api-reviews";

const VALID_QUEUE_PAGE: ReviewQueuePage = {
  items: [
    {
      case_id: "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      signal_id: "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
      reason: "event_match_ambiguous",
      opened_at: "2026-08-29T12:00:00Z",
      title: "Suspected Dengue outbreak reported in District 5",
      source_name: "Local News",
      source_url: "https://news.example/dengue-outbreak",
      first_seen_at: "2026-08-29T12:00:00Z",
      retrieval_attempts: 0,
      extracted_disease_text: "dengue",
      canonical_disease: "Dengue",
      locations: [
        {
          location_role: "primary",
          precision: "place",
          country_name: "Vietnam",
          admin1_name: "Ho Chi Minh",
          place_name: "District 5",
          resolved_name: "District 5, Ho Chi Minh, Vietnam",
        },
      ],
      candidate_events: [
        {
          event_id: "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
          public_id: "EVT-2026-0042",
          title: "Dengue 2026 Outbreak",
          verification_status: "unverified",
          match_score: 0.85,
        },
      ],
      allowed_resolutions: ["link_event", "create_event", "dismiss"],
    },
  ],
  total_open_cases: 1,
  disease_options: [
    {
      id: "d4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a",
      canonical_name: "Dengue",
    },
  ],
  limit: 50,
  offset: 0,
};

const VALID_CASE_RESULT: ReviewCaseResult = {
  case_id: "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  signal_id: "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
  resolution: "link_event",
  processing_status: "matched",
  selected_disease_id: null,
  selected_event_id: "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
  resolved_at: "2026-08-29T12:05:00Z",
};

describe("api-reviews runtime validators", () => {
  it("accepts a valid ReviewQueuePage fixture", () => {
    expect(isReviewQueuePage(VALID_QUEUE_PAGE)).toBe(true);
  });

  it("rejects payload containing forbidden private keys like raw_text", () => {
    const leaked = { ...VALID_QUEUE_PAGE, raw_text: "secret payload text" };
    expect(isReviewQueuePage(leaked)).toBe(false);
  });

  it("rejects candidate with match score outside 0..1 range", () => {
    const invalidCandidate = {
      ...VALID_QUEUE_PAGE,
      items: [
        {
          ...VALID_QUEUE_PAGE.items[0],
          candidate_events: [
            {
              ...VALID_QUEUE_PAGE.items[0].candidate_events![0],
              match_score: 1.05,
            },
          ],
        },
      ],
    };
    expect(isReviewQueuePage(invalidCandidate)).toBe(false);
  });

  it("rejects invalid review reason", () => {
    const invalidReason = {
      ...VALID_QUEUE_PAGE,
      items: [
        {
          ...VALID_QUEUE_PAGE.items[0],
          reason: "not_a_valid_reason",
        },
      ],
    };
    expect(isReviewQueuePage(invalidReason)).toBe(false);
  });

  it("accepts a valid ReviewCaseResult fixture", () => {
    expect(isReviewCaseResult(VALID_CASE_RESULT)).toBe(true);
  });

  it("rejects invalid UUID in ReviewCaseResult", () => {
    const invalid = { ...VALID_CASE_RESULT, case_id: "invalid-uuid" };
    expect(isReviewCaseResult(invalid)).toBe(false);
  });
});

describe("getReviewQueue and resolveReview fetchers", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("getReviewQueue returns ready state on valid 200 response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => VALID_QUEUE_PAGE,
    } as Response);

    const result = await getReviewQueue("valid-token");
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.total_open_cases).toBe(1);
    }
  });

  it("getReviewQueue returns unauthorized on 401 response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Unauthorized" }),
    } as Response);

    const result = await getReviewQueue("invalid-token");
    expect(result.status).toBe("unauthorized");
  });

  it("resolveReview returns success state on 200", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => VALID_CASE_RESULT,
    } as Response);

    const result = await resolveReview(
      "valid-token",
      "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      {
        action: "link_event",
        event_id: "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
      },
    );
    expect(result.status).toBe("success");
  });

  it("resolveReview returns conflict state on 409", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Case already resolved" }),
    } as Response);

    const result = await resolveReview(
      "valid-token",
      "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      { action: "dismiss", note: "Duplicate" },
    );
    expect(result.status).toBe("conflict");
  });
});
