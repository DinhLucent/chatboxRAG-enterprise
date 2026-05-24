param(
    [string]$OutputDir = "backups"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "."
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $root $OutputDir
$backupPath = Join-Path $backupDir "procedure-kb-$timestamp.zip"

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$paths = @(
    "source",
    "manifest",
    "normalized",
    "eval",
    "data",
    ".env.production.example",
    ".env.example"
) | Where-Object { Test-Path (Join-Path $root $_) }

if (-not $paths) {
    throw "No workspace paths found to back up."
}

$tempDir = Join-Path $env:TEMP "procedure-kb-backup-$timestamp"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

try {
    foreach ($path in $paths) {
        $source = Join-Path $root $path
        $target = Join-Path $tempDir $path
        if (Test-Path $source -PathType Container) {
            Copy-Item -Path $source -Destination $target -Recurse -Force
        } else {
            $parent = Split-Path $target -Parent
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
            Copy-Item -Path $source -Destination $target -Force
        }
    }
    Compress-Archive -Path (Join-Path $tempDir "*") -DestinationPath $backupPath -Force
    Write-Host $backupPath
} finally {
    if (Test-Path $tempDir) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
}
