import type { RadarItem, RadarLocation } from "./api-radar";

export interface RadarMapProperties {
  id: string;
  title_english: string;
  label: string;
  precision: string;
  role: string;
  credibility_tier: string;
  is_official: boolean;
  early_signal_score: number | null;
  has_event: boolean;
}

export interface RadarMapFeature {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number]; // [longitude, latitude]
  };
  properties: RadarMapProperties;
}

export interface RadarFeatureCollection {
  type: "FeatureCollection";
  features: RadarMapFeature[];
}

export function isPlottableLocation(
  location: RadarLocation | null,
): location is RadarLocation & { latitude: number; longitude: number } {
  if (!location) return false;
  if (location.precision === "unresolved") return false;
  return (
    typeof location.latitude === "number" &&
    !Number.isNaN(location.latitude) &&
    typeof location.longitude === "number" &&
    !Number.isNaN(location.longitude)
  );
}

export function toGeoJsonFeatures(
  items: readonly RadarItem[],
): RadarFeatureCollection {
  const features: RadarMapFeature[] = [];

  for (const item of items) {
    if (!isPlottableLocation(item.location)) continue;

    features.push({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [item.location.longitude, item.location.latitude],
      },
      properties: {
        id: item.id,
        title_english: item.title_english,
        label: item.location.label,
        precision: item.location.precision,
        role: item.location.role,
        credibility_tier: item.source.credibility_tier,
        is_official: item.source.is_official,
        early_signal_score: item.event?.early_signal_score ?? null,
        has_event:
          item.event_context_status === "attached" && item.event !== null,
      },
    });
  }

  return {
    type: "FeatureCollection",
    features,
  };
}

function formatTierLabel(tier: string, isOfficial: boolean): string {
  if (isOfficial) return "Official Source";
  switch (tier) {
    case "official":
      return "Official Source";
    case "high":
      return "High Credibility Source";
    case "medium":
      return "Medium Credibility Source";
    default:
      return "Unknown Credibility Source";
  }
}

export function getMarkerAriaLabel(item: RadarItem): string {
  const sourceLabel = formatTierLabel(
    item.source.credibility_tier,
    item.source.is_official,
  );
  if (item.location && item.location.label) {
    return `${item.title_english} (${item.location.label}, ${item.location.precision}) — ${sourceLabel}`;
  }
  return `${item.title_english} — ${sourceLabel}`;
}
