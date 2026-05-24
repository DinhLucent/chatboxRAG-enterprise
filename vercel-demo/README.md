# Vercel Demo Interface

This is a lightweight public demo UI for executives. It contains no core document processing or retrieval logic.

Flow:

```text
Browser
-> Vercel static UI
-> Vercel API proxy
-> secure tunnel to local computer
-> local chatbot backend
```

## Environment Variables

Set these in Vercel project settings:

```text
KB_BACKEND_BASE_URL=https://your-secure-tunnel-url
KB_BACKEND_TOKEN=your-local-backend-token
DEMO_ACCESS_TOKEN=short-demo-password-for-viewers
```

`KB_BACKEND_TOKEN` is the local chatbot token from `KB_AUTH_TOKEN`.

## Local Backend

Run the local backend with auth enabled:

```powershell
$env:KB_REQUIRE_AUTH="true"
$env:KB_AUTH_TOKEN="<long-random-token>"
.\scripts\start-app.ps1
```

Expose it through a tunnel such as Cloudflare Tunnel, ngrok, or Tailscale Funnel, then set `KB_BACKEND_BASE_URL` to that public HTTPS URL.

## Deploy

```powershell
cd vercel-demo
vercel
vercel --prod
```

