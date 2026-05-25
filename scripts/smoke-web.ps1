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
    query = "Quy trinh lap dat gom nhung buoc nao?"
    provider = $Provider
}
Assert-Smoke -Condition (@($chat.citations).Count -gt 0) -Message "known chat question returned no citations"
Assert-Smoke -Condition (@($chat.citations | Where-Object { $_.doc_id -eq "KT-QT-426" -or $_.display_code -eq "PD-TECH-A-01" }).Count -gt 0) -Message "known chat question did not cite scoped installation procedure"
Assert-Smoke -Condition (-not [string]::IsNullOrWhiteSpace([string]$chat.answer)) -Message "chat answer is empty"

$firstCitation = @($chat.citations)[0]
Assert-Smoke -Condition (-not [string]::IsNullOrWhiteSpace([string]$firstCitation.anchor_id)) -Message "known chat citation did not include anchor_id"
Assert-Smoke -Condition ([int]$firstCitation.line_start -ge 1 -and [int]$firstCitation.line_end -ge [int]$firstCitation.line_start) -Message "known chat citation did not include valid line bounds"

$citationDocId = [uri]::EscapeDataString([string]$firstCitation.doc_id)
$citationVersion = [uri]::EscapeDataString([string]$firstCitation.version)
$citationAnchor = [uri]::EscapeDataString([string]$firstCitation.anchor_id)
$citationDetail = Invoke-KbApi -Path "/api/documents/$citationDocId/$citationVersion/citation/$citationAnchor"
Assert-Smoke -Condition ($citationDetail.citation.anchor_id -eq $firstCitation.anchor_id) -Message "citation endpoint did not resolve requested anchor"
Assert-Smoke -Condition (@($citationDetail.citation_preview.lines | Where-Object { $_.highlight -eq $true }).Count -gt 0) -Message "citation endpoint did not return highlighted Markdown preview"

$publicChat = Invoke-KbApi -Path "/api/user/chat" -Method Post -Public -Body @{
    query = "Quy trinh lap dat gom nhung buoc nao?"
    answer_style = "steps"
    session_id = "smoke-citation-viewer"
    use_llm = $false
}
Assert-Smoke -Condition (@($publicChat.citations).Count -gt 0) -Message "public chat returned no citations"
$publicCitation = @($publicChat.citations)[0]
Assert-Smoke -Condition (-not [string]::IsNullOrWhiteSpace([string]$publicCitation.anchor_id)) -Message "public citation did not include safe anchor_id"
$publicCitationJson = $publicChat.citations | ConvertTo-Json -Depth 8 -Compress
Assert-Smoke -Condition ($publicCitationJson -notmatch "source_path|normalized_path|score|chunk") -Message "public citation leaked internal locator fields"

$publicDocId = [uri]::EscapeDataString([string]$publicCitation.doc_id)
$publicVersion = [uri]::EscapeDataString([string]$publicCitation.version)
$publicAnchor = [uri]::EscapeDataString([string]$publicCitation.anchor_id)
$publicCitationDetail = Invoke-KbApi -Path "/api/user/documents/$publicDocId/$publicVersion/citation/$publicAnchor" -Public
$publicCitationDetailJson = $publicCitationDetail | ConvertTo-Json -Depth 10 -Compress
Assert-Smoke -Condition ($publicCitationDetailJson -notmatch "source_path|normalized_path|chunk_id|score") -Message "public citation endpoint leaked internal fields"
Assert-Smoke -Condition (@($publicCitationDetail.preview.lines | Where-Object { $_.highlight -eq $true }).Count -gt 0) -Message "public citation endpoint did not return highlighted Markdown preview"

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
    citation_anchor = $firstCitation.anchor_id
    public_citation_anchor = $publicCitation.anchor_id
    evaluation_pass = if ($SkipEvaluation) { $null } else { $evaluation.pass }
    readiness_ready = $readiness.ready
    llm_state = $llmStatus.state
} | ConvertTo-Json -Depth 5
