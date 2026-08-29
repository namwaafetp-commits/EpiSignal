import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RadarEventGroup, RadarFeedState } from "../lib/api-radar";
import { HomeShell } from "./home-shell";

// Mock SignalMap
vi.mock("./signal-map", () => ({
  SignalMap: ({
    items,
    groups = [],
    selectedId,
    onSelect,
  }: {
    items: unknown[];
    groups?: unknown[];
    selectedId: string | null;
    onSelect: (id: string) => void;
  }) => (
    <div data-testid="mock-signal-map" data-selected={selectedId}>
      <span>
        Plotted {items.length} items in {groups.length} groups
      </span>
      <button onClick={() => onSelect("item-1")}>Select Item 1</button>
    </div>
  ),
}));

const SAMPLE_EVENT_GROUP: RadarEventGroup = {
  event_public_id: "EVT-2026-00077",
  event: {
    public_id: "EVT-2026-00077",
    verification_status: "officially_confirmed",
    early_signal_score: 0.9,
    evidence_score: 0.95,
  },
  signal_count: 3,
  representative_title: "Cholera cluster in Cacuaco district",
  representative_brief: [
    {
      slot: "what_where",
      text: "Cholera cluster reported in Cacuaco district.",
      reported: true,
    },
    {
      slot: "counts",
      text: "42 cases and 2 deaths.",
      reported: true,
    },
    {
      slot: "timing",
      text: "Onset late August.",
      reported: true,
    },
    {
      slot: "spread",
      text: "No spread reported.",
      reported: false,
    },
    {
      slot: "reporting",
      text: "Reported by the Municipal Health Directorate.",
      reported: true,
    },
  ],
  representative_location: {
    role: "primary",
    precision: "place",
    label: "Cacuaco",
    country_code: "AO",
    latitude: -8.7803,
    longitude: 13.3667,
  },
  representative_source: {
    name: "WHO AFRO",
    url: "https://afro.who.int/report/456",
    is_official: true,
    credibility_tier: "official",
  },
  all_source_names: ["WHO AFRO", "Radio Nacional de Angola"],
  earliest_published_at: "2026-08-28T08:00:00Z",
  latest_published_at: "2026-08-28T11:00:00Z",
  first_seen_at: "2026-08-28T11:05:00Z",
};

const SAMPLE_READY_RADAR: RadarFeedState = {
  status: "ready",
  data: {
    event_groups: [],
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
  it("renders masthead navigation including Review Queue link", () => {
    render(
      <HomeShell
        apiStatus="ready"
        radarFeed={{
          status: "ready",
          data: {
            event_groups: [],
            items: [],
            window_start: "",
            window_end: "",
            hours: 48,
            limit: 50,
          },
        }}
      />,
    );

    expect(screen.getByRole("link", { name: /review queue/i })).toHaveAttribute(
      "href",
      "/admin/reviews",
    );
    expect(
      screen.getByRole("link", { name: /pipeline monitor/i }),
    ).toHaveAttribute("href", "/admin/pipeline");
  });

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
            event_groups: [],
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

  it("allows selecting a signal card on click and via keyboard Enter/Space", async () => {
    const user = userEvent.setup();
    render(<HomeShell apiStatus="ready" radarFeed={SAMPLE_READY_RADAR} />);

    const card = screen.getByRole("button", {
      name: /select signal: cholera outbreak in luanda province/i,
    });
    expect(card).toHaveAttribute("data-selected", "false");

    // Click selection
    await user.click(card);
    expect(card).toHaveAttribute("data-selected", "true");

    // Keyboard selection with Enter
    await user.keyboard("{Enter}");
    expect(card).toHaveAttribute("data-selected", "true");

    // Keyboard selection with Space
    await user.keyboard(" ");
    expect(card).toHaveAttribute("data-selected", "true");
  });

  it("strictly derives official standing from is_official and renders credibility tier separately", () => {
    // Non-official source even if credibility_tier is "official"
    const feedNonOfficial: RadarFeedState = {
      status: "ready",
      data: {
        ...SAMPLE_READY_RADAR.data!,
        items: [
          {
            ...SAMPLE_READY_RADAR.data!.items[0],
            source: {
              name: "Independent Health Blog",
              url: "https://blog.health/1",
              is_official: false,
              credibility_tier: "official",
            },
          },
        ],
      },
    };

    render(<HomeShell apiStatus="ready" radarFeed={feedNonOfficial} />);
    expect(screen.getByText("Media Source")).toBeInTheDocument();
    expect(screen.getByText("Tier: official")).toBeInTheDocument();
    expect(screen.queryByText("Official Source")).not.toBeInTheDocument();
  });

  it("renders location unresolved when location is null", () => {
    const feedNoLoc: RadarFeedState = {
      status: "ready",
      data: {
        ...SAMPLE_READY_RADAR.data!,
        items: [
          {
            ...SAMPLE_READY_RADAR.data!.items[0],
            location: null,
          },
        ],
      },
    };

    render(<HomeShell apiStatus="ready" radarFeed={feedNoLoc} />);
    expect(screen.getByText("📍 Location unresolved")).toBeInTheDocument();
  });

  it("renders a grouped event as one combined card with report count, sources, and time span", () => {
    const feedGrouped: RadarFeedState = {
      status: "ready",
      data: {
        ...SAMPLE_READY_RADAR.data!,
        items: [],
        event_groups: [SAMPLE_EVENT_GROUP],
      },
    };

    render(<HomeShell apiStatus="ready" radarFeed={feedGrouped} />);

    // Combined card header: representative title, report count badge, unique sources
    expect(
      screen.getByText("Cholera cluster in Cacuaco district"),
    ).toBeInTheDocument();
    expect(screen.getByText("3 reports")).toBeInTheDocument();
    expect(
      screen.getByText(/WHO AFRO · Radio Nacional de Angola/),
    ).toBeInTheDocument();

    // Earliest to latest published span
    expect(screen.getByText(/First published/i)).toBeInTheDocument();
    expect(screen.getByText(/Latest published/i)).toBeInTheDocument();

    // Representative brief, location, and event context with scores
    expect(
      screen.getByText("Cholera cluster reported in Cacuaco district."),
    ).toBeInTheDocument();
    expect(screen.getByText(/📍 Cacuaco \(place\)/i)).toBeInTheDocument();
    expect(screen.getByText(/EVT-2026-00077/i)).toBeInTheDocument();
    expect(screen.getByText(/officially confirmed/i)).toBeInTheDocument();
    expect(screen.getByText(/surveillance interest:/i)).toBeInTheDocument();
    expect(screen.getByText(/evidence support:/i)).toBeInTheDocument();

    // Representative source link
    const link = screen.getByRole("link", { name: /view original source/i });
    expect(link).toHaveAttribute("href", "https://afro.who.int/report/456");

    // Grouped signals must not also appear as individual cards: the list holds
    // exactly one selectable card and the map receives zero items, one group.
    expect(
      screen.getAllByRole("button", { name: /select signal:/i }),
    ).toHaveLength(1);
    expect(screen.getByText(/0 items in 1 groups/i)).toBeInTheDocument();
  });

  it("renders grouped members only inside the cluster card next to standalone signals", () => {
    const feedMixed: RadarFeedState = {
      status: "ready",
      data: {
        ...SAMPLE_READY_RADAR.data!,
        items: [
          {
            ...SAMPLE_READY_RADAR.data!.items[0],
            title_english: "Standalone measles report",
          },
        ],
        event_groups: [SAMPLE_EVENT_GROUP],
      },
    };

    render(<HomeShell apiStatus="ready" radarFeed={feedMixed} />);

    // One combined card for the group plus one standalone item card
    expect(
      screen.getAllByRole("button", { name: /select signal:/i }),
    ).toHaveLength(2);
    expect(
      screen.getByText("Cholera cluster in Cacuaco district"),
    ).toBeInTheDocument();
    expect(screen.getByText("Standalone measles report")).toBeInTheDocument();
    expect(screen.getByText(/1 items in 1 groups/i)).toBeInTheDocument();

    // The group card is selectable like a signal card
    const groupCard = screen.getByRole("button", {
      name: /select signal: cholera cluster in cacuaco district/i,
    });
    expect(groupCard).toHaveAttribute("data-selected", "false");
  });
});
