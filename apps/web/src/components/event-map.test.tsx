import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardEvent } from "../lib/api-dashboard";

type MockMapInstance = {
  fitBounds: ReturnType<typeof vi.fn>;
  easeTo: ReturnType<typeof vi.fn>;
  flyTo: ReturnType<typeof vi.fn>;
  handlers: Map<string, (event?: unknown) => void>;
  layers: Array<Record<string, unknown>>;
  queryRenderedFeatures: ReturnType<typeof vi.fn>;
  sources: Record<
    string,
    {
      data: unknown;
      getClusterExpansionZoom: ReturnType<typeof vi.fn>;
      options: Record<string, unknown>;
      setData: ReturnType<typeof vi.fn>;
    }
  >;
  trigger: (event: string, layer?: string, payload?: unknown) => void;
};

const mapState = vi.hoisted(() => ({
  instances: [] as MockMapInstance[],
}));

vi.mock("maplibre-gl", () => {
  class MockMap {
    fitBounds = vi.fn();
    easeTo = vi.fn();
    flyTo = vi.fn();
    handlers = new Map<string, (event?: unknown) => void>();
    layers: Array<Record<string, unknown>> = [];
    queryRenderedFeatures = vi.fn(() => []);
    sources: MockMapInstance["sources"] = {};

    constructor() {
      mapState.instances.push(this);
    }

    addControl() {}

    on(event: string, layerOrHandler: unknown, maybeHandler?: unknown) {
      const handler = maybeHandler ?? layerOrHandler;
      if (typeof handler === "function") {
        const layer =
          maybeHandler === undefined ? "map" : String(layerOrHandler);
        this.handlers.set(
          `${event}:${layer}`,
          handler as (event?: unknown) => void,
        );
      }
      return this;
    }

    trigger(event: string, layer = "map", payload: unknown = {}) {
      this.handlers.get(`${event}:${layer}`)?.(payload);
    }

    remove() {}

    addSource(id: string, source: { data: unknown; [key: string]: unknown }) {
      this.sources[id] = {
        data: source.data,
        getClusterExpansionZoom: vi.fn().mockResolvedValue(5),
        options: source,
        setData: vi.fn(),
      };
    }

    getSource(id: string) {
      return this.sources[id];
    }

    addLayer(layer: Record<string, unknown>) {
      this.layers.push(layer);
    }

    getLayer() {
      return {};
    }

    setPaintProperty() {}

    getZoom() {
      return 2;
    }

    getCanvas() {
      return { style: { cursor: "" } };
    }
  }

  class MockNavigationControl {}

  return {
    default: { Map: MockMap, NavigationControl: MockNavigationControl },
    Map: MockMap,
    NavigationControl: MockNavigationControl,
  };
});

import {
  EventMap,
  DEFAULT_MAP_VIEWPORT,
  REGION_BOUNDS,
  getMapCounts,
  toGeoJson,
  type EventMapRegion,
} from "./event-map";

const events: DashboardEvent[] = [];

function event(
  publicId: string,
  coordinates: [number, number] | null = [13.66, -8.58],
): DashboardEvent {
  return {
    public_id: publicId,
    headline: `Event ${publicId}`,
    summary: "A mapped event.",
    disease: "Cholera",
    event_type: "outbreak",
    status: "ongoing",
    country_code: coordinates ? "AO" : null,
    admin1: coordinates ? "Cacuaco" : null,
    first_reported_at: "2026-08-01T00:00:00Z",
    latest_report_at: "2026-08-30T10:00:00Z",
    article_count: 1,
    last_summarized_at: "2026-08-30T13:00:00Z",
    latitude: coordinates?.[1] ?? null,
    longitude: coordinates?.[0] ?? null,
    map_level: coordinates ? "admin1" : null,
  };
}

describe("EventMap regional viewport", () => {
  beforeEach(() => {
    mapState.instances.length = 0;
  });

  it("applies the selected region on mount, region changes, and global reset only", () => {
    const { rerender } = render(
      <EventMap
        events={events}
        region="Africa"
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];

    act(() => map.trigger("load"));
    expect(map.fitBounds).toHaveBeenCalledWith(
      [
        [-20, -36],
        [55, 38],
      ],
      expect.objectContaining({ duration: 700 }),
    );

    const viewportCallCount =
      map.fitBounds.mock.calls.length + map.easeTo.mock.calls.length;
    rerender(
      <EventMap
        events={[...events]}
        region="Africa"
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(map.fitBounds.mock.calls.length + map.easeTo.mock.calls.length).toBe(
      viewportCallCount,
    );

    rerender(
      <EventMap
        events={events}
        region="ASEAN"
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(map.fitBounds).toHaveBeenLastCalledWith(
      [
        [92, -12],
        [142, 29],
      ],
      expect.objectContaining({ duration: 700 }),
    );

    rerender(
      <EventMap
        events={events}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(map.easeTo).toHaveBeenLastCalledWith({
      center: [15, 5],
      zoom: 1.8,
      duration: 700,
    });
  });

  it.each(Object.entries(REGION_BOUNDS))(
    "fits the %s region bounds on mount",
    (region, bounds) => {
      render(
        <EventMap
          events={events}
          region={region as EventMapRegion}
          selectedId={null}
          onSelect={vi.fn()}
        />,
      );
      const map = mapState.instances[0];

      act(() => map.trigger("load"));

      expect(map.fitBounds).toHaveBeenCalledWith(
        bounds,
        expect.objectContaining({ duration: 700 }),
      );
    },
  );
});

describe("EventMap coverage and interaction", () => {
  beforeEach(() => {
    mapState.instances.length = 0;
  });

  it("keeps collocated mapped events in GeoJSON and counts unique locations", () => {
    const data = [event("one"), event("two"), event("three", null)];

    expect(
      toGeoJson(data).features.map((feature) => feature.properties.id),
    ).toEqual(["one", "two"]);
    expect(getMapCounts(data)).toEqual({ mappedCount: 2, locationCount: 1 });
  });

  it("configures native clustering and renders a cluster count layer", () => {
    render(
      <EventMap
        events={[event("one"), event("two")]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];

    act(() => map.trigger("load"));

    expect(map.sources.events.data).toMatchObject({
      type: "FeatureCollection",
      features: expect.any(Array),
    });
    expect(map.sources.events.options).toMatchObject({
      cluster: true,
      clusterRadius: 50,
      clusterMaxZoom: 8,
    });
    expect(map.layers.map((layer) => layer.id)).toEqual([
      "events-clusters",
      "events-cluster-count",
      "events-circles",
    ]);
    expect(map.layers[0]).toMatchObject({
      filter: ["has", "point_count"],
    });
    expect(map.layers[2]).toMatchObject({
      filter: ["!", ["has", "point_count"]],
    });
  });

  it("zooms to expand a clicked cluster", async () => {
    render(
      <EventMap
        events={[event("one"), event("two")]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));
    map.sources.events.getClusterExpansionZoom.mockResolvedValue(6);

    act(() =>
      map.trigger("click", "events-clusters", {
        features: [{ properties: { cluster_id: 12 } }],
        lngLat: { lng: 13.66, lat: -8.58 },
      }),
    );

    await waitFor(() =>
      expect(map.easeTo).toHaveBeenLastCalledWith({
        center: [13.66, -8.58],
        zoom: 6,
        duration: 700,
      }),
    );
  });

  it("shows every event at an exact-coordinate collision and preserves selection", () => {
    const onSelect = vi.fn();
    render(
      <EventMap
        events={[event("one"), event("two")]}
        region=""
        selectedId={null}
        onSelect={onSelect}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));
    map.queryRenderedFeatures.mockReturnValue([
      { properties: { id: "one" } },
      { properties: { id: "two" } },
    ]);

    act(() =>
      map.trigger("click", "events-circles", {
        point: { x: 20, y: 20 },
        features: [{ properties: { id: "one" } }],
      }),
    );

    expect(
      screen.getByRole("dialog", { name: /events at this location/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /event one/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /event two/i }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /event two/i }));

    expect(onSelect).toHaveBeenCalledWith("two");
    expect(
      screen.queryByRole("dialog", { name: /events at this location/i }),
    ).not.toBeInTheDocument();
  });

  it("resets the world viewport, clears selection, and closes overlap UI", () => {
    const onReset = vi.fn();
    render(
      <EventMap
        events={[event("one"), event("two")]}
        region=""
        selectedId={"one"}
        onSelect={vi.fn()}
        onReset={onReset}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));
    map.queryRenderedFeatures.mockReturnValue([
      { properties: { id: "one" } },
      { properties: { id: "two" } },
    ]);
    act(() =>
      map.trigger("click", "events-circles", {
        point: { x: 20, y: 20 },
      }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /reset map view/i }));

    expect(onReset).toHaveBeenCalledOnce();
    expect(map.easeTo).toHaveBeenLastCalledWith({
      ...DEFAULT_MAP_VIEWPORT,
      duration: 700,
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each(["Asia", "ASEAN"] as const)(
    "resets the selected %s region to its bounds",
    (region) => {
      render(
        <EventMap
          events={events}
          region={region}
          selectedId={null}
          onSelect={vi.fn()}
        />,
      );
      const map = mapState.instances[0];
      act(() => map.trigger("load"));

      fireEvent.click(screen.getByRole("button", { name: /reset map view/i }));

      expect(map.fitBounds).toHaveBeenLastCalledWith(
        REGION_BOUNDS[region],
        expect.objectContaining({ duration: 700 }),
      );
    },
  );

  it("exposes an accessible reset control and truthful map counts", () => {
    render(
      <EventMap
        events={[event("one"), event("two"), event("three", null)]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Reset map view" }),
    ).toHaveAttribute("title", "Reset view");
    expect(
      screen.getByText("2 mapped · 1 locations · 3 events"),
    ).toBeInTheDocument();
  });
});
