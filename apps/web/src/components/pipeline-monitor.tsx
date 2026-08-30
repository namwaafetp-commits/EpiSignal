import Link from "next/link";
import type { PipelineRun, PipelineRunState } from "../lib/api-pipeline";

export interface PipelineMonitorProps {
  pipelineState: PipelineRunState;
}

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value));
}

function formatStatus(run: PipelineRun) {
  if (run.status === "running") {
    if (run.is_stale) {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-300">
          Running — stale
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-blue-100 text-blue-900 border border-blue-300">
        Running
      </span>
    );
  }

  if (run.status === "succeeded") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-emerald-100 text-emerald-900 border border-emerald-300">
        Succeeded
      </span>
    );
  }

  // Failed
  const hasProgress = Object.values(run.stage_counts).some((counts) =>
    Object.values(counts).some((c) => c > 0),
  );

  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-rose-100 text-rose-900 border border-rose-300">
      {hasProgress ? "Failed after partial progress" : "Failed"}
    </span>
  );
}

function formatStageCounts(
  stageCounts: Record<string, Record<string, number>>,
) {
  const entries = Object.entries(stageCounts);
  if (entries.length === 0) return "—";
  return entries
    .map(([stage, counts]) => {
      const countsStr = Object.entries(counts)
        .map(([k, v]) => `${v} ${k}`)
        .join(", ");
      return `${stage}: ${countsStr}`;
    })
    .join(" | ");
}

export function PipelineMonitor({ pipelineState }: PipelineMonitorProps) {
  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <div className="mb-6">
        <Link
          href="/"
          className="text-sm font-medium text-teal-700 hover:text-teal-900 inline-flex items-center gap-1 mb-4"
        >
          ← Back to Signal Radar
        </Link>
        <h1 className="text-3xl font-bold text-slate-900">
          Pipeline Execution Monitor
        </h1>
        <p className="text-sm text-slate-600 mt-1">
          Read-only operational history of automated surveillance and extraction
          runs.
        </p>
      </div>

      {pipelineState.status === "loading" ? (
        <p className="empty-state">Loading pipeline execution history…</p>
      ) : pipelineState.status === "unavailable" ? (
        <p className="empty-state">
          Pipeline history unavailable. The API could not load execution
          records.
        </p>
      ) : pipelineState.data.items.length === 0 ? (
        <p className="empty-state">No pipeline runs recorded.</p>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg border border-slate-200 shadow-sm">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-slate-700">
              <tr>
                <th className="px-4 py-3 text-left font-semibold">
                  Started (UTC)
                </th>
                <th className="px-4 py-3 text-left font-semibold">Status</th>
                <th className="px-4 py-3 text-left font-semibold">
                  Chain / Trigger
                </th>
                <th className="px-4 py-3 text-left font-semibold">
                  Surveillance Window
                </th>
                <th className="px-4 py-3 text-left font-semibold">
                  Stage Progress
                </th>
                <th className="px-4 py-3 text-left font-semibold">Failures</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {pipelineState.data.items.map((run) => (
                <tr key={run.id} className="hover:bg-slate-50/50">
                  <td className="px-4 py-3 text-slate-900 whitespace-nowrap">
                    <div>{formatDate(run.started_at)}</div>
                    {run.finished_at && (
                      <div className="text-xs text-slate-500">
                        Finished: {formatDate(run.finished_at)}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {formatStatus(run)}
                  </td>
                  <td className="px-4 py-3 text-slate-700 whitespace-nowrap">
                    <span className="font-medium capitalize">{run.chain}</span>{" "}
                    · <span className="capitalize">{run.trigger}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">
                    {run.window_start ? (
                      <div>
                        {formatDate(run.window_start)} →{" "}
                        {formatDate(run.window_end)}
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-700 max-w-xs">
                    <div>{formatStageCounts(run.stage_counts)}</div>
                    {Object.keys(run.backlog).length > 0 && (
                      <div className="text-slate-500 mt-0.5">
                        Backlog:{" "}
                        {Object.entries(run.backlog)
                          .map(([k, v]) => `${v} ${k}`)
                          .join(", ")}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-rose-700 whitespace-nowrap">
                    {run.failures.length > 0 ? (
                      <ul className="space-y-0.5">
                        {run.failures.map((f, idx) => (
                          <li key={idx} className="font-mono">
                            {f.stage}: {f.error ?? "Unspecified error"}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
