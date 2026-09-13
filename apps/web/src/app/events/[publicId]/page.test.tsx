import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EventDetailResponse } from "@/lib/api-events";
import * as apiEvents from "@/lib/api-events";
import * as apiDashboard from "@/lib/api-dashboard";
import type { DashboardEvent } from "@/lib/api-dashboard";
import EventPage from "./page";

vi.mock("next/navigation", () => ({
  notFound: vi.fn(),
}));

const detail = {
  public_id: "EVT-2026-00001",
  headline: "Cholera activity increasing in Cacuaco",
  summary: "Health officials are monitoring a cholera outbreak.",
  disease: "Cholera",
  disease_group: "enteric_food_waterborne",
  disease_group_label: "Enteric / food- & water-borne infections",
  host_sector: "human",
  event_type: "outbreak",
  status: "ongoing",
  verification_status: "signal",
  country_code: "AO",
  admin1: "Cacuaco",
  admin2: null,
  first_reported_at: "2026-08-01T00:00:00Z",
  latest_report_at: "2026-08-30T10:00:00Z",
  article_count: 1,
  last_summarized_at: "2026-08-30T13:00:00Z",
  early_signal_score: 0.8,
  evidence_score: 0.7,
  locations: [],
  sources: [
    {
      signal_id: "11111111-1111-1111-1111-111111111111",
      title: "WHO AFRO cholera update",
      source_name: "WHO AFRO",
      url: "https://example.org/who-afro-cholera",
      published_at: "2026-08-30T12:00:00Z",
      first_seen_at: "2026-08-30T12:05:00Z",
      is_official: true,
      is_primary: true,
      credibility_tier: "official",
      relationship_type: "primary",
    },
  ],
  observations: [],
  summaries: [
    {
      version: 1,
      headline: "Cholera activity increasing in Cacuaco",
      summary: "Health officials are monitoring a cholera outbreak.",
      trajectory: "Increasing",
      snapshot: ["68 confirmed cases", "Cacuaco"],
      key_driver: "Ongoing local transmission.",
      response: "Case investigation is underway.",
      risk: "Risk remains regional.",
      model_id: "test-model",
      created_at: "2026-08-30T13:00:00Z",
    },
  ],
} satisfies EventDetailResponse;

describe("EventPage", () => {
  beforeEach(() => {
    vi.spyOn(apiEvents, "getEventDetail").mockResolvedValue(detail);
    vi.spyOn(apiDashboard, "getDashboardEvents").mockResolvedValue({
      status: "unavailable",
      data: null,
    });
  });

  it("renders one editorial headline, compact provenance, and direct source links", async () => {
    const page = await EventPage({
      params: Promise.resolve({ publicId: detail.public_id }),
    });
    render(page);

    expect(screen.getByRole("main")).toHaveClass("event-content");
    expect(screen.getByText("Cacuaco, Angola")).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { name: detail.headline }),
    ).toHaveLength(1);
    expect(screen.getByText("THE BRIEF")).toBeVisible();
    expect(
      screen.getByRole("link", { name: /WHO AFRO cholera update/i }),
    ).toHaveAttribute("target", "_blank");
    expect(screen.getByText("01")).toBeVisible();
    // The top navigation carries the way back now.
    expect(
      screen.queryByRole("link", { name: /Back to briefing/i }),
    ).toBeNull();
    // Removed in favour of the headline and brief carrying the page.
    expect(
      screen.queryByRole("heading", { name: "EVENT TIMELINE" }),
    ).toBeNull();
    expect(screen.queryByText("First seen")).toBeNull();
  });

  it("renders legacy structured brief content under The Brief", async () => {
    const page = await EventPage({
      params: Promise.resolve({ publicId: detail.public_id }),
    });
    render(page);

    expect(screen.getByRole("heading", { name: "THE BRIEF" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "The Snapshot" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Key Driver" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Response" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Public/Global Risk" }),
    ).toBeVisible();
    expect(screen.getByText(/68 confirmed cases \| Cacuaco/)).toBeVisible();
    expect(screen.getByText("Ongoing local transmission.")).toBeVisible();
    expect(screen.getByText("Case investigation is underway.")).toBeVisible();
  });

  it("falls back to legacy summary text when structured fields are absent", async () => {
    vi.spyOn(apiEvents, "getEventDetail").mockResolvedValueOnce({
      ...detail,
      summary: "Legacy summary text.",
      summaries: [
        {
          ...detail.summaries[0],
          summary: "Legacy summary text.",
          snapshot: null,
          key_driver: null,
          response: null,
          risk: null,
        },
      ],
    });

    const page = await EventPage({
      params: Promise.resolve({ publicId: detail.public_id }),
    });
    render(page);

    expect(screen.getByText("Legacy summary text.")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "The Snapshot" })).toBeNull();
  });

  it("renders the flexible summary payload without legacy headings", async () => {
    vi.spyOn(apiEvents, "getEventDetail").mockResolvedValueOnce({
      ...detail,
      summary_payload: {
        title: "Dengue activity is being monitored",
        bullets: [
          "Cases were reported in the affected area.",
          "Local response teams are investigating.",
          "Further reporting is expected.",
        ],
        takeaway: "Watch for evidence of wider transmission.",
      },
    });

    const page = await EventPage({
      params: Promise.resolve({ publicId: detail.public_id }),
    });
    render(page);

    expect(screen.getByRole("heading", { name: "THE BRIEF" })).toBeVisible();
    expect(
      screen.queryByRole("heading", {
        name: "Dengue activity is being monitored",
      }),
    ).toBeNull();
    expect(
      screen.getByText("Cases were reported in the affected area."),
    ).toBeVisible();
    expect(
      screen.getByText(/Watch for evidence of wider transmission/),
    ).toBeVisible();
    expect(screen.queryByRole("heading", { name: "The Snapshot" })).toBeNull();
  });

  it("leads with three sources and collapses the rest of the trail", async () => {
    vi.spyOn(apiEvents, "getEventDetail").mockResolvedValueOnce({
      ...detail,
      sources: Array.from({ length: 7 }, (_, i) => ({
        ...detail.sources[0],
        signal_id: `0000000${i}-1111-1111-1111-111111111111`,
        title: `Linked report ${i + 1}`,
        url: `https://example.org/report-${i + 1}`,
      })),
    });

    const page = await EventPage({
      params: Promise.resolve({ publicId: detail.public_id }),
    });
    render(page);

    expect(screen.getByRole("heading", { name: "SOURCES · 7" })).toBeVisible();
    // All seven stay in the DOM and keep their numbering; four are collapsed.
    expect(screen.getAllByRole("link", { name: /Linked report/ })).toHaveLength(
      7,
    );
    expect(screen.getByText("Show 4 more sources")).toBeVisible();
    expect(screen.getByText("03")).toBeVisible();
    expect(screen.getByText("04")).not.toBeVisible();
  });

  it("lists related reporting as plain headlines, ranked by shared metadata", async () => {
    const sibling = {
      public_id: "EVT-2026-00002",
      headline: "Cholera cases reported in a neighbouring district",
      summary: "More cholera reporting.",
      disease: "Cholera",
      disease_group: "enteric_food_waterborne",
      disease_group_label: "Enteric / food- & water-borne infections",
      host_sector: "human",
      event_type: "outbreak",
      status: "ongoing",
      country_code: "AO",
      admin1: "Cacuaco",
      first_reported_at: "2026-08-02T00:00:00Z",
      latest_report_at: "2026-08-29T10:00:00Z",
      article_count: 2,
      last_summarized_at: "2026-08-29T13:00:00Z",
      latitude: null,
      longitude: null,
      map_level: null,
    } as DashboardEvent;

    vi.spyOn(apiDashboard, "getDashboardEvents").mockResolvedValueOnce({
      status: "ready",
      data: { items: [sibling], total: 1 },
    });

    const page = await EventPage({
      params: Promise.resolve({ publicId: detail.public_id }),
    });
    render(page);

    expect(
      screen.getByRole("heading", { name: "RELATED REPORTING" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: sibling.headline }),
    ).toHaveAttribute("href", "/events/EVT-2026-00002");
    // Headlines only: no score, no match reasons, no standing caveat.
    expect(screen.queryByText(/Match score/)).toBeNull();
    expect(screen.queryByText(/Same disease group/)).toBeNull();
  });
});
