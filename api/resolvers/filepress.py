import os
import re
import base64
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

def _extract_gdrive_id(val) -> str | None:
    if not val:
        return None
    if isinstance(val, list):
        for item in val:
            gid = _extract_gdrive_id(item)
            if gid:
                return gid
        return None
    if not isinstance(val, str):
        return None
    val = val.strip()

    # 1. Direct Google Drive URL
    m = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([a-zA-Z0-9_-]{20,50})", val)
    if m:
        return m.group(1)

    # 2. Flapdooodle or Index URL containing base64 token in path (/download/<token>/...)
    m = re.search(r"/download/([a-zA-Z0-9+/=_-]+)", val)
    token = m.group(1) if m else val
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        parts = decoded.split("@")
        if parts and re.match(r"^[a-zA-Z0-9_-]{20,50}$", parts[0]):
            return parts[0]
    except Exception:
        pass

    # 3. Raw Google Drive ID (standard 33-char or 25-50 char, but NOT a 24-char hex MongoDB ObjectId)
    if re.match(r"^[a-zA-Z0-9_-]{25,50}$", val) and not re.match(r"^[a-fA-F0-9]{24}$", val):
        return val

    return None

def _first_url(val):
    if isinstance(val, list):
        for v in val:
            if isinstance(v, str) and v.startswith("http"):
                return v
    if isinstance(val, str) and val.startswith("http"):
        return val
    return None

def resolve_filepress(url: str, cookie: str = "") -> dict:
    """Resolve Filepress / Filebee link directly into Google Drive download link without requiring cookies."""
    raw = urlparse(url)
    file_id = raw.path.strip("/").split("/")[-1].split("?")[0].split("#")[0]
    if not file_id:
        raise ValueError("Invalid Filepress URL: could not extract file ID")

    effective_cookie = _normalize_cookie(cookie) or _normalize_cookie(os.environ.get("FILEPRESS_COOKIE", ""))

    origin = f"{raw.scheme}://{raw.netloc}" if raw.netloc else "https://new4.filepress.lat"
    bases = ["https://new4.filepress.lat"]
    if origin not in bases:
        bases.insert(0, origin)
    for b in FILEPRESS_BASES:
        if b not in bases:
            bases.append(b)

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

    gdrive_link = None
    index_link = None
    streamtape_raw = None

    # Priority of methods to obtain Google Drive link without requiring cookies:
    # 1. publicDownlaod (guest direct Google Drive download)
    # 2. indexDownlaod (index download containing embedded base64 Google Drive file ID)
    # 3. publicUserDownlaod (authenticated user Google Drive download, if cookie is provided)
    methods = ["publicDownlaod", "indexDownlaod"]
    if effective_cookie:
        methods.insert(0, "publicUserDownlaod")

    for base in bases:
        api1 = f"{base}/api/file/downlaod/"
        api2 = f"{base}/api/file/downlaod2/"
        for method in methods:
            j_gd = _post(api1, {"id": file_id, "method": method}, timeout=12)
            if j_gd and j_gd.get("status") and j_gd.get("data"):
                tok = j_gd["data"]
                gid = _extract_gdrive_id(tok)
                if gid:
                    gdrive_link = f"https://drive.google.com/uc?id={gid}&export=download"
                    break
                # Step 2: MongoDB ObjectId -> Direct Google Drive ID or Flapdooodle Index URL
                first_tok = tok[0] if isinstance(tok, list) and tok else tok
                if isinstance(first_tok, str):
                    j_gd2 = _post(api2, {"id": first_tok, "method": method}, timeout=10)
                    if j_gd2 and j_gd2.get("status") and j_gd2.get("data"):
                        tok2 = j_gd2["data"]
                        gid2 = _extract_gdrive_id(tok2)
                        if gid2:
                            gdrive_link = f"https://drive.google.com/uc?id={gid2}&export=download"
                            break
                        if method == "indexDownlaod":
                            idx_u = _first_url(tok2)
                            if idx_u:
                                index_link = idx_u
            if gdrive_link:
                break
        if gdrive_link:
            break

    # If Google Drive link wasn't resolved, attempt StreamTape mirror as fallback
    if not gdrive_link:
        for base in bases:
            j_st = _post(f"{base}/api/file/downlaod/", {"id": file_id, "method": "streamTapeDownload"}, timeout=8)
            if j_st and j_st.get("status") and j_st.get("data"):
                st_val = _first_url(j_st["data"]) or (j_st["data"] if isinstance(j_st["data"], str) and j_st["data"].startswith("http") else None)
                if st_val:
                    streamtape_raw = st_val
                    break

    links = {}
    if gdrive_link:
        links["GoogleDrive"] = gdrive_link
    if index_link:
        links["Index"] = index_link
        links["Direct"] = index_link
    if streamtape_raw:
        links["StreamTape"] = streamtape_raw

    primary = gdrive_link or index_link or streamtape_raw
    if not primary:
        if last_err_code == "FILE_NOT_FOUND":
            raise ValueError("Filepress error: File not found or deleted on Filepress (FILE_NOT_FOUND)")
        err_msg = last_err_msg or last_err_code or "Failed to generate download link from Filepress"
        raise ValueError(f"Filepress error: {err_msg}")

    return {
        "success": True,
        "url": primary,
        "direct_url": gdrive_link or primary,
        "gdrive_url": gdrive_link,
        "file_id": file_id,
        "links": links,
    }
