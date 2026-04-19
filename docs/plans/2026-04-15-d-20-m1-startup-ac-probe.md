# D-20 — M1 startup-AC probe not executed during audit

**Tracker ID:** D-20
**Source:** milestone-1 REQUIREMENTS.md §"M1 Acceptance Criteria Results" — "UNKNOWN (not tested in audit)" for `npm install` and `prisma migrate dev`
**Session:** 3
**Size:** M (~100 LOC)
**Risk:** MEDIUM
**Status:** plan

---

## 1. Problem statement

M1 has 7 explicit startup ACs. The build-j audit only verified 5 of them statically (Swagger UI present, ports observed, test runners configured). Two are marked UNKNOWN because audit has no step to actually execute them:
- `npm install` at root — must exit 0.
- `npx prisma migrate dev --name init` — must exit 0.

This means M1 "clearing" the audit doesn't actually prove M1's narrow ACs pass. An operator has to manually run commands to verify — which is exactly the brittleness M1 audit is supposed to replace.

## 2. Root cause

Audit phase is model-driven: it reads files and reasons about them. It doesn't execute commands against the scaffolded workspace.

## 3. Proposed fix shape

### 3a. Infrastructure-milestone startup-AC probe

For milestones with `template: full_stack` and `complexity_estimate.entity_count == 0` (infrastructure-only), add an explicit audit-phase probe:

```python
def run_m1_startup_probe(workspace: Path) -> dict[str, dict]:
    """Run the M1 startup ACs and return structured results."""
    results = {}
    
    # AC: npm install
    r = subprocess.run(["npm", "install"], cwd=workspace, capture_output=True, timeout=300)
    results["npm_install"] = {"exit_code": r.returncode, "stdout_tail": r.stdout[-1000:].decode(errors="ignore")}
    
    # AC: docker-compose up -d
    r = subprocess.run(["docker", "compose", "up", "-d", "postgres"], cwd=workspace, capture_output=True, timeout=120)
    results["compose_up"] = {"exit_code": r.returncode, ...}
    
    # AC: prisma migrate dev
    r = subprocess.run(["npx", "prisma", "migrate", "dev", "--name", "init"], cwd=workspace / "apps/api", capture_output=True, timeout=180)
    results["prisma_migrate"] = {...}
    
    # AC: jest runs (zero tests)
    r = subprocess.run(["npm", "run", "test:api"], cwd=workspace, capture_output=True, timeout=60)
    results["test_api"] = {...}
    
    # AC: vitest runs (zero tests)
    r = subprocess.run(["npm", "run", "test:web"], cwd=workspace, capture_output=True, timeout=60)
    results["test_web"] = {...}
    
    # Teardown
    subprocess.run(["docker", "compose", "down"], cwd=workspace, timeout=60)
    
    return results
```

### 3b. Include in AUDIT_REPORT.json

Add a top-level `acceptance_tests` section:

```json
{
  ...
  "acceptance_tests": {
    "m1_startup_probe": {
      "npm_install": {"status": "pass", "exit_code": 0},
      "compose_up": {"status": "pass", "exit_code": 0},
      "prisma_migrate": {"status": "pass", "exit_code": 0},
      "test_api": {"status": "pass", "exit_code": 0},
      "test_web": {"status": "pass", "exit_code": 0}
    }
  },
  ...
}
```

### 3c. Fail the audit if any probe fails

If any probe returns non-zero, audit verdict is FAIL regardless of finding count. Updates `AUDIT_REPORT.json.verdict`.

## 4. Test plan

File: `tests/test_m1_startup_probe.py`

1. **Successful probe populates acceptance_tests.** Mock all subprocess calls to return exit 0; assert `acceptance_tests.m1_startup_probe.npm_install.status == "pass"`.
2. **Failed probe marks audit FAIL.** Mock npm install returning exit 1; assert `AUDIT_REPORT.json.verdict == "FAIL"`.
3. **Probe only runs for infrastructure milestones.** Mock an M3-like milestone (entity_count=1); assert probe skipped, with skip reason logged.
4. **Timeout handled gracefully.** Mock a subprocess that hangs past timeout; assert probe records timeout as failure, moves on.
5. **Teardown always runs.** Mock probe mid-way failure; assert `docker compose down` still called.

Target: 5 tests.

## 5. Rollback plan

Feature flag `config.v18.m1_startup_probe: bool = True`. Flip off to restore pre-fix behavior.

## 6. Success criteria

- Unit tests pass.
- Gate A smoke: `AUDIT_REPORT.json.acceptance_tests.m1_startup_probe.*.status` is `pass` for all five ACs.
- M1 audit verdict `PASS` only when all five probes pass.

## 7. Sequencing notes

- Land in Session 3 alongside D-07 (audit schema) and D-13 (state finalize).
- Depends on A-01 (compose file), A-02 (port 3001), A-07 (vitest installed) — the probe can only pass if those are correct. Sequence: A-01/A-02/A-07 land Session 2, probe lands Session 3.
- Windows caveat: `docker compose` may need `docker-compose` legacy form; detect and use whichever is available.
