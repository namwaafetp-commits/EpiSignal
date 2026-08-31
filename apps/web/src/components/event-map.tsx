"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { DashboardEvent } from "../lib/api-dashboard";

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

export interface EventMapProps {
  events: DashboardEvent[];
  region: EventMapRegion;
  selectedId: string | null;
  onSelect: (publicId: string) => void;
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

function toGeoJson(events: readonly DashboardEvent[]) {
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
        location: event.admin1
          ? `${event.admin1}, ${event.country_code ?? "Unknown country"}`
          : (event.country_code ?? "Unknown location"),
      },
    })),
  };
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
      center: [15, 5],
      zoom: 1.8,
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
}: EventMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const onSelectRef = useRef(onSelect);
  const eventsRef = useRef(events);
  const selectedIdRef = useRef(selectedId);
  const [mapError, setMapError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);
  const mappedCount = events.filter(isMappedEvent).length;

  useEffect(() => {
    onSelectRef.current = onSelect;
    eventsRef.current = events;
    selectedIdRef.current = selectedId;
  }, [events, onSelect, selectedId]);

  useEffect(() => {
    if (!mapContainerRef.current) return;
    try {
      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        style: CARTO_DARK_STYLE,
        center: [15, 5],
        zoom: 1.8,
        minZoom: 1,
        maxZoom: 14,
      });
      map.addControl(new maplibregl.NavigationControl(), "top-right");
      map.on("load", () => {
        setIsLoaded(true);
        map.addSource("events", {
          type: "geojson",
          data: toGeoJson(eventsRef.current),
        });
        map.addLayer({
          id: "events-circles",
          type: "circle",
          source: "events",
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

        map.on("click", "events-circles", (event) => {
          const publicId = event.features?.[0]?.properties?.id;
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
        {mappedCount} of {events.length} events mapped.
      </div>
      <div className="map-legend">
        <span className="map-legend__dot" aria-hidden="true" />
        {mappedCount} mapped · {events.length} events
      </div>
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
