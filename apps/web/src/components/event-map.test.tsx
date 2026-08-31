import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardEvent } from "../lib/api-dashboard";

type MockMapInstance = {
  fitBounds: ReturnType<typeof vi.fn>;
  easeTo: ReturnType<typeof vi.fn>;
  handlers: Map<string, (event?: unknown) => void>;
  trigger: (event: string) => void;
};

const mapState = vi.hoisted(() => ({
  instances: [] as MockMapInstance[],
}));

vi.mock("maplibre-gl", () => {
  class MockMap {
    fitBounds = vi.fn();
    easeTo = vi.fn();
    handlers = new Map<string, (event?: unknown) => void>();

    constructor() {
      mapState.instances.push(this);
    }

    addControl() {}

    on(event: string, layerOrHandler: unknown, maybeHandler?: unknown) {
      const handler = maybeHandler ?? layerOrHandler;
      if (typeof handler === "function") {
        this.handlers.set(event, handler as (event?: unknown) => void);
      }
      return this;
    }

    trigger(event: string) {
      this.handlers.get(event)?.();
    }

    remove() {}

    addSource() {}

    getSource() {
      return { setData: vi.fn() };
    }

    addLayer() {}

    getLayer() {
      return {};
    }

    setPaintProperty() {}

    flyTo() {}

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

import { EventMap, REGION_BOUNDS, type EventMapRegion } from "./event-map";

const events: DashboardEvent[] = [];

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
