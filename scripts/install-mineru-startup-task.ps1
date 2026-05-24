param(
    [string]$TaskName = "DemoChatbot-MinerU-Tool",
    [int]$ApiPort = 8010,
    [int]$WebUIPort = 7860,
    [switch]$WithWebUI
)

$ErrorActionPreference = "Stop"

$script = (Resolve-Path (Join-Path $PSScriptRoot "start-mineru-tool.ps1")).Path
$args = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -ApiPort $ApiPort -Quiet"
if ($WithWebUI) {
    $args += " -WithWebUI -WebUIPort $WebUIPort"
}

$scheduledTaskCreated = $false
$scheduledTaskError = $null

try {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $args
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Force `
        -ErrorAction Stop | Out-Null
    $scheduledTaskCreated = $true
} catch {
    $scheduledTaskError = $_.Exception.Message
}

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "$TaskName.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = $args
$shortcut.WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$shortcut.WindowStyle = 7
$shortcut.Description = "Start MinerU tool API for demo chatbot"
$shortcut.Save()

[PSCustomObject]@{
    ok = $true
    task_name = $TaskName
    scheduled_task_created = $scheduledTaskCreated
    scheduled_task_error = $scheduledTaskError
    startup_shortcut = $shortcutPath
    starts_at = "Windows user logon"
    command = "powershell.exe $args"
} | ConvertTo-Json -Depth 4
