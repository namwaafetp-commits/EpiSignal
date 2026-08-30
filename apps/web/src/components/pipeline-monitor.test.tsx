import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PipelineRunState } from "../lib/api-pipeline";
import { PipelineMonitor } from "./pipeline-monitor";

const SAMPLE_RUNS_STATE: PipelineRunState = {
  status: "ready",
  data: {
    items: [
      {
        id: "11111111-1111-1111-1111-111111111111",
        chain: "daily",
        trigger: "scheduled",
        status: "succeeded",
        started_at: "2026-08-28T10:00:00Z",
        finished_at: "2026-08-28T10:15:00Z",
        window_start: "2026-08-27T10:00:00Z",
        window_end: "2026-08-28T10:00:00Z",
        stage_counts: {
          extract: { extracted: 10, review: 2 },
        },
        backlog: { unextracted: 0 },
        failures: [],
        is_stale: false,
      },
      {
        id: "22222222-2222-2222-2222-222222222222",
        chain: "daily",
        trigger: "manual",
        status: "failed",
        started_at: "2026-08-28T09:00:00Z",
        finished_at: "2026-08-28T09:05:00Z",
        window_start: "2026-08-27T09:00:00Z",
        window_end: "2026-08-28T09:00:00Z",
        stage_counts: {
          extract: { extracted: 4, review: 1 },
        },
        backlog: { unextracted: 5 },
        failures: [{ stage: "extract", error: "TimeoutError" }],
        is_stale: false,
      },
      {
        id: "33333333-3333-3333-3333-333333333333",
        chain: "daily",
        trigger: "scheduled",
        status: "running",
        started_at: "2026-08-28T08:00:00Z",
        finished_at: null,
        window_start: null,
        window_end: null,
        stage_counts: {},
        backlog: {},
        failures: [],
        is_stale: true,
      },
      {
        id: "44444444-4444-4444-4444-444444444444",
        chain: "daily",
        trigger: "scheduled",
        status: "running",
        started_at: "2026-08-28T11:00:00Z",
        finished_at: null,
        window_start: null,
        window_end: null,
        stage_counts: {},
        backlog: {},
        failures: [],
        is_stale: false,
      },
    ],
    limit: 20,
  },
};

describe("PipelineMonitor", () => {
  it("renders loading state", () => {
    render(
      <PipelineMonitor pipelineState={{ status: "loading", data: null }} />,
    );
    expect(
      screen.getByText(/loading pipeline execution history/i),
    ).toBeInTheDocument();
  });

  it("renders unavailable state", () => {
    render(
      <PipelineMonitor pipelineState={{ status: "unavailable", data: null }} />,
    );
    expect(
      screen.getByText(/pipeline history unavailable/i),
    ).toBeInTheDocument();
  });

  it("renders empty state", () => {
    render(
      <PipelineMonitor
        pipelineState={{ status: "ready", data: { items: [], limit: 20 } }}
      />,
    );
    expect(screen.getByText(/no pipeline runs recorded/i)).toBeInTheDocument();
  });

  it("renders succeeded, failed, running, and stale-running runs with counts and failure stages", () => {
    render(<PipelineMonitor pipelineState={SAMPLE_RUNS_STATE} />);

    // Check statuses
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(
      screen.getByText(/failed after partial progress/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Running — stale")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();

    // Check failure details
    expect(screen.getByText(/extract: TimeoutError/i)).toBeInTheDocument();

    // Check counts
    expect(
      screen.getByText(/extract: 10 extracted, 2 review/i),
    ).toBeInTheDocument();

    // Check back to radar link
    const link = screen.getByRole("link", { name: /back to signal radar/i });
    expect(link).toHaveAttribute("href", "/");
  });

  it("guarantees read-only nature with no buttons or forms", () => {
    render(<PipelineMonitor pipelineState={SAMPLE_RUNS_STATE} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });
});
