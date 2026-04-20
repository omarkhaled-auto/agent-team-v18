# Proof 01 - Enforcement Escalation And State

## Scope

Show that H3f changes Wave A ownership from detection-only to a real gate when
`wave_a_ownership_enforcement_enabled=True`, while preserving the legacy
non-blocking path when only the old H1a flag is on.

## Evidence

Pytest command:

```text
pytest tests/test_h3f_ownership_enforcement.py tests/test_config_v18_loader_gaps.py -v --tb=short
```

Relevant tests:

- `test_detector_sets_blocks_wave_only_when_h3f_gate_is_enabled`
- `test_wave_a_ownership_check_reports_but_does_not_fail_when_hard_fail_flag_off`
- `test_wave_a_ownership_hard_fail_redispatches_with_rejection_context`

Observed results:

- Detector surface:
  - legacy path: `OWNERSHIP-WAVE-A-FORBIDDEN-001` stays `HIGH`, `blocks_wave=False`
  - H3f gate path: same finding code stays `HIGH`, `blocks_wave=True`
- Detection-only executor path:
  - Wave A remains successful
  - no `failed_wave`
  - no redispatch history
- Hard-fail executor path:
  - Wave A fails on ownership
  - redispatch is scheduled back to Wave A
  - rejection context includes `OWNERSHIP-WAVE-A-FORBIDDEN-001`

Ring summary:

```text
37 passed in 0.51s
```

Output file:

- `v18 test runs/phase-h3f-validation/pytest-output-h3f-ring.txt`

## Conclusion

H3f does not change the detector code or pattern ID. It changes the outcome:
when the new H3f flag is on, ownership findings become a real Wave A failure
and feed the existing H3e redispatch path.
