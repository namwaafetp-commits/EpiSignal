import type { paths } from "@episignal/contracts";

export type ReviewQueuePage =
  paths["/api/v1/admin/reviews"]["get"]["responses"][200]["content"]["application/json"];

export type ReviewQueueItem = ReviewQueuePage["items"][number];
export type ReviewCandidateEvent = NonNullable<
  ReviewQueueItem["candidate_events"]
>[number];
export type ReviewDiseaseOption = ReviewQueuePage["disease_options"][number];
export type ReviewSignalLocation = NonNullable<
  ReviewQueueItem["locations"]
>[number];

export type ReviewCaseResult =
  paths["/api/v1/admin/reviews/{case_id}/resolve"]["post"]["responses"][200]["content"]["application/json"];

export type ResolveReviewRequest =
  paths["/api/v1/admin/reviews/{case_id}/resolve"]["post"]["requestBody"]["content"]["application/json"];

export type ReviewQueueState =
  | { status: "ready"; data: ReviewQueuePage }
  | { status: "loading"; data: null }
  | { status: "unauthorized"; data: null }
  | { status: "unavailable"; data: null };

export type ReviewResolutionState =
  | { status: "success"; data: ReviewCaseResult }
  | { status: "conflict"; message: string }
  | { status: "unauthorized"; message: string }
  | { status: "invalid"; message: string }
  | { status: "unavailable"; message: string };

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const ISO_DATETIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

const VALID_REASONS = new Set([
  "retrieval_failed",
  "extraction_rejected",
  "disease_unresolved",
  "location_unresolved",
  "event_match_ambiguous",
  "content_integrity",
  "legacy_unclassified",
]);

const VALID_RESOLUTIONS = new Set([
  "retry_retrieval",
  "retry_extraction",
  "assign_disease",
  "retry_geocoding",
  "link_event",
  "create_event",
  "dismiss",
  "recovered_automatically",
]);

const VALID_VERIFICATION_STATUSES = new Set([
  "unverified",
  "probable",
  "confirmed",
]);

const VALID_LOCATION_ROLES = new Set(["primary", "secondary", "context"]);
const VALID_PRECISIONS = new Set(["place", "admin2", "admin1", "country"]);

const FORBIDDEN_KEYS = new Set([
  "raw_text",
  "source_span",
  "prompt",
  "api_key",
  "secret",
  "password",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown, minimum: number) {
  return Number.isInteger(value) && Number(value) >= minimum;
}

function isTimestamp(value: unknown, nullable = false) {
  if (nullable && value === null) return true;
  if (typeof value !== "string" || !ISO_DATETIME_PATTERN.test(value)) {
    return false;
  }
  return !Number.isNaN(Date.parse(value));
}

function isHttpUrl(value: unknown): boolean {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function hasForbiddenKeys(record: Record<string, unknown>): boolean {
  for (const key of Object.keys(record)) {
    if (FORBIDDEN_KEYS.has(key)) return true;
  }
  return false;
}

export function isReviewCandidateEvent(
  value: unknown,
): value is ReviewCandidateEvent {
  if (!isRecord(value) || hasForbiddenKeys(value)) return false;
  return (
    typeof value.event_id === "string" &&
    UUID_PATTERN.test(value.event_id) &&
    typeof value.public_id === "string" &&
    typeof value.title === "string" &&
    typeof value.verification_status === "string" &&
    VALID_VERIFICATION_STATUSES.has(value.verification_status) &&
    typeof value.match_score === "number" &&
    value.match_score >= 0.0 &&
    value.match_score <= 1.0
  );
}

export function isReviewDiseaseOption(
  value: unknown,
): value is ReviewDiseaseOption {
  if (!isRecord(value) || hasForbiddenKeys(value)) return false;
  return (
    typeof value.id === "string" &&
    UUID_PATTERN.test(value.id) &&
    typeof value.canonical_name === "string" &&
    value.canonical_name.trim().length > 0
  );
}

export function isReviewSignalLocation(
  value: unknown,
): value is ReviewSignalLocation {
  if (!isRecord(value) || hasForbiddenKeys(value)) return false;
  return (
    typeof value.location_role === "string" &&
    VALID_LOCATION_ROLES.has(value.location_role) &&
    typeof value.precision === "string" &&
    VALID_PRECISIONS.has(value.precision) &&
    (value.country_name === undefined ||
      value.country_name === null ||
      typeof value.country_name === "string") &&
    (value.admin1_name === undefined ||
      value.admin1_name === null ||
      typeof value.admin1_name === "string") &&
    (value.place_name === undefined ||
      value.place_name === null ||
      typeof value.place_name === "string") &&
    (value.resolved_name === undefined ||
      value.resolved_name === null ||
      typeof value.resolved_name === "string")
  );
}

export function isReviewQueueItem(value: unknown): value is ReviewQueueItem {
  if (!isRecord(value) || hasForbiddenKeys(value)) return false;
  if (
    typeof value.case_id !== "string" ||
    !UUID_PATTERN.test(value.case_id) ||
    typeof value.signal_id !== "string" ||
    !UUID_PATTERN.test(value.signal_id) ||
    typeof value.reason !== "string" ||
    !VALID_REASONS.has(value.reason) ||
    !isTimestamp(value.opened_at) ||
    typeof value.title !== "string" ||
    typeof value.source_name !== "string" ||
    !isHttpUrl(value.source_url) ||
    !isTimestamp(value.first_seen_at) ||
    !isInteger(value.retrieval_attempts, 0)
  ) {
    return false;
  }

  if (value.locations !== undefined && Array.isArray(value.locations)) {
    if (!value.locations.every(isReviewSignalLocation)) return false;
  }

  if (
    value.candidate_events !== undefined &&
    Array.isArray(value.candidate_events)
  ) {
    if (!value.candidate_events.every(isReviewCandidateEvent)) return false;
  }

  if (
    value.allowed_resolutions !== undefined &&
    Array.isArray(value.allowed_resolutions)
  ) {
    if (
      !value.allowed_resolutions.every(
        (action) => typeof action === "string" && VALID_RESOLUTIONS.has(action),
      )
    ) {
      return false;
    }
  }

  return true;
}

export function isReviewQueuePage(value: unknown): value is ReviewQueuePage {
  if (!isRecord(value) || hasForbiddenKeys(value)) return false;
  if (!Array.isArray(value.items) || !Array.isArray(value.disease_options)) {
    return false;
  }
  if (!isInteger(value.total_open_cases, 0)) return false;
  if (!isInteger(value.limit, 1) || Number(value.limit) > 100) return false;
  if (!isInteger(value.offset, 0)) return false;

  return (
    value.items.every(isReviewQueueItem) &&
    value.disease_options.every(isReviewDiseaseOption)
  );
}

export function isReviewCaseResult(value: unknown): value is ReviewCaseResult {
  if (!isRecord(value) || hasForbiddenKeys(value)) return false;
  return (
    typeof value.case_id === "string" &&
    UUID_PATTERN.test(value.case_id) &&
    typeof value.signal_id === "string" &&
    UUID_PATTERN.test(value.signal_id) &&
    typeof value.resolution === "string" &&
    VALID_RESOLUTIONS.has(value.resolution) &&
    typeof value.processing_status === "string" &&
    !isTimestamp(value.resolved_at) === false &&
    (value.selected_disease_id === undefined ||
      value.selected_disease_id === null ||
      (typeof value.selected_disease_id === "string" &&
        UUID_PATTERN.test(value.selected_disease_id))) &&
    (value.selected_event_id === undefined ||
      value.selected_event_id === null ||
      (typeof value.selected_event_id === "string" &&
        UUID_PATTERN.test(value.selected_event_id)))
  );
}

export async function getReviewQueue(
  token: string,
  limit = 50,
  offset = 0,
  reason?: string,
  status?: string,
): Promise<ReviewQueueState> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (reason) params.set("reason", reason);
    if (status) params.set("status", status);

    const response = await fetch(
      `${baseUrl}/api/v1/admin/reviews?${params.toString()}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );

    if (response.status === 401) {
      return { status: "unauthorized", data: null };
    }
    if (!response.ok) {
      return { status: "unavailable", data: null };
    }

    const body: unknown = await response.json();
    if (!isReviewQueuePage(body)) {
      return { status: "unavailable", data: null };
    }
    return { status: "ready", data: body };
  } catch {
    return { status: "unavailable", data: null };
  }
}

export async function resolveReview(
  token: string,
  caseId: string,
  command: ResolveReviewRequest,
): Promise<ReviewResolutionState> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(
      `${baseUrl}/api/v1/admin/reviews/${caseId}/resolve`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(command),
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );

    if (response.status === 401) {
      return { status: "unauthorized", message: "Unauthorized admin token" };
    }
    if (response.status === 409) {
      return {
        status: "conflict",
        message: "Review case already resolved or target candidate modified",
      };
    }
    if (response.status === 422) {
      return {
        status: "invalid",
        message: "Invalid resolution action or missing required fields",
      };
    }
    if (!response.ok) {
      return { status: "unavailable", message: "Review resolution failed" };
    }

    const body: unknown = await response.json();
    if (!isReviewCaseResult(body)) {
      return {
        status: "unavailable",
        message: "Invalid response format from review resolution",
      };
    }
    return { status: "success", data: body };
  } catch {
    return {
      status: "unavailable",
      message: "Connection error while resolving review case",
    };
  }
}
