import type { paths } from "@episignal/contracts";

export type EvidenceFeed =
  paths["/api/v1/signals"]["get"]["responses"][200]["content"]["application/json"];

export type EvidenceFeedState =
  | { status: "ready"; data: EvidenceFeed }
  | { status: "loading"; data: null }
  | { status: "unavailable"; data: null };

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

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

function isEvidenceItem(value: unknown) {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    UUID_PATTERN.test(value.id) &&
    typeof value.source_name === "string" &&
    value.source_name.length > 0 &&
    typeof value.title === "string" &&
    value.title.length > 0 &&
    typeof value.raw_text === "string" &&
    value.raw_text.trim().length > 0 &&
    isSourceUrl(value.url) &&
    isTimestamp(value.published_at, true) &&
    isTimestamp(value.retrieved_at)
  );
}

function isEvidenceFeed(value: unknown): value is EvidenceFeed {
  if (!isRecord(value) || !Array.isArray(value.items)) return false;
  if (
    !isInteger(value.total, 0) ||
    !isInteger(value.source_count, 0) ||
    !isInteger(value.limit, 1) ||
    Number(value.limit) > 50 ||
    !isInteger(value.offset, 0) ||
    value.items.length > Number(value.limit) ||
    Number(value.source_count) > Number(value.total) ||
    (Number(value.total) > 0 && Number(value.source_count) === 0) ||
    (value.items.length > 0 &&
      Number(value.total) < Number(value.offset) + value.items.length)
  ) {
    return false;
  }
  return value.items.every(isEvidenceItem);
}

export async function getEvidenceFeed(): Promise<EvidenceFeedState> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${baseUrl}/api/v1/signals`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return { status: "unavailable", data: null };
    const body: unknown = await response.json();
    if (!isEvidenceFeed(body)) return { status: "unavailable", data: null };
    return { status: "ready", data: body };
  } catch {
    return { status: "unavailable", data: null };
  }
}
