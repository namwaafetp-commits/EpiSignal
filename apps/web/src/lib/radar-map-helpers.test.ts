import { describe, expect, it } from "vitest";
import type { RadarItem, RadarLocation } from "./api-radar";
import {
  getMarkerAriaLabel,
  isPlottableLocation,
  toGeoJsonFeatures,
} from "./radar-map-helpers";

function makeItem(
  overrides: Partial<RadarItem> = {},
  locationOverrides: Partial<RadarLocation> | null = {},
): RadarItem {
  const loc: RadarLocation | null =
    locationOverrides === null
      ? null
      : {
          role: "primary",
          precision: "place",
          label: "Luanda",
          country_code: "AO",
          latitude: -8.8383,
          longitude: 13.2344,
          ...locationOverrides,
        };

  return {
    id: "24681357-1234-5678-9abc-def012345678",
    title_english: "Cholera in Luanda",
    brief: [
      { slot: "what_where", text: "Cholera in Luanda.", reported: true },
      { slot: "counts", text: "120 cases.", reported: true },
      { slot: "timing", text: "Aug 20.", reported: true },
      { slot: "spread", text: "District wide.", reported: true },
      { slot: "reporting", text: "MoH.", reported: true },
    ],
    signal_type: "outbreak_report",
    processing_status: "matched",
    published_at: "2026-08-28T10:00:00Z",
    first_seen_at: "2026-08-28T10:05:00Z",
    source: {
      name: "WHO AFRO",
      url: "https://afro.who.int/report/123",
      is_official: true,
      credibility_tier: "official",
    },
    extraction_confidence: 0.95,
    location: loc,
    event_context_status: "attached",
    event: {
      public_id: "EVT-2026-00042",
      verification_status: "officially_confirmed",
      early_signal_score: 0.88,
      evidence_score: 0.94,
    },
    ...overrides,
  };
}

describe("isPlottableLocation", () => {
  it("returns true for valid resolved location with coordinates", () => {
    const loc: RadarLocation = {
      role: "primary",
      precision: "place",
      label: "Kano",
      country_code: "NG",
      latitude: 12.0,
      longitude: 8.5,
    };
    expect(isPlottableLocation(loc)).toBe(true);
  });

  it("returns false for null location", () => {
    expect(isPlottableLocation(null)).toBe(false);
  });

  it("returns false for unresolved precision", () => {
    const loc: RadarLocation = {
      role: "primary",
      precision: "unresolved",
      label: "Unknown Area",
      country_code: "NG",
      latitude: 12.0,
      longitude: 8.5,
    };
    expect(isPlottableLocation(loc)).toBe(false);
  });

  it("returns false when latitude or longitude is null", () => {
    const loc1: RadarLocation = {
      role: "primary",
      precision: "place",
      label: "Kano",
      country_code: "NG",
      latitude: null,
      longitude: 8.5,
    };
    expect(isPlottableLocation(loc1)).toBe(false);

    const loc2: RadarLocation = {
      role: "primary",
      precision: "place",
      label: "Kano",
      country_code: "NG",
      latitude: 12.0,
      longitude: null,
    };
    expect(isPlottableLocation(loc2)).toBe(false);
  });
});

describe("toGeoJsonFeatures", () => {
  it("transforms plottable items to GeoJSON FeatureCollection with exact properties", () => {
    const item1 = makeItem({ id: "11111111-1111-1111-1111-111111111111" });
    const item2 = makeItem(
      {
        id: "22222222-2222-2222-2222-222222222222",
        title_english: "Mpox in Kinshasa",
        event_context_status: "none",
        event: null,
      },
      {
        label: "Kinshasa",
        precision: "admin1",
        latitude: -4.4419,
        longitude: 15.2663,
      },
    );
    const unplottable = makeItem(
      { id: "33333333-3333-3333-3333-333333333333" },
      null,
    );

    const geojson = toGeoJsonFeatures([item1, item2, unplottable]);

    expect(geojson.type).toBe("FeatureCollection");
    expect(geojson.features).toHaveLength(2);

    expect(geojson.features[0]).toEqual({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [13.2344, -8.8383], // [longitude, latitude]
      },
      properties: {
        id: "11111111-1111-1111-1111-111111111111",
        title_english: "Cholera in Luanda",
        label: "Luanda",
        precision: "place",
        role: "primary",
        credibility_tier: "official",
        is_official: true,
        early_signal_score: 0.88,
        has_event: true,
      },
    });

    expect(geojson.features[1]).toEqual({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [15.2663, -4.4419],
      },
      properties: {
        id: "22222222-2222-2222-2222-222222222222",
        title_english: "Mpox in Kinshasa",
        label: "Kinshasa",
        precision: "admin1",
        role: "primary",
        credibility_tier: "official",
        is_official: true,
        early_signal_score: null,
        has_event: false,
      },
    });
  });
});

describe("getMarkerAriaLabel", () => {
  it("formats accessible description for official source and location", () => {
    const item = makeItem();
    expect(getMarkerAriaLabel(item)).toBe(
      "Cholera in Luanda (Luanda, place) — Official Source",
    );
  });

  it("formats accessible description for high credibility source without location", () => {
    const item = makeItem(
      {
        source: {
          name: "Local News",
          url: "https://news.ao/1",
          is_official: false,
          credibility_tier: "high",
        },
      },
      null,
    );
    expect(getMarkerAriaLabel(item)).toBe(
      "Cholera in Luanda — High Credibility Source",
    );
  });
});
