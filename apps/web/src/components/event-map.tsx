"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { DashboardEvent } from "../lib/api-dashboard";

export interface EventMapProps {
  events: DashboardEvent[];
  onSelect: (publicId: string) => void;
}

const CARTO_POSITRON_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

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
        map_level: event.map_level,
      },
    })),
  };
}

export function EventMap({ events, onSelect }: EventMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onSelectRef = useRef(onSelect);
  const eventsRef = useRef(events);
  const [mapError, setMapError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);
  const mappedCount = events.filter(isMappedEvent).length;

  useEffect(() => {
    onSelectRef.current = onSelect;
    eventsRef.current = events;
  }, [events, onSelect]);

  useEffect(() => {
    if (!mapContainerRef.current) return;
    try {
      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        style: CARTO_POSITRON_STYLE,
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
            "circle-radius": 7,
            "circle-color": [
              "case",
              ["==", ["get", "map_level"], "admin1"],
              "#d97706",
              "#2563eb",
            ],
            "circle-stroke-width": 2,
            "circle-stroke-color": "#ffffff",
          },
        });
        map.on("click", "events-circles", (event) => {
          const publicId = event.features?.[0]?.properties?.id;
          if (typeof publicId === "string") onSelectRef.current(publicId);
        });
        map.on("mouseenter", "events-circles", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "events-circles", () => {
          map.getCanvas().style.cursor = "";
        });
      });
      map.on("error", () => setMapError(true));
      mapRef.current = map;
      return () => {
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

  return (
    <section
      role="region"
      aria-label="Epidemiological Event Map"
      className="relative w-full h-80 sm:h-96 md:h-[450px] bg-slate-100 rounded-lg overflow-hidden border border-slate-200"
    >
      <div className="sr-only" aria-live="polite">
        {mappedCount} of {events.length} events mapped.
      </div>
      <div className="absolute top-2 left-2 z-10 bg-white/90 backdrop-blur-sm px-2.5 py-1 rounded text-xs font-medium text-slate-700 shadow-sm border border-slate-200">
        {mappedCount} mapped / {events.length} events
      </div>
      {mapError ? (
        <div className="flex h-full items-center justify-center text-sm text-slate-500">
          Map unavailable. All events remain accessible in the list below.
        </div>
      ) : (
        <div ref={mapContainerRef} className="w-full h-full" />
      )}
    </section>
  );
}
