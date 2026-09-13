"use client";

import { useEffect, useRef, useState } from "react";
import { RotateCcw, X } from "lucide-react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { DashboardEvent } from "../lib/api-dashboard";
import { countryName } from "../lib/country";

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
  theme?: "light" | "dark";
}

const CARTO_LIGHT_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const CARTO_DARK_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const MAP_STYLE = { light: CARTO_LIGHT_STYLE, dark: CARTO_DARK_STYLE };
const MAP_MOVE_DURATION = 700;

// Points are graded by how recently the event was reported: newest reads red,
// and the ramp cools to yellow as reporting ages.
export const RECENCY_RAMP_HOURS = 168;
export const RECENCY_COLORS = [
  "#c1121f",
  "#e05a17",
  "#dfa520",
  "#d9cb4f",
] as const;

function mapMoveDuration() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ? 0
    : MAP_MOVE_DURATION;
}

function isMappedEvent(
  event: DashboardEvent,
): event is DashboardEvent & { latitude: number; longitude: number } {
  return (
    (event.map_level === "admin1" || event.map_level === "country") &&
    typeof event.latitude === "number" &&
    typeof event.longitude === "number" &&
    Number.isFinite(event.latitude) &&
    Number.isFinite(event.longitude) &&
    event.latitude >= -90 &&
    event.latitude <= 90 &&
    event.longitude >= -180 &&
    event.longitude <= 180
  );
}

function reportAgeHours(reportedAt: string, now: number) {
  const timestamp = Date.parse(reportedAt);
  if (!Number.isFinite(timestamp)) return RECENCY_RAMP_HOURS;
  return Math.max(0, (now - timestamp) / 3_600_000);
}

export function toGeoJson(
  events: readonly DashboardEvent[],
  now: number = Date.now(),
) {
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
        disease_group: event.disease_group ?? "unknown",
        age_hours: reportAgeHours(event.latest_report_at, now),
        headline: event.headline,
        location: mapLocation(event.admin1, event.country_code),
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

function mapLocation(admin1: string | null, countryCode: string | null) {
  const country = countryName(countryCode);
  return admin1 ? `${admin1}, ${country}` : country;
}

function applyRegionViewport(map: maplibregl.Map, region: EventMapRegion) {
  const duration = mapMoveDuration();
  if (!region) {
    map.easeTo({
      ...DEFAULT_MAP_VIEWPORT,
      duration,
    });
    return;
  }

  map.fitBounds(REGION_BOUNDS[region], {
    padding: 40,
    duration,
    maxZoom: 6,
  });
}

function addEventLayers(
  map: maplibregl.Map,
  events: readonly DashboardEvent[],
  selectedId: string | null,
) {
  map.addSource("events", {
    type: "geojson",
    data: toGeoJson(events),
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
        "#718087",
        10,
        "#8a826f",
        30,
        "#8f706b",
      ],
      "circle-radius": ["step", ["get", "point_count"], 18, 10, 24, 30, 30],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#f4f1e8",
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
    paint: { "text-color": "#252525" },
  });
  map.addLayer({
    id: "events-circles",
    type: "circle",
    source: "events",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-radius": ["case", ["==", ["get", "id"], selectedId || ""], 10, 6],
      "circle-color": [
        "interpolate",
        ["linear"],
        ["get", "age_hours"],
        0,
        RECENCY_COLORS[0],
        24,
        RECENCY_COLORS[1],
        72,
        RECENCY_COLORS[2],
        RECENCY_RAMP_HOURS,
        RECENCY_COLORS[3],
      ],
      "circle-opacity": 0.92,
      "circle-stroke-width": [
        "case",
        ["==", ["get", "id"], selectedId || ""],
        3,
        1.5,
      ],
      "circle-stroke-color": "#f4f1e8",
    },
  });
}

export function EventMap({
  events,
  region,
  selectedId,
  onSelect,
  onReset,
  theme = "light",
}: EventMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const onSelectRef = useRef(onSelect);
  const onResetRef = useRef(onReset);
  const eventsRef = useRef(events);
  const selectedIdRef = useRef(selectedId);
  const themeRef = useRef(theme);
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
        style: MAP_STYLE[themeRef.current],
        ...DEFAULT_MAP_VIEWPORT,
        minZoom: 1,
        maxZoom: 14,
      });
      map.addControl(new maplibregl.NavigationControl(), "top-right");
      map.on("load", () => {
        setIsLoaded(true);
        addEventLayers(map, eventsRef.current, selectedIdRef.current);

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
            duration: mapMoveDuration(),
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
    const map = mapRef.current;
    if (!map || !isLoaded || themeRef.current === theme) return;
    themeRef.current = theme;
    map.setStyle(MAP_STYLE[theme]);
    map.once("style.load", () => {
      if (mapRef.current === map && themeRef.current === theme) {
        addEventLayers(map, eventsRef.current, selectedIdRef.current);
      }
    });
  }, [isLoaded, theme]);

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
        duration: mapMoveDuration(),
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
        <span>Newest</span>
        <span className="map-legend__ramp" aria-hidden="true" />
        <span>Older</span>
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
        <RotateCcw aria-hidden="true" size={18} />
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
              <X aria-hidden="true" size={18} />
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
                <span>{mapLocation(event.admin1, event.country_code)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      {mapError ? (
        <div className="map-fallback">
          Map unavailable. All events remain accessible in Briefing view.
        </div>
      ) : (
        <div ref={mapContainerRef} className="event-map__canvas" />
      )}
    </section>
  );
}
