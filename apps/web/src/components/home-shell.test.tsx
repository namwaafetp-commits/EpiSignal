import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DashboardEvent, DashboardFeedState } from "../lib/api-dashboard";
import { HomeShell } from "./home-shell";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("./event-map", () => ({
  EventMap: ({
    events,
    onSelect,
  }: {
    events: DashboardEvent[];
    onSelect: (publicId: string) => void;
  }) => (
    <div data-testid="mock-event-map">
      <span>
        {events.filter((event) => event.map_level !== null).length} mapped /{" "}
        {events.length} events
      </span>
      <button onClick={() => onSelect(events[0]?.public_id)}>
        Open marker
      </button>
    </div>
  ),
}));

const EVENTS: DashboardEvent[] = [
  {
    public_id: "EVT-2026-00001",
    headline: "Cholera in Cacuaco",
    summary: "Health officials are monitoring a cholera outbreak.",
    disease: "Cholera",
    event_type: "outbreak",
    status: "ongoing",
    country_code: "AO",
    town: "Cacuaco",
    first_reported_at: "2026-08-01T00:00:00Z",
    latest_report_at: "2026-08-30T00:00:00Z",
    article_count: 3,
    last_summarized_at: "2026-08-30T01:00:00Z",
    latitude: -8.58,
    longitude: 13.66,
    map_level: "town",
  },
  {
    public_id: "EVT-2026-00002",
    headline: "Dengue in Thailand",
    summary: "A country-level dengue summary.",
    disease: "Dengue",
    event_type: "outbreak",
    status: "monitoring",
    country_code: "TH",
    town: null,
    first_reported_at: "2025-01-01T00:00:00Z",
    latest_report_at: "2025-01-02T00:00:00Z",
    article_count: 1,
    last_summarized_at: "2025-01-03T00:00:00Z",
    latitude: 15.87,
    longitude: 100.99,
    map_level: "country",
  },
];

const ready: DashboardFeedState = {
  status: "ready",
  data: { items: EVENTS, total: EVENTS.length },
};

describe("HomeShell", () => {
  it("renders every summarized event and map counts", () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    expect(
      screen.getByRole("heading", { name: "Summarized Events" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2 events · 2 mapped")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /View event: Cholera in Cacuaco/i }),
    ).toHaveAttribute("href", "/events/EVT-2026-00001");
    expect(
      screen.getByText("A country-level dengue summary."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/signals plotted|48h|Recent Signals/i),
    ).not.toBeInTheDocument();
  });

  it("routes a map marker to the existing event detail page", async () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    screen.getByRole("button", { name: "Open marker" }).click();

    expect(push).toHaveBeenCalledWith("/events/EVT-2026-00001");
  });

  it("renders loading, unavailable, and empty states", () => {
    const { rerender } = render(
      <HomeShell
        apiStatus="loading"
        eventFeed={{ status: "loading", data: null }}
      />,
    );
    expect(screen.getByText("Loading summarized events…")).toBeInTheDocument();

    rerender(
      <HomeShell
        apiStatus="unavailable"
        eventFeed={{ status: "unavailable", data: null }}
      />,
    );
    expect(
      screen.getByText(/API could not load summaries/i),
    ).toBeInTheDocument();

    rerender(
      <HomeShell
        apiStatus="ready"
        eventFeed={{ status: "ready", data: { items: [], total: 0 } }}
      />,
    );
    expect(
      screen.getByText("No summarized events stored."),
    ).toBeInTheDocument();
  });
});
