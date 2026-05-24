param(
    [string]$Port = $env:KB_WEB_PORT
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Port)) {
    $Port = "8088"
}

if ([string]::IsNullOrWhiteSpace($env:KB_AUTH_TOKEN)) {
    Write-Host "KB_AUTH_TOKEN is empty. Production compose will fail closed for protected APIs."
    Write-Host "Set it first, for example: `$env:KB_AUTH_TOKEN='change-me-long-random-token'"
}

$env:KB_WEB_PORT = $Port
docker compose -f docker-compose.app.yml up --build -d
Write-Host "Procedure KB app requested at http://127.0.0.1:$Port"
