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

      {selectedId &&
        (() => {
          const selectedItem = items.find((i) => i.id === selectedId);
          if (!selectedItem || !isPlottableLocation(selectedItem.location)) {
            return null;
          }
          return (
            <div
              role="dialog"
              aria-label="Selected signal details"
              className="absolute bottom-2 left-2 right-2 sm:right-auto sm:max-w-sm z-20 bg-white/95 backdrop-blur-sm p-3.5 rounded-lg shadow-md border border-slate-200 text-xs space-y-2"
            >
              <div className="flex items-start justify-between gap-2">
                <h4 className="font-bold text-slate-900 text-sm leading-tight">
                  {selectedItem.title_english}
                </h4>
                <button
                  type="button"
                  onClick={() => onSelect("")}
                  className="text-slate-400 hover:text-slate-600 font-bold px-1 rounded hover:bg-slate-100"
                  aria-label="Close signal details"
                >
                  ✕
                </button>
              </div>

              <div className="flex flex-wrap gap-1.5 pt-0.5">
                <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-100 text-slate-800 font-medium">
                  {selectedItem.source.is_official
                    ? "Official Source"
                    : "Media Source"}
                </span>
                <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">
                  Tier: {selectedItem.source.credibility_tier}
                </span>
                <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-medium">
                  📍 {selectedItem.location.label} (
                  {selectedItem.location.precision})
                </span>
                <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-800 border border-indigo-200 font-medium">
                  {Math.round(selectedItem.extraction_confidence * 100)}%
                  extraction confidence
                </span>
              </div>

              {selectedItem.event && (
                <div className="mt-1 pt-1.5 border-t border-slate-100 bg-amber-50/70 p-2 rounded border border-amber-200">
                  <div className="flex items-center justify-between font-semibold text-amber-950">
                    <span>Event: {selectedItem.event.public_id}</span>
                    <span className="font-normal capitalize text-amber-900">
                      {selectedItem.event.verification_status.replace(
                        /_/g,
                        " ",
                      )}
                    </span>
                  </div>
                  <div className="flex gap-3 text-amber-900 mt-1">
                    {selectedItem.event.early_signal_score !== null && (
                      <span>
                        Surveillance:{" "}
                        <strong>
                          {Math.round(
                            selectedItem.event.early_signal_score * 100,
                          )}
                          %
                        </strong>
                      </span>
                    )}
                    {selectedItem.event.evidence_score !== null && (
                      <span>
                        Evidence:{" "}
                        <strong>
                          {Math.round(selectedItem.event.evidence_score * 100)}%
                        </strong>
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })()}
    </section>
  );
}
