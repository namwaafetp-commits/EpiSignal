import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RadarFeedState } from "../lib/api-radar";
import { HomeShell } from "./home-shell";

// Mock SignalMap
vi.mock("./signal-map", () => ({
  SignalMap: ({
    items,
    selectedId,
    onSelect,
  }: {
    items: unknown[];
    selectedId: string | null;
    onSelect: (id: string) => void;
  }) => (
    <div data-testid="mock-signal-map" data-selected={selectedId}>
      <span>Plotted {items.length} items</span>
      <button onClick={() => onSelect("item-1")}>Select Item 1</button>
    </div>
  ),
}));

const SAMPLE_READY_RADAR: RadarFeedState = {
  status: "ready",
  data: {
    items: [
      {
        id: "24681357-1234-5678-9abc-def012345678",
        title_english: "Cholera outbreak in Luanda Province",
        brief: [
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
        ],
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
  },
};

describe("HomeShell", () => {
  it("renders loading state when radar feed is loading", () => {
    render(
      <HomeShell
        apiStatus="loading"
        radarFeed={{ status: "loading", data: null }}
      />,
    );

    expect(screen.getByText(/loading recent signals/i)).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("renders unavailable state when radar feed is unavailable", () => {
    render(
      <HomeShell
        apiStatus="ready"
        radarFeed={{ status: "unavailable", data: null }}
      />,
    );

    expect(screen.getByText(/signals unavailable/i)).toBeInTheDocument();
  });

  it("renders empty state when radar feed has 0 items", () => {
    render(
      <HomeShell
        apiStatus="ready"
        radarFeed={{
          status: "ready",
          data: {
            items: [],
            window_start: "2026-08-26T12:00:00Z",
            window_end: "2026-08-28T12:00:00Z",
            hours: 48,
            limit: 50,
          },
        }}
      />,
    );

    expect(
      screen.getByText(/no signals found in the selected window/i),
    ).toBeInTheDocument();
  });

  it("renders full radar card with 5 slots, source metadata, separate event scores, and safe source link", () => {
    render(<HomeShell apiStatus="ready" radarFeed={SAMPLE_READY_RADAR} />);

    // English Title
    expect(
      screen.getByText("Cholera outbreak in Luanda Province"),
    ).toBeInTheDocument();

    // 5 Brief slots
    expect(
      screen.getByText("Cholera outbreak reported in Luanda province."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("120 suspected cases and 4 deaths."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Cases reported between August 20 and August 27."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Spread observed across two municipal districts."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Reported by the Provincial Health Directorate."),
    ).toBeInTheDocument();

    // Metadata
    expect(screen.getByText(/official source/i)).toBeInTheDocument();
    expect(screen.getAllByText(/luanda province/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/95% extraction confidence/i)).toBeInTheDocument();

    // Separate event scores
    expect(screen.getByText(/surveillance interest:/i)).toBeInTheDocument();
    expect(screen.getByText(/evidence support:/i)).toBeInTheDocument();
    expect(screen.getByText(/88%/i)).toBeInTheDocument();
    expect(screen.getByText(/94%/i)).toBeInTheDocument();
    expect(screen.getByText(/EVT-2026-00042/i)).toBeInTheDocument();

    // Safe external source link
    const link = screen.getByRole("link", { name: /view original source/i });
    expect(link).toHaveAttribute("href", "https://afro.who.int/report/123");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("renders unmatched and ambiguous event statuses accurately", () => {
    const feedUnmatched: RadarFeedState = {
      status: "ready",
      data: {
        ...SAMPLE_READY_RADAR.data!,
        items: [
          {
            ...SAMPLE_READY_RADAR.data!.items[0],
            event_context_status: "none",
            event: null,
          },
        ],
      },
    };

    const { rerender } = render(
      <HomeShell apiStatus="ready" radarFeed={feedUnmatched} />,
    );
    expect(screen.getByText(/unattached signal/i)).toBeInTheDocument();

    const feedAmbiguous: RadarFeedState = {
      status: "ready",
      data: {
        ...SAMPLE_READY_RADAR.data!,
        items: [
          {
            ...SAMPLE_READY_RADAR.data!.items[0],
            event_context_status: "ambiguous",
            event: null,
          },
        ],
      },
    };

    rerender(<HomeShell apiStatus="ready" radarFeed={feedAmbiguous} />);
    expect(screen.getByText(/ambiguous signal/i)).toBeInTheDocument();
  });

  it("allows selecting a signal card on click", async () => {
    const user = userEvent.setup();
    render(<HomeShell apiStatus="ready" radarFeed={SAMPLE_READY_RADAR} />);

    const card = screen.getByRole("article");
    await user.click(card);

    expect(card).toHaveAttribute("data-selected", "true");
  });
});
