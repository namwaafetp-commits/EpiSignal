import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  analyticsEventNames,
  countBucket,
  sourceDomain,
  trackPageView,
  trackEvent,
  trackSearchUsed,
  type AnalyticsEvent,
} from "./analytics";
import { getUmamiScriptProps } from "./umami-config";

describe("Umami configuration", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("does not render a script when either public setting is missing", () => {
    vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "website-id");
    vi.stubEnv("NEXT_PUBLIC_UMAMI_SCRIPT_URL", "");

    expect(getUmamiScriptProps()).toBeNull();
  });

  it("renders one non-blocking script with the configured website id", () => {
    vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "website-id");
    vi.stubEnv(
      "NEXT_PUBLIC_UMAMI_SCRIPT_URL",
      "https://stats.example/script.js",
    );

    expect(getUmamiScriptProps()).toEqual({
      id: "episignal-umami",
      src: "https://stats.example/script.js",
      strategy: "afterInteractive",
      "data-website-id": "website-id",
      "data-auto-track": "true",
      "data-auto-pageview": "false",
      "data-exclude-search": "true",
    });
  });
});

describe("analytics event boundary", () => {
  const track = vi.fn();

  beforeEach(() => {
    track.mockReset();
    vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "website-id");
    vi.stubEnv(
      "NEXT_PUBLIC_UMAMI_SCRIPT_URL",
      "https://stats.example/script.js",
    );
    window.umami = { track };
  });

  afterEach(() => {
    delete window.umami;
    vi.unstubAllEnvs();
  });

  it("accepts only the approved event names", () => {
    expect(analyticsEventNames).toEqual([
      "view_switch",
      "theme_change",
      "filter_change",
      "search_used",
      "map_event_open",
      "briefing_event_open",
      "reading_pane_open",
      "full_event_open",
      "source_click",
    ]);

    const events: AnalyticsEvent[] = [
      { name: "view_switch", properties: { view: "map" } },
      { name: "theme_change", properties: { theme: "dark" } },
      { name: "filter_change", properties: { filter: "country" } },
      { name: "search_used", properties: { results_bucket: "1-5" } },
      {
        name: "map_event_open",
        properties: { disease_group: "vector_borne", host_sector: "human" },
      },
      {
        name: "briefing_event_open",
        properties: {
          disease_group: "vector_borne",
          host_sector: "human",
          source_count_bucket: "6-20",
        },
      },
      { name: "reading_pane_open", properties: {} },
      { name: "full_event_open", properties: {} },
      { name: "source_click", properties: { source_domain: "who.int" } },
    ];

    for (const event of events) trackEvent(event);

    expect(track).toHaveBeenCalledTimes(events.length);
  });

  it("is a no-op when Umami is not loaded", () => {
    delete window.umami;

    expect(() =>
      trackEvent({ name: "full_event_open", properties: {} }),
    ).not.toThrow();
  });

  it("requires both public settings before sending", () => {
    vi.stubEnv("NEXT_PUBLIC_UMAMI_SCRIPT_URL", "");

    trackEvent({ name: "full_event_open", properties: {} });

    expect(track).not.toHaveBeenCalled();
  });

  it("buckets search counts without accepting search text", () => {
    trackSearchUsed(0);
    trackSearchUsed(3);
    trackSearchUsed(12);
    trackSearchUsed(21);

    expect([0, 3, 12, 21].map(countBucket)).toEqual([
      "0",
      "1-5",
      "6-20",
      "20+",
    ]);

    expect(track.mock.calls.map(([payload]) => payload.data)).toEqual([
      { results_bucket: "0" },
      { results_bucket: "1-5" },
      { results_bucket: "6-20" },
      { results_bucket: "20+" },
    ]);
  });

  it("normalizes source links to a bounded domain value", () => {
    expect(sourceDomain("https://www.who.int/news/item?secret=1")).toBe(
      "who.int",
    );
    expect(sourceDomain("https://reuters.com/world/story")).toBe("reuters.com");
    expect(sourceDomain("https://private.example/article")).toBe("other");
    expect(sourceDomain("not a url")).toBe("other");
  });

  it("never forwards private content in analytics payloads", () => {
    trackSearchUsed(2);
    trackEvent({
      name: "source_click",
      properties: { source_domain: sourceDomain("https://www.who.int/story") },
    });
    trackEvent({
      name: "briefing_event_open",
      properties: {
        disease_group: "other_infectious",
        host_sector: "unknown",
        source_count_bucket: "1-5",
      },
    });

    const payload = JSON.stringify(track.mock.calls);
    expect(payload).not.toContain("search query");
    expect(payload).not.toContain("headline");
    expect(payload).not.toContain("summary");
    expect(payload).not.toContain("EVT-2026-00001");
    expect(payload).not.toContain("https://www.who.int/story");
    expect(track).toHaveBeenCalledWith({
      website: "website-id",
      url: "/",
      title: "EpiSignal — Map",
      name: "source_click",
      data: { source_domain: "who.int" },
    });
  });

  it("sanitizes event-detail paths for custom events and page views", () => {
    window.history.replaceState(null, "", "/events/EVT-2026-00001");

    trackPageView(window.location.pathname);
    trackEvent({ name: "full_event_open", properties: {} });

    expect(track).toHaveBeenNthCalledWith(1, {
      website: "website-id",
      url: "/events/:public_id",
      title: "EpiSignal — Event",
    });
    expect(track).toHaveBeenNthCalledWith(2, {
      website: "website-id",
      url: "/events/:public_id",
      title: "EpiSignal — Event",
      name: "full_event_open",
      data: {},
    });
    expect(JSON.stringify(track.mock.calls)).not.toContain("EVT-2026-00001");
  });
});
