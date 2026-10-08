import { describe, expect, it } from "vitest";
import type { DashboardEvent } from "./api-dashboard";
import { filterEvents, readFilters } from "./event-filters";

function event(publicId: string, latestReportAt: string): DashboardEvent {
  return {
    public_id: publicId,
    headline: publicId,
    summary: "summary",
    disease: "Dengue",
    event_type: "outbreak",
    status: "monitoring",
    country_code: "TH",
    admin1: null,
    first_reported_at: latestReportAt,
    latest_report_at: latestReportAt,
    article_count: 1,
    last_summarized_at: latestReportAt,
    latitude: null,
    longitude: null,
    map_level: null,
  };
}

describe("Briefing filter ordering", () => {
  it("preserves the server's ranked order when requested", () => {
    const events = [
      event("EVT-RANKED-OLDER", "2026-09-17T10:00:00Z"),
      event("EVT-RANKED-NEWER", "2026-09-17T11:00:00Z"),
    ];

    expect(
      filterEvents(
        events,
        readFilters("", "briefing"),
        Date.parse("2026-09-17T12:00:00Z"),
        true,
      ).map((item) => item.public_id),
    ).toEqual(["EVT-RANKED-OLDER", "EVT-RANKED-NEWER"]);
  });
});
