# RDX Multi-Bypass API (Vercel & Heroku Ready)

High-Speed Direct Download Link Resolver API for Filepress, HubCloud, GDFlix, GoFile, MultiCloud, GDXFiles, DriveSeed, HubDrive, and V-Cloud.

Bypasses Cloudflare WAF and datacenter IP blocks by serving requests from clean edge serverless IPs.

---

## 🚀 1-Click Vercel Deploy

1. Go to [Vercel](https://vercel.com) and click **"Add New..."** -> **"Project"**.
2. Select your repository: **`RDX-EXPART/Rdx-Bypass`**.
3. Keep default settings (Framework: **Other**, Root Directory: `./`).
4. Click **Deploy**.
5. Your API will be live at: `https://<your-project-name>.vercel.app`

---

## 📡 Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/bypass?url=<link>` | GET / POST | Auto-routes by link domain (Filepress, Hubcloud, GDFlix, etc.) |
| `/filepress?url=<link>` | GET / POST | Resolves Filepress (Direct Index + StreamTape) |
| `/hubcloud?url=<link>` | GET / POST | Resolves Hubcloud (R2, FastDL, Pixeldrain, GoFile) |
| `/gdflix?url=<link>` | GET / POST | Resolves GDFlix (Direct Cloud, R2, FastDL) |
| `/gofile?url=<link>` | GET / POST | Resolves GoFile (`https://gofile.io/d/...`) |
| `/multicloud?url=<link>` | GET / POST | Resolves MultiCloudLinks |
| `/gdxfiles?url=<link>` | GET / POST | Resolves GDXFiles |
| `/driveseed?url=<link>` | GET / POST | Resolves DriveSeed & HubDrive |
| `/vcloud?url=<link>` | GET / POST | Resolves V-Cloud links (via FlareSolverr) |
| `/health` | GET | Health check (`{"status": "ok"}`) |

### Optional Query Parameters
- `dl=true` : Directly redirects (HTTP 302) to the resolved download link.
- `cookie=...` : Optional login cookie.
- `password=...` : Optional file password.

---

## 🤖 Connect with RDX Leech Bot

In your Heroku Leech Bot's **Config Vars** (or `config.env`), set:

```env
RDX_BYPASS_API = https://<your-project-name>.vercel.app
```

The bot will automatically route Filepress, Hubcloud, GDFlix, GoFile, and other links through your Vercel API!
