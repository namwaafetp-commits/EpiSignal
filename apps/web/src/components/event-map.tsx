"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { DashboardEvent } from "../lib/api-dashboard";
import { formatCountryLocation } from "../lib/country";

export type EventMapRegion =
  | ""
  | "Africa"
  | "Asia"
  | "Europe"
  | "North America"
  | "South America"
  | "Oceania"
  | "ASEAN";

type NamedEventMapRegion = Exclude<EventMapRegion, "">;

export const REGION_BOUNDS = {
  Africa: [
    [-20, -36],
    [55, 38],
  ],
  Asia: [
    [25, -12],
    [180, 80],
  ],
  Europe: [
    [-25, 34],
    [45, 72],
  ],
  "North America": [
    [-170, 5],
    [-50, 83],
  ],
  "South America": [
    [-82, -56],
    [-34, 14],
  ],
  Oceania: [
    [110, -50],
    [180, 10],
  ],
  ASEAN: [
    [92, -12],
    [142, 29],
  ],
} satisfies Record<NamedEventMapRegion, [[number, number], [number, number]]>;

export const DEFAULT_MAP_VIEWPORT = {
  center: [15, 5] as [number, number],
  zoom: 1.8,
};

export interface EventMapProps {
  events: DashboardEvent[];
  region: EventMapRegion;
  selectedId: string | null;
  onSelect: (publicId: string) => void;
  onReset?: () => void;
}

const CARTO_DARK_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

function isMappedEvent(
  event: DashboardEvent,
): event is DashboardEvent & { latitude: number; longitude: number } {
  return (
    (event.map_level === "admin1" || event.map_level === "country") &&
    typeof event.latitude === "number" &&
    typeof event.longitude === "number"
  );
}

export function toGeoJson(events: readonly DashboardEvent[]) {
  return {
    type: "FeatureCollection" as const,
    features: events.filter(isMappedEvent).map((event) => ({
      type: "Feature" as const,
      geometry: {
        type: "Point" as const,
        coordinates: [event.longitude, event.latitude] as [number, number],
      },
      properties: {
        id: event.public_id,
        headline: event.headline,
        location: formatCountryLocation(event.admin1, event.country_code),
      },
    })),
  };
}

export function getMapCounts(events: readonly DashboardEvent[]) {
  const mappedEvents = events.filter(isMappedEvent);
  const locations = new Set(
    mappedEvents.map((event) => `${event.longitude},${event.latitude}`),
  );
  return { mappedCount: mappedEvents.length, locationCount: locations.size };
}

function tooltipContent(headline: string, location: string) {
  const content = document.createElement("div");
  content.className = "map-tooltip";
  const title = document.createElement("strong");
  title.textContent = headline;
  const place = document.createElement("span");
  place.textContent = location;
  content.append(title, place);
  return content;
}

function applyRegionViewport(map: maplibregl.Map, region: EventMapRegion) {
  if (!region) {
    map.easeTo({
      ...DEFAULT_MAP_VIEWPORT,
      duration: 700,
    });
    return;
  }

  map.fitBounds(REGION_BOUNDS[region], {
    padding: 40,
    duration: 700,
    maxZoom: 6,
  });
}

export function EventMap({
  events,
  region,
  selectedId,
  onSelect,
  onReset,
}: EventMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const onSelectRef = useRef(onSelect);
  const onResetRef = useRef(onReset);
  const eventsRef = useRef(events);
  const selectedIdRef = useRef(selectedId);
  const [mapError, setMapError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);
  const [overlapEvents, setOverlapEvents] = useState<DashboardEvent[]>([]);
  const { mappedCount, locationCount } = getMapCounts(events);

  useEffect(() => {
    onSelectRef.current = onSelect;
    onResetRef.current = onReset;
    eventsRef.current = events;
    selectedIdRef.current = selectedId;
  }, [events, onReset, onSelect, selectedId]);

  useEffect(() => {
    if (!mapContainerRef.current) return;
    try {
      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        style: CARTO_DARK_STYLE,
        ...DEFAULT_MAP_VIEWPORT,
        minZoom: 1,
        maxZoom: 14,
      });
      map.addControl(new maplibregl.NavigationControl(), "top-right");
      map.on("load", () => {
        setIsLoaded(true);
        map.addSource("events", {
          type: "geojson",
          data: toGeoJson(eventsRef.current),
          cluster: true,
          clusterRadius: 50,
          clusterMaxZoom: 8,
        });
        map.addLayer({
          id: "events-clusters",
          type: "circle",
          source: "events",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": [
              "step",
              ["get", "point_count"],
              "#41d5d0",
              10,
              "#f1b45f",
              30,
              "#e86d5d",
            ],
            "circle-radius": [
              "step",
              ["get", "point_count"],
              18,
              10,
              24,
              30,
              30,
            ],
            "circle-stroke-width": 2,
            "circle-stroke-color": "#b8fffa",
          },
        });
        map.addLayer({
          id: "events-cluster-count",
          type: "symbol",
          source: "events",
          filter: ["has", "point_count"],
          layout: {
            "text-field": ["get", "point_count_abbreviated"],
            "text-size": 12,
          },
          paint: {
            "text-color": "#101b2d",
          },
        });
        map.addLayer({
          id: "events-circles",
          type: "circle",
          source: "events",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": [
              "case",
              ["==", ["get", "id"], selectedIdRef.current || ""],
              10,
              6,
            ],
            "circle-color": "#41d5d0",
            "circle-opacity": 0.92,
            "circle-stroke-width": [
              "case",
              ["==", ["get", "id"], selectedIdRef.current || ""],
              3,
              1.5,
            ],
            "circle-stroke-color": "#b8fffa",
          },
        });

        map.on("click", "events-clusters", async (event) => {
          const feature = event.features?.[0];
          const clusterId = feature?.properties?.cluster_id;
          const source = map.getSource("events") as GeoJSONSource | undefined;
          if (typeof clusterId !== "number" || !source || !event.lngLat) {
            return;
          }
          const zoom = await source.getClusterExpansionZoom(clusterId);
          map.easeTo({
            center: [event.lngLat.lng, event.lngLat.lat],
            zoom,
            duration: 700,
          });
        });
        map.on("click", "events-circles", (event) => {
          const features = map.queryRenderedFeatures(event.point, {
            layers: ["events-circles"],
          });
          const ids = [
            ...new Set(
              features
                .map((feature) => feature.properties?.id)
                .filter((id): id is string => typeof id === "string"),
            ),
          ];
          if (ids.length === 0) {
            const publicId = event.features?.[0]?.properties?.id;
            if (typeof publicId === "string") ids.push(publicId);
          }
          const selectedEvents = ids
            .map((id) =>
              eventsRef.current.find((item) => item.public_id === id),
            )
            .filter((event): event is DashboardEvent => event !== undefined);
          if (selectedEvents.length > 1) {
            popupRef.current?.remove();
            popupRef.current = null;
            setOverlapEvents(selectedEvents);
            return;
          }
          const publicId = selectedEvents[0]?.public_id ?? ids[0];
          if (typeof publicId === "string") onSelectRef.current(publicId);
        });
        map.on("mouseenter", "events-circles", (event) => {
          map.getCanvas().style.cursor = "pointer";
          const feature = event.features?.[0];
          const properties = feature?.properties;
          if (!properties || !event.lngLat) return;
          popupRef.current?.remove();
          popupRef.current = new maplibregl.Popup({
            closeButton: false,
            closeOnClick: false,
            offset: 12,
            className: "event-map-popup",
          })
            .setLngLat(event.lngLat)
            .setDOMContent(
              tooltipContent(
                String(properties.headline ?? "Event"),
                String(properties.location ?? "Location unresolved"),
              ),
            )
            .addTo(map);
        });
        map.on("mouseleave", "events-circles", () => {
          map.getCanvas().style.cursor = "";
          popupRef.current?.remove();
          popupRef.current = null;
        });
      });
      map.on("error", () => setMapError(true));
      mapRef.current = map;
      return () => {
        popupRef.current?.remove();
        popupRef.current = null;
        map.remove();
        mapRef.current = null;
      };
    } catch {
      queueMicrotask(() => setMapError(true));
    }
  }, []);

  useEffect(() => {
    if (!mapRef.current || !isLoaded) return;
    const source = mapRef.current.getSource("events") as
      GeoJSONSource | undefined;
    source?.setData(toGeoJson(events));
  }, [events, isLoaded]);

  useEffect(() => {
    if (!mapRef.current || !isLoaded) return;
    applyRegionViewport(mapRef.current, region);
  }, [isLoaded, region]);

  useEffect(() => {
    if (!mapRef.current || !isLoaded) return;
    const map = mapRef.current;
    if (map.getLayer("events-circles")) {
      map.setPaintProperty("events-circles", "circle-radius", [
        "case",
        ["==", ["get", "id"], selectedId || ""],
        10,
        6,
      ]);
      map.setPaintProperty("events-circles", "circle-stroke-width", [
        "case",
        ["==", ["get", "id"], selectedId || ""],
        3,
        1.5,
      ]);
    }
    const selectedEvent = eventsRef.current.find(
      (event) => event.public_id === selectedId,
    );
    if (selectedEvent && isMappedEvent(selectedEvent)) {
      map.flyTo({
        center: [selectedEvent.longitude, selectedEvent.latitude],
        zoom: Math.max(map.getZoom(), 4),
        duration: 700,
      });
    }
  }, [isLoaded, selectedId]);

  return (
    <section
      role="region"
      aria-label="Epidemiological Event Map"
      className="event-map"
    >
      <div className="sr-only" aria-live="polite">
        {mappedCount} mapped events across {locationCount} locations,{" "}
        {events.length} total.
      </div>
      <div className="map-legend">
        <span className="map-legend__dot" aria-hidden="true" />
        {mappedCount} mapped · {locationCount} locations · {events.length}{" "}
        events
      </div>
      <button
        type="button"
        className="map-reset-control"
        aria-label="Reset map view"
        title="Reset view"
        onClick={() => {
          popupRef.current?.remove();
          popupRef.current = null;
          setOverlapEvents([]);
          onResetRef.current?.();
          if (mapRef.current && isLoaded) {
            applyRegionViewport(mapRef.current, region);
          }
        }}
      >
        Reset view
      </button>
      {overlapEvents.length > 1 && (
        <div
          className="event-map-overlap"
          role="dialog"
          aria-label="Events at this location"
        >
          <div className="event-map-overlap__header">
            <strong>{overlapEvents.length} events at this location</strong>
            <button
              type="button"
              aria-label="Close events at this location"
              onClick={() => setOverlapEvents([])}
            >
              ×
            </button>
          </div>
          <div className="event-map-overlap__list">
            {overlapEvents.map((event) => (
              <button
                type="button"
                key={event.public_id}
                onClick={() => {
                  setOverlapEvents([]);
                  onSelectRef.current(event.public_id);
                }}
              >
                <strong>{event.headline}</strong>
                <span>
                  {formatCountryLocation(event.admin1, event.country_code)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      {mapError ? (
        <div className="map-fallback">
          Map unavailable. All events remain accessible in Calendar view.
        </div>
      ) : (
        <div ref={mapContainerRef} className="event-map__canvas" />
      )}
    </section>
  );
}
