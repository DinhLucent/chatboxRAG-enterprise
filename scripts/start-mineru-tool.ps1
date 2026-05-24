param(
    [string]$MinerURoot = "C:\Users\ADMIN\Documents\pdftomm\MinerU",
    [string]$HostName = "127.0.0.1",
    [int]$ApiPort = 8010,
    [switch]$WithWebUI,
    [int]$WebUIPort = 7860,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtime = Join-Path $workspace ".runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

$mineruApi = (Get-Command "mineru-api.exe" -ErrorAction SilentlyContinue).Source
$mineruGradio = (Get-Command "mineru-gradio.exe" -ErrorAction SilentlyContinue).Source

if ([string]::IsNullOrWhiteSpace($mineruApi)) {
    $mineruApi = Join-Path $MinerURoot ".venv\Scripts\mineru-api.exe"
}
if ([string]::IsNullOrWhiteSpace($mineruGradio)) {
    $mineruGradio = Join-Path $MinerURoot ".venv\Scripts\mineru-gradio.exe"
}
if (-not (Test-Path $MinerURoot)) {
    throw "MinerU root not found: $MinerURoot"
}
if (-not (Test-Path $mineruApi)) {
    throw "mineru-api.exe not found. Checked PATH and $mineruApi"
}

function Test-ListeningPort {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Start-HiddenTool {
    param(
        [string]$Name,
        [string]$Exe,
        [string]$Arguments,
        [string]$OutLog,
        [string]$ErrLog,
        [string]$PidFile
    )

    Set-Content -Path $OutLog -Value "" -Encoding UTF8
    Set-Content -Path $ErrLog -Value "" -Encoding UTF8
    $cmd = @"
Set-Location -LiteralPath '$MinerURoot'
`$env:MINERU_MODEL_SOURCE='local'
`$env:MINERU_DEVICE_MODE='cpu'
`$env:GRADIO_ANALYTICS_ENABLED='False'
& '$Exe' $Arguments
"@
    $proc = Start-Process -FilePath powershell.exe `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd)
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII
    return $proc.Id
}

$apiUrl = "http://${HostName}:${ApiPort}"
$apiAlreadyRunning = Test-ListeningPort -Port $ApiPort
$apiPid = $null
if (-not $apiAlreadyRunning) {
    $apiPid = Start-HiddenTool `
        -Name "mineru-api" `
        -Exe $mineruApi `
        -Arguments "--host $HostName --port $ApiPort" `
        -OutLog (Join-Path $runtime "mineru-api-$ApiPort.out.log") `
        -ErrLog (Join-Path $runtime "mineru-api-$ApiPort.err.log") `
        -PidFile (Join-Path $runtime "mineru-api-$ApiPort.pid")

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-ListeningPort -Port $ApiPort) {
            break
        }
    }
}

$webUrl = "http://${HostName}:${WebUIPort}"
$webAlreadyRunning = Test-ListeningPort -Port $WebUIPort
$webPid = $null
if ($WithWebUI -and -not $webAlreadyRunning) {
    if (-not (Test-Path $mineruGradio)) {
        throw "mineru-gradio.exe not found. Checked PATH and $mineruGradio"
    }
    $webPid = Start-HiddenTool `
        -Name "mineru-gradio" `
        -Exe $mineruGradio `
        -Arguments "--server-name $HostName --server-port $WebUIPort --api-url $apiUrl --max-convert-pages 300" `
        -OutLog (Join-Path $runtime "mineru-gradio-$WebUIPort.out.log") `
        -ErrLog (Join-Path $runtime "mineru-gradio-$WebUIPort.err.log") `
        -PidFile (Join-Path $runtime "mineru-gradio-$WebUIPort.pid")
}

$envFile = Join-Path $runtime "mineru-tool.env.ps1"
Set-Content -Path $envFile -Encoding UTF8 -Value @(
    "`$env:MINERU_EXECUTABLE='mineru'"
    "`$env:MINERU_API_URL='$apiUrl'"
    "`$env:MINERU_METHOD='auto'"
    "`$env:MINERU_BACKEND='pipeline'"
    "`$env:MINERU_BACKEND_URL=''"
    "`$env:MINERU_FORMULA='true'"
    "`$env:MINERU_TABLE='true'"
    "`$env:MINERU_IMAGE_ANALYSIS='true'"
    "`$env:MINERU_MAX_PAGES='300'"
    "`$env:MINERU_TIMEOUT_SECONDS='1800'"
)

$result = [PSCustomObject]@{
    ok = (Test-ListeningPort -Port $ApiPort)
    api_url = $apiUrl
    api_port = $ApiPort
    api_started_pid = $apiPid
    api_already_running = $apiAlreadyRunning
    web_url = if ($WithWebUI -or $webAlreadyRunning) { $webUrl } else { $null }
    web_port = if ($WithWebUI -or $webAlreadyRunning) { $WebUIPort } else { $null }
    web_started_pid = $webPid
    web_already_running = $webAlreadyRunning
    env_file = $envFile
    mineru_root = $MinerURoot
}

if (-not $Quiet) {
    $result | ConvertTo-Json -Depth 4
}
