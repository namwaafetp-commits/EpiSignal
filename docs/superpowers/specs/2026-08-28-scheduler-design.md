# Scheduler — Design

**Date:** 2026-08-28
**Status:** Approved
**Item:** `L`
**Depends on:** `D2a` story clustering (`docs/superpowers/specs/2026-08-28-story-clustering-design.md`)
**Phase 1 spec:** §42 Scheduler, §16 Ingestion pipeline

## Goal

Run the whole pipeline — ingestion, discovery, dedupe, extraction, geocoding,
and matching — once a day without a human typing seven commands in order, and
leave a durable record of what each run did.

Until this item exists, every runner is invoked by hand. That is why the live
database holds two geocoded signals and zero events: the pipeline works, and
nobody has been running it.

## Position

`L` writes no signal, no event, and no observation of its own. It is an
orchestrator: every stage it calls is an existing, already-verified runner path,
and each of those paths is idempotent by `processing_status`. `L` adds exactly
three things those runners do not have — an order, a record, and a lock.

It unblocks nothing structurally. It is scheduled ahead of `D2b` and `E` because
both of those need a corpus of real events to be tuned or judged against, and a
corpus is what running daily produces.

## Vocabulary

`CONTEXT.md` is the naming authority. Two clarifications, because this item sits
near words it already governs:

**Stage**: one step of the pipeline — `discover`, `extract`, `geocode`. This
does not contradict `CONTEXT.md`'s `_Avoid_: level, stage` under **Tier**. That
avoidance is scoped to the model ladder: a rung of the ladder is a *tier*, never
a stage. A step of the pipeline has been a *stage* since `B` shipped as "Stage
0", and the runners already print "what stage failed". Keep both meanings, and
never use *stage* for a ladder rung.

**Chain**: an ordered sequence of stages run under one lock and recorded as one
row. There is one chain, `daily`. *Chain* is a new word; it is deliberately not
*pipeline*, which names the whole system, or *pass*, which `D2a` uses for one
sweep of one stage.

**Run**: one execution of one chain. Persisted as one `pipeline_runs` row.

## Decisions

### The OS drives the cadence, not a Python process

`pnpm pipeline:run` runs the `daily` chain once and exits. Windows Task
Scheduler invokes it. No daemon, no in-process scheduler, no queue.

This is the shape every runner already has, and the shape the discovery design
predicted: "A CLI command an external scheduler calls. An in-process daemon is
deployment infrastructure that does not exist yet"
(`2026-08-27-gdelt-discovery-design.md`, the trigger row of its decision table).
A one-shot process cannot leak, cannot wedge, and cannot lose future ticks when
one tick dies. Phase 1 §42's "avoid complex distributed queues initially" points
the same way.

The cost is that cadence lives outside the repository, in a Task Scheduler
entry. That is accepted: the trigger is deployment, and deployment for the MVP
is one laptop.

### A missed day is repaired, not lost

Discovery's window is anchored to the moment of the run, and nothing records how
far back it has already looked:

```python
window = TimeWindow(start=moment - timedelta(minutes=window_minutes), end=moment)
```

On a 15-minute cadence that is fine. On a daily cadence run from a laptop that
sleeps, every hour the machine is off is an hour of news no run ever asks for
again — there is no watermark and no retry that repairs it.

So the `daily` chain computes discovery's window from the last run that
discovered successfully, not from a constant. `window_start` is the previous
run's `window_end`; `window_end` is now. With no previous run it falls back to
`EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES`. The span is clamped to
`EPISIGNAL_PIPELINE_CATCH_UP_MAX_MINUTES`, so a laptop closed for a month asks
for the last seven days rather than issuing an unbounded query GDELT would
refuse.

Clamping loses data. It loses it loudly: the run records the window it actually
asked for, so a truncated catch-up is visible in `pipeline_runs` rather than
inferred from a hole in the signals.

### A failing stage does not stop the chain

Every stage selects its own backlog by `processing_status`. A failed extraction
does not invalidate the signals that were extracted yesterday and are waiting to
be geocoded. So the chain runs every stage, records which ones failed, and exits
non-zero if any did.

The alternative — abort on first failure — would let one OpenRouter outage block
geocoding and matching of work that was already ready, and grow the backlog
silently until the next day.

### One run at a time, enforced by the database

A manual `pnpm pipeline:run` while the scheduled task is mid-run would have two
processes calling the same non-transactional stages against the same rows. The
chain takes a PostgreSQL session-level advisory lock before the first stage and
holds it until the last. A second invocation that cannot take the lock prints
that a run is already in progress and exits `0` — a skipped overlap is the
correct outcome, not a failure.

The lock is advisory and session-scoped, so it dies with the process. A killed
run cannot leave the pipeline permanently locked.

### The run is recorded in the database

`pipeline_runs` answers three questions that stdout cannot: did it run last
night, what did each stage do, and how far back did discovery actually look.
Journald does not exist on Windows, terminal scrollback is not queryable, and
item `E`'s admin monitoring needs a table to render — if this item does not
create one, `E` will.

### Backlog depth is recorded, because the budgets do not compose

Discovery stores up to `EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN` articles (default
`200`) per run. Extraction handles up to `EPISIGNAL_AI_SIGNAL_BATCH_LIMIT`
signals (default `100`). Run daily at those defaults and the un-extracted
backlog grows by one hundred signals a day, for ever, and nothing in the current
output says so.

Rather than pick numbers for a traffic pattern nobody has measured yet, every
run records the count of signals at each `processing_status`. A backlog that
grows every day is then a fact in a table instead of a surprise in three weeks.

For the MVP the `.env` recommends `EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN=100`, so
intake matches what extraction can drain in the same run. That is a
recommendation in configuration, not a constraint in code: the numbers to tune
are exactly the numbers that must stay tunable.

## Architecture

`episignal_backend/schedule/`, with the same seam `events/` has: pure modules
that know nothing about storage, one adapter that opens sessions, one module
that imports SQLAlchemy.

| File | Responsibility | Imports SQLAlchemy |
| --- | --- | --- |
| `schedule/documents.py` | `StageName`, `StageOutcome`, `ChainOutcome`, `DiscoveryWindow` | no |
| `schedule/chains.py` | `DAILY_CHAIN`, the ordered stage names | no |
| `schedule/window.py` | `catch_up_window` — pure arithmetic over two instants | no |
| `schedule/protocol.py` | `PipelineRunRepository`, the storage boundary | no |
| `schedule/run.py` | `run_chain` — order, failure policy, outcome assembly | no |
| `schedule/stages.py` | Maps a stage name to the existing runner path | no (imports `db.session`) |
| `schedule/repository.py` | `SqlAlchemyPipelineRunRepository`, the advisory lock | yes |
| `pipeline_runner.py` | `pnpm pipeline:run` — argv, printing, exit code | no |
| `models/pipeline.py` | The `PipelineRun` model | yes |

`run_chain` takes a mapping of stage name to a zero-argument callable returning
counts. That is what makes the failure policy, the ordering, and the outcome
assembly testable without a database, a socket, or a model call.

## The daily chain

```text
ingest_who -> ingest_ecdc -> discover -> dedupe -> extract -> geocode -> match
```

Ingestion of the two official sources runs first: an official WHO or ECDC
document that corroborates a story should be in the database before that story's
media coverage is matched to an event, not a day behind it.

`--only <stage>` runs one stage under the same lock and the same recording, for
the case where one stage failed and is being retried by hand.

## Migration `20260828_0008_pipeline_runs`

```text
pipeline_runs
  id             uuid        pk, gen_random_uuid()
  chain          vocabulary(PipelineChain)      not null
  trigger        vocabulary(PipelineTrigger)    not null
  status         vocabulary(PipelineRunStatus)  not null
  started_at     timestamptz not null
  finished_at    timestamptz null
  window_start   timestamptz null
  window_end     timestamptz null
  stage_counts   jsonb       not null, default '{}'
  backlog        jsonb       not null, default '{}'
  failed_stages  jsonb       not null, default '[]'
  created_at     timestamptz not null
  updated_at     timestamptz not null
```

`status` is `running`, `succeeded`, or `failed`. A row is inserted as `running`
before the first stage, so a run killed mid-flight leaves a `running` row with a
null `finished_at` — which is the evidence that it was killed, and is not
cleaned up automatically.

`window_start` and `window_end` are the window discovery actually asked GDELT
for, which is what the next run reads to compute its own.

An index on `(chain, started_at DESC)` serves the only query the code makes: the
most recent run of a chain.

## Settings

| Setting | Default | Why |
| --- | --- | --- |
| `EPISIGNAL_PIPELINE_CATCH_UP_MAX_MINUTES` | `10080` | Seven days. Bounds the catch-up query after a long gap. |
| `EPISIGNAL_PIPELINE_CHAIN` | `daily` | The chain `pnpm pipeline:run` runs with no argument. |

For the MVP the `.env` also sets, with no code change required:

```dotenv
EPISIGNAL_GDELT_POLL_INTERVAL_MINUTES=1440
EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES=1500
EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN=100
```

`1500` over `1440` is the sixty-minute overlap the discovery design already asks
for, so scheduler jitter cannot open a gap. The existing
`window_covers_the_interval` validator enforces the relationship; no new
validator is needed.

## Trigger

`scripts/run-pipeline.ps1` wraps `corepack pnpm pipeline:run`, matching
`scripts/match-events.ps1`. A Windows Task Scheduler entry runs it daily.
Registration is documented in `docs/architecture/scheduling.md`, including "run
whether or not the user is logged on" and "start when available" so a run missed
while the laptop was asleep fires on wake — which is the case the catch-up
window was built for.

The task is documented, not created by code. Creating scheduled tasks on a
developer's machine from a test suite is not something this project should do.

## Failure and secrecy posture

`pipeline_runner.py` prints counts and stage names only, never a connection
string, an article body, or an API key — the posture `geocode_runner.py` and
`event_runner.py` already state in their docstrings. A stage failure is recorded
as the exception's type name, never its payload, for the same reason: an
exception raised near the session can carry the connection string.

## Acceptance

1. `pnpm pipeline:run` runs seven stages in order and prints one line per stage
   plus a final backlog line.
2. A stage raising does not prevent later stages from running; the run exits `1`
   and names the failed stage.
3. A second `pnpm pipeline:run` started while one is running prints that a run
   is in progress and exits `0`.
4. With no prior run, discovery's window is `EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES`
   wide. With a prior run, it starts at that run's `window_end`. After a gap
   longer than the clamp, it is exactly `EPISIGNAL_PIPELINE_CATCH_UP_MAX_MINUTES`
   wide.
5. Every run leaves exactly one `pipeline_runs` row, and a killed run leaves a
   `running` row with a null `finished_at`.
6. `corepack pnpm verify` passes.

## Out of scope, deliberately

- Any in-process scheduler, daemon, queue, or worker pool. Phase 1 §42.
- Creating, deleting, or inspecting Windows scheduled tasks from Python.
- Retrying a failed stage inside the same run. The next day's run picks the
  backlog up, and `--only` retries by hand.
- Alerting when a run fails or is missed. That is item `E`'s admin monitoring,
  and it reads the table this item creates.
- Backfilling the news that was never discovered before this item existed. The
  catch-up window looks back at most seven days, and only from the first run.
