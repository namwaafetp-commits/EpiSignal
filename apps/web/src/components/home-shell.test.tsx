import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardEvent, DashboardFeedState } from "../lib/api-dashboard";
import type { EventDetailResponse } from "../lib/api-events";
import { HomeShell } from "./home-shell";

const getEventDetail = vi.fn();
vi.mock("../lib/api-events", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api-events")>()),
  getEventDetail: (...args: unknown[]) => getEventDetail(...args),
}));

vi.mock("./event-map", () => ({
  EventMap: ({
    events,
    selectedId,
    onSelect,
    region,
  }: {
    events: DashboardEvent[];
    selectedId: string | null;
    onSelect: (publicId: string) => void;
    region: string;
  }) => (
    <div data-testid="mock-event-map">
      <span data-testid="map-region">{region}</span>
      <span>
        {events.filter((event) => event.map_level !== null).length} mapped /{" "}
        {events.length} events
      </span>
      <span data-testid="selected-marker">{selectedId ?? "none"}</span>
      {events.map((event) => (
        <span key={event.public_id}>{event.headline}</span>
      ))}
      <button onClick={() => onSelect(events[0]?.public_id)}>
        Open marker
      </button>
    </div>
  ),
}));

const EVENTS: DashboardEvent[] = [
  {
    public_id: "EVT-2026-00001",
    headline: "Cholera activity increasing in Cacuaco",
    summary: "Health officials are monitoring a cholera outbreak.",
    disease: "Cholera",
    event_type: "outbreak",
    status: "ongoing",
    country_code: "AO",
    admin1: "Cacuaco",
    first_reported_at: "2026-08-01T00:00:00Z",
    latest_report_at: "2026-08-30T10:00:00Z",
    article_count: 3,
    last_summarized_at: "2026-08-30T13:00:00Z",
    latitude: -8.58,
    longitude: 13.66,
    map_level: "admin1",
  },
  {
    public_id: "EVT-2026-00002",
    headline: "Dengue activity in Thailand",
    summary: "A country-level dengue summary.",
    disease: "Dengue",
    event_type: "outbreak",
    status: "monitoring",
    country_code: "TH",
    admin1: null,
    first_reported_at: "2026-08-01T00:00:00Z",
    latest_report_at: "2026-08-29T12:00:00Z",
    article_count: 1,
    last_summarized_at: "2026-08-29T13:00:00Z",
    latitude: null,
    longitude: null,
    map_level: null,
  },
];

const ready: DashboardFeedState = {
  status: "ready",
  data: { items: EVENTS, total: EVENTS.length },
};

const detail = {
  public_id: "EVT-2026-00001",
  headline: EVENTS[0].headline,
  summary: EVENTS[0].summary,
  disease: "Cholera",
  event_type: "outbreak",
  status: "ongoing",
  verification_status: "signal",
  country_code: "AO",
  admin1: "Cacuaco",
  admin2: null,
  first_reported_at: EVENTS[0].first_reported_at,
  latest_report_at: EVENTS[0].latest_report_at,
  article_count: 3,
  last_summarized_at: EVENTS[0].last_summarized_at,
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
    {
      signal_id: "22222222-2222-2222-2222-222222222222",
      title: "Angola health bulletin",
      source_name: "Angola Health Ministry",
      url: "https://example.org/angola-health",
      published_at: "2026-08-30T11:00:00Z",
      first_seen_at: "2026-08-30T11:05:00Z",
      is_official: true,
      is_primary: false,
      credibility_tier: "official",
      relationship_type: "corroborating",
    },
    {
      signal_id: "33333333-3333-3333-3333-333333333333",
      title: "Local cholera report",
      source_name: "Luanda News",
      url: "https://example.org/luanda-news",
      published_at: null,
      first_seen_at: "2026-08-30T10:00:00Z",
      is_official: false,
      is_primary: false,
      credibility_tier: "medium",
      relationship_type: "corroborating",
    },
    {
      signal_id: "44444444-4444-4444-4444-444444444444",
      title: "District situation report",
      source_name: "Cacuaco District",
      url: "https://example.org/cacuaco-report",
      published_at: null,
      first_seen_at: "2026-08-30T09:00:00Z",
      is_official: false,
      is_primary: false,
      credibility_tier: "medium",
      relationship_type: "corroborating",
    },
  ],
  observations: [],
  summaries: [
    {
      version: 1,
      headline: EVENTS[0].headline,
      summary: EVENTS[0].summary,
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

describe("HomeShell", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-31T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("defaults to Map, fills the full map view, and shows filtered stats", () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    expect(screen.getByRole("button", { name: "Map" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByRole("region", { name: /event map/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Filtered event statistics"),
    ).toHaveTextContent("2 EVENTS · 1 MAPPED · 2 COUNTRIES · 2 ACTIVE");
    expect(screen.queryByText("Recent events")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/map_level|processing_status/i),
    ).not.toBeInTheDocument();
  });

  it("selects a map marker and opens a floating detail panel", async () => {
    vi.useRealTimers();
    getEventDetail.mockResolvedValue(detail);
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    fireEvent.click(screen.getByRole("button", { name: "Open marker" }));
    expect(screen.getByTestId("selected-marker")).toHaveTextContent(
      "EVT-2026-00001",
    );
    expect(
      screen.getByRole("dialog", { name: /event details/i }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("dialog", { name: /event details/i })).getByText(
        "Public/global risk",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("Risk remains regional.")).toBeInTheDocument(),
    );
    const dialog = screen.getByRole("dialog", { name: /event details/i });
    expect(dialog.querySelector(".event-detail-panel__summary")).toHaveClass(
      "event-detail-panel__summary",
    );
    expect(
      within(dialog).getByRole("link", { name: /WHO AFRO/ }),
    ).toHaveAttribute("target", "_blank");
    expect(
      within(dialog).getByRole("link", { name: /WHO AFRO/ }),
    ).toHaveAttribute("href", "https://example.org/who-afro-cholera");
    expect(
      dialog.querySelectorAll(".event-detail-panel__source-links a"),
    ).toHaveLength(3);
    expect(within(dialog).getByText("+1 more sources")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Close event details" }),
    );
    expect(
      screen.queryByRole("dialog", { name: /event details/i }),
    ).not.toBeInTheDocument();
  });

  it("combines region, disease, and time filters and preserves them in Calendar", () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Thailand" },
    });
    expect(screen.getByText("Dengue activity in Thailand")).toBeInTheDocument();
    expect(
      screen.queryByText("Cholera activity increasing in Cacuaco"),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });

    expect(screen.getByRole("button", { name: "7D" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.change(screen.getByLabelText("Region"), {
      target: { value: "Asia" },
    });
    fireEvent.change(screen.getByLabelText("Disease"), {
      target: { value: "Dengue" },
    });
    expect(screen.getByText("Dengue activity in Thailand")).toBeInTheDocument();
    expect(
      screen.queryByText("Cholera activity increasing in Cacuaco"),
    ).not.toBeInTheDocument();

    expect(
      screen.getByText(/1 EVENTS · 0 MAPPED · 1 COUNTRIES · 1 ACTIVE/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(
      screen.getByRole("heading", { name: "Surveillance calendar" }),
    ).toBeInTheDocument();
    expect(screen.getByText("29 AUG 2026")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open event: Dengue activity/i }),
    ).toHaveAttribute("href", "/events/EVT-2026-00002");
    expect(screen.getByLabelText("Region")).toHaveValue("Asia");
    expect(screen.getByRole("button", { name: "7D" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("passes the selected region to the map without changing it for other filters", () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    expect(screen.getByTestId("map-region")).toHaveTextContent("");
    fireEvent.change(screen.getByLabelText("Region"), {
      target: { value: "Africa" },
    });
    expect(screen.getByTestId("map-region")).toHaveTextContent("Africa");

    fireEvent.change(screen.getByLabelText("Disease"), {
      target: { value: "Cholera" },
    });
    fireEvent.click(screen.getByRole("button", { name: "24H" }));
    expect(screen.getByTestId("map-region")).toHaveTextContent("Africa");
  });

  it("supports 24H, 30D, Custom, and ASEAN region filtering", () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    fireEvent.click(screen.getByRole("button", { name: "24H" }));
    expect(
      screen.queryByText("Cholera activity increasing in Cacuaco"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Dengue activity in Thailand"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "30D" }));
    expect(
      screen.getByText("Cholera activity increasing in Cacuaco"),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Region"), {
      target: { value: "ASEAN" },
    });
    expect(screen.getByText("Dengue activity in Thailand")).toBeInTheDocument();
    expect(
      screen.queryByText("Cholera activity increasing in Cacuaco"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Custom" }));
    expect(screen.getByLabelText("From")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-08-29" },
    });
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "2026-08-29" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByText("Dengue activity in Thailand")).toBeInTheDocument();
  });

  it("renders newest calendar group before older group", () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));

    const content = screen.getByRole("main").textContent ?? "";
    expect(content.indexOf("30 AUG 2026")).toBeLessThan(
      content.indexOf("29 AUG 2026"),
    );
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
      screen.getByText("No events match these filters."),
    ).toBeInTheDocument();
  });
});
