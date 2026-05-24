param(
    [string]$HostName = $env:KB_WEB_HOST,
    [string]$Port = $env:KB_WEB_PORT
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($HostName)) {
    $HostName = "127.0.0.1"
}
if ([string]::IsNullOrWhiteSpace($Port)) {
    $Port = "8088"
}

$env:KB_WEB_HOST = $HostName
$env:KB_WEB_PORT = $Port

python -m poc_workflow.webapp
