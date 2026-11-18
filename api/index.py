import logging
import os
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, APIRouter, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from .resolvers.filepress import resolve_filepress
from .resolvers.hubcloud import resolve_hubcloud
from .resolvers.gdflix import resolve_gdflix
from .resolvers.gofile import resolve_gofile
from .resolvers.multicloud import resolve_multicloud
from .resolvers.gdxfiles import resolve_gdxfiles
from .resolvers.driveseed import resolve_driveseed
from .resolvers.vcloud import resolve_vcloud
from .resolvers.ouo import resolve_ouo_async, resolve_ouo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rdx-bypass")

app = FastAPI(
    title="RDX Multi-Bypass API",
    description="High-Speed Direct Download Link Resolver API for Filepress, HubCloud, GDFlix, GoFile, MultiCloud, GDXFiles, DriveSeed, HubDrive, V-Cloud & Ouo",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UrlPayload(BaseModel):
    url: str
    cookie: Optional[str] = ""
    password: Optional[str] = ""
    dl: Optional[bool] = False

async def _auto_route(url: str, cookie: str = "", password: str = "") -> dict:
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    if any(k in host for k in ("ouo.io", "ouo.press", "ouo.today", "ouo.site")):
        return await resolve_ouo_async(url)
    elif any(k in host for k in ("filepress", "filebee")):
        return resolve_filepress(url, cookie=cookie)
    elif any(k in host for k in ("hubcloud", "gamerxyt")) or "hubcloud.php" in url:
        return resolve_hubcloud(url)
    elif "gdflix" in host:
        return resolve_gdflix(url)
    elif "gofile.io" in host:
        return resolve_gofile(url, password=password)
    elif any(k in host for k in ("multicloudlinks", "savelinks", "multidownload")):
        return resolve_multicloud(url)
    elif "gdxfiles" in host:
        return resolve_gdxfiles(url)
    elif "driveseed" in host:
        return resolve_driveseed(url)
    elif any(k in host for k in ("hubdrive", "hblinks", "drivehub")):
        return resolve_driveseed(url)
    elif any(k in host for k in ("vcloud", "v-cloud", "fastdl.beer")):
        return resolve_vcloud(url)
    else:
        if "/file/" in path:
            return resolve_filepress(url, cookie=cookie)
        return resolve_hubcloud(url)

router = APIRouter()

@router.get("/")
def root():
    return {
        "name": "RDX Multi-Bypass API",
        "version": "2.1.0",
        "status": "online",
        "endpoints": {
            "auto_bypass": "/bypass?url=<link> (GET/POST)",
            "filepress": "/filepress?url=<link> (GET/POST)",
            "ouo": "/ouo?url=<link> (GET/POST)",
            "hubcloud": "/hubcloud?url=<link> (GET/POST)",
            "gdflix": "/gdflix?url=<link> (GET/POST)",
            "gofile": "/gofile?url=<link> (GET/POST)",
            "multicloud": "/multicloud?url=<link> (GET/POST)",
            "gdxfiles": "/gdxfiles?url=<link> (GET/POST)",
            "driveseed": "/driveseed?url=<link> (GET/POST)",
            "hubdrive": "/hubdrive?url=<link> (GET/POST)",
            "vcloud": "/vcloud?url=<link> (GET/POST)",
            "health": "/health",
        },
        "params": {
            "url": "Target URL to resolve (required)",
            "dl": "If true, redirects directly (302) to the resolved download link (optional)",
            "cookie": "Optional login cookie (e.g. for Filepress)",
            "password": "Optional password (e.g. for GoFile)",
        },
    }

@router.get("/health")
def health():
    return {"status": "ok", "service": "RDX Multi-Bypass API"}

@router.get("/bypass")
async def bypass_get(url: str = Query(..., description="Target file URL"), dl: bool = False, cookie: str = "", password: str = ""):
    try:
        res = await _auto_route(url, cookie=cookie, password=password)
        if dl and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        logger.warning("Bypass failed for %s: %s", url, e)
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.post("/bypass")
async def bypass_post(payload: UrlPayload):
    try:
        res = await _auto_route(payload.url, cookie=payload.cookie or "", password=payload.password or "")
        if payload.dl and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        logger.warning("Bypass failed for %s: %s", payload.url, e)
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/ouo")
@router.post("/ouo")
async def endpoint_ouo(url: str = "", dl: bool = False, payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = await resolve_ouo_async(target)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/filepress")
@router.post("/filepress")
def endpoint_filepress(url: str = "", dl: bool = False, cookie: str = "", payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    ck = (payload.cookie if payload else "") or cookie
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_filepress(target, cookie=ck)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/hubcloud")
@router.post("/hubcloud")
def endpoint_hubcloud(url: str = "", dl: bool = False, payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_hubcloud(target)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/gdflix")
@router.post("/gdflix")
def endpoint_gdflix(url: str = "", dl: bool = False, payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_gdflix(target)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/gofile")
@router.post("/gofile")
def endpoint_gofile(url: str = "", dl: bool = False, password: str = "", payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    pwd = (payload.password if payload else "") or password
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_gofile(target, password=pwd)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/multicloud")
@router.post("/multicloud")
def endpoint_multicloud(url: str = "", dl: bool = False, payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_multicloud(target)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/gdxfiles")
@router.post("/gdxfiles")
def endpoint_gdxfiles(url: str = "", dl: bool = False, payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_gdxfiles(target)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/driveseed")
@router.post("/driveseed")
def endpoint_driveseed(url: str = "", dl: bool = False, payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_driveseed(target)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/hubdrive")
@router.post("/hubdrive")
def endpoint_hubdrive(url: str = "", dl: bool = False, payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_driveseed(target)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@router.get("/vcloud")
@router.post("/vcloud")
def endpoint_vcloud(url: str = "", dl: bool = False, payload: Optional[UrlPayload] = None):
    target = payload.url if payload else url
    if not target:
        raise HTTPException(status_code=400, detail="Missing required 'url' parameter")
    try:
        res = resolve_vcloud(target)
        if (payload.dl if payload else dl) and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

# Register router at root / and prefix /api
app.include_router(router)
app.include_router(router, prefix="/api")

# Catch-all fallback so no request path ever gets 404
@app.api_route("/{full_path:path}", methods=["GET", "POST"])
async def catch_all_fallback(full_path: str, request: Request):
    cleaned = full_path.strip("/")
    for prefix in ("api/index.py", "index.py", "api"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip("/")

    if not cleaned or cleaned == "":
        return root()
    elif cleaned == "health":
        return health()

    url = request.query_params.get("url", "")
    dl = request.query_params.get("dl", "").lower() in ("true", "1")
    cookie = request.query_params.get("cookie", "")
    password = request.query_params.get("password", "")

    if not url:
        return root()

    try:
        if cleaned in ("ouo", "ouo.io", "ouo.press"):
            res = await resolve_ouo_async(url)
        elif cleaned == "filepress":
            res = resolve_filepress(url, cookie=cookie)
        elif cleaned == "hubcloud":
            res = resolve_hubcloud(url)
        elif cleaned == "gdflix":
            res = resolve_gdflix(url)
        elif cleaned == "gofile":
            res = resolve_gofile(url, password=password)
        elif cleaned == "multicloud":
            res = resolve_multicloud(url)
        elif cleaned == "gdxfiles":
            res = resolve_gdxfiles(url)
        elif cleaned in ("driveseed", "hubdrive"):
            res = resolve_driveseed(url)
        elif cleaned == "vcloud":
            res = resolve_vcloud(url)
        else:
            res = await _auto_route(url, cookie=cookie, password=password)

        if dl and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
