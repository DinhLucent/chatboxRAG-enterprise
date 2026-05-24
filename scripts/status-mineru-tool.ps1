param(
    [int]$ApiPort = 8010,
    [int]$WebUIPort = 7860
)

$ErrorActionPreference = "Stop"

function Get-PortStatus {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) {
        return [PSCustomObject]@{ listening = $false; port = $Port; pid = $null; process = $null }
    }
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    return [PSCustomObject]@{
        listening = $true
        port = $Port
        pid = $conn.OwningProcess
        process = $proc.ProcessName
    }
}

$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtime = Join-Path $workspace ".runtime"
$api = Get-PortStatus -Port $ApiPort
$web = Get-PortStatus -Port $WebUIPort

$health = $null
if ($api.listening) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 5
    } catch {
        $health = @{ error = $_.Exception.Message }
    }
}

[PSCustomObject]@{
    api = $api
    api_url = "http://127.0.0.1:$ApiPort"
    api_health = $health
    webui = $web
    webui_url = if ($web.listening) { "http://127.0.0.1:$WebUIPort" } else { $null }
    env_file = Join-Path $runtime "mineru-tool.env.ps1"
    logs = @{
        api_out = Join-Path $runtime "mineru-api-$ApiPort.out.log"
        api_err = Join-Path $runtime "mineru-api-$ApiPort.err.log"
        web_out = Join-Path $runtime "mineru-gradio-$WebUIPort.out.log"
        web_err = Join-Path $runtime "mineru-gradio-$WebUIPort.err.log"
    }
} | ConvertTo-Json -Depth 6
