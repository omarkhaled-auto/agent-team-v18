$ErrorActionPreference = "Continue"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$projectDir = "C:\Users\Omar Khaled\OneDrive\Desktop\agent-team-v15"
$pytestExe = "$projectDir\.venv\Scripts\pytest.exe"
$outFile = "$projectDir\__test_output3.txt"

Set-Location $projectDir

$results = @()
$results += "=== Full Test Suite (ignoring test_sdk_cmd_overflow.py) ==="
$r = & $pytestExe tests/ -q --tb=short --ignore=tests/test_sdk_cmd_overflow.py 2>&1 | Out-String
$results += $r

$output = $results -join "`n"
[System.IO.File]::WriteAllText($outFile, $output, [System.Text.Encoding]::UTF8)
Write-Host "Done."
