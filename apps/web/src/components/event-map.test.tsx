import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardEvent } from "../lib/api-dashboard";

type MockMapInstance = {
  fitBounds: ReturnType<typeof vi.fn>;
  easeTo: ReturnType<typeof vi.fn>;
  flyTo: ReturnType<typeof vi.fn>;
  setStyle: ReturnType<typeof vi.fn>;
  handlers: Map<string, (event?: unknown) => void>;
  layers: Array<Record<string, unknown>>;
  queryRenderedFeatures: ReturnType<typeof vi.fn>;
  getSource: ReturnType<typeof vi.fn>;
  sources: Record<
    string,
    {
      data: MockFeatureCollection;
      getClusterExpansionZoom: ReturnType<typeof vi.fn>;
      options: Record<string, unknown>;
      setData: ReturnType<typeof vi.fn>;
    }
  >;
  trigger: (event: string, layer?: string, payload?: unknown) => void;
  pixelsPerDegree: number;
  removed: boolean;
};

type MockFeatureCollection = {
  features: Array<{
    geometry: { coordinates: [number, number] };
    properties: { id: string };
  }>;
};

const mapState = vi.hoisted(() => ({
  instances: [] as MockMapInstance[],
  options: [] as Array<Record<string, unknown>>,
  popups: [] as Array<{ content: Node | null }>,
}));

vi.mock("maplibre-gl", () => {
  class MockMap {
    fitBounds = vi.fn();
    easeTo = vi.fn();
    flyTo = vi.fn();
    setStyle = vi.fn();
    handlers = new Map<string, (event?: unknown) => void>();
    layers: Array<Record<string, unknown>> = [];
    queryRenderedFeatures = vi.fn(() => []);
    getSource = vi.fn((id: string) => this.sources[id]);
    sources: MockMapInstance["sources"] = {};
    pixelsPerDegree = 2;
    removed = false;

    constructor(options: Record<string, unknown>) {
      mapState.instances.push(this);
      mapState.options.push(options);
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

    once(event: string, handler: unknown) {
      if (typeof handler === "function") {
        this.handlers.set(`${event}:map`, handler as (event?: unknown) => void);
      }
      return this;
    }

    trigger(event: string, layer = "map", payload: unknown = {}) {
      this.handlers.get(`${event}:${layer}`)?.(payload);
    }

    off(event: string, layerOrHandler: unknown, maybeHandler?: unknown) {
      const handler = maybeHandler ?? layerOrHandler;
      const layer = maybeHandler === undefined ? "map" : String(layerOrHandler);
      const key = `${event}:${layer}`;
      if (this.handlers.get(key) === handler) this.handlers.delete(key);
      return this;
    }

    remove() {
      this.removed = true;
    }

    isRemoved() {
      return this.removed;
    }

    addSource(id: string, source: { data: unknown; [key: string]: unknown }) {
      const entry = {
        data: source.data as MockFeatureCollection,
        getClusterExpansionZoom: vi.fn().mockResolvedValue(5),
        options: source,
        setData: vi.fn((data: unknown) => {
          entry.data = data as MockFeatureCollection;
        }),
      };
      this.sources[id] = entry;
    }

    addLayer(layer: Record<string, unknown>) {
      this.layers.push({ ...layer, paint: { ...(layer.paint as object) } });
    }

    getLayer(id: string) {
      return this.layers.find((layer) => layer.id === id);
    }

    setPaintProperty(id: string, property: string, value: unknown) {
      const layer = this.layers.find((candidate) => candidate.id === id);
      if (layer) {
        layer.paint = {
          ...(layer.paint as object),
          [property]: value,
        };
      }
    }

    getZoom() {
      return 2;
    }

    project(coordinate: [number, number]) {
      return {
        x: coordinate[0] * this.pixelsPerDegree,
        y: coordinate[1] * this.pixelsPerDegree,
      };
    }

    unproject(point: { x: number; y: number } | [number, number]) {
      const [x, y] = Array.isArray(point) ? point : [point.x, point.y];
      return {
        lng: x / this.pixelsPerDegree,
        lat: y / this.pixelsPerDegree,
      };
    }

    getCanvas() {
      return { style: { cursor: "" } };
    }
  }

  class MockPopup {
    content: Node | null = null;

    constructor() {
      mapState.popups.push(this);
    }

    setLngLat() {
      return this;
    }

    setDOMContent(content: Node) {
      this.content = content;
      return this;
    }

    addTo() {
      return this;
    }

    remove() {}
  }

  class MockNavigationControl {}

  return {
    default: {
      Map: MockMap,
      Popup: MockPopup,
      NavigationControl: MockNavigationControl,
    },
    Map: MockMap,
    Popup: MockPopup,
    NavigationControl: MockNavigationControl,
  };
});

import {
  EventMap,
  DEFAULT_MAP_VIEWPORT,
  REGION_BOUNDS,
  getMapCounts,
  toGeoJson,
  displayCoordinates,
  type EventMapRegion,
} from "./event-map";

type ScreenPoint = { x: number; y: number };

function screenProjection(pixelsPerDegree: number) {
  return {
    project([longitude, latitude]: [number, number]): ScreenPoint {
      return { x: longitude * pixelsPerDegree, y: latitude * pixelsPerDegree };
    },
    unproject({ x, y }: ScreenPoint) {
      return { lng: x / pixelsPerDegree, lat: y / pixelsPerDegree };
    },
  };
}

function screenDistance(
  left: [number, number],
  right: [number, number],
  pixelsPerDegree: number,
) {
  const dx = (left[0] - right[0]) * pixelsPerDegree;
  const dy = (left[1] - right[1]) * pixelsPerDegree;
  return Math.hypot(dx, dy);
}

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
    mapState.options.length = 0;
    mapState.popups.length = 0;
  });

  afterEach(() => vi.unstubAllGlobals());

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
    mapState.options.length = 0;
    mapState.popups.length = 0;
  });

  afterEach(() => vi.unstubAllGlobals());

  it("keeps canonical GeoJSON coordinates and separates exact points in screen space", () => {
    const projector = screenProjection(2);
    const data = [event("one"), event("two")];
    const features = toGeoJson(data, 0).features;
    const positions = [...displayCoordinates(data, projector).values()];

    expect(
      screenDistance(positions[0], positions[1], 2),
    ).toBeGreaterThanOrEqual(16);
    expect(features.map((feature) => feature.geometry.coordinates)).toEqual([
      [13.66, -8.58],
      [13.66, -8.58],
    ]);
    expect(displayCoordinates([event("two"), event("one")], projector)).toEqual(
      displayCoordinates([event("one"), event("two")], projector),
    );
  });

  it("separates three exact-coordinate events deterministically in screen space", () => {
    const projector = screenProjection(2);
    const input = [event("three"), event("one"), event("two")];
    const first = [...displayCoordinates(input, projector).values()];
    const second = [...displayCoordinates(input, projector).values()];
    const positions = first;

    for (let left = 0; left < positions.length; left += 1) {
      for (let right = left + 1; right < positions.length; right += 1) {
        expect(
          screenDistance(positions[left], positions[right], 2),
        ).toBeGreaterThanOrEqual(16);
      }
    }
    expect(first).toEqual(second);
    expect(input.every((item) => item.longitude === 13.66)).toBe(true);
  });

  it("returns nearby points to canonical positions when zoom separates them", () => {
    const nearby = event("nearby", [18.66, -8.58]);
    const worldProjector = screenProjection(2);
    const zoomedProjector = screenProjection(10);
    const worldPosition = displayCoordinates(
      [event("one"), nearby],
      worldProjector,
    ).get("nearby");
    const zoomedPosition = displayCoordinates(
      [event("one"), nearby],
      zoomedProjector,
    ).get("nearby");

    expect(worldPosition).not.toEqual([nearby.longitude, nearby.latitude]);
    expect(zoomedPosition).toEqual([nearby.longitude, nearby.latitude]);
  });

  it("keeps a fanned group separated from a neighboring singleton", () => {
    const projector = screenProjection(1);
    const neighbor = event("edge", [21.66, 7.42]);
    const positions = [
      ...displayCoordinates(
        [event("one"), event("two"), neighbor],
        projector,
      ).values(),
    ];

    for (let left = 0; left < positions.length; left += 1) {
      for (let right = left + 1; right < positions.length; right += 1) {
        expect(
          screenDistance(positions[left], positions[right], 1),
        ).toBeGreaterThanOrEqual(16);
      }
    }
  });

  it("keeps collocated source event data canonical", () => {
    const data = [event("one"), event("two"), event("three", null)];
    const features = toGeoJson(data, 0).features;

    expect(features.map((feature) => feature.properties.id)).toEqual([
      "one",
      "two",
    ]);
    expect(features[0].geometry.coordinates).toEqual(
      features[1].geometry.coordinates,
    );
    expect(data[0].longitude).toBe(13.66);
    expect(data[1].longitude).toBe(13.66);
    expect(getMapCounts(data)).toEqual({ mappedCount: 2, locationCount: 1 });
  });

  it("keeps screen-space positions stable and canonical source positions unchanged", () => {
    const nearby = event("nearby", [13.9, -8.58]);
    const input = [event("one"), nearby, event("two"), event("three")];
    const projector = screenProjection(2);

    const nearbyPositions = displayCoordinates(
      [event("one"), nearby],
      projector,
    );
    const exactPositions = displayCoordinates(
      [event("one"), event("two"), event("three")],
      projector,
    );
    const first = toGeoJson(input, 0).features;
    const second = toGeoJson(input, 0).features;

    expect(nearbyPositions.get("one")).not.toEqual(
      nearbyPositions.get("nearby"),
    );
    expect(new Set(exactPositions.values())).toHaveLength(3);
    expect(
      new Set(first.map((feature) => feature.geometry.coordinates.join(","))),
    ).toHaveLength(2);
    expect(first.map((feature) => feature.geometry.coordinates)).toEqual(
      second.map((feature) => feature.geometry.coordinates),
    );
  });

  it("keeps only valid world coordinates and carries disease groups into map features", () => {
    const valid = { ...event("valid"), disease_group: "vector_borne" };
    const invalid = { ...event("invalid"), latitude: 100, longitude: 200 };

    expect(toGeoJson([valid, invalid]).features).toEqual([
      expect.objectContaining({
        properties: expect.objectContaining({
          id: "valid",
          disease_group: "vector_borne",
        }),
      }),
    ]);
  });

  it("uses the light Carto style by default and safely reloads layers when theme changes", () => {
    const { rerender } = render(
      <EventMap
        events={[event("one")]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));

    expect(mapState.options[0]).toMatchObject({
      style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    });

    rerender(
      <EventMap
        events={[event("one")]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
        theme="dark"
      />,
    );

    expect(mapState.instances).toHaveLength(1);
    expect(map.setStyle).toHaveBeenCalledWith(
      "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    );

    act(() => map.trigger("style.load"));
    expect(map.layers.map((layer) => layer.id)).toEqual(["events-circles"]);
  });

  it("removes map movement animation when reduced motion is preferred", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    render(
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
      REGION_BOUNDS.Africa,
      expect.objectContaining({ duration: 0 }),
    );
  });

  it("keeps map-unavailable events discoverable from Briefing", () => {
    render(
      <EventMap
        events={events}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];

    act(() => map.trigger("error"));

    expect(
      screen.getByText(/all events remain accessible in briefing view/i),
    ).toBeInTheDocument();
  });

  it("renders one source and one unclustered circle layer", () => {
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
    expect(map.sources.events.options.cluster).not.toBe(true);
    expect(Object.keys(map.sources)).toEqual(["events"]);
    expect(map.layers.map((layer) => layer.id)).toEqual(["events-circles"]);
    expect(map.layers[0]).not.toHaveProperty("filter");
    expect(map.sources.events.data.features[0].properties).toMatchObject({
      canonical_latitude: -8.58,
      canonical_longitude: 13.66,
    });
  });

  it("supports hover and click for every screen-deconflicted event", () => {
    const onSelect = vi.fn();
    render(
      <EventMap
        events={[event("one"), event("two"), event("three")]}
        region=""
        selectedId={null}
        onSelect={onSelect}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));

    expect(map.sources.events.data.features).toHaveLength(3);
    expect(
      new Set(
        map.sources.events.data.features.map(
          (feature: { properties: { id: string } }) => feature.properties.id,
        ),
      ),
    ).toHaveLength(3);

    for (const publicId of ["one", "two", "three"]) {
      act(() =>
        map.trigger("mouseenter", "events-circles", {
          features: [
            {
              properties: {
                id: publicId,
                headline: `Event ${publicId}`,
                location: "Angola",
              },
            },
          ],
          lngLat: { lng: 13.66, lat: -8.58 },
        }),
      );
      expect(mapState.popups.at(-1)?.content?.textContent).toContain(
        `Event ${publicId}`,
      );

      act(() =>
        map.trigger("click", "events-circles", {
          features: [{ properties: { id: publicId } }],
        }),
      );
    }

    expect(onSelect.mock.calls.map(([publicId]) => publicId)).toEqual([
      "one",
      "two",
      "three",
    ]);
  });

  it("recomputes display positions after zoom changes", () => {
    const nearby = event("nearby", [18.66, -8.58]);
    render(
      <EventMap
        events={[event("one"), nearby]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];

    act(() => map.trigger("load"));
    const source = map.sources.events;
    expect(source.data.features[1].geometry.coordinates).not.toEqual([
      nearby.longitude,
      nearby.latitude,
    ]);

    map.pixelsPerDegree = 10;
    act(() => map.trigger("zoomend"));
    expect(source.data.features[1].geometry.coordinates).toEqual([
      nearby.longitude,
      nearby.latitude,
    ]);
  });

  it("updates one source without accumulating layers when event set changes", () => {
    const { rerender } = render(
      <EventMap
        events={[event("one"), event("two")]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));
    expect(
      map.sources.events.data.features[0].geometry.coordinates,
    ).not.toEqual([13.66, -8.58]);

    rerender(
      <EventMap
        events={[event("three")]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );

    expect(Object.keys(map.sources)).toEqual(["events"]);
    expect(map.layers.map((layer) => layer.id)).toEqual(["events-circles"]);
    expect(map.sources.events.data.features).toHaveLength(1);
    expect(map.sources.events.data.features[0].geometry.coordinates).toEqual([
      13.66, -8.58,
    ]);
  });

  it("recomputes display positions after a coalesced resize", () => {
    const frame = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback) => {
        callback(0);
        return 1;
      });
    const nearby = event("nearby", [18.66, -8.58]);
    render(
      <EventMap
        events={[event("one"), nearby]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));

    map.pixelsPerDegree = 10;
    act(() => {
      map.trigger("resize");
      map.trigger("resize");
    });

    expect(frame).toHaveBeenCalledOnce();
    expect(map.sources.events.data.features[1].geometry.coordinates).toEqual([
      nearby.longitude,
      nearby.latitude,
    ]);
  });

  it("cancels pending display refresh before removing the map", () => {
    const callbacks: FrameRequestCallback[] = [];
    const frame = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback) => {
        callbacks.push(callback);
        return 42;
      });
    const cancel = vi
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation(() => undefined);
    const { unmount } = render(
      <EventMap
        events={[event("one"), event("two")]}
        region=""
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));
    act(() => map.trigger("resize"));
    map.getSource.mockClear();

    unmount();

    expect(cancel).toHaveBeenCalledWith(42);
    expect(map.removed).toBe(true);
    expect(map.handlers).toEqual(new Map());

    act(() => callbacks[0](0));
    expect(map.getSource).not.toHaveBeenCalled();

    frame.mockRestore();
    cancel.mockRestore();
  });

  it("preserves selected state in the shared circle layer", () => {
    render(
      <EventMap
        events={[event("one"), event("two")]}
        region=""
        selectedId="two"
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));
    expect(
      (map.layers[0].paint as Record<string, unknown>)["circle-radius"],
    ).toEqual(["case", ["==", ["get", "id"], "two"], 10, 6]);
  });

  it("flies to selected event canonical coordinates", () => {
    const selected = event("selected", [18.66, -8.58]);
    render(
      <EventMap
        events={[event("one"), selected]}
        region=""
        selectedId="selected"
        onSelect={vi.fn()}
      />,
    );
    const map = mapState.instances[0];
    act(() => map.trigger("load"));

    expect(map.flyTo).toHaveBeenCalledWith(
      expect.objectContaining({ center: [18.66, -8.58] }),
    );
  });

  it("resets the world viewport", () => {
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

    fireEvent.click(screen.getByRole("button", { name: /reset map view/i }));

    expect(onReset).toHaveBeenCalledOnce();
    expect(map.easeTo).toHaveBeenLastCalledWith({
      ...DEFAULT_MAP_VIEWPORT,
      duration: 700,
    });
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
    // Counts moved to the live region; the visible legend now keys the
    // recency colour ramp instead of repeating numbers over the map.
    expect(
      screen.getByText("2 mapped events across 1 locations, 3 total."),
    ).toBeInTheDocument();
    expect(screen.getByText("Newest")).toBeInTheDocument();
    expect(screen.getByText("Older")).toBeInTheDocument();
  });
});
