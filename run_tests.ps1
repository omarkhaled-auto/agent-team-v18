Set-Location "C:\Users\Omar Khaled\OneDrive\Desktop\agent-team-v15"

Write-Host "============================================================"
Write-Host "AUDIT TESTS"
Write-Host "============================================================"
& .\.venv\Scripts\pytest.exe tests\test_audit_models.py tests\test_audit_team.py tests\test_audit_prompts.py -v --tb=short 2>&1 | Out-File -FilePath "audit_test_output.txt" -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host "FULL TEST SUITE"
Write-Host "============================================================"
& .\.venv\Scripts\pytest.exe tests\ -q --tb=short --ignore=tests\test_sdk_cmd_overflow.py 2>&1 | Out-File -FilePath "full_test_output.txt" -Encoding utf8

Write-Host "Done. Check audit_test_output.txt and full_test_output.txt"
