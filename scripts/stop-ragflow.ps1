$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ragflowDocker = Join-Path $repoRoot "refs\ragflow\docker"

Push-Location $ragflowDocker
try {
    docker compose down
}
finally {
    Pop-Location
}
