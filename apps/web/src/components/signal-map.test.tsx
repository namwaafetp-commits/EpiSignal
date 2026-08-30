import { render, screen, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import maplibregl from "maplibre-gl";
import type { RadarItem } from "../lib/api-radar";
import { SignalMap } from "./signal-map";

vi.mock("maplibre-gl", () => {
  class MockMap {
    addControl() {}
    on() {
      return { unsubscribe: () => {} };
    }
    off() {
      return { unsubscribe: () => {} };
    }
    remove() {}
    addSource() {}
    getSource() {
      return { setData: vi.fn() };
    }
    addLayer() {}
    flyTo() {}
    getZoom() {
      return 2;
    }
    getCanvas() {
      return { style: { cursor: "" } };
    }
    isStyleLoaded() {
      return true;
    }
  }

  class MockNavigationControl {}

  return {
    default: {
      Map: MockMap,
      NavigationControl: MockNavigationControl,
    },
    Map: MockMap,
    NavigationControl: MockNavigationControl,
  };
});

const sampleItems: RadarItem[] = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    title_english: "Cholera in Luanda",
    brief: [
      { slot: "what_where", text: "Cholera in Luanda.", reported: true },
      { slot: "counts", text: "120 cases.", reported: true },
      { slot: "timing", text: "Aug 20.", reported: true },
      { slot: "spread", text: "District wide.", reported: true },
      { slot: "reporting", text: "MoH.", reported: true },
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
      precision: "place",
      label: "Luanda",
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
  {
    id: "22222222-2222-2222-2222-222222222222",
    title_english: "Unknown fever",
    brief: [
      { slot: "what_where", text: "Unknown fever.", reported: true },
      { slot: "counts", text: "No counts.", reported: false },
      { slot: "timing", text: "No dates.", reported: false },
      { slot: "spread", text: "No spread.", reported: false },
      { slot: "reporting", text: "No reporting.", reported: false },
    ],
    signal_type: "case_report",
    processing_status: "extracted",
    published_at: null,
    first_seen_at: "2026-08-28T10:05:00Z",
    source: {
      name: "Local News",
      url: "https://local.ao/1",
      is_official: false,
      credibility_tier: "medium",
    },
    extraction_confidence: 0.75,
    location: null,
    event_context_status: "none",
    event: null,
  },
];

describe("SignalMap", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders map container with accessible label and coverage text", () => {
    render(
      <SignalMap items={sampleItems} selectedId={null} onSelect={vi.fn()} />,
    );

    const mapRegion = screen.getByRole("region", {
      name: /epidemiological signal map/i,
    });
    expect(mapRegion).toBeInTheDocument();
    expect(
      screen.getAllByText(/1 of 2 signals plotted/i).length,
    ).toBeGreaterThan(0);
  });

  it("initializes maplibre map and navigation control on mount and cleans up on unmount", () => {
    const addControlSpy = vi.spyOn(maplibregl.Map.prototype, "addControl");
    const removeSpy = vi.spyOn(maplibregl.Map.prototype, "remove");
    const onSpy = vi.spyOn(maplibregl.Map.prototype, "on");

    const { unmount } = render(
      <SignalMap items={sampleItems} selectedId={null} onSelect={vi.fn()} />,
    );

    expect(addControlSpy).toHaveBeenCalled();
    expect(onSpy).toHaveBeenCalledWith("load", expect.any(Function));

    unmount();
    expect(removeSpy).toHaveBeenCalled();
  });

  it("renders fallback message when map encounters an error", () => {
    let errorHandler: (() => void) | undefined;
    vi.spyOn(maplibregl.Map.prototype, "on").mockImplementation(
      (event: string, handler: unknown) => {
        if (event === "error" && typeof handler === "function") {
          errorHandler = handler as () => void;
        }
        return { unsubscribe: () => {} } as never;
      },
    );

    render(
      <SignalMap items={sampleItems} selectedId={null} onSelect={vi.fn()} />,
    );

    expect(errorHandler).toBeDefined();
    act(() => {
      errorHandler?.();
    });

    expect(screen.getByText(/map unavailable/i)).toBeInTheDocument();
  });

  it("renders accessible marker detail popup when a plottable signal is selected", () => {
    const onSelect = vi.fn();
    render(
      <SignalMap
        items={sampleItems}
        selectedId="11111111-1111-1111-1111-111111111111"
        onSelect={onSelect}
      />,
    );

    const dialog = screen.getByRole("dialog", {
      name: /selected signal details/i,
    });
    expect(dialog).toBeInTheDocument();

    // English title
    expect(screen.getByText("Cholera in Luanda")).toBeInTheDocument();

    // Source standing and tier
    expect(screen.getByText("Official Source")).toBeInTheDocument();
    expect(screen.getByText("Tier: official")).toBeInTheDocument();

    // Location precision and label
    expect(screen.getByText(/📍 Luanda \(place\)/i)).toBeInTheDocument();

    // Confidence
    expect(screen.getByText(/95% extraction confidence/i)).toBeInTheDocument();

    // Event verification status and separate scores
    expect(screen.getByText("Event: EVT-2026-00042")).toBeInTheDocument();
    expect(screen.getByText("officially confirmed")).toBeInTheDocument();
    expect(screen.getByText(/Surveillance:/i)).toBeInTheDocument();
    expect(screen.getByText(/88%/i)).toBeInTheDocument();
    expect(screen.getByText(/Evidence:/i)).toBeInTheDocument();
    expect(screen.getByText(/94%/i)).toBeInTheDocument();

    // Close button
    const closeBtn = screen.getByRole("button", {
      name: /close signal details/i,
    });
    closeBtn.click();
    expect(onSelect).toHaveBeenCalledWith("");
  });
});
