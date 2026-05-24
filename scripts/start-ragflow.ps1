param(
    [ValidateSet("cpu", "gpu")]
    [string]$Device = "cpu",

    [ValidateSet("elasticsearch", "infinity", "oceanbase", "opensearch", "seekdb")]
    [string]$DocEngine = "elasticsearch"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ragflowDocker = Join-Path $repoRoot "refs\ragflow\docker"

if (-not (Test-Path (Join-Path $ragflowDocker "docker-compose.yml"))) {
    throw "RAGFlow docker-compose.yml not found under $ragflowDocker"
}

$env:DOC_ENGINE = $DocEngine
$env:DEVICE = $Device
$env:COMPOSE_PROFILES = "$DocEngine,$Device"

Push-Location $ragflowDocker
try {
    docker compose up -d
    Write-Host ""
    Write-Host "RAGFlow is starting."
    Write-Host "Web UI:      http://localhost:80"
    Write-Host "HTTP API:    http://localhost:9380"
    Write-Host "Admin API:   http://localhost:9381"
    Write-Host ""
    Write-Host "Check status with: .\scripts\status-ragflow.ps1"
}
finally {
    Pop-Location
}
