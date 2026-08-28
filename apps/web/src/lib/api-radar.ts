import type { paths } from "@episignal/contracts";

export type RadarFeed =
  paths["/api/v1/radar"]["get"]["responses"][200]["content"]["application/json"];

export type RadarItem = RadarFeed["items"][number];
export type RadarLocation = NonNullable<RadarItem["location"]>;
export type RadarEventContext = NonNullable<RadarItem["event"]>;
export type RadarSource = RadarItem["source"];
export type BriefPoint = RadarItem["brief"][number];

export type RadarFeedState =
  | { status: "ready"; data: RadarFeed }
  | { status: "loading"; data: null }
  | { status: "unavailable"; data: null };

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const BRIEF_SLOTS = [
  "what_where",
  "counts",
  "timing",
  "spread",
  "reporting",
] as const;

const CREDIBILITY_TIERS = new Set(["official", "high", "medium", "unknown"]);
const LOCATION_ROLES = new Set([
  "primary",
  "exposure",
  "diagnosis",
  "travel",
  "reporting",
  "affected_area",
]);
const LOCATION_PRECISIONS = new Set([
  "place",
  "admin2",
  "admin1",
  "country",
  "unresolved",
]);
const EVENT_STATUSES = new Set([
  "officially_confirmed",
  "high_credibility",
  "signal",
  "unverified",
  "rumor_monitoring",
]);
const SIGNAL_TYPES = new Set([
  "outbreak_report",
  "surveillance_update",
  "case_report",
  "imported_case",
  "public_health_action",
  "vaccination_campaign",
  "risk_assessment",
  "situation_report",
  "research",
  "rumor",
  "unknown",
]);
const PROCESSING_STATUSES = new Set([
  "fetched",
  "normalized",
  "classified",
  "extracted",
  "geocoded",
  "matched",
  "published",
  "duplicate",
  "failed",
  "needs_review",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isInteger(value: unknown, minimum: number) {
  return Number.isInteger(value) && Number(value) >= minimum;
}

function isTimestamp(value: unknown, nullable = false) {
  if (nullable && value === null) return true;
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

function isSourceUrl(value: unknown) {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

function isScore(value: unknown, nullable = false) {
  if (nullable && value === null) return true;
  return (
    typeof value === "number" &&
    !Number.isNaN(value) &&
    value >= 0 &&
    value <= 1
  );
}

function isBriefPoint(value: unknown, expectedSlot: string): boolean {
  if (!isRecord(value)) return false;
  return (
    value.slot === expectedSlot &&
    typeof value.text === "string" &&
    typeof value.reported === "boolean"
  );
}

function isRadarSource(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.name === "string" &&
    value.name.length > 0 &&
    isSourceUrl(value.url) &&
    typeof value.is_official === "boolean" &&
    typeof value.credibility_tier === "string" &&
    CREDIBILITY_TIERS.has(value.credibility_tier)
  );
}

function isRadarLocation(value: unknown): boolean {
  if (value === null) return true;
  if (!isRecord(value)) return false;
  if (
    typeof value.role !== "string" ||
    !LOCATION_ROLES.has(value.role) ||
    typeof value.precision !== "string" ||
    !LOCATION_PRECISIONS.has(value.precision) ||
    typeof value.label !== "string" ||
    value.label.length === 0 ||
    (value.country_code !== null && typeof value.country_code !== "string")
  ) {
    return false;
  }

  const lat = value.latitude;
  const lon = value.longitude;
  if (lat === null && lon === null) {
    return true;
  }
  if (typeof lat === "number" && typeof lon === "number") {
    return (
      !Number.isNaN(lat) &&
      !Number.isNaN(lon) &&
      lat >= -90 &&
      lat <= 90 &&
      lon >= -180 &&
      lon <= 180
    );
  }
  return false;
}

function isRadarEventContext(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.public_id === "string" &&
    value.public_id.length > 0 &&
    typeof value.verification_status === "string" &&
    EVENT_STATUSES.has(value.verification_status) &&
    isScore(value.early_signal_score, true) &&
    isScore(value.evidence_score, true)
  );
}

function isRadarItem(value: unknown): boolean {
  if (!isRecord(value)) return false;
  if (
    typeof value.id !== "string" ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.title_english !== "string" ||
    value.title_english.length === 0 ||
    typeof value.signal_type !== "string" ||
    !SIGNAL_TYPES.has(value.signal_type) ||
    typeof value.processing_status !== "string" ||
    !PROCESSING_STATUSES.has(value.processing_status) ||
    !isTimestamp(value.published_at, true) ||
    !isTimestamp(value.first_seen_at) ||
    !isScore(value.extraction_confidence) ||
    !isRadarSource(value.source) ||
    !isRadarLocation(value.location)
  ) {
    return false;
  }

  if (
    !Array.isArray(value.brief) ||
    value.brief.length !== BRIEF_SLOTS.length
  ) {
    return false;
  }
  for (let i = 0; i < BRIEF_SLOTS.length; i++) {
    if (!isBriefPoint(value.brief[i], BRIEF_SLOTS[i])) {
      return false;
    }
  }

  const status = value.event_context_status;
  if (status === "none" || status === "ambiguous") {
    return value.event === null;
  }
  if (status === "attached") {
    return isRadarEventContext(value.event);
  }
  return false;
}

export function isRadarFeed(value: unknown): value is RadarFeed {
  if (!isRecord(value) || !Array.isArray(value.items)) return false;
  if (
    !isTimestamp(value.window_start) ||
    !isTimestamp(value.window_end) ||
    !isInteger(value.hours, 1) ||
    Number(value.hours) > 168 ||
    !isInteger(value.limit, 1) ||
    Number(value.limit) > 100 ||
    value.items.length > Number(value.limit)
  ) {
    return false;
  }
  return value.items.every(isRadarItem);
}

export async function getRadarFeed({
  hours = 48,
  limit = 50,
}: {
  hours?: number;
  limit?: number;
} = {}): Promise<RadarFeedState> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const params = new URLSearchParams({
      hours: String(hours),
      limit: String(limit),
    });
    const response = await fetch(
      `${baseUrl}/api/v1/radar?${params.toString()}`,
      {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) return { status: "unavailable", data: null };
    const body: unknown = await response.json();
    if (!isRadarFeed(body)) return { status: "unavailable", data: null };
    return { status: "ready", data: body };
  } catch {
    return { status: "unavailable", data: null };
  }
}
