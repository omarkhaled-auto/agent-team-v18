"""Tests for Dockerfile templates (v16 Phase 1.8)."""

from __future__ import annotations

import pytest

from agent_team_v15.dockerfile_templates import (
    PYTHON_DOCKERFILE,
    TYPESCRIPT_DOCKERFILE,
    FRONTEND_DOCKERFILE,
    DOTNET_DOCKERFILE,
    DOCKERIGNORE_TEMPLATE,
    get_dockerfile_template,
    get_dockerignore,
    format_dockerfile_reference,
)


# ===================================================================
# Template content tests
# ===================================================================

class TestPythonDockerfile:
    def test_multi_stage(self):
        assert "AS builder" in PYTHON_DOCKERFILE

    def test_non_root_user(self):
        assert "appuser" in PYTHON_DOCKERFILE
        assert "USER appuser" in PYTHON_DOCKERFILE

    def test_healthcheck_uses_urllib(self):
        assert "urllib.request" in PYTHON_DOCKERFILE
        assert "curl" not in PYTHON_DOCKERFILE

    def test_healthcheck_uses_127_0_0_1(self):
        assert "127.0.0.1" in PYTHON_DOCKERFILE
        assert "localhost" not in PYTHON_DOCKERFILE

    def test_start_period_90s(self):
        assert "start-period=90s" in PYTHON_DOCKERFILE

    def test_retries_5(self):
        assert "retries=5" in PYTHON_DOCKERFILE

    def test_port_placeholder(self):
        assert "{port}" in PYTHON_DOCKERFILE


class TestTypescriptDockerfile:
    def test_multi_stage(self):
        assert "AS builder" in TYPESCRIPT_DOCKERFILE

    def test_non_root_user(self):
        assert "appuser" in TYPESCRIPT_DOCKERFILE

    def test_healthcheck_uses_wget(self):
        assert "wget" in TYPESCRIPT_DOCKERFILE

    def test_healthcheck_uses_127_0_0_1(self):
        assert "127.0.0.1" in TYPESCRIPT_DOCKERFILE

    def test_start_period_90s(self):
        assert "start-period=90s" in TYPESCRIPT_DOCKERFILE

    def test_npm_ci_omit_dev(self):
        assert "npm ci --omit=dev" in TYPESCRIPT_DOCKERFILE

    def test_node_alpine_base(self):
        assert "node:20-alpine" in TYPESCRIPT_DOCKERFILE


class TestFrontendDockerfile:
    def test_multi_stage(self):
        assert "AS builder" in FRONTEND_DOCKERFILE

    def test_nginx_stable_alpine(self):
        assert "nginx:stable-alpine" in FRONTEND_DOCKERFILE

    def test_has_healthcheck(self):
        assert "HEALTHCHECK" in FRONTEND_DOCKERFILE
        assert "wget" in FRONTEND_DOCKERFILE

    def test_spa_routing(self):
        assert "try_files" in FRONTEND_DOCKERFILE
        assert "index.html" in FRONTEND_DOCKERFILE

    def test_dynamic_dist_detection(self):
        """Must handle Angular, React, and Vue build output paths."""
        assert "dist/*/browser/" in FRONTEND_DOCKERFILE  # Angular 17+
        assert "/tmp/build" in FRONTEND_DOCKERFILE  # React
        assert "/tmp/dist" in FRONTEND_DOCKERFILE  # Vue/Vite

    def test_no_hardcoded_project_name(self):
        """Must NOT hardcode a specific project name in the dist path."""
        assert "globalbooks" not in FRONTEND_DOCKERFILE.lower()

    def test_expose_80(self):
        assert "EXPOSE 80" in FRONTEND_DOCKERFILE

    def test_inline_nginx_config(self):
        """Uses inline printf for nginx config, not external file."""
        assert "printf" in FRONTEND_DOCKERFILE


class TestDotnetDockerfile:
    def test_multi_stage(self):
        assert "AS build" in DOTNET_DOCKERFILE

    def test_non_root_user(self):
        assert "appuser" in DOTNET_DOCKERFILE

    def test_aspnetcore_urls(self):
        assert "ASPNETCORE_URLS" in DOTNET_DOCKERFILE


class TestDockerignore:
    def test_excludes_node_modules(self):
        assert "node_modules" in DOCKERIGNORE_TEMPLATE

    def test_excludes_pycache(self):
        assert "__pycache__" in DOCKERIGNORE_TEMPLATE

    def test_excludes_git(self):
        assert ".git" in DOCKERIGNORE_TEMPLATE

    def test_excludes_env(self):
        assert ".env" in DOCKERIGNORE_TEMPLATE


# ===================================================================
# Function tests
# ===================================================================

class TestGetDockerfileTemplate:
    def test_python(self):
        t = get_dockerfile_template("python", 8080)
        assert "8080" in t
        assert "uvicorn" in t

    def test_nestjs(self):
        t = get_dockerfile_template("nestjs", 8080)
        assert "8080" in t
        assert "node" in t

    def test_angular_auto_port(self):
        t = get_dockerfile_template("angular")
        assert "EXPOSE 80" in t

    def test_frontend_auto_port(self):
        t = get_dockerfile_template("frontend")
        assert "EXPOSE 80" in t

    def test_unknown_defaults_to_python(self):
        t = get_dockerfile_template("unknown_stack", 3000)
        assert "uvicorn" in t
        assert "3000" in t

    def test_case_insensitive(self):
        t = get_dockerfile_template("Python", 8080)
        assert "uvicorn" in t

    def test_dotnet(self):
        t = get_dockerfile_template("dotnet", 8080)
        assert "dotnet" in t
        assert "8080" in t


class TestFormatDockerfileReference:
    def test_returns_markdown(self):
        ref = format_dockerfile_reference("python", 8080)
        assert "```dockerfile" in ref
        assert "DOCKERFILE REFERENCE" in ref
        assert ".dockerignore" in ref

    def test_includes_template_content(self):
        ref = format_dockerfile_reference("nestjs", 8080)
        assert "npm ci" in ref
        assert "wget" in ref

    def test_includes_dockerignore(self):
        ref = format_dockerfile_reference("angular")
        assert "node_modules" in ref
