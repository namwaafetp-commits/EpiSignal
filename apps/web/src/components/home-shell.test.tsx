import {
  fireEvent,
  cleanup,
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
const track = vi.fn();
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
    disease_group: "enteric_food_waterborne",
    disease_group_label: "Enteric / food- & water-borne infections",
    host_sector: "human",
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
    disease_group: "vector_borne",
    disease_group_label: "Vector-borne infections",
    host_sector: "both",
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
  disease_group: "enteric_food_waterborne",
  disease_group_label: "Enteric / food- & water-borne infections",
  host_sector: "human",
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

const NOW = Date.parse("2026-08-31T12:00:00Z");

describe("HomeShell UI v2", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_UMAMI_WEBSITE_ID", "website-id");
    vi.stubEnv(
      "NEXT_PUBLIC_UMAMI_SCRIPT_URL",
      "https://stats.example/script.js",
    );
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-08-31T12:00:00Z"));
    window.history.replaceState(null, "", "/");
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    getEventDetail.mockResolvedValue(detail);
    track.mockReset();
    window.umami = { track };
  });
  afterEach(() => {
    cleanup();
    delete window.umami;
    vi.unstubAllEnvs();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
  it("opens a map preview with sources, closes with Escape and restores focus", async () => {
    // The map opens on Today, so widen the window to reach the fixtures.
    window.history.replaceState(null, "", "/?period=72h");
    render(<HomeShell now={NOW} apiStatus="ready" eventFeed={ready} />);
    const marker = screen.getByRole("button", { name: "Open marker" });
    marker.focus();
    fireEvent.click(marker);
    const pane = screen.getByRole("dialog", { name: "Event details" });
    await waitFor(() =>
      expect(
        within(pane).getByRole("link", { name: /WHO AFRO cholera update/ }),
      ).toHaveAttribute("href", "https://example.org/who-afro-cholera"),
    );
    expect(
      within(pane).getByRole("link", { name: "View full event" }),
    ).toHaveAttribute("href", "/events/EVT-2026-00001?period=72h");
    fireEvent.click(
      within(pane).getByRole("link", { name: "View full event" }),
    );
    expect(track).toHaveBeenCalledWith(
      expect.objectContaining({ name: "full_event_open", data: {} }),
    );
    fireEvent.keyDown(pane, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(marker).toHaveFocus();
  });

  it("tracks map selection and pane opening with controlled properties", () => {
    window.history.replaceState(null, "", "/?period=72h");
    render(<HomeShell now={NOW} apiStatus="ready" eventFeed={ready} />);

    fireEvent.click(screen.getByRole("button", { name: "Open marker" }));

    expect(track).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "reading_pane_open",
        data: {},
      }),
    );
    expect(track).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "map_event_open",
        data: {
          disease_group: "enteric_food_waterborne",
          host_sector: "human",
        },
      }),
    );
  });
  it("renders a headline-first briefing and opens a reading pane", async () => {
    render(
      <HomeShell
        now={NOW}
        view="briefing"
        apiStatus="ready"
        eventFeed={ready}
      />,
    );
    expect(screen.getByRole("heading", { name: "The Briefing" })).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: EVENTS[0].headline }));
    expect(screen.getByRole("dialog", { name: "Event details" })).toBeVisible();
    expect(track).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "briefing_event_open",
        data: {
          disease_group: "enteric_food_waterborne",
          host_sector: "human",
          source_count_bucket: "1-5",
        },
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Loading source links…"),
      ).not.toBeInTheDocument(),
    );
  });
  it("combines URL filters and includes both-sector events under Animal", async () => {
    window.history.replaceState(
      null,
      "",
      "/briefing?period=7d&host=animal&disease_group=vector_borne&country=TH",
    );
    render(
      <HomeShell
        now={NOW}
        view="briefing"
        apiStatus="ready"
        eventFeed={ready}
      />,
    );
    expect(
      screen.getByRole("link", { name: EVENTS[1].headline }),
    ).toBeVisible();
    expect(
      screen.queryByRole("link", { name: EVENTS[0].headline }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Host")).toHaveValue("animal");
    fireEvent.change(screen.getByLabelText("Search"), {
      target: { value: "no-such-event" },
    });
    // Search commits on a pause rather than per keystroke.
    await waitFor(() =>
      expect(window.location.search).toContain("q=no-such-event"),
    );
    expect(screen.getByText("No events match these filters.")).toBeVisible();
    window.history.replaceState(null, "", "/briefing?period=30d");
    fireEvent.popState(window);
    expect(
      screen.getByRole("link", { name: EVENTS[0].headline }),
    ).toBeVisible();
    expect(screen.getByLabelText("Host")).toHaveValue("");
  });
  it("supports UTC Today, rolling periods and inclusive custom dates", () => {
    render(
      <HomeShell
        now={NOW}
        view="briefing"
        apiStatus="ready"
        eventFeed={ready}
      />,
    );
    fireEvent.change(screen.getByLabelText("Period"), {
      target: { value: "today" },
    });
    expect(track).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "filter_change",
        data: { filter: "period" },
      }),
    );
    expect(screen.getByText("No events match these filters.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Period"), {
      target: { value: "3d" },
    });
    expect(
      screen.getByRole("link", { name: EVENTS[1].headline }),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Period"), {
      target: { value: "custom" },
    });
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-08-29" },
    });
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "2026-08-29" },
    });
    expect(
      screen.getByRole("link", { name: EVENTS[1].headline }),
    ).toBeVisible();
    expect(
      screen.queryByRole("link", { name: EVENTS[0].headline }),
    ).not.toBeInTheDocument();
    expect(window.location.search).toContain("from=2026-08-29");
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-09-01" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose a valid date range",
    );
  });
  it("searches country names and preserves query on full-event links", async () => {
    render(
      <HomeShell
        now={NOW}
        view="briefing"
        apiStatus="ready"
        eventFeed={ready}
      />,
    );
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Angola" },
    });
    await waitFor(() =>
      expect(
        screen.getByRole("link", { name: EVENTS[0].headline }),
      ).toHaveAttribute("href", "/events/EVT-2026-00001?q=Angola"),
    );
    expect(track).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "search_used",
        data: { results_bucket: "1-5" },
      }),
    );
    expect(
      screen.queryByRole("link", { name: EVENTS[1].headline }),
    ).not.toBeInTheDocument();
  });
  it("keeps native modified-click navigation", () => {
    render(
      <HomeShell
        now={NOW}
        view="briefing"
        apiStatus="ready"
        eventFeed={ready}
      />,
    );
    fireEvent.click(screen.getByRole("link", { name: EVENTS[0].headline }), {
      ctrlKey: true,
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("distinguishes unavailable, loading and empty feed", () => {
    const view = render(
      <HomeShell
        now={NOW}
        apiStatus="loading"
        eventFeed={{ status: "loading", data: null }}
      />,
    );
    expect(screen.getByText("Loading summarized events…")).toBeVisible();
    view.rerender(
      <HomeShell
        now={NOW}
        apiStatus="unavailable"
        eventFeed={{ status: "unavailable", data: null }}
      />,
    );
    expect(screen.getByText(/API could not load summaries/)).toBeVisible();
    view.rerender(
      <HomeShell
        now={NOW}
        apiStatus="ready"
        eventFeed={{ status: "ready", data: { items: [], total: 0 } }}
      />,
    );
    expect(screen.getByText("No events match these filters.")).toBeVisible();
  });

  it("offers a way out of an empty result", () => {
    window.history.replaceState(null, "", "/briefing?period=7d&country=ZZ");
    render(
      <HomeShell
        now={NOW}
        view="briefing"
        apiStatus="ready"
        eventFeed={ready}
      />,
    );
    expect(screen.getByText("No events match these filters.")).toBeVisible();

    const emptyState = screen.getByRole("status");
    fireEvent.click(
      within(emptyState).getByRole("button", { name: "Reset filters" }),
    );
    expect(window.location.search).toBe("");
    expect(
      screen.getByRole("link", { name: EVENTS[0].headline }),
    ).toBeVisible();
  });

  it("gives the map short Today-first windows and the briefing wider ranges", () => {
    window.history.replaceState(null, "", "/");
    const view = render(
      <HomeShell now={NOW} apiStatus="ready" eventFeed={ready} />,
    );
    const mapPeriod = screen.getByLabelText("Period");
    expect(mapPeriod).toHaveValue("today");
    expect(
      [...mapPeriod.querySelectorAll("option")].map((o) => o.value),
    ).toEqual(["today", "24h", "48h", "72h", "custom"]);
    view.unmount();

    window.history.replaceState(null, "", "/briefing");
    render(
      <HomeShell
        now={NOW}
        view="briefing"
        apiStatus="ready"
        eventFeed={ready}
      />,
    );
    const briefingPeriod = screen.getByLabelText("Period");
    expect(briefingPeriod).toHaveValue("7d");
    expect(
      [...briefingPeriod.querySelectorAll("option")].map((o) => o.value),
    ).toEqual(["today", "24h", "3d", "7d", "30d", "custom"]);
  });
});
