import { render, screen, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { RadarItem } from "../lib/api-radar";
import { SignalMap } from "./signal-map";

const mockMapInstance = {
  addControl: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  remove: vi.fn(),
  addSource: vi.fn(),
  getSource: vi.fn(),
  addLayer: vi.fn(),
  flyTo: vi.fn(),
  getZoom: vi.fn(() => 2),
  getCanvas: vi.fn(() => ({ style: { cursor: "" } })),
  isStyleLoaded: vi.fn(() => true),
};

vi.mock("maplibre-gl", () => {
  return {
    default: {
      Map: vi.fn().mockImplementation(() => mockMapInstance),
      NavigationControl: vi.fn(),
    },
    Map: vi.fn().mockImplementation(() => mockMapInstance),
    NavigationControl: vi.fn(),
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
    vi.clearAllMocks();
  });

  it("renders map container with accessible label and coverage text", () => {
    render(
      <SignalMap items={sampleItems} selectedId={null} onSelect={vi.fn()} />,
    );

    const mapRegion = screen.getByRole("region", {
      name: /epidemiological signal map/i,
    });
    expect(mapRegion).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 signals plotted/i)).toBeInTheDocument();
  });

  it("initializes maplibre map and navigation control on mount and cleans up on unmount", () => {
    const { unmount } = render(
      <SignalMap items={sampleItems} selectedId={null} onSelect={vi.fn()} />,
    );

    expect(mockMapInstance.addControl).toHaveBeenCalled();
    expect(mockMapInstance.on).toHaveBeenCalledWith(
      "load",
      expect.any(Function),
    );

    unmount();
    expect(mockMapInstance.remove).toHaveBeenCalled();
  });

  it("renders fallback message when map encounters an error", () => {
    let errorHandler: (() => void) | undefined;
    mockMapInstance.on.mockImplementation(
      (event: string, handler: () => void) => {
        if (event === "error") {
          errorHandler = handler;
        }
        return mockMapInstance;
      },
    );

    render(
      <SignalMap items={sampleItems} selectedId={null} onSelect={vi.fn()} />,
    );

    expect(errorHandler).toBeDefined();
    act(() => {
      errorHandler!();
    });

    expect(screen.getByText(/map unavailable/i)).toBeInTheDocument();
  });
});
