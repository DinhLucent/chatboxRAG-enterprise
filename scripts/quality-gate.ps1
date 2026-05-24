param(
    [ValidateSet("local", "production")]
    [string]$Mode = "local",

    [ValidateSet("local", "auto", "ragflow")]
    [string]$Provider = "local",

    [string]$Cases,

    [switch]$CheckNetwork,
    [switch]$KeepSandbox,
    [switch]$SkipPytest,
    [switch]$SkipEvaluation,

    [int]$LatencyTargetMs = 12000
)

$ErrorActionPreference = "Stop"

$argsList = @(
    "-m", "poc_workflow", "quality-gate",
    "--mode", $Mode,
    "--provider", $Provider,
    "--latency-target-ms", "$LatencyTargetMs"
)

if (-not [string]::IsNullOrWhiteSpace($Cases)) {
    $argsList += @("--cases", $Cases)
}
if ($CheckNetwork) {
    $argsList += "--check-network"
}
if ($KeepSandbox) {
    $argsList += "--keep-sandbox"
}
if ($SkipPytest) {
    $argsList += "--skip-pytest"
}
if ($SkipEvaluation) {
    $argsList += "--skip-evaluation"
}

python @argsList
exit $LASTEXITCODE
