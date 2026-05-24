# MinerU As A Background Agent Tool

MinerU is installed and usable on this machine.

```text
Project root: C:\Users\ADMIN\Documents\pdftomm\MinerU
Python env:   C:\Users\ADMIN\miniconda3\envs\prismaflex
CLI:          mineru
API:          mineru-api
WebUI:        mineru-gradio
Version:      3.1.15
```

## Runtime Decision

Use MinerU as a background API service for agents:

```text
AI agent / ingestion pipeline
-> http://127.0.0.1:8010
-> MinerU conversion
-> normalized Markdown
-> manifest pending_review
```

Keep the Gradio WebUI optional for manual visual checks:

```text
http://127.0.0.1:7860
```

Port `8000` is not used because another application is already listening there.

## Commands

Start API:

```powershell
.\scripts\start-mineru-tool.ps1
```

Start API and WebUI:

```powershell
.\scripts\start-mineru-tool.ps1 -WithWebUI
```

Check:

```powershell
.\scripts\status-mineru-tool.ps1
```

Stop:

```powershell
.\scripts\stop-mineru-tool.ps1
```

Install auto-start at Windows user logon:

```powershell
.\scripts\install-mineru-startup-task.ps1 -WithWebUI
```

On this machine, Windows blocked scheduled task registration without elevated permissions, so the installer also creates a user Startup shortcut:

```text
C:\Users\ADMIN\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\DemoChatbot-MinerU-Tool.lnk
```

This is enough for normal use: MinerU starts hidden after the ADMIN user logs into Windows.

## Agent Rule

Before converting non-Markdown documents, an agent should run:

```powershell
.\scripts\agent-ingest-inbox.ps1
```

This starts MinerU API if needed and sets:

```text
MINERU_API_URL=http://127.0.0.1:8010
```

The chatbot converter already reads `MINERU_API_URL`, so no code changes are needed for the normal ingestion path.
