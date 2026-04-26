# Milestone 1 Pre-Smoke Gate

A fresh Milestone 1 smoke is not justified until all items below are true for
the current codebase and the intended run workspace:

1. Targeted pytest is green for the provider routing, repair routing, OpenAPI
   fidelity, Wave D prompt/artifact, Context7 fallback, and observer checks.
2. No WaveResult telemetry for the candidate run has `fallback_used=true`.
3. No Wave C artifact has `contract_fidelity=degraded` or a non-empty
   `degradation_reason`.
4. No wave telemetry has `success=false`, `wave_timed_out=true`, or a non-empty
   failed-wave marker such as `error_message`.
5. No non-Wave-A telemetry has non-empty `scope_violations`.
6. `.agent-team/observer_log.jsonl` has no repeated identical log-only steer
   messages for stale plan/diff payloads.
7. The run uses Codex app-server for Codex-owned waves and Agent Teams for
   intentional Claude-owned waves: `agent_teams.enabled=True`,
   `agent_teams.fallback_to_cli=False`, and `v18.codex_transport_mode=app-server`.

The preserved `C:\smoke\clean-r1b1-postwedge-13` workspace remains
forensic-only evidence and must not be used as completion proof.
