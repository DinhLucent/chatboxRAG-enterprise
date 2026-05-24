# MinerU Agent Tool

This tool wraps the existing local MinerU project at:

```text
C:\Users\ADMIN\Documents\pdftomm\MinerU
```

It provides a persistent hidden MinerU API service for AI agents and an optional WebUI for manual checks.

## Service URLs

```text
MinerU API:   http://127.0.0.1:8010
MinerU WebUI: http://127.0.0.1:7860
```

Port `8000` is intentionally avoided because another local application is already using it.

## Start

```powershell
.\scripts\start-mineru-tool.ps1
```

Start API plus WebUI:

```powershell
.\scripts\start-mineru-tool.ps1 -WithWebUI
```

## Status

```powershell
.\scripts\status-mineru-tool.ps1
```

## Stop

```powershell
.\scripts\stop-mineru-tool.ps1
```

## Auto Start On Windows Logon

```powershell
.\scripts\install-mineru-startup-task.ps1 -WithWebUI
```

The service runs hidden. It continues after the terminal window is closed. If Windows restarts, the scheduled task starts it again at user logon.

If Windows denies scheduled task creation, the installer creates a Startup shortcut instead:

```text
C:\Users\ADMIN\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\DemoChatbot-MinerU-Tool.lnk
```

## Agent Ingestion Flow

Agents should run:

```powershell
.\scripts\agent-ingest-inbox.ps1
```

That script:

1. Initializes the chatbot workspace.
2. Starts MinerU API on `http://127.0.0.1:8010` if needed.
3. Sets `MINERU_API_URL`.
4. Prepares inbox files.
5. Converts source files through MinerU.
6. Produces `pending_review` manifest records.

The agent should not manually edit `normalized/` unless it also updates `manifest/records.json`.
