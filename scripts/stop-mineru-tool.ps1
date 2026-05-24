param(
    [int]$ApiPort = 8010,
    [int]$WebUIPort = 7860
)

$ErrorActionPreference = "Stop"

function Stop-PortOwner {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        return $conn.OwningProcess
    }
    return $null
}

$stopped = [ordered]@{}
$stopped["api"] = Stop-PortOwner -Port $ApiPort
$stopped["webui"] = Stop-PortOwner -Port $WebUIPort

$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtime = Join-Path $workspace ".runtime"
Get-ChildItem $runtime -Filter "mineru-*.pid" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

[PSCustomObject]@{
    stopped = $stopped
} | ConvertTo-Json -Depth 4
