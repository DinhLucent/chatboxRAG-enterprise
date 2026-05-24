param(
    [string]$AppRoot = "",
    [int]$Port = 3001,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($AppRoot)) {
    $AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\refs\freellmapi")).Path
} else {
    $AppRoot = (Resolve-Path $AppRoot).Path
}

$entry = Join-Path $AppRoot "server\dist\index.js"
if (-not (Test-Path -LiteralPath $entry)) {
    throw "FreeLLMAPI entrypoint not found: $entry. Build refs\freellmapi first."
}

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    $result = [PSCustomObject]@{
        ok = $true
        already_running = $true
        port = $Port
        pid = $existing.OwningProcess
        url = "http://127.0.0.1:$Port"
    }
    if (-not $Quiet) {
        $result | ConvertTo-Json -Depth 4
    }
    return
}

$runtime = Join-Path $AppRoot ".runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

$outLog = Join-Path $runtime "freellmapi.out.log"
$errLog = Join-Path $runtime "freellmapi.err.log"
$pidFile = Join-Path $runtime "freellmapi.pid"

$env:PORT = [string]$Port
$process = Start-Process `
    -FilePath "node" `
    -ArgumentList @("server/dist/index.js") `
    -WorkingDirectory $AppRoot `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

$deadline = (Get-Date).AddSeconds(20)
do {
    Start-Sleep -Milliseconds 500
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
} while (-not $listening -and (Get-Date) -lt $deadline)

$result = [PSCustomObject]@{
    ok = [bool]$listening
    already_running = $false
    port = $Port
    pid = $process.Id
    url = "http://127.0.0.1:$Port"
    stdout_log = $outLog
    stderr_log = $errLog
    pid_file = $pidFile
}

if (-not $Quiet) {
    $result | ConvertTo-Json -Depth 4
}
