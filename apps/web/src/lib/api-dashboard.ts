export interface DashboardEvent {
  public_id: string;
  headline: string;
  summary: string;
  disease: string | null;
  event_type: string;
  status: string;
  country_code: string | null;
  town: string | null;
  first_reported_at: string | null;
  latest_report_at: string;
  article_count: number;
  last_summarized_at: string;
  latitude: number | null;
  longitude: number | null;
  map_level: "town" | "country" | null;
}

export interface DashboardEventsResponse {
  items: DashboardEvent[];
  total: number;
}

export type DashboardFeedState =
  | { status: "ready"; data: DashboardEventsResponse }
  | { status: "loading"; data: null }
  | { status: "unavailable"; data: null };

const ISO_DATETIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function isTimestamp(value: unknown, nullable = false): boolean {
  if (nullable && value === null) return true;
  return (
    typeof value === "string" &&
    ISO_DATETIME_PATTERN.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isCoordinate(
  value: unknown,
  minimum: number,
  maximum: number,
): boolean {
  return (
    value === null ||
    (typeof value === "number" &&
      !Number.isNaN(value) &&
      value >= minimum &&
      value <= maximum)
  );
}

function isDashboardEvent(value: unknown): value is DashboardEvent {
  if (typeof value !== "object" || value === null) return false;
  const event = value as Record<string, unknown>;
  return (
    typeof event.public_id === "string" &&
    event.public_id.length > 0 &&
    typeof event.headline === "string" &&
    event.headline.length > 0 &&
    typeof event.summary === "string" &&
    event.summary.trim().length > 0 &&
    (event.disease === null || typeof event.disease === "string") &&
    typeof event.event_type === "string" &&
    typeof event.status === "string" &&
    (event.country_code === null || typeof event.country_code === "string") &&
    (event.town === null || typeof event.town === "string") &&
    isTimestamp(event.first_reported_at, true) &&
    isTimestamp(event.latest_report_at) &&
    Number.isInteger(event.article_count) &&
    Number(event.article_count) >= 0 &&
    isTimestamp(event.last_summarized_at) &&
    isCoordinate(event.latitude, -90, 90) &&
    isCoordinate(event.longitude, -180, 180) &&
    (event.map_level === null ||
      event.map_level === "town" ||
      event.map_level === "country")
  );
}

function isDashboardResponse(value: unknown): value is DashboardEventsResponse {
  if (typeof value !== "object" || value === null) return false;
  const response = value as Record<string, unknown>;
  return (
    Array.isArray(response.items) &&
    response.items.every(isDashboardEvent) &&
    Number.isInteger(response.total) &&
    Number(response.total) === response.items.length
  );
}

export async function getDashboardEvents(): Promise<DashboardFeedState> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${baseUrl}/api/v1/events/dashboard`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return { status: "unavailable", data: null };
    const body: unknown = await response.json();
    if (!isDashboardResponse(body)) {
      return { status: "unavailable", data: null };
    }
    return { status: "ready", data: body };
  } catch {
    return { status: "unavailable", data: null };
  }
}
