# syntax=docker/dockerfile:1.6
# Curated pnpm-workspace Next.js Dockerfile.
# Build context MUST be repo root (.) so pnpm-workspace.yaml is in scope.
# Sources (verbatim canonical patterns):
#   - https://github.com/vercel/next.js/blob/canary/docs/app/guides/self-hosting.mdx
#   - https://context7.com/pnpm/pnpm/llms.txt (workspace install + frozen-lockfile)
#   - https://github.com/docker/docs/blob/main/content/manuals/build/building/multi-stage.md

# ---- Stage 1: base — pnpm via corepack ----
FROM node:{{ NODE_VERSION }} AS base
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /app

# ---- Stage 2: deps — install only, cacheable ----
FROM base AS deps
# Copy workspace manifest + lockfile + every workspace package.json BEFORE
# sources so the install layer is cached independently of app-code changes.
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
COPY apps/{{ WEB_SERVICE_NAME }}/package.json apps/{{ WEB_SERVICE_NAME }}/
COPY packages/shared/package.json packages/shared/
RUN pnpm install --frozen-lockfile

# ---- Stage 3: build — next build ----
FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/{{ WEB_SERVICE_NAME }}/node_modules ./apps/{{ WEB_SERVICE_NAME }}/node_modules
COPY . .
WORKDIR /app/apps/{{ WEB_SERVICE_NAME }}
RUN pnpm next build

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
# Hoisted store — pnpm symlinks resolve via /app/node_modules.
COPY --from=build /app/node_modules /app/node_modules
# Workspace-local node_modules — required for `next start` to resolve
# workspace-scoped symlinks (audit fix vs. legacy scaffold template, which
# omitted this copy and could fail module resolution at runtime).
COPY --from=build /app/apps/{{ WEB_SERVICE_NAME }}/node_modules ./node_modules

RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE {{ WEB_PORT }}
CMD ["pnpm", "next", "start"]
