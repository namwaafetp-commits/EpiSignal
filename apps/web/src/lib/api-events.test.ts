import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  isEventListResponse,
  getEventList,
  getEventDetail,
} from "./api-events";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function okResponse(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

describe("isEventListResponse", () => {
  it("accepts a shaped events list", () => {
    const body = {
      items: [
        {
          public_id: "EVT-2026-00042",
          headline: "Dengue in Chiang Mai",
          summary: "Ongoing outbreak.",
          disease: "Dengue",
          event_type: "outbreak",
          status: "ongoing",
          verification_status: "signal",
          country_code: "TH",
          admin1: "Chiang Mai",
          admin2: null,
          first_reported_at: "2026-08-25T00:00:00Z",
          latest_report_at: "2026-08-28T12:00:00Z",
          article_count: 3,
          last_summarized_at: null,
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    };
    expect(isEventListResponse(body)).toBe(true);
  });

  it("rejects an item without a public_id", () => {
    const body = {
      items: [{ headline: "no id" }],
      total: 1,
      limit: 20,
      offset: 0,
    };
    expect(isEventListResponse(body)).toBe(false);
  });
});

describe("getEventList", () => {
  it("returns unavailable when fetch fails", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    const result = await getEventList({ limit: 10 });
    expect(result.status).toBe("unavailable");
  });

  it("returns ready when the response is shaped", async () => {
    const body = {
      items: [
        {
          public_id: "EVT-2026-00042",
          headline: "Dengue in Chiang Mai",
          summary: null,
          disease: null,
          event_type: "outbreak",
          status: "monitoring",
          verification_status: "signal",
          country_code: null,
          admin1: null,
          admin2: null,
          first_reported_at: null,
          latest_report_at: "2026-08-28T12:00:00Z",
          article_count: 1,
          last_summarized_at: null,
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    };
    fetchMock.mockResolvedValue(okResponse(body));
    const result = await getEventList({ limit: 20 });
    expect(result.status).toBe("ready");
  });
});

describe("getEventDetail", () => {
  it("returns null for a 404", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({}),
    } as Response);
    const detail = await getEventDetail("EVT-NOPE");
    expect(detail).toBeNull();
  });
});
