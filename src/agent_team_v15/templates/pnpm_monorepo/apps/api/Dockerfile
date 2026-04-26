# syntax=docker/dockerfile:1.6
# Curated pnpm-workspace NestJS + Prisma Dockerfile.
# Build context MUST be repo root (.) so pnpm-workspace.yaml is in scope.
# Sources (verbatim canonical patterns):
#   - https://github.com/docker/docs/blob/main/content/manuals/build/building/multi-stage.md
#   - https://context7.com/pnpm/pnpm/llms.txt (workspace install + frozen-lockfile)
#   - https://github.com/nestjs/docs.nestjs.com/blob/master/content/recipes/prisma.md
#   - https://github.com/prisma/docs/blob/main/content/200-orm/200-prisma-client/500-deployment/101-deploy-prisma.mdx

# ---- Stage 1: deps — install only, cacheable across source changes ----
FROM node:{{ NODE_VERSION }} AS deps
RUN corepack enable && corepack prepare pnpm@10.17.1 --activate
WORKDIR /app

# Copy workspace manifest + lockfile + every package.json BEFORE sources
# so the install layer is cached independently of app code changes (DOCK-003).
COPY .npmrc pnpm-workspace.yaml pnpm-lock.yaml package.json ./
COPY apps/{{ API_SERVICE_NAME }}/package.json apps/{{ API_SERVICE_NAME }}/
COPY apps/{{ WEB_SERVICE_NAME }}/package.json apps/{{ WEB_SERVICE_NAME }}/
COPY packages/shared/package.json packages/shared/
RUN pnpm install --frozen-lockfile
RUN mkdir -p apps/{{ API_SERVICE_NAME }}/node_modules

# ---- Stage 2: build — compile TS + generate Prisma client ----
FROM node:{{ NODE_VERSION }} AS build
RUN corepack enable && corepack prepare pnpm@10.17.1 --activate
WORKDIR /app

# Copy only the hoisted store from deps — pnpm puts its virtual store
# and workspace symlinks under /app/node_modules. Per-workspace
# node_modules subdirs (apps/*/node_modules, packages/*/node_modules)
# are NOT guaranteed to exist when a workspace has no local deps of its
# own, so attempting a separate COPY for each would fail with
# "failed to compute cache key: not found" against a lean lockfile.
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/{{ API_SERVICE_NAME }}/node_modules ./apps/{{ API_SERVICE_NAME }}/node_modules

# Full repo context is required here — NestJS build reads tsconfig.base.json
# from the repo root and @taskflow/shared from packages/shared/.
COPY . .

# TypeScript incremental caches from a host or previous smoke run can make a
# clean container build skip JS emits while still leaving stale declarations.
RUN find apps packages -name '*.tsbuildinfo' -type f -delete

# Generate Prisma client if schema is present. Runs before build so the
# client's types are available to tsc. Using `pnpm --filter` keeps the
# command idempotent when no prisma schema exists (the script is a no-op).
RUN pnpm --filter {{ API_SERVICE_NAME }} exec sh -c '[ -f prisma/schema.prisma ] && pnpm exec prisma generate || true'
RUN pnpm --filter {{ API_SERVICE_NAME }} build

# ---- Stage 3: runtime — thin image, node_modules from build (has Prisma client) ----
FROM node:{{ NODE_VERSION }} AS runtime
ENV NODE_ENV=production
WORKDIR /app

# Non-root user for runtime (security hardening).
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy node_modules from BUILD stage (not deps) — Prisma client generation
# writes into node_modules/@prisma/client during the build stage; the deps
# stage's node_modules does not include it. Single-COPY keeps the build
# robust when a workspace has no local node_modules subtree (see deps
# stage comment above).
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/apps/{{ API_SERVICE_NAME }}/node_modules ./apps/{{ API_SERVICE_NAME }}/node_modules
COPY --from=build /app/apps/{{ API_SERVICE_NAME }}/dist ./apps/{{ API_SERVICE_NAME }}/dist
COPY --from=build /app/apps/{{ API_SERVICE_NAME }}/package.json ./apps/{{ API_SERVICE_NAME }}/package.json
COPY --from=build /app/apps/{{ API_SERVICE_NAME }}/prisma ./apps/{{ API_SERVICE_NAME }}/prisma

RUN chown -R appuser:appgroup /app
USER appuser

WORKDIR /app/apps/{{ API_SERVICE_NAME }}
EXPOSE {{ API_PORT }}

# Production entrypoint — migrate then seed then run. `migrate deploy` is the
# production-safe variant (never drops data); `migrate dev` is forbidden.
CMD ["sh", "-c", "npx prisma migrate deploy && npx prisma db seed && node dist/main.js"]
