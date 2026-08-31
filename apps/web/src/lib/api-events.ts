import type { paths } from "@episignal/contracts";

export type EventListResponse =
  paths["/api/v1/events"]["get"]["responses"][200]["content"]["application/json"];
export type EventListItem = EventListResponse["items"][number];
export type EventDetailResponse =
  paths["/api/v1/events/{public_id}"]["get"]["responses"][200]["content"]["application/json"];
export type EventSourceItemList =
  paths["/api/v1/events/{public_id}/sources"]["get"]["responses"][200]["content"]["application/json"];
export type EventObservationItemList =
  paths["/api/v1/events/{public_id}/observations"]["get"]["responses"][200]["content"]["application/json"];
export type EventSourceItem = EventSourceItemList[number];
export type ObservationItem = EventObservationItemList[number];

export type EventFeedState =
  | { status: "ready"; data: EventListResponse }
  | { status: "loading"; data: null }
  | { status: "unavailable"; data: null };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

const ISO_DATETIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function isTimestamp(value: unknown, nullable = false) {
  if (nullable && value === null) return true;
  if (typeof value !== "string" || !ISO_DATETIME_PATTERN.test(value))
    return false;
  return !Number.isNaN(Date.parse(value));
}

function isEventListItem(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.public_id === "string" &&
    value.public_id.length > 0 &&
    (value.headline === null || typeof value.headline === "string") &&
    (value.disease === null || typeof value.disease === "string") &&
    typeof value.status === "string" &&
    typeof value.verification_status === "string" &&
    typeof value.article_count === "number"
  );
}

export function isEventListResponse(
  value: unknown,
): value is EventListResponse {
  if (!isRecord(value) || !Array.isArray(value.items)) return false;
  if (
    typeof value.total !== "number" ||
    typeof value.limit !== "number" ||
    typeof value.offset !== "number"
  ) {
    return false;
  }
  return value.items.every(isEventListItem);
}

function isEventDetailResponse(value: unknown): value is EventDetailResponse {
  if (!isRecord(value)) return false;
  const d = value as Record<string, unknown>;
  return (
    typeof d.public_id === "string" &&
    d.public_id.length > 0 &&
    typeof d.status === "string" &&
    typeof d.verification_status === "string" &&
    typeof d.article_count === "number" &&
    isTimestamp(d.latest_report_at as unknown) &&
    Array.isArray(d.sources) &&
    Array.isArray(d.observations)
  );
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

export async function getEventList({
  limit = 20,
  offset = 0,
  disease,
  country,
  status,
}: {
  limit?: number;
  offset?: number;
  disease?: string;
  country?: string;
  status?: string;
} = {}): Promise<EventFeedState> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (disease) params.set("disease", disease);
    if (country) params.set("country", country);
    if (status) params.set("status", status);
    const response = await fetch(
      `${baseUrl}/api/v1/events?${params.toString()}`,
      {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) return { status: "unavailable", data: null };
    const body: unknown = await response.json();
    if (!isEventListResponse(body))
      return { status: "unavailable", data: null };
    return { status: "ready", data: body };
  } catch {
    return { status: "unavailable", data: null };
  }
}

export async function getEventDetail(
  publicId: string,
): Promise<EventDetailResponse | null> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    if (!publicId || typeof publicId !== "string") return null;
    const response = await fetch(
      `${baseUrl}/api/v1/events/${encodeURIComponent(publicId)}`,
      { cache: "no-store", signal: AbortSignal.timeout(5000) },
    );
    if (!response.ok) return null;
    const body: unknown = await response.json();
    if (!isEventDetailResponse(body)) return null;
    return body;
  } catch {
    return null;
  }
}

export async function getEventSources(
  publicId: string,
): Promise<EventSourceItemList | null> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(
      `${baseUrl}/api/v1/events/${encodeURIComponent(publicId)}/sources`,
      { cache: "no-store", signal: AbortSignal.timeout(5000) },
    );
    if (!response.ok) return null;
    const body: unknown = await response.json();
    if (!Array.isArray(body)) return null;
    return body as EventSourceItemList;
  } catch {
    return null;
  }
}

export async function getEventObservations(
  publicId: string,
): Promise<EventObservationItemList | null> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(
      `${baseUrl}/api/v1/events/${encodeURIComponent(publicId)}/observations`,
      { cache: "no-store", signal: AbortSignal.timeout(5000) },
    );
    if (!response.ok) return null;
    const body: unknown = await response.json();
    if (!Array.isArray(body)) return null;
    return body as EventObservationItemList;
  } catch {
    return null;
  }
}

export function formatVerificationStatus(status: string) {
  switch (status) {
    case "officially_confirmed":
      return "Officially Confirmed";
    case "high_credibility":
      return "High Credibility Event";
    case "signal":
      return "Early Signal Event";
    case "unverified":
      return "Unverified Event";
    case "rumor_monitoring":
      return "Rumor Monitoring";
    default:
      return status;
  }
}

export function dateLabel(value: string | null) {
  if (!value) return "Not reported";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value));
}

export function relativeTimeLabel(value: string) {
  const minutes = Math.round((Date.now() - Date.parse(value)) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export function isValidSourceEntry(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof (value as Record<string, unknown>).source_name === "string" &&
    isSourceUrl((value as Record<string, unknown>).url)
  );
}
