param(
    [switch]$DryRun,
    [switch]$SkipMinerUStart,
    [int]$MinerUApiPort = 8010
)

$ErrorActionPreference = "Stop"

python -m poc_workflow init

if (-not $SkipMinerUStart) {
    & (Join-Path $PSScriptRoot "start-mineru-tool.ps1") -ApiPort $MinerUApiPort -Quiet
    $mineruEnv = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\.runtime")).Path "mineru-tool.env.ps1"
    if (Test-Path $mineruEnv) {
        . $mineruEnv
    }
}

if ($DryRun) {
    python -m poc_workflow prepare-inbox --dry-run
    exit 0
}

python -m poc_workflow prepare-inbox
python -m poc_workflow process-source
python -m poc_workflow manifest
