# syntax=docker/dockerfile:1.6
# Curated pnpm-workspace Next.js Dockerfile.
# Build context MUST be repo root (.) so pnpm-workspace.yaml is in scope.
# Sources (verbatim canonical patterns):
#   - https://github.com/vercel/next.js/blob/canary/docs/app/guides/self-hosting.mdx
#   - https://context7.com/pnpm/pnpm/llms.txt (workspace install + frozen-lockfile)
#   - https://github.com/docker/docs/blob/main/content/manuals/build/building/multi-stage.md

# ---- Stage 1: base — pnpm via corepack ----
FROM node:{{ NODE_VERSION }} AS base
RUN corepack enable && corepack prepare pnpm@10.17.1 --activate
WORKDIR /app

# ---- Stage 2: deps — install only, cacheable ----
FROM base AS deps
# Copy workspace manifest + lockfile + every workspace package.json BEFORE
# sources so the install layer is cached independently of app-code changes.
COPY .npmrc package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/{{ WEB_SERVICE_NAME }}/package.json apps/{{ WEB_SERVICE_NAME }}/
COPY packages/shared/package.json packages/shared/
RUN pnpm install --frozen-lockfile
RUN mkdir -p apps/{{ WEB_SERVICE_NAME }}/node_modules

# ---- Stage 3: build — next build ----
FROM base AS build
# Single-COPY pattern: /app/node_modules carries pnpm's hoisted store and
# any per-workspace symlinks. Per-path COPYs from deps would fail when
# a workspace has no local node_modules subtree (lean lockfile case).
COPY --from=deps /app ./
COPY . .
WORKDIR /app
# Discard TypeScript incremental caches copied from the host before building
# inside Docker; they are path- and output-state-sensitive.
RUN find apps packages -name '*.tsbuildinfo' -type f -delete
# Run the package's own build script rather than invoking `next` directly.
# The script is the app's contract — it may wrap `next build` with codegen,
# prebuild, or standalone output. Using the package script keeps the
# Dockerfile decoupled from app-level tooling choices.
RUN pnpm --filter {{ WEB_SERVICE_NAME }} build

# ---- Stage 4: runner — thin production image ----
FROM base AS runner
ENV NODE_ENV=production

# Non-root user for runtime (security hardening — audit fix vs. legacy
# scaffold template which ran as root).
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app/apps/{{ WEB_SERVICE_NAME }}
COPY --from=build /app/apps/{{ WEB_SERVICE_NAME }}/.next ./.next
COPY --from=build /app/apps/{{ WEB_SERVICE_NAME }}/public ./public
COPY --from=build /app/apps/{{ WEB_SERVICE_NAME }}/package.json ./package.json
# Hoisted store — pnpm symlinks resolve via /app/node_modules. Workspace
# symlinks (if any) live inside this tree, so a single COPY carries both.
# This replaces the per-workspace node_modules COPY that the pre-smoke
# draft attempted (that COPY would fail when the workspace had no local
# node_modules subtree).
COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/apps/{{ WEB_SERVICE_NAME }}/node_modules ./node_modules

RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE {{ WEB_PORT }}
CMD ["pnpm", "next", "start", "-p", "{{ WEB_PORT }}"]
