$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$env:PYTHONPATH = Join-Path $repoRoot 'src'

python -m agent_team_v15.m1_fast_forward --repo $repoRoot @args
