from __future__ import annotations

from agent_team_v15.quality_validators import run_infrastructure_scan


def test_infrastructure_scan_blocks_next_worker_threads(tmp_path) -> None:
    web_dir = tmp_path / "apps" / "web"
    web_dir.mkdir(parents=True)
    cfg = web_dir / "next.config.mjs"
    cfg.write_text(
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = { experimental: { workerThreads: true } };\n"
        "export default nextConfig;\n",
        encoding="utf-8",
    )

    violations = run_infrastructure_scan(tmp_path)

    assert any(
        v.check == "INFRA-006"
        and v.file_path == "apps/web/next.config.mjs"
        and "workerThreads" in v.message
        for v in violations
    )
