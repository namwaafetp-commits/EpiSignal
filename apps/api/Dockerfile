# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.12.5-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY pyproject.toml uv.lock pnpm-workspace.yaml ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY packages/backend/pyproject.toml packages/backend/pyproject.toml
COPY apps/api apps/api
COPY packages/backend packages/backend
COPY database database

RUN uv sync --frozen --package episignal-api --no-dev

FROM ghcr.io/astral-sh/uv:0.12.5-python3.12-bookworm-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

RUN groupadd --system --gid 10001 episignal \
    && useradd --system --uid 10001 --gid episignal --create-home episignal

COPY --from=builder --chown=episignal:episignal /app /app

USER episignal

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"

CMD ["uv", "run", "--frozen", "--no-sync", "--package", "episignal-api", "python", "-m", "episignal_api.run"]
