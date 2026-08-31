import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DashboardEvent, DashboardFeedState } from "../lib/api-dashboard";
import type { EventDetailResponse } from "../lib/api-events";
import { HomeShell } from "./home-shell";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const getEventDetail = vi.fn();
vi.mock("../lib/api-events", () => ({
  getEventDetail: (...args: unknown[]) => getEventDetail(...args),
}));

vi.mock("./event-map", () => ({
  EventMap: ({
    events,
    selectedId,
    onSelect,
  }: {
    events: DashboardEvent[];
    selectedId: string | null;
    onSelect: (publicId: string) => void;
  }) => (
    <div data-testid="mock-event-map">
      <span>
        {events.filter((event) => event.map_level !== null).length} mapped /{" "}
        {events.length} events
      </span>
      <span data-testid="selected-marker">{selectedId ?? "none"}</span>
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
    latest_report_at: "2026-08-30T12:00:00Z",
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
  sources: [],
  observations: [],
  summaries: [
    {
      version: 1,
      headline: EVENTS[0].headline,
      summary: EVENTS[0].summary,
      status: "ongoing",
      latest_development: "Two additional districts reported cases.",
      uncertainties: null,
      model_id: "test-model",
      created_at: "2026-08-30T13:00:00Z",
    },
  ],
} satisfies EventDetailResponse;

describe("HomeShell", () => {
  it("defaults to Map and shows dashboard stats plus unmapped events", () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    expect(screen.getByRole("button", { name: "Map" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByRole("region", { name: /event map/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 mapped \/ 2 events/)).toBeInTheDocument();
    expect(
      screen.getByText("Total events").previousElementSibling,
    ).toHaveTextContent("2");
    expect(
      screen.getByText("Countries").previousElementSibling,
    ).toHaveTextContent("2");
    expect(
      screen.getByText("Active events").previousElementSibling,
    ).toHaveTextContent("2");
    expect(
      screen.getByRole("button", { name: /view event: Dengue activity/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/map_level|processing_status/i),
    ).not.toBeInTheDocument();
  });

  it("selects a map marker or recent event card and opens detail panel", async () => {
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
        "Latest development",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText("Two additional districts reported cases."),
      ).toBeInTheDocument(),
    );

    fireEvent.click(
      screen.getByRole("button", { name: /view event: Dengue activity/i }),
    );
    expect(screen.getByTestId("selected-marker")).toHaveTextContent(
      "EVT-2026-00002",
    );
    expect(getEventDetail).toHaveBeenCalledWith("EVT-2026-00002");
  });

  it("filters same dashboard events in Map and Calendar views", () => {
    render(<HomeShell apiStatus="ready" eventFeed={ready} />);

    fireEvent.change(screen.getByLabelText("Disease"), {
      target: { value: "Dengue" },
    });
    expect(screen.getByText("Dengue activity in Thailand")).toBeInTheDocument();
    expect(
      screen.queryByText("Cholera activity increasing in Cacuaco"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(
      screen.getByRole("heading", { name: "Surveillance calendar" }),
    ).toBeInTheDocument();
    expect(screen.getByText("29 AUG 2026")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open event: Dengue activity/i }),
    ).toHaveAttribute("href", "/events/EVT-2026-00002");
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
