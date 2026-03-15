"""Tests for interface registry (scaling component 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.interface_registry import (
    InterfaceRegistry,
    ModuleInterface,
    FunctionSignature,
    EndpointEntry,
    EventEntry,
    extract_module_interface,
    update_registry_from_milestone,
    save_registry,
    load_registry,
    format_registry_for_prompt,
    get_targeted_files,
    _detect_service_dirs,
)


# ===================================================================
# Extract module interface
# ===================================================================

class TestExtractModuleInterface:
    def test_python_functions(self, tmp_path):
        svc = tmp_path / "auth"
        svc.mkdir()
        (svc / "service.py").write_text(
            "async def create_user(email: str, password: str) -> dict:\n"
            "    pass\n\n"
            "def get_user(user_id: str) -> dict:\n"
            "    pass\n\n"
            "def _internal_helper():\n"
            "    pass\n",
            encoding="utf-8",
        )
        iface = extract_module_interface(svc, "auth", tmp_path)
        names = {f.name for f in iface.functions}
        assert "create_user" in names
        assert "get_user" in names
        assert "_internal_helper" not in names  # Private, filtered
        # Check async detection
        create = next(f for f in iface.functions if f.name == "create_user")
        assert create.is_async is True
        get = next(f for f in iface.functions if f.name == "get_user")
        assert get.is_async is False

    def test_python_routes(self, tmp_path):
        svc = tmp_path / "gl"
        svc.mkdir()
        (svc / "routes.py").write_text(
            '@router.get("/journal-entries")\n'
            "async def list_entries(): pass\n\n"
            '@router.post("/journal-entries")\n'
            "async def create_entry(): pass\n",
            encoding="utf-8",
        )
        iface = extract_module_interface(svc, "gl", tmp_path)
        assert len(iface.endpoints) == 2
        methods = {ep.method for ep in iface.endpoints}
        assert "GET" in methods
        assert "POST" in methods

    def test_python_classes(self, tmp_path):
        svc = tmp_path / "ar"
        svc.mkdir()
        (svc / "models.py").write_text(
            "class Invoice(Base): pass\n"
            "class Customer(Base): pass\n",
            encoding="utf-8",
        )
        iface = extract_module_interface(svc, "ar", tmp_path)
        assert "Invoice" in iface.types
        assert "Customer" in iface.types

    def test_typescript_functions(self, tmp_path):
        svc = tmp_path / "ar"
        svc.mkdir()
        (svc / "service.ts").write_text(
            "async createInvoice(data: CreateInvoiceDto): Promise<Invoice> {\n"
            "  return this.repo.save(data);\n"
            "}\n",
            encoding="utf-8",
        )
        iface = extract_module_interface(svc, "ar", tmp_path)
        names = {f.name for f in iface.functions}
        assert "createInvoice" in names

    def test_event_detection(self, tmp_path):
        svc = tmp_path / "ar"
        svc.mkdir()
        (svc / "events.py").write_text(
            'await publish_event("ar.invoice.created", payload)\n'
            'await subscribe("gl.period.closed", handler)\n',
            encoding="utf-8",
        )
        iface = extract_module_interface(svc, "ar", tmp_path)
        pubs = [e for e in iface.events if e.direction == "publish"]
        subs = [e for e in iface.events if e.direction == "subscribe"]
        assert len(pubs) == 1
        assert pubs[0].event_name == "ar.invoice.created"
        assert len(subs) == 1
        assert subs[0].event_name == "gl.period.closed"

    def test_empty_dir(self, tmp_path):
        svc = tmp_path / "empty"
        svc.mkdir()
        iface = extract_module_interface(svc, "empty", tmp_path)
        assert iface.functions == []
        assert iface.types == []

    def test_nonexistent_dir(self, tmp_path):
        iface = extract_module_interface(tmp_path / "nope", "nope")
        assert iface.module_name == "nope"
        assert iface.functions == []


# ===================================================================
# Registry update
# ===================================================================

class TestUpdateRegistry:
    def test_update_adds_module(self, tmp_path):
        # Create a service directory
        svc = tmp_path / "services" / "auth"
        svc.mkdir(parents=True)
        (svc / "main.py").write_text(
            "def login(email: str, password: str) -> dict:\n    pass\n",
            encoding="utf-8",
        )
        registry = InterfaceRegistry(project_name="test")
        registry = update_registry_from_milestone(
            registry, tmp_path, "milestone-1",
        )
        assert "auth" in registry.modules
        assert registry.last_updated_milestone == "milestone-1"

    def test_update_overwrites_existing(self, tmp_path):
        svc = tmp_path / "services" / "gl"
        svc.mkdir(parents=True)
        (svc / "service.py").write_text("def old_func(): pass\n", encoding="utf-8")

        registry = InterfaceRegistry()
        registry = update_registry_from_milestone(registry, tmp_path, "m1")
        assert any(f.name == "old_func" for f in registry.modules["gl"].functions)

        # Update with new code
        (svc / "service.py").write_text("def new_func(): pass\n", encoding="utf-8")
        registry = update_registry_from_milestone(registry, tmp_path, "m2")
        assert any(f.name == "new_func" for f in registry.modules["gl"].functions)
        assert registry.modules["gl"].updated_by_milestone == "m2"


# ===================================================================
# Serialization
# ===================================================================

class TestSerialization:
    def test_roundtrip(self, tmp_path):
        registry = InterfaceRegistry(
            project_name="TestApp",
            last_updated_milestone="m3",
            modules={
                "auth": ModuleInterface(
                    module_name="auth",
                    functions=[FunctionSignature(
                        name="login", file_path="auth/service.py",
                        params=["email", "password"], return_type="dict",
                        is_async=True, line=10,
                    )],
                    endpoints=[EndpointEntry(
                        method="POST", path="/login", handler="login",
                        file_path="auth/routes.py", line=5,
                    )],
                    events=[EventEntry(
                        event_name="auth.user.created", direction="publish",
                        handler="create_user", file_path="auth/service.py",
                    )],
                    types=["User", "Role"],
                    updated_by_milestone="m2",
                ),
            },
        )
        path = tmp_path / "registry.json"
        save_registry(registry, path)
        loaded = load_registry(path)

        assert loaded.project_name == "TestApp"
        assert loaded.last_updated_milestone == "m3"
        assert "auth" in loaded.modules
        auth = loaded.modules["auth"]
        assert len(auth.functions) == 1
        assert auth.functions[0].name == "login"
        assert auth.functions[0].is_async is True
        assert len(auth.endpoints) == 1
        assert auth.endpoints[0].method == "POST"
        assert len(auth.events) == 1
        assert "User" in auth.types

    def test_load_missing_file(self, tmp_path):
        registry = load_registry(tmp_path / "nonexistent.json")
        assert registry.modules == {}

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        registry = load_registry(path)
        assert registry.modules == {}


# ===================================================================
# Prompt formatting
# ===================================================================

class TestFormatRegistryForPrompt:
    def test_empty_registry(self):
        result = format_registry_for_prompt(InterfaceRegistry())
        assert result == ""

    def test_includes_module_info(self):
        registry = InterfaceRegistry(modules={
            "gl": ModuleInterface(
                module_name="gl",
                functions=[FunctionSignature(
                    name="create_journal", file_path="gl/service.py",
                    params=["data", "tenant_id"], return_type="JournalEntry",
                    is_async=True,
                )],
                endpoints=[EndpointEntry(
                    method="POST", path="/journal-entries",
                    handler="create_entry", file_path="gl/routes.py",
                )],
                events=[EventEntry(
                    event_name="gl.entry.created", direction="publish",
                    handler="", file_path="gl/service.py",
                )],
                types=["JournalEntry", "JournalLine"],
            ),
        })
        text = format_registry_for_prompt(registry)
        assert "gl" in text
        assert "create_journal" in text
        assert "POST /journal-entries" in text
        assert "gl.entry.created" in text
        assert "JournalEntry" in text

    def test_respects_token_budget(self):
        # Create a large registry
        modules = {}
        for i in range(50):
            modules[f"svc_{i}"] = ModuleInterface(
                module_name=f"svc_{i}",
                functions=[FunctionSignature(
                    name=f"func_{j}", file_path=f"svc_{i}/service.py",
                    params=["a", "b", "c"], return_type="dict",
                ) for j in range(20)],
            )
        registry = InterfaceRegistry(modules=modules)
        text = format_registry_for_prompt(registry, max_tokens=5000)
        assert "truncated" in text.lower()


# ===================================================================
# Targeted file loading
# ===================================================================

class TestGetTargetedFiles:
    def test_loads_requested_functions(self, tmp_path):
        # Create a source file
        svc = tmp_path / "gl" / "service.py"
        svc.parent.mkdir(parents=True)
        svc.write_text(
            "async def create_journal_entry(data):\n"
            "    return await db.insert(data)\n",
            encoding="utf-8",
        )
        registry = InterfaceRegistry(modules={
            "gl": ModuleInterface(
                module_name="gl",
                functions=[FunctionSignature(
                    name="create_journal_entry",
                    file_path="gl/service.py",
                )],
            ),
        })
        result = get_targeted_files(
            registry, ["create_journal_entry"], tmp_path,
        )
        assert "create_journal_entry" in result
        assert "db.insert" in result

    def test_empty_functions_list(self, tmp_path):
        registry = InterfaceRegistry()
        result = get_targeted_files(registry, [], tmp_path)
        assert "TARGETED FILE" in result


# ===================================================================
# Service directory detection
# ===================================================================

class TestDetectServiceDirs:
    def test_detects_services_dir(self, tmp_path):
        (tmp_path / "services" / "auth").mkdir(parents=True)
        (tmp_path / "services" / "gl").mkdir(parents=True)
        dirs = _detect_service_dirs(tmp_path)
        assert "services/auth" in dirs
        assert "services/gl" in dirs

    def test_detects_frontend(self, tmp_path):
        (tmp_path / "frontend").mkdir()
        dirs = _detect_service_dirs(tmp_path)
        assert "frontend" in dirs

    def test_detects_shared(self, tmp_path):
        (tmp_path / "shared").mkdir()
        dirs = _detect_service_dirs(tmp_path)
        assert "shared" in dirs


# ===================================================================
# Real project integration
# ===================================================================

class TestRealProject:
    def test_globalbooks_standalone(self):
        project = Path(r"C:\MY_PROJECTS\globalbooks-standalone")
        if not project.is_dir():
            pytest.skip("GlobalBooks standalone not available")

        registry = InterfaceRegistry(project_name="GlobalBooks")
        registry = update_registry_from_milestone(registry, project, "test")

        assert len(registry.modules) >= 5
        # Check that real functions were extracted
        total_funcs = sum(len(m.functions) for m in registry.modules.values())
        total_types = sum(len(m.types) for m in registry.modules.values())
        total_endpoints = sum(len(m.endpoints) for m in registry.modules.values())

        print(f"\nModules: {len(registry.modules)}")
        for name, mod in sorted(registry.modules.items()):
            print(f"  {name}: {len(mod.functions)} funcs, {len(mod.types)} types, "
                  f"{len(mod.endpoints)} endpoints, {len(mod.events)} events")
        print(f"Total: {total_funcs} functions, {total_types} types, {total_endpoints} endpoints")

        # Prompt format should be reasonable size
        prompt = format_registry_for_prompt(registry)
        print(f"Prompt size: {len(prompt)} chars (~{len(prompt)//4} tokens)")
        assert len(prompt) > 100
        assert len(prompt) // 4 < 30000  # Should fit in token budget
