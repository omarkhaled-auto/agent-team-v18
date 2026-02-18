$ErrorActionPreference = "Continue"
$projectDir = "C:\Users\Omar Khaled\OneDrive\Desktop\agent-team-v15"
$pytestExe = Join-Path $projectDir ".venv\Scripts\pytest.exe"
$outFile = Join-Path $projectDir "__final_test_output.txt"

Set-Location $projectDir

# Clear old output
if (Test-Path $outFile) { Remove-Item $outFile }

$sb = [System.Text.StringBuilder]::new()

# --- Part 1: Audit tests ---
$sb.AppendLine("=" * 60) | Out-Null
$sb.AppendLine("PART 1: AUDIT TESTS (verbose)") | Out-Null
$sb.AppendLine("=" * 60) | Out-Null

$r = & $pytestExe tests/test_audit_models.py tests/test_audit_team.py tests/test_audit_prompts.py -v --tb=short 2>&1 | Out-String
$sb.AppendLine($r) | Out-Null
$sb.AppendLine("AUDIT EXIT CODE: $LASTEXITCODE") | Out-Null

# --- Part 2: Full suite ---
$sb.AppendLine("") | Out-Null
$sb.AppendLine("=" * 60) | Out-Null
$sb.AppendLine("PART 2: FULL TEST SUITE (quiet)") | Out-Null
$sb.AppendLine("=" * 60) | Out-Null

$r2 = & $pytestExe tests/ -q --tb=short --ignore=tests/test_sdk_cmd_overflow.py 2>&1 | Out-String
$sb.AppendLine($r2) | Out-Null
$sb.AppendLine("FULL SUITE EXIT CODE: $LASTEXITCODE") | Out-Null

$sb.ToString() | Out-File -FilePath $outFile -Encoding utf8
Write-Host "Results written to $outFile"
