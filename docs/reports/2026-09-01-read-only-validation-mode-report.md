# Read-Only Metadata Repair Validation Mode

Date: 2026-09-01

## 1. Files changed

- `packages/backend/src/episignal_backend/db/session.py`
- `packages/backend/src/episignal_backend/metadata_repair_ai_runner.py`
- `packages/backend/tests/test_metadata_repair_ai_runner.py`
- `packages/backend/tests/test_read_only_transaction.py`

## 2. Read-only enforcement mechanism

`metadata:repair-ai --dry-run --enforce-read-only` now executes, immediately
after opening its session and before repository/model queries:

```sql
SET TRANSACTION READ ONLY;
SHOW transaction_read_only;
```

The run continues only when PostgreSQL reports `on`. The mode remains dry-run;
AI calls are allowed, while database writes are prohibited by PostgreSQL.

## 3. Fail-closed behavior

The transaction guard raises when `SHOW transaction_read_only` returns anything
other than `on`, including `off`. The exception rolls back through
`session_scope` and prevents event inspection from starting.

## 4. PostgreSQL write-rejection test

`packages/backend/tests/test_read_only_transaction.py` uses only
`EPISIGNAL_TEST_DATABASE_URL`, rejects a URL equal to
`EPISIGNAL_DATABASE_URL`, sets transaction read-only, and attempts an
`UPDATE ... WHERE false`. PostgreSQL must reject the statement, followed by a
rollback.

Local result: skipped because `EPISIGNAL_TEST_DATABASE_URL` was not configured.
It was not pointed at production.

## 5. `--apply` incompatibility

`--apply --enforce-read-only` is rejected by argument parsing before a database
session opens. Focused test passed.

## 6. Verification

Focused command:

```text
uv run pytest packages/backend/tests/test_metadata_repair_ai_runner.py packages/backend/tests/test_read_only_transaction.py -q -rA
7 passed, 1 skipped
```

The skipped test is the PostgreSQL integration test described above.

Full command:

```text
corepack pnpm verify
```

Result: PASS — 107 web tests passed; 1,286 backend tests passed; 1 skipped;
formatting, lint, mypy (134 source files), TypeScript, contracts, and Next
production build passed. Two pre-existing Starlette deprecation warnings were
reported.

## 7. Commit

Implementation commit: `f0cdd331460b71c91d7d7bb0e1cf379965d76df4`

Production validation was not run. No `--apply`, deployment, merge,
migration, production write, or scheduler change was performed.
