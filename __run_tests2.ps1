$ErrorActionPreference = "Continue"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$projectDir = "C:\Users\Omar Khaled\OneDrive\Desktop\agent-team-v15"
$pythonExe = "$projectDir\.venv\Scripts\python.exe"
$pytestExe = "$projectDir\.venv\Scripts\pytest.exe"
$outFile = "$projectDir\__test_output2.txt"

Set-Location $projectDir

$results = @()
$results += "=== STEP 1: Python Version ==="
$results += (& $pythonExe --version 2>&1 | Out-String)

$results += "=== STEP 2: Compile Checks ==="
$files = @(
    "src/agent_team/audit_models.py",
    "src/agent_team/audit_prompts.py",
    "src/agent_team/audit_team.py",
    "src/agent_team/config.py",
    "src/agent_team/agents.py",
    "src/agent_team/cli.py"
)
foreach ($f in $files) {
    $cmd = "import py_compile; py_compile.compile('$f', doraise=True); print('$f OK')"
    $r = & $pythonExe -c $cmd 2>&1 | Out-String
    $results += $r.Trim()
}

$results += ""
$results += "=== STEP 3: Audit Tests ==="
$r = & $pytestExe tests/test_audit_models.py tests/test_audit_team.py tests/test_audit_prompts.py -v --tb=short 2>&1 | Out-String
$results += $r

$results += ""
$results += "=== STEP 4: Full Test Suite ==="
$r = & $pytestExe tests/ -x -q --tb=short 2>&1 | Out-String
$results += $r

$output = $results -join "`n"
[System.IO.File]::WriteAllText($outFile, $output, [System.Text.Encoding]::UTF8)
Write-Host "Done. Output written to $outFile"
