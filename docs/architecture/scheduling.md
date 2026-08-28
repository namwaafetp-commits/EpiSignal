# Pipeline Scheduling

This document describes how the EpiSignal daily pipeline is scheduled, locked, recorded, and recovered after downtime.

## What `pnpm pipeline:run` does

`pnpm pipeline:run` executes the complete daily processing chain once and exits:

```text
ingest_who -> ingest_ecdc -> discover -> dedupe -> extract -> geocode -> match
```

1. **Official source ingestion (`ingest_who`, `ingest_ecdc`):** Ingests new official reports from WHO DON and ECDC Epidemiological Updates.
2. **GDELT discovery (`discover`):** Searches GDELT within a calculated publication window, fetches article bodies, and stores new signals. Retries pending article stubs first.
3. **Stage 0 deduplication (`dedupe`):** Filters exact and near-duplicate articles using MinHash / Jaccard similarity before AI processing.
4. **AI extraction (`extract`):** Classifies and extracts structured epidemiological entities via OpenRouter / LLM.
5. **Geocoding (`geocode`):** Resolves extracted place names to coordinates using the GeoNames gazetteer.
6. **Story clustering and event matching (`match`):** Clusters signals and matches or creates canonical outbreak events with dual scores.

### Mutual exclusion and locking

The pipeline acquires a PostgreSQL session-level advisory lock (`pg_try_advisory_lock(7284015531)`) before executing the first stage. If another run is already in progress, the command prints `A pipeline run is already in progress; nothing to do.` and immediately exits with return code `0`.

Because the lock is session-scoped, it automatically releases when the runner process terminates or if the connection closes.

## Windows Task Scheduler Setup

The pipeline is triggered once daily by Windows Task Scheduler invoking `scripts/run-pipeline.ps1`.

### Task Registration

1. Open **Task Scheduler** (`taskschd.msc`).
2. Select **Create Task...** (not Basic Task).
3. On the **General** tab:
   - Name: `EpiSignal Daily Pipeline`
   - Description: `Daily automated execution of the EpiSignal ingestion, discovery, and matching pipeline.`
   - Security options: Select **Run whether user is logged on or not** and **Run with highest privileges** if needed.
4. On the **Triggers** tab:
   - Click **New...**
   - Begin the task: **On a schedule**, Daily, set preferred time (e.g. `02:00:00`).
   - Recur every: `1` days.
   - Under Advanced settings, check **Stop task if it runs longer than**: `2 hours`.
   - Ensure **Enabled** is checked.
5. On the **Actions** tab:
   - Click **New...**
   - Action: **Start a program**
   - Program/script: `powershell.exe`
   - Add arguments: `-NoProfile -ExecutionPolicy Bypass -File "D:\Projects\Side Project\EpiSignal\scripts\run-pipeline.ps1"`
   - Start in: `D:\Projects\Side Project\EpiSignal`
6. On the **Settings** tab:
   - Check **Allow task to be run on demand**.
   - Check **Run task as soon as possible after a scheduled start is missed** (CRITICAL: enables catch-up when machine was asleep).
   - If the task fails, restart every: `15 minutes`, attempt to restart up to `3 times`.
   - If the running task does not end when requested, force it to stop: Checked.

## The Catch-Up Window

On a daily cadence, a sleeping or offline machine would miss news if discovery used a static window. The pipeline tracks previous runs to ensure no gap is missed:

- `window_start` is set to the `window_end` of the previous successful run of the chain.
- `window_end` is the current execution timestamp (`now`).
- If no previous run exists, it falls back to `EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES` (default 1500 minutes / 25 hours).
- If the machine was offline for an extended period, the catch-up span is clamped to `EPISIGNAL_PIPELINE_CATCH_UP_MAX_MINUTES` (default 10080 minutes / 7 days).

When clamping occurs, the run records the exact clamped `window_start` and `window_end` in `pipeline_runs`, making any unavoidable coverage truncation visible and queryable.

## Inspecting Pipeline Runs

Every run persists a record in the `pipeline_runs` table. To inspect recent runs:

```sql
SELECT started_at, finished_at, status, failed_stages, backlog
FROM pipeline_runs
ORDER BY started_at DESC
LIMIT 7;
```

### Run Statuses

- `succeeded`: All stages completed successfully.
- `failed`: One or more stages raised an exception. Later stages still executed, and the failed stage names are recorded in `failed_stages`.
- `running`: The run is in progress. A row that remains in `running` status with a `NULL` `finished_at` indicates a killed or abruptly terminated process. These rows are never cleaned up automatically to preserve operational history.

## Retrying a Single Stage

If an individual stage failed (e.g. temporary API outage during extraction) and needs to be re-run manually:

```powershell
corepack pnpm pipeline:run -- --only extract
```

This runs only the specified stage under the same advisory lock and records a new run row. Valid stage options are:
`ingest_who`, `ingest_ecdc`, `discover`, `dedupe`, `extract`, `geocode`, `match`.
