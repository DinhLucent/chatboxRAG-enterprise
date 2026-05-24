param(
    [int]$Limit = 1,
    [ValidateSet("procedure", "vendor_document", "form_checklist", "faq_troubleshooting", "all")]
    [string]$Category = "procedure",
    [switch]$DryRun,
    [switch]$SkipMinerUStart,
    [int]$MinerUApiPort = 8010
)

$ErrorActionPreference = "Stop"

if ($Limit -lt 1 -or $Limit -gt 5) {
    throw "Limit must be between 1 and 5 for OCR-required processing batches."
}

python -m poc_workflow init

$mineruEnv = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\.runtime")).Path "mineru-tool.env.ps1"

if (-not $SkipMinerUStart) {
    & (Join-Path $PSScriptRoot "start-mineru-tool.ps1") -ApiPort $MinerUApiPort -Quiet
}

if (Test-Path $mineruEnv) {
    . $mineruEnv
}

$env:MINERU_METHOD = "ocr"
$env:MINERU_BACKEND = "pipeline"
$env:MINERU_FORMULA = "true"
$env:MINERU_TABLE = "true"
$env:MINERU_IMAGE_ANALYSIS = "true"
$env:MINERU_MAX_PAGES = "300"
$env:MINERU_TIMEOUT_SECONDS = "1800"

$categoryArg = if ($Category -eq "all") { "all" } else { $Category }
$processArgs = @("process-ocr-required", "--limit", "$Limit", "--category", $categoryArg)
if ($DryRun) {
    $processArgs += "--dry-run"
}

python -m poc_workflow @processArgs
python -m poc_workflow manifest
