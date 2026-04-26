$ErrorActionPreference = 'Stop'

$repo = 'C:\Projects\agent-team-v18-codex'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$run = Join-Path $repo ('v18 test runs\m1-hardening-smoke-' + $stamp)

New-Item -ItemType Directory -Force -Path $run | Out-Null

$prd = Join-Path $run 'PRD.md'
$cfg = Join-Path $run 'config.yaml'
$log = Join-Path $run 'BUILD_LOG.txt'
$err = Join-Path $run 'BUILD_ERR.txt'
$exitFile = Join-Path $run 'EXIT_CODE.txt'
$pidFile = Join-Path $run 'AGENT_TEAM_PID.txt'
$runDirFile = Join-Path $run 'RUN_DIR.txt'

Copy-Item -LiteralPath (Join-Path $repo 'v18 test runs\TASKFLOW_MINI_PRD.md') -Destination $prd -Force
Copy-Item -LiteralPath (Join-Path $repo 'v18 test runs\configs\taskflow-smoke-test-config.yaml') -Destination $cfg -Force

[System.Diagnostics.Process]::GetCurrentProcess().Id | Set-Content -LiteralPath $pidFile
('RUN_DIR=' + $run) | Tee-Object -FilePath $runDirFile
('LOG=' + $log)
('ERR=' + $err)

$dockerPreflight = Join-Path $run 'docker-ps-preflight.txt'
docker ps *> $dockerPreflight
if ($LASTEXITCODE -ne 0) {
    $LASTEXITCODE | Set-Content -LiteralPath $exitFile
    throw 'docker ps failed; smoke not started'
}

Set-Content -LiteralPath $err -Value 'stderr and PowerShell error stream are merged into BUILD_LOG.txt by this launcher.'

$argsList = @(
    '--prd', $prd,
    '--config', $cfg,
    '--depth', 'exhaustive',
    '--cwd', $run,
    '--reset-failed-milestones'
)

$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $run
& agent-team-v15 @argsList *> $log
$code = $LASTEXITCODE
if ($null -eq $code) {
    $code = 0
}
$code | Set-Content -LiteralPath $exitFile
exit $code
