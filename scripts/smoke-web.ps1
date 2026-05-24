param(
    [string]$BaseUrl = "http://127.0.0.1:8088",
    [string]$Provider = "local",
    [string]$Token = $env:KB_AUTH_TOKEN
)

$ErrorActionPreference = "Stop"

$headers = @{}
if (-not [string]::IsNullOrWhiteSpace($Token)) {
    $headers["X-KB-Token"] = $Token
}

$health = Invoke-RestMethod -Uri "$BaseUrl/api/health" -Method Get -Headers $headers
$manifest = Invoke-RestMethod -Uri "$BaseUrl/api/manifest" -Method Get -Headers $headers
$chat = Invoke-RestMethod -Uri "$BaseUrl/api/chat" -Method Post -ContentType "application/json" -Headers $headers -Body (@{
    query = "Quy trinh xu ly su co ky thuat gom nhung buoc nao?"
    provider = $Provider
} | ConvertTo-Json)
$evaluation = Invoke-RestMethod -Uri "$BaseUrl/api/evaluate" -Method Post -ContentType "application/json" -Headers $headers -Body (@{
    provider = $Provider
    latency_target_ms = 12000
} | ConvertTo-Json)

[PSCustomObject]@{
    health = $health.workspace
    manifest_records = @($manifest).Count
    chat_provider = $chat.provider
    citation_count = @($chat.citations).Count
    evaluation_pass = $evaluation.pass
} | ConvertTo-Json -Depth 5
