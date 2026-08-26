# Supabase setup

EpiSignal keeps every private connection string on the server side. Only the
FastAPI service and the Alembic environment read `EPISIGNAL_DATABASE_URL`; the
browser never receives it.

## Choose a connection mode

Supabase exposes three ways to reach the same PostgreSQL database. They are not
interchangeable for this project.

| Mode                          | Port | Use it for                                                            |
| ----------------------------- | ---- | --------------------------------------------------------------------- |
| Direct connection             | 5432 | Preferred for migrations when your network has IPv6.                   |
| Shared pooler, session mode   | 5432 | The persistent API fallback on IPv4-only networks.                     |
| Shared pooler, transaction mode | 6543 | Not the default here. It is for short-lived serverless invocations.  |

The API and the Alembic runner hold a long-lived SQLAlchemy pool, so transaction
mode on port 6543 is the wrong default: prepared statements and session state do
not survive it. Use the direct connection when IPv6 works, otherwise the session
-mode pooler on port 5432.

## URL-encode the password

The database URL is a single string, so any character that is reserved in a URL
must be percent-encoded in the password. `@` becomes `%40`, `#` becomes `%23`,
`/` becomes `%2F`, and `:` becomes `%3A`. A raw `@` splits the URL in the wrong
place and produces a confusing "malformed URL" error rather than an auth error.

## Enable PostGIS before migrating

Enable the `postgis` extension in the Supabase dashboard (Database → Extensions)
before running the first migration. The initial revision issues
`CREATE EXTENSION IF NOT EXISTS postgis`, but a project that has never enabled it
may lack permission to create it from a migration. Downgrading never drops
PostGIS, because a hosted project can share the extension with other schemas.

## Keep the environment file private

`apps/api/.env` is ignored by Git and must never be pasted into an issue, a chat
message, a log, a screenshot, or a browser setting. `apps/api/.env.example` is
the only version-controlled copy and contains placeholders only. If a real
connection string is ever exposed, rotate the database password in the Supabase
dashboard immediately.

## Commands

```powershell
Copy-Item apps/api/.env.example apps/api/.env
Copy-Item apps/web/.env.local.example apps/web/.env.local
pnpm db:check
pnpm db:migrate
pnpm db:seed
powershell -File scripts/verify-live-database.ps1   # or: pwsh -File ...
```

`pnpm db:check` reports whether the failure is configuration, connection, or
PostGIS. `pnpm db:seed` is idempotent: it matches diseases on `slug` and sources
on `name`, so repeated runs never duplicate a canonical identity.
