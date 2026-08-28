import type { paths } from "@episignal/contracts";

export type PipelineRunList =
  paths["/api/v1/admin/pipeline-runs"]["get"]["responses"][200]["content"]["application/json"];

export type PipelineRun = PipelineRunList["items"][number];
export type PipelineFailure = PipelineRun["failures"][number];

export type PipelineRunState =
  | { status: "ready"; data: PipelineRunList }
  | { status: "loading"; data: null }
  | { status: "unavailable"; data: null };

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const VALID_CHAINS = new Set(["daily"]);
const VALID_TRIGGERS = new Set(["scheduled", "manual"]);
const VALID_STATUSES = new Set(["running", "succeeded", "failed"]);
const VALID_STAGES = new Set([
  "ingest_who",
  "ingest_ecdc",
  "discover",
  "dedupe",
  "extract",
  "geocode",
  "match",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown, minimum: number) {
  return Number.isInteger(value) && Number(value) >= minimum;
}

function isTimestamp(value: unknown, nullable = false) {
  if (nullable && value === null) return true;
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

function isPipelineFailure(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  if (keys.some((k) => k !== "stage" && k !== "error")) return false;
  return (
    typeof value.stage === "string" &&
    VALID_STAGES.has(value.stage) &&
    (value.error === null || typeof value.error === "string")
  );
}

function isPipelineRun(value: unknown): boolean {
  if (!isRecord(value)) return false;
  if (
    typeof value.id !== "string" ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.chain !== "string" ||
    !VALID_CHAINS.has(value.chain) ||
    typeof value.trigger !== "string" ||
    !VALID_TRIGGERS.has(value.trigger) ||
    typeof value.status !== "string" ||
    !VALID_STATUSES.has(value.status) ||
    !isTimestamp(value.started_at) ||
    !isTimestamp(value.finished_at, true) ||
    !isTimestamp(value.window_start, true) ||
    !isTimestamp(value.window_end, true) ||
    typeof value.is_stale !== "boolean" ||
    (value.is_stale && value.status !== "running") ||
    !isRecord(value.stage_counts) ||
    !isRecord(value.backlog) ||
    !Array.isArray(value.failures)
  ) {
    return false;
  }

  // Validate stage_counts: dict[str, dict[str, int]]
  for (const [stage, counts] of Object.entries(value.stage_counts)) {
    if (!VALID_STAGES.has(stage) || !isRecord(counts)) return false;
    for (const count of Object.values(counts)) {
      if (!isInteger(count, 0)) return false;
    }
  }

  // Validate backlog: dict[str, int]
  for (const count of Object.values(value.backlog)) {
    if (!isInteger(count, 0)) return false;
  }

  // Validate failures
  return value.failures.every(isPipelineFailure);
}

export function isPipelineRunList(value: unknown): value is PipelineRunList {
  if (!isRecord(value) || !Array.isArray(value.items)) return false;
  if (!isInteger(value.limit, 1) || Number(value.limit) > 50) return false;
  if (value.items.length > Number(value.limit)) return false;
  return value.items.every(isPipelineRun);
}

export async function getPipelineRuns(limit = 20): Promise<PipelineRunState> {
  const baseUrl =
    process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const params = new URLSearchParams({
      limit: String(limit),
    });
    const response = await fetch(
      `${baseUrl}/api/v1/admin/pipeline-runs?${params.toString()}`,
      {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) return { status: "unavailable", data: null };
    const body: unknown = await response.json();
    if (!isPipelineRunList(body)) return { status: "unavailable", data: null };
    return { status: "ready", data: body };
  } catch {
    return { status: "unavailable", data: null };
  }
}
