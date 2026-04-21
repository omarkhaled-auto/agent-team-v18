<!-- Verification fidelity: runtime -->
## Runtime Verification Report

### Docker Build: 3/3 services

- postgres: PASS
- api: PASS
- web: PASS

### Services: 3/3 healthy

- api: HEALTHY
- postgres: HEALTHY
- web: HEALTHY

### Migrations: OK

### Smoke Test: 0/2 services responding

- api: FAIL
- web: FAIL

### Fix Loop: 4 attempts, $2.07 spent

- web (round 1, build): $0.36
- api (round 1, build): $0.40
- web (round 2, build): $0.33
- (all) (round 1, startup): $0.98

**Total duration:** 835.7s

**Fix rounds completed:** 4
