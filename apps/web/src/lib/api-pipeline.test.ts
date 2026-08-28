import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  getPipelineRuns,
  isPipelineRunList,
  type PipelineRunList,
} from "./api-pipeline";

const VALID_PIPELINE_RUNS: PipelineRunList = {
  items: [
    {
      id: "12345678-1234-5678-1234-567812345678",
      chain: "daily",
      trigger: "scheduled",
      status: "failed",
      started_at: "2026-08-28T10:00:00Z",
      finished_at: "2026-08-28T10:08:30Z",
      window_start: "2026-08-27T10:00:00Z",
      window_end: "2026-08-28T10:00:00Z",
      stage_counts: {
        extract: { extracted: 10, review: 2 },
      },
      backlog: { extracted: 0 },
      failures: [{ stage: "extract", error: "TimeoutError" }],
      is_stale: false,
    },
  ],
  limit: 20,
};

describe("isPipelineRunList", () => {
  it("accepts valid pipeline runs list", () => {
    expect(isPipelineRunList(VALID_PIPELINE_RUNS)).toBe(true);
  });

  it("accepts empty items array", () => {
    expect(isPipelineRunList({ items: [], limit: 20 })).toBe(true);
  });

  it("accepts running run that is stale", () => {
    const data: PipelineRunList = {
      items: [
        {
          id: "12345678-1234-5678-1234-567812345678",
          chain: "daily",
          trigger: "scheduled",
          status: "running",
          started_at: "2026-08-28T06:00:00Z",
          finished_at: null,
          window_start: null,
          window_end: null,
          stage_counts: {},
          backlog: {},
          failures: [],
          is_stale: true,
        },
      ],
      limit: 20,
    };
    expect(isPipelineRunList(data)).toBe(true);
  });

  it("rejects is_stale=true when status is not running", () => {
    const data = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data.items[0].status = "succeeded";
    data.items[0].is_stale = true;
    expect(isPipelineRunList(data)).toBe(false);
  });

  it("rejects negative counts in stage_counts or backlog", () => {
    const data1 = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data1.items[0].stage_counts.extract.extracted = -1;
    expect(isPipelineRunList(data1)).toBe(false);

    const data2 = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data2.items[0].backlog.extracted = -5;
    expect(isPipelineRunList(data2)).toBe(false);
  });

  it("rejects unknown stage name or status", () => {
    const data1 = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data1.items[0].status = "canceled";
    expect(isPipelineRunList(data1)).toBe(false);

    const data2 = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data2.items[0].failures[0].stage = "unknown_stage";
    expect(isPipelineRunList(data2)).toBe(false);
  });

  it("rejects extra unexpected fields in failure objects", () => {
    const data = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data.items[0].failures[0].message = "Secret error message!";
    expect(isPipelineRunList(data)).toBe(false);
  });

  it("rejects date-only and non-ISO timestamp formats", () => {
    const data1 = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data1.items[0].started_at = "2026-08-28";
    expect(isPipelineRunList(data1)).toBe(false);

    const data2 = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data2.items[0].finished_at = "Fri, 28 Aug 2026 10:08:30 GMT";
    expect(isPipelineRunList(data2)).toBe(false);
  });

  it("rejects invalid error type identifiers in failures", () => {
    const data1 = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data1.items[0].failures[0].error = "https://example.com/api/secret";
    expect(isPipelineRunList(data1)).toBe(false);

    const data2 = JSON.parse(JSON.stringify(VALID_PIPELINE_RUNS));
    data2.items[0].failures[0].error = "Failed to connect: secret_pw";
    expect(isPipelineRunList(data2)).toBe(false);
  });
});

describe("getPipelineRuns", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches and returns ready status on valid JSON response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => VALID_PIPELINE_RUNS,
    } as Response);

    const result = await getPipelineRuns(20);
    expect(result).toEqual({ status: "ready", data: VALID_PIPELINE_RUNS });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/admin/pipeline-runs?limit=20"),
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("returns unavailable when fetch fails or returns non-200", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 500,
    } as Response);

    const result = await getPipelineRuns();
    expect(result).toEqual({ status: "unavailable", data: null });
  });

  it("returns unavailable when network throws error", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("Network failure"));

    const result = await getPipelineRuns();
    expect(result).toEqual({ status: "unavailable", data: null });
  });

  it("returns unavailable when body fails schema validation", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ invalid: "payload" }),
    } as Response);

    const result = await getPipelineRuns();
    expect(result).toEqual({ status: "unavailable", data: null });
  });
});
