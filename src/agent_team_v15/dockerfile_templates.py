"""Battle-tested Dockerfile templates for v16 pipeline (Phase 1.8).

Merges standalone builder's security patterns (multi-stage, non-root user,
selective COPY, .dockerignore) with super-team's operational reliability
(90s start-period, 127.0.0.1, stdlib healthcheck, dynamic dist detection).

These templates are injected into milestone execution prompts when the
milestone involves Docker/infrastructure setup.

Evidence from production builds:
- 40s start-period caused false-negative health failures (SupplyForge Run 2)
- curl-based healthcheck adds 15MB attack surface (GlobalBooks standalone)
- Hardcoded Angular dist path breaks on project name changes (GlobalBooks)
- Missing frontend HEALTHCHECK breaks docker-compose depends_on (LedgerPro)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Python / FastAPI
# ---------------------------------------------------------------------------

PYTHON_DOCKERFILE = """\
# ---- Builder Stage ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
EXPOSE {port}
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \\
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "{port}"]
"""


# ---------------------------------------------------------------------------
# TypeScript / NestJS
# ---------------------------------------------------------------------------

TYPESCRIPT_DOCKERFILE = """\
# ---- Builder Stage ----
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- Runtime Stage ----
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/package*.json ./
RUN npm ci --omit=dev
COPY --from=builder /app/dist ./dist
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
EXPOSE {port}
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \\
  CMD wget -qO- http://127.0.0.1:{port}/health || exit 1
CMD ["node", "dist/main"]
"""


# ---------------------------------------------------------------------------
# Frontend / Angular / React / Vue (nginx)
# ---------------------------------------------------------------------------

FRONTEND_DOCKERFILE = """\
# ---- Build Stage ----
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- Serve Stage ----
FROM nginx:stable-alpine
# Auto-detect framework build output (Angular 17+, React, Vue/Vite)
COPY --from=builder /app/dist/ /tmp/dist/
COPY --from=builder /app/build/ /tmp/build/ 2>/dev/null || true
RUN if ls /tmp/dist/*/browser/ >/dev/null 2>&1; then \\
      cp -r /tmp/dist/*/browser/* /usr/share/nginx/html/; \\
    elif [ -d /tmp/build ] && [ "$(ls -A /tmp/build)" ]; then \\
      cp -r /tmp/build/* /usr/share/nginx/html/; \\
    elif [ -d /tmp/dist ] && [ "$(ls -A /tmp/dist)" ]; then \\
      cp -r /tmp/dist/* /usr/share/nginx/html/; \\
    fi && rm -rf /tmp/dist /tmp/build
# SPA routing — all paths fall back to index.html
RUN printf 'server {\\n  listen 80;\\n  root /usr/share/nginx/html;\\n  location / {\\n    try_files $uri $uri/ /index.html;\\n  }\\n}\\n' \\
      > /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\
  CMD wget -qO- http://127.0.0.1:80/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
"""


# ---------------------------------------------------------------------------
# .NET / ASP.NET Core
# ---------------------------------------------------------------------------

DOTNET_DOCKERFILE = """\
# ---- Build Stage ----
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY *.sln ./
COPY */*.csproj ./
RUN for f in *.csproj; do mkdir -p "$(basename "$f" .csproj)" && mv "$f" "$(basename "$f" .csproj)/"; done 2>/dev/null; dotnet restore
COPY . .
RUN dotnet publish -c Release -o /app/publish --no-restore

# ---- Runtime Stage ----
FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app/publish .
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser
ENV ASPNETCORE_URLS=http://+:{port}
EXPOSE {port}
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \\
  CMD wget -qO- http://127.0.0.1:{port}/health || exit 1
ENTRYPOINT ["dotnet", "App.dll"]
"""


# ---------------------------------------------------------------------------
# .dockerignore template
# ---------------------------------------------------------------------------

DOCKERIGNORE_TEMPLATE = """\
node_modules
dist
build
.angular
.next
.nuxt
.output
__pycache__
*.pyc
.venv
venv
.git
.env
.env.*
*.db
*.sqlite
coverage
.pytest_cache
.mypy_cache
.tox
"""


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------

_TEMPLATES = {
    "python": PYTHON_DOCKERFILE,
    "fastapi": PYTHON_DOCKERFILE,
    "typescript": TYPESCRIPT_DOCKERFILE,
    "nestjs": TYPESCRIPT_DOCKERFILE,
    "node": TYPESCRIPT_DOCKERFILE,
    "express": TYPESCRIPT_DOCKERFILE,
    "frontend": FRONTEND_DOCKERFILE,
    "angular": FRONTEND_DOCKERFILE,
    "react": FRONTEND_DOCKERFILE,
    "vue": FRONTEND_DOCKERFILE,
    "dotnet": DOTNET_DOCKERFILE,
    "csharp": DOTNET_DOCKERFILE,
}


def get_dockerfile_template(stack: str, port: int = 8080) -> str:
    """Return a Dockerfile template for the given tech stack.

    Parameters
    ----------
    stack :
        Technology identifier (e.g., "python", "nestjs", "angular", "dotnet").
        Case-insensitive.
    port :
        Port number for EXPOSE and HEALTHCHECK. Default 8080 for backends,
        80 for frontend (auto-detected if stack is frontend).

    Returns
    -------
    str
        Dockerfile content with {port} placeholders replaced.
    """
    key = stack.lower().strip()
    template = _TEMPLATES.get(key, PYTHON_DOCKERFILE)

    # Auto-set port for frontend
    if key in ("frontend", "angular", "react", "vue"):
        port = 80

    return template.replace("{port}", str(port))


def get_dockerignore() -> str:
    """Return a standard .dockerignore template."""
    return DOCKERIGNORE_TEMPLATE


def format_dockerfile_reference(stack: str, port: int = 8080) -> str:
    """Format a Dockerfile template as a prompt reference block.

    Returns a markdown code block with the template, suitable for injection
    into milestone execution prompts.
    """
    template = get_dockerfile_template(stack, port)
    return (
        f"\n[DOCKERFILE REFERENCE — {stack.upper()} TEMPLATE]\n"
        f"Use this battle-tested Dockerfile template as your starting point:\n"
        f"```dockerfile\n{template}```\n"
        f"\nAlso create a `.dockerignore` file:\n"
        f"```\n{DOCKERIGNORE_TEMPLATE}```\n"
    )
