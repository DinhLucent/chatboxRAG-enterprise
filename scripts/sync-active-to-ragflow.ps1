param(
    [string]$BaseUrl = $env:RAGFLOW_BASE_URL,
    [string]$ApiKey = $env:RAGFLOW_API_KEY,
    [string]$DatasetId = $env:RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID,
    [switch]$DeleteAll,
    [switch]$NoParse
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    throw "Missing BaseUrl. Pass -BaseUrl or set RAGFLOW_BASE_URL."
}
if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    throw "Missing ApiKey. Pass -ApiKey or set RAGFLOW_API_KEY."
}
if ([string]::IsNullOrWhiteSpace($DatasetId)) {
    throw "Missing DatasetId. Pass -DatasetId or set RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID."
}

$argsList = @(
    "-m", "poc_workflow",
    "sync-ragflow",
    "--base-url", $BaseUrl,
    "--api-key", $ApiKey,
    "--dataset-id", $DatasetId
)

if ($DeleteAll) {
    $argsList += "--delete-all"
}
if ($NoParse) {
    $argsList += "--no-parse"
}

python @argsList
