import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { isRadarFeed, getRadarFeed, type RadarFeed } from "./api-radar";

const VALID_BRIEF: RadarFeed["items"][number]["brief"] = [
  {
    slot: "what_where",
    text: "Cholera outbreak reported in Luanda province.",
    reported: true,
  },
  {
    slot: "counts",
    text: "120 suspected cases and 4 deaths.",
    reported: true,
  },
  {
    slot: "timing",
    text: "Cases reported between August 20 and August 27.",
    reported: true,
  },
  {
    slot: "spread",
    text: "Spread observed across two municipal districts.",
    reported: true,
  },
  {
    slot: "reporting",
    text: "Reported by the Provincial Health Directorate.",
    reported: true,
  },
];

const VALID_EVENT_GROUP: RadarFeed["event_groups"][number] = {
  event_public_id: "EVT-2026-00042",
  event: {
    public_id: "EVT-2026-00042",
    verification_status: "officially_confirmed",
    early_signal_score: 0.88,
    evidence_score: 0.94,
  },
  signal_count: 2,
  representative_title: "Cholera outbreak in Luanda Province",
  representative_brief: VALID_BRIEF,
  representative_location: {
    role: "primary",
    precision: "admin1",
    label: "Luanda Province",
    country_code: "AO",
    latitude: -8.8383,
    longitude: 13.2344,
  },
  representative_source: {
    name: "WHO AFRO",
    url: "https://afro.who.int/report/123",
    is_official: true,
    credibility_tier: "official",
  },
  all_source_names: ["WHO AFRO", "Radio Nacional de Angola"],
  earliest_published_at: "2026-08-28T08:00:00Z",
  latest_published_at: "2026-08-28T10:00:00Z",
  first_seen_at: "2026-08-28T10:05:00Z",
};

const VALID_RADAR_FEED: RadarFeed = {
  event_groups: [VALID_EVENT_GROUP],
  items: [
    {
      id: "24681357-1234-5678-9abc-def012345678",
      title_english: "Cholera outbreak in Luanda Province",
      brief: VALID_BRIEF,
      signal_type: "outbreak_report",
      processing_status: "matched",
      published_at: "2026-08-28T10:00:00Z",
      first_seen_at: "2026-08-28T10:05:00Z",
      source: {
        name: "WHO AFRO",
        url: "https://afro.who.int/report/123",
        is_official: true,
        credibility_tier: "official",
      },
      extraction_confidence: 0.95,
      location: {
        role: "primary",
        precision: "admin1",
        label: "Luanda Province",
        country_code: "AO",
        latitude: -8.8383,
        longitude: 13.2344,
      },
      event_context_status: "attached",
      event: {
        public_id: "EVT-2026-00042",
        verification_status: "officially_confirmed",
        early_signal_score: 0.88,
        evidence_score: 0.94,
      },
    },
  ],
  window_start: "2026-08-26T12:00:00Z",
  window_end: "2026-08-28T12:00:00Z",
  hours: 48,
  limit: 50,
};

describe("isRadarFeed", () => {
  it("accepts a fully conforming radar feed", () => {
    expect(isRadarFeed(VALID_RADAR_FEED)).toBe(true);
  });

  it("accepts empty items array", () => {
    expect(
      isRadarFeed({
        ...VALID_RADAR_FEED,
        items: [],
      }),
    ).toBe(true);
  });

  it("accepts empty event_groups array", () => {
    expect(
      isRadarFeed({
        ...VALID_RADAR_FEED,
        event_groups: [],
      }),
    ).toBe(true);
  });

  it("accepts event group with null published timestamps", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.event_groups[0].earliest_published_at = null;
    feed.event_groups[0].latest_published_at = null;
    expect(isRadarFeed(feed)).toBe(true);
  });

  it("rejects a feed missing event_groups", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    delete feed.event_groups;
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects event group with signal_count below 2", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.event_groups[0].signal_count = 1;
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects event group with empty event_public_id", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.event_groups[0].event_public_id = "";
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects event group with invalid event context", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.event_groups[0].event.verification_status = "super_confirmed";
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects event group with empty representative_title", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.event_groups[0].representative_title = "";
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects event group with malformed representative brief", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    const tmp = feed.event_groups[0].representative_brief[0];
    feed.event_groups[0].representative_brief[0] =
      feed.event_groups[0].representative_brief[1];
    feed.event_groups[0].representative_brief[1] = tmp;
    expect(isRadarFeed(feed)).toBe(false);

    const feedMissing = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feedMissing.event_groups[0].representative_brief.pop();
    expect(isRadarFeed(feedMissing)).toBe(false);
  });

  it("rejects event group with empty or invalid all_source_names", () => {
    const feedEmpty = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feedEmpty.event_groups[0].all_source_names = [];
    expect(isRadarFeed(feedEmpty)).toBe(false);

    const feedBlank = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feedBlank.event_groups[0].all_source_names = ["WHO AFRO", ""];
    expect(isRadarFeed(feedBlank)).toBe(false);
  });

  it("rejects event group with invalid representative_source", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.event_groups[0].representative_source.url = "not-a-valid-url";
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects event group with non-ISO first_seen_at", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.event_groups[0].first_seen_at = "August 28, 2026";
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("accepts location with null coordinates", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.items[0].location.latitude = null;
    feed.items[0].location.longitude = null;
    feed.items[0].location.precision = "unresolved";
    expect(isRadarFeed(feed)).toBe(true);
  });

  it("accepts null location", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.items[0].location = null;
    expect(isRadarFeed(feed)).toBe(true);
  });

  it("accepts none and ambiguous event context statuses with null event", () => {
    const feedNone = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feedNone.items[0].event_context_status = "none";
    feedNone.items[0].event = null;
    expect(isRadarFeed(feedNone)).toBe(true);

    const feedAmbiguous = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feedAmbiguous.items[0].event_context_status = "ambiguous";
    feedAmbiguous.items[0].event = null;
    expect(isRadarFeed(feedAmbiguous)).toBe(true);
  });

  it("rejects when event is provided for none or ambiguous status", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.items[0].event_context_status = "none";
    // event is not null
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects attached status when event is null", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.items[0].event_context_status = "attached";
    feed.items[0].event = null;
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects brief with wrong slot order or missing slots", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    // Swap first two slots
    const tmp = feed.items[0].brief[0];
    feed.items[0].brief[0] = feed.items[0].brief[1];
    feed.items[0].brief[1] = tmp;
    expect(isRadarFeed(feed)).toBe(false);

    // Missing slot
    const feedMissing = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feedMissing.items[0].brief.pop();
    expect(isRadarFeed(feedMissing)).toBe(false);
  });

  it("rejects partially specified coordinates", () => {
    const feed1 = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed1.items[0].location.latitude = 12.0;
    feed1.items[0].location.longitude = null;
    expect(isRadarFeed(feed1)).toBe(false);

    const feed2 = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed2.items[0].location.latitude = null;
    feed2.items[0].location.longitude = 10.0;
    expect(isRadarFeed(feed2)).toBe(false);
  });

  it("rejects out of range coordinates", () => {
    const feed = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed.items[0].location.latitude = 95.0;
    expect(isRadarFeed(feed)).toBe(false);
  });

  it("rejects unknown credibility tier or invalid source URL", () => {
    const feed1 = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed1.items[0].source.credibility_tier = "super_high";
    expect(isRadarFeed(feed1)).toBe(false);

    const feed2 = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed2.items[0].source.url = "not-a-valid-url";
    expect(isRadarFeed(feed2)).toBe(false);
  });

  it("rejects date-only and non-ISO timestamp formats", () => {
    const feed1 = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed1.items[0].published_at = "2026-08-28";
    expect(isRadarFeed(feed1)).toBe(false);

    const feed2 = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed2.items[0].first_seen_at = "August 28, 2026 10:00:00 GMT";
    expect(isRadarFeed(feed2)).toBe(false);

    const feed3 = JSON.parse(JSON.stringify(VALID_RADAR_FEED));
    feed3.window_start = "2026-08-26";
    expect(isRadarFeed(feed3)).toBe(false);
  });
});

describe("getRadarFeed", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches and returns ready status on valid JSON response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => VALID_RADAR_FEED,
    } as Response);

    const result = await getRadarFeed({ hours: 24, limit: 10 });
    expect(result).toEqual({ status: "ready", data: VALID_RADAR_FEED });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/radar?hours=24&limit=10"),
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("returns unavailable when fetch fails or returns non-200", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 500,
    } as Response);

    const result = await getRadarFeed();
    expect(result).toEqual({ status: "unavailable", data: null });
  });

  it("returns unavailable when network throws error", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("Network failure"));

    const result = await getRadarFeed();
    expect(result).toEqual({ status: "unavailable", data: null });
  });

  it("returns unavailable when body fails schema validation", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ invalid: "payload" }),
    } as Response);

    const result = await getRadarFeed();
    expect(result).toEqual({ status: "unavailable", data: null });
  });
});
