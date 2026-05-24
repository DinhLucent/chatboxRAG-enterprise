param(
    [string]$OutputPath = "",
    [switch]$NoLogs
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputPath = "data\diagnostics\diagnostics-$stamp.json"
}

$parent = Split-Path -Parent $OutputPath
if (-not [string]::IsNullOrWhiteSpace($parent)) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

$args = @("-m", "poc_workflow", "diagnostics")
if ($NoLogs) {
    $args += "--no-logs"
}

python @args | Set-Content -Path $OutputPath -Encoding UTF8
Write-Output $OutputPath
