#!/usr/bin/env python
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest",
     "tests/test_audit_models.py",
     "tests/test_audit_team.py",
     "tests/test_audit_prompts.py",
     "-q", "--tb=short"],
    text=True
)
sys.exit(result.returncode)
