"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { RadarItem } from "../lib/api-radar";
import {
  isPlottableLocation,
  toGeoJsonFeatures,
} from "../lib/radar-map-helpers";

export interface SignalMapProps {
  items: RadarItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const CARTO_POSITRON_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

export function SignalMap({ items, selectedId, onSelect }: SignalMapProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [mapError, setMapError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);

  const plottableCount = items.filter((i) =>
    isPlottableLocation(i.location),
  ).length;
  const totalCount = items.length;

  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const itemsRef = useRef(items);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const selectedIdRef = useRef(selectedId);
  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

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
        const geojsonData = toGeoJsonFeatures(itemsRef.current);

        map.addSource("signals", {
          type: "geojson",
          data: geojsonData,
        });

        // Add circles for markers
        map.addLayer({
          id: "signals-circles",
          type: "circle",
          source: "signals",
          paint: {
            "circle-radius": [
              "case",
              ["==", ["get", "id"], selectedIdRef.current || ""],
              10,
              6,
            ],
            "circle-color": [
              "case",
              ["get", "has_event"],
              "#d97706", // warm amber for attached event
              "#2563eb", // blue for signal
            ],
            "circle-stroke-width": [
              "case",
              ["==", ["get", "id"], selectedIdRef.current || ""],
              3,
              1.5,
            ],
            "circle-stroke-color": "#ffffff",
          },
        });

        // Click handler on marker
        map.on("click", "signals-circles", (e) => {
          const feature = e.features?.[0];
          const id = feature?.properties?.id;
          if (id && typeof id === "string") {
            onSelectRef.current(id);
          }
        });

        map.on("mouseenter", "signals-circles", () => {
          map.getCanvas().style.cursor = "pointer";
        });

        map.on("mouseleave", "signals-circles", () => {
          map.getCanvas().style.cursor = "";
        });
      });

      map.on("error", () => {
        setMapError(true);
      });

      mapRef.current = map;

      return () => {
        map.remove();
        mapRef.current = null;
      };
    } catch {
      queueMicrotask(() => {
        setMapError(true);
      });
    }
  }, []);

  // Update source data when items change
  useEffect(() => {
    if (!mapRef.current || !isLoaded) return;
    const source = mapRef.current.getSource("signals") as
      GeoJSONSource | undefined;
    if (source && typeof source.setData === "function") {
      source.setData(toGeoJsonFeatures(items));
    }
  }, [items, isLoaded]);

  // Update selection styling and fly to location
  useEffect(() => {
    if (!mapRef.current || !isLoaded) return;
    const map = mapRef.current;

    if (typeof map.getLayer === "function" && map.getLayer("signals-circles")) {
      map.setPaintProperty("signals-circles", "circle-radius", [
        "case",
        ["==", ["get", "id"], selectedId || ""],
        10,
        6,
      ]);
      map.setPaintProperty("signals-circles", "circle-stroke-width", [
        "case",
        ["==", ["get", "id"], selectedId || ""],
        3,
        1.5,
      ]);
    }

    if (selectedId) {
      const selectedItem = items.find((i) => i.id === selectedId);
      if (
        selectedItem &&
        isPlottableLocation(selectedItem.location) &&
        typeof map.flyTo === "function"
      ) {
        map.flyTo({
          center: [
            selectedItem.location.longitude,
            selectedItem.location.latitude,
          ],
          zoom: Math.max(map.getZoom(), 4),
          duration: 1000,
        });
      }
    }
  }, [selectedId, items, isLoaded]);

  return (
    <section
      role="region"
      aria-label="Epidemiological Signal Map"
      className="relative w-full h-80 sm:h-96 md:h-[450px] bg-slate-100 rounded-lg overflow-hidden border border-slate-200"
    >
      <div className="sr-only" aria-live="polite">
        {plottableCount} of {totalCount} signals plotted on map.
      </div>
      <div className="absolute top-2 left-2 z-10 bg-white/90 backdrop-blur-sm px-2.5 py-1 rounded text-xs font-medium text-slate-700 shadow-sm border border-slate-200">
        <span>
          {plottableCount} of {totalCount} signals plotted
        </span>
        {totalCount > plottableCount && (
          <span className="text-slate-500 ml-1">
            ({totalCount - plottableCount} unresolved coordinates)
          </span>
        )}
      </div>
      {mapError ? (
        <div className="flex h-full items-center justify-center text-sm text-slate-500">
          Map unavailable. All signals remain accessible in the list below.
        </div>
      ) : (
        <div ref={mapContainerRef} className="w-full h-full" />
      )}
    </section>
  );
}
