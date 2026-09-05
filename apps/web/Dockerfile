# syntax=docker/dockerfile:1

FROM node:22.19.0-bookworm-slim AS base

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

RUN corepack enable

WORKDIR /app

FROM base AS dependencies

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json

RUN pnpm install --frozen-lockfile

FROM dependencies AS builder

ARG NEXT_PUBLIC_EPISIGNAL_API_URL
ENV NEXT_PUBLIC_EPISIGNAL_API_URL=$NEXT_PUBLIC_EPISIGNAL_API_URL

COPY apps/web apps/web
COPY packages/contracts packages/contracts

RUN pnpm --filter @episignal/web build

FROM node:22.19.0-bookworm-slim AS runtime

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app

RUN groupadd --system --gid 10001 episignal \
    && useradd --system --uid 10001 --gid episignal --create-home episignal

COPY --from=builder --chown=episignal:episignal /app/apps/web/.next/standalone ./
COPY --from=builder --chown=episignal:episignal /app/apps/web/.next/static ./apps/web/.next/static

USER episignal

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(response => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "apps/web/server.js"]
