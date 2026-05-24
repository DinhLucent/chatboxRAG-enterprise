param(
    [string]$HostName = $env:KB_WEB_HOST,
    [string]$Port = $env:KB_WEB_PORT,
    [string]$FreeLLMApiUrl = $env:FREELLMAPI_URL
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($HostName)) {
    $HostName = "127.0.0.1"
}
if ([string]::IsNullOrWhiteSpace($Port)) {
    $Port = "8088"
}
if ([string]::IsNullOrWhiteSpace($FreeLLMApiUrl)) {
    $FreeLLMApiUrl = "http://127.0.0.1:3001"
}

$env:KB_WEB_HOST = $HostName
$env:KB_WEB_PORT = $Port

if (
    [string]::IsNullOrWhiteSpace($env:POC_LLM_API_KEY) -and
    [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)
) {
    try {
        $freeKey = (Invoke-RestMethod -Uri "$FreeLLMApiUrl/api/settings/api-key" -TimeoutSec 3).apiKey
        if (-not [string]::IsNullOrWhiteSpace($freeKey)) {
            $env:POC_LLM_BASE_URL = "$FreeLLMApiUrl/v1"
            $env:POC_LLM_API_KEY = $freeKey
            if ([string]::IsNullOrWhiteSpace($env:POC_LLM_MODEL)) {
                $env:POC_LLM_MODEL = "auto"
            }
        }
    } catch {
        Write-Warning "FreeLLMAPI is not reachable at $FreeLLMApiUrl. The app will start without LLM runtime."
    }
}

python -m poc_workflow.webapp
