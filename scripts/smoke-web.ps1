param(
    [string]$BaseUrl = "http://127.0.0.1:8088",
    [string]$Provider = "local",
    [string]$Token = $env:KB_AUTH_TOKEN,
    [switch]$SkipEvaluation
)

$ErrorActionPreference = "Stop"

$headers = @{}
if (-not [string]::IsNullOrWhiteSpace($Token)) {
    $headers["X-KB-Token"] = $Token
}

function Invoke-KbApi {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateSet("Get", "Post")][string]$Method = "Get",
        [object]$Body = $null,
        [switch]$Public
    )

    $requestHeaders = if ($Public) { @{} } else { $headers }
    $uri = "$BaseUrl$Path"
    if ($null -eq $Body) {
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $requestHeaders
    }
    return Invoke-RestMethod -Uri $uri -Method $Method -ContentType "application/json" -Headers $requestHeaders -Body ($Body | ConvertTo-Json -Depth 8)
}

function Assert-Smoke {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw "Smoke check failed: $Message"
    }
}

$authStatus = Invoke-KbApi -Path "/api/auth-status" -Public
Assert-Smoke -Condition ($authStatus.required -ne $true -or -not [string]::IsNullOrWhiteSpace($Token)) -Message "operator auth is required but no token was provided"

$health = Invoke-KbApi -Path "/api/health"
$manifest = @()
foreach ($item in (Invoke-KbApi -Path "/api/manifest")) {
    $manifest += $item
}
$uploadQueue = Invoke-KbApi -Path "/api/upload-queue"
$readiness = Invoke-KbApi -Path "/api/readiness"
$llmStatus = Invoke-KbApi -Path "/api/llm/status?check_live=false"

Assert-Smoke -Condition ($null -ne $health.workspace) -Message "health did not return workspace"
Assert-Smoke -Condition ($manifest.Count -gt 0) -Message "manifest has no records"
Assert-Smoke -Condition ($null -ne $uploadQueue.summary) -Message "upload queue summary is missing"

$activeRecords = @()
foreach ($record in $manifest) {
    if ($record.status -eq "active") {
        $activeRecords += $record
    }
}
Assert-Smoke -Condition ($activeRecords.Count -gt 0) -Message "manifest has no active records"

$documentDetail = $null
$documentFailures = @()
foreach ($record in $activeRecords) {
    $docId = [uri]::EscapeDataString([string]$record.doc_id)
    $version = [uri]::EscapeDataString([string]$record.version)
    try {
        $candidate = Invoke-KbApi -Path "/api/documents/$docId/$version"
        if (
            $candidate.record.status -eq "active" -and
            $candidate.metadata_sidecar.exists -eq $true -and
            $candidate.markdown.exists -eq $true
        ) {
            $documentDetail = $candidate
            break
        }
        $documentFailures += "$($record.doc_id) v$($record.version): incomplete document detail"
    } catch {
        $documentFailures += "$($record.doc_id) v$($record.version): $($_.Exception.Message)"
    }
}

Assert-Smoke -Condition ($null -ne $documentDetail) -Message "no active record has readable document detail: $($documentFailures -join '; ')"

$chat = Invoke-KbApi -Path "/api/chat" -Method Post -Body @{
    query = "Quy trinh kiem soat tai lieu ho so quy dinh gi?"
    provider = $Provider
}
Assert-Smoke -Condition (@($chat.citations).Count -gt 0) -Message "known chat question returned no citations"
Assert-Smoke -Condition (@($chat.citations | Where-Object { $_.doc_id -eq "KT-QT-215" }).Count -gt 0) -Message "known chat question did not cite KT-QT-215"
Assert-Smoke -Condition (-not [string]::IsNullOrWhiteSpace([string]$chat.answer)) -Message "chat answer is empty"

$evaluation = $null
if (-not $SkipEvaluation) {
    $evaluation = Invoke-KbApi -Path "/api/evaluate" -Method Post -Body @{
        provider = $Provider
        latency_target_ms = 12000
    }
    Assert-Smoke -Condition ($evaluation.pass -eq $true) -Message "evaluation did not pass"
}

[PSCustomObject]@{
    status = "pass"
    base_url = $BaseUrl
    auth_required = $authStatus.required
    health_workspace = $health.workspace
    manifest_records = @($manifest).Count
    active_records = $activeRecords.Count
    upload_queue = $uploadQueue.summary
    document_detail = @{
        doc_id = $documentDetail.record.doc_id
        version = $documentDetail.record.version
        metadata_sidecar = $documentDetail.metadata_sidecar.exists
        markdown = $documentDetail.markdown.exists
        qa_report = $documentDetail.qa_report.exists
    }
    chat_provider = $chat.provider
    citation_count = @($chat.citations).Count
    evaluation_pass = if ($SkipEvaluation) { $null } else { $evaluation.pass }
    readiness_ready = $readiness.ready
    llm_state = $llmStatus.state
} | ConvertTo-Json -Depth 5
