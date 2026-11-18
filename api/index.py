import logging
import os
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rdx-bypass")

app = FastAPI(
    title="RDX Multi-Bypass API",
    description="High-Speed Direct Download Link Resolver for Filepress, HubCloud, GDFlix, GoFile, MultiCloud, GDXFiles, DriveSeed, HubDrive & V-Cloud",
    version="2.0.0",
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

def _auto_route(url: str, cookie: str = "", password: str = "") -> dict:
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    if any(k in host for k in ("filepress", "filebee")):
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
    elif "vcloud" in host or "v-cloud" in host:
        return resolve_vcloud(url)
    else:
        # Default try hubcloud or filepress
        if "/file/" in path:
            return resolve_filepress(url, cookie=cookie)
        return resolve_hubcloud(url)

@app.get("/")
def root():
    return {
        "name": "RDX Multi-Bypass API",
        "version": "2.0.0",
        "status": "online",
        "endpoints": {
            "auto_bypass": "/bypass?url=<link> (GET/POST)",
            "filepress": "/filepress?url=<link> (GET/POST)",
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

@app.get("/health")
def health():
    return {"status": "ok", "service": "RDX Multi-Bypass API"}

@app.get("/bypass")
def bypass_get(url: str = Query(..., description="Target file URL"), dl: bool = False, cookie: str = "", password: str = ""):
    try:
        res = _auto_route(url, cookie=cookie, password=password)
        if dl and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        logger.warning("Bypass failed for %s: %s", url, e)
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

@app.post("/bypass")
def bypass_post(payload: UrlPayload):
    try:
        res = _auto_route(payload.url, cookie=payload.cookie or "", password=payload.password or "")
        if payload.dl and res.get("url"):
            return RedirectResponse(url=res["url"], status_code=302)
        return res
    except Exception as e:
        logger.warning("Bypass failed for %s: %s", payload.url, e)
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

# Dedicated Endpoints
@app.get("/filepress")
@app.post("/filepress")
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

@app.get("/hubcloud")
@app.post("/hubcloud")
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

@app.get("/gdflix")
@app.post("/gdflix")
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

@app.get("/gofile")
@app.post("/gofile")
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

@app.get("/multicloud")
@app.post("/multicloud")
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

@app.get("/gdxfiles")
@app.post("/gdxfiles")
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

@app.get("/driveseed")
@app.post("/driveseed")
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

@app.get("/hubdrive")
@app.post("/hubdrive")
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

@app.get("/vcloud")
@app.post("/vcloud")
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
