import os
import re
import logging
from urllib.parse import urlparse
import requests

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

FILEPRESS_BASES = [
    "https://new4.filepress.lat",
    "https://filepress.lat",
    "https://filebee.xyz",
    "https://filepress.store",
]

def _normalize_cookie(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    if "connect.sid=" in raw:
        m = re.search(r"connect\.sid=[^\s;]+", raw)
        if m:
            return m.group(0)
    lines = raw.splitlines()
    clean_pairs = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            name, value = parts[5].strip(), parts[6].strip()
            if name == "connect.sid":
                return f"connect.sid={value}"
            clean_pairs.append(f"{name}={value}")
        elif line.startswith("connect.sid="):
            return line.rstrip(";")
        elif line.startswith("s%3A") or line.startswith("s:"):
            return f"connect.sid={line.rstrip(';')}"
    if clean_pairs:
        return "; ".join(clean_pairs)
    return raw

def resolve_filepress(url: str, cookie: str = "") -> dict:
    """Resolve Filepress / Filebee link directly into Google Drive download link."""
    raw = urlparse(url)
    file_id = raw.path.strip("/").split("/")[-1].split("?")[0].split("#")[0]
    if not file_id:
        raise ValueError("Invalid Filepress URL: could not extract file ID")

    effective_cookie = _normalize_cookie(cookie) or _normalize_cookie(os.environ.get("FILEPRESS_COOKIE", ""))

    origin = f"{raw.scheme}://{raw.netloc}" if raw.netloc else "https://new4.filepress.lat"
    bases = [origin] + [b for b in FILEPRESS_BASES if b != origin]

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"{origin}/file/{file_id}",
        "Origin": origin,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    if effective_cookie:
        headers["Cookie"] = effective_cookie

    try:
        from curl_cffi import requests as cf_requests
        use_cffi = True
    except ImportError:
        use_cffi = False

    last_err_code = None
    last_err_msg = None

    def _post(endpoint, payload, timeout=12):
        nonlocal last_err_code, last_err_msg
        if use_cffi:
            for imp in ("chrome120", "chrome"):
                try:
                    r = cf_requests.post(endpoint, headers=headers, json=payload, impersonate=imp, timeout=timeout, verify=False)
                    if r.text:
                        try:
                            j = r.json()
                            err = j.get("err")
                            if err:
                                last_err_code = err
                            msg = j.get("statusText") or j.get("error")
                            if msg:
                                last_err_msg = msg
                            return j
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug("curl_cffi POST %s failed: %s", endpoint, e)
        try:
            r = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if r.text:
                try:
                    j = r.json()
                    err = j.get("err")
                    if err:
                        last_err_code = err
                    msg = j.get("statusText") or j.get("error")
                    if msg:
                        last_err_msg = msg
                    return j
                except Exception:
                    pass
        except Exception as e:
            logger.debug("requests POST %s failed: %s", endpoint, e)
        return None

    def _first_url(val):
        if isinstance(val, list):
            for v in val:
                if isinstance(v, str) and v.startswith("http"):
                    return v
        if isinstance(val, str) and val.startswith("http"):
            return val
        return None

    gdrive_link = None
    methods = ["publicUserDownlaod", "publicDownlaod"] if effective_cookie else ["publicDownlaod", "publicUserDownlaod"]

    for base in bases:
        api1 = f"{base}/api/file/downlaod/"
        api2 = f"{base}/api/file/downlaod2/"
        for method in methods:
            j_gd = _post(api1, {"id": file_id, "method": method}, timeout=12)
            if j_gd and j_gd.get("status") and j_gd.get("data"):
                tok = j_gd["data"]
                val = _first_url(tok)
                if val:
                    gdrive_link = val
                    break
                # Step 2: MongoDB ObjectId to Google Drive ID
                j_gd2 = _post(api2, {"id": tok, "method": method}, timeout=10)
                if j_gd2 and j_gd2.get("status") and j_gd2.get("data"):
                    gd2_val = _first_url(j_gd2["data"]) or j_gd2["data"]
                    if isinstance(gd2_val, str) and gd2_val.startswith("http"):
                        gdrive_link = gd2_val
                        break
                    elif isinstance(gd2_val, str) and len(gd2_val) >= 20:
                        gdrive_link = f"https://drive.google.com/uc?id={gd2_val}&export=download"
                        break
            if gdrive_link:
                break
        if gdrive_link:
            break

    if not gdrive_link:
        if last_err_code == "FILE_NOT_FOUND":
            raise ValueError("Filepress error: File not found or deleted on Filepress (FILE_NOT_FOUND)")
        if last_err_code == "DRIVE_NOT_CONNECTED":
            raise ValueError("Filepress error: Google Drive is not connected to your Filepress account! (DRIVE_NOT_CONNECTED)")
        if last_err_code == "LOGIN_REQUIRED" or (not effective_cookie and last_err_code == "METHOD_NOT_FOUND"):
            raise ValueError("Filepress error: Login cookie required for this file! Upload your Filepress cookies as private file 'filepress.txt' (/bsetting -> Private Files) or set FILEPRESS_COOKIE.")
        err_msg = last_err_msg or last_err_code or "Failed to generate Google Drive link"
        raise ValueError(f"Filepress error: {err_msg}")

    return {
        "success": True,
        "url": gdrive_link,
        "direct_url": gdrive_link,
        "gdrive_url": gdrive_link,
        "file_id": file_id,
        "links": {
            "GoogleDrive": gdrive_link
        },
    }
