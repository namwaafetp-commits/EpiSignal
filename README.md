# EpiSignal

Open global outbreak intelligence. EpiSignal turns public health reporting into
traceable events: every claim keeps the source that made it, the time it was
made, and the observation history that followed.

**Product principle:** never show a number without the evidence behind it.

## Current scope

This repository currently contains the **foundation only**:

- a responsive public shell that renders honestly while empty;
- a FastAPI service with liveness, readiness, and version routes;
- a versioned PostgreSQL/PostGIS schema for sources, signals, events,
  event–signal relationships, observations, and locations;
- reviewed canonical disease and source identities;
- generated OpenAPI and TypeScript contracts.

There is **no live ingestion and no fabricated outbreak data**. No connector runs
yet, the seeded sources are deliberately inactive, and the interface shows no
case counts, no severity colours, and no sample outbreak cards. Event records
appear only after source ingestion is connected in a later slice.

## Prerequisites

- Node.js 22 with pnpm 11 (`corepack enable`)
- Python 3.12 with [uv](https://docs.astral.sh/uv/)
- A Supabase project with PostGIS enabled
- PowerShell for the verification scripts (Windows PowerShell 5.1 or `pwsh` 7)

## Workspace map

```text
apps/web/             Next.js App Router application and UI tests
apps/api/             FastAPI composition, routes, middleware, tests
packages/backend/     Domain models, database configuration, seeds, health
packages/contracts/   OpenAPI JSON and generated TypeScript declarations
database/migrations/  Alembic environment and immutable revisions
database/seeds/       Reviewed JSON seed datasets
docs/architecture/    Setup and architectural notes
scripts/              PowerShell verification and live database smoke scripts
```

## Quick start (Windows)

```powershell
corepack enable
pnpm install
uv sync
Copy-Item apps/api/.env.example apps/api/.env
Copy-Item apps/web/.env.local.example apps/web/.env.local
pnpm dev
```

Fill in `apps/api/.env` before starting the API: importing the production entry
point fails immediately when configuration is missing or invalid.

## Environment

| Variable                        | Where           | Purpose                                        |
| ------------------------------- | --------------- | ---------------------------------------------- |
| `EPISIGNAL_DATABASE_URL`        | `apps/api/.env` | Private PostgreSQL URL. Server side only.       |
| `EPISIGNAL_API_HOST` / `_PORT`  | `apps/api/.env` | Local bind address for the development server.  |
| `EPISIGNAL_CORS_ORIGINS`        | `apps/api/.env` | Comma-separated HTTP(S) origins.                |
| `NEXT_PUBLIC_EPISIGNAL_API_URL` | `apps/web/.env.local` | Public base URL the shell reads readiness from. |

See [docs/architecture/supabase-setup.md](docs/architecture/supabase-setup.md)
for connection modes, password encoding, and PostGIS.

## Local URLs

- Web shell: <http://localhost:3000>
- API liveness: <http://127.0.0.1:8000/health/live>
- API readiness: <http://127.0.0.1:8000/health/ready>
- API metadata: <http://127.0.0.1:8000/api/v1>
- API docs: <http://127.0.0.1:8000/docs>

## Quality commands

```powershell
pnpm verify            # format, lint, type-check, test, contract drift, build
pnpm test              # web and Python tests
pnpm typecheck         # tsc and mypy
pnpm contracts:check   # regenerate contracts and fail on drift
pnpm db:check          # readiness probe against the configured database
pnpm db:seed           # seed canonical diseases, sources, GDELT query rules, and Stage 0 filter rules
pnpm discover:gdelt    # discover local media signals through GDELT DOC 2.0
pnpm dedupe:signals    # resolve syndicated copies to one primary signal
pnpm ingest:who        # ingest WHO Disease Outbreak News
pnpm ingest:ecdc       # ingest ECDC Epidemiological Updates

```

`pnpm verify` needs no credentials.

## Live database safety

`pnpm db:migrate`, `pnpm db:seed`, and `scripts/verify-live-database.ps1` act on
the **real** database named by `apps/api/.env`. They migrate and seed; they never
create, reset, delete, or drop a Supabase project. Seeding is idempotent, so a
repeated run keeps the same identities. `apps/api/.env` is ignored by Git and
must never be pasted into an issue, a log, or a browser setting.

## Source provenance

Provenance is structural, not cosmetic:

- a **source** is a publisher with a credibility tier and an official flag;
- a **signal** is one retrieved document from a source, keyed by its original
  URL, with the retrieval time and processing status;
- an **event** aggregates signals through `event_signals`, which records how each
  signal relates to the event and whether it is the primary report;
- an **observation** records reported figures at a point in time and always keeps
  both the event and the signal it came from, so a number can be traced back to
  the document that stated it;
- a **location** records where an event happened and how the coordinates were
  geocoded.

Nothing is overwritten in place: new reporting arrives as new observations.

## Design

- Foundation design: [docs/superpowers/specs/2026-08-26-foundation-design.md](docs/superpowers/specs/2026-08-26-foundation-design.md)
- GDELT discovery design: [docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md](docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md)
- GDELT layer architecture: [docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md](docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md)

## Attribution

Place names are resolved against a GeoNames extract. See
`database/seeds/gazetteer/ATTRIBUTION.md` for the CC BY 4.0 attribution.

