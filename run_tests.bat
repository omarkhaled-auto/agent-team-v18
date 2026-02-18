@echo off
cd /d "C:\Users\Omar Khaled\OneDrive\Desktop\agent-team-v15"

echo ============================================================
echo AUDIT TESTS
echo ============================================================
.venv\Scripts\pytest.exe tests\test_audit_models.py tests\test_audit_team.py tests\test_audit_prompts.py -v --tb=short

echo.
echo ============================================================
echo FULL TEST SUITE
echo ============================================================
.venv\Scripts\pytest.exe tests\ -q --tb=short --ignore=tests\test_sdk_cmd_overflow.py
