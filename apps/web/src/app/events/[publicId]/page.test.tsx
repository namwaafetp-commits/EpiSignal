import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EventDetailResponse } from "@/lib/api-events";
import * as apiEvents from "@/lib/api-events";
import EventPage from "./page";

vi.mock("next/navigation", () => ({
  notFound: vi.fn(),
}));

const detail = {
  public_id: "EVT-2026-00001",
  headline: "Cholera activity increasing in Cacuaco",
  summary: "Health officials are monitoring a cholera outbreak.",
  disease: "Cholera",
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
      snapshot: {
        cases: "68 confirmed cases",
        deaths: null,
        cfr: null,
        geographic_extent: "Cacuaco",
      },
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
  });

  it("uses homepage dark theme, readable location, and direct source links", async () => {
    const page = await EventPage({
      params: Promise.resolve({ publicId: detail.public_id }),
    });
    render(page);

    expect(screen.getByRole("main")).toHaveClass("event-page");
    expect(screen.getByText("Cacuaco, 🇦🇴 Angola")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /WHO AFRO cholera update/i }),
    ).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: /Back to map/i })).toHaveAttribute(
      "href",
      "/",
    );
  });
});
