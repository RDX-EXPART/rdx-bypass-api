import os
import re
import base64
import logging
import urllib.request
from urllib.parse import urlparse
import requests
from .streamtape import resolve_streamtape

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

def _is_gdrive_public(gdrive_id: str, timeout: int = 4) -> bool:
    """Check if Google Drive export link is accessible without requiring 'Request Access'."""
    try:
        url = f"https://drive.google.com/uc?id={gdrive_id}&export=download"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if "accounts.google.com" in newurl or "ServiceLogin" in newurl:
                    return None
                return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)

        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=timeout) as resp:
            content = resp.read(2048).decode("utf-8", errors="ignore")
            final_url = resp.geturl()
            if "accounts.google.com" in final_url or "ServiceLogin" in final_url:
                return False
            if "Sign in" in content and "request-storage-access" in content:
                return False
            return True
    except urllib.error.HTTPError as e:
        if e.code in (302, 303) and ("accounts.google.com" in e.headers.get("Location", "") or "ServiceLogin" in e.headers.get("Location", "")):
            return False
        return False
    except Exception:
        return False

def _first_url(val):
    if isinstance(val, list):
        for v in val:
            if isinstance(v, str) and v.startswith("http"):
                return v
    if isinstance(val, str) and val.startswith("http"):
        return val
    return None

def resolve_filepress(url: str, cookie: str = "") -> dict:
    """Resolve Filepress / Filebee link into both Direct and Google Drive download links."""
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
    gdrive_public = False
    index_link = None
    streamtape_raw = None
    streamtape_direct = None

    # 1. Query publicDownlaod (guest direct Google Drive download)
    for base in bases:
        api1 = f"{base}/api/file/downlaod/"
        api2 = f"{base}/api/file/downlaod2/"
        j_gd = _post(api1, {"id": file_id, "method": "publicDownlaod"}, timeout=12)
        if j_gd and j_gd.get("status") and j_gd.get("data"):
            tok = j_gd["data"]
            gid = _extract_gdrive_id(tok)
            if gid:
                gdrive_link = f"https://drive.google.com/uc?id={gid}&export=download"
                gdrive_public = _is_gdrive_public(gid)
                break
            first_tok = tok[0] if isinstance(tok, list) and tok else tok
            if isinstance(first_tok, str):
                j_gd2 = _post(api2, {"id": first_tok, "method": "publicDownlaod"}, timeout=10)
                if j_gd2 and j_gd2.get("status") and j_gd2.get("data"):
                    gid2 = _extract_gdrive_id(j_gd2["data"])
                    if gid2:
                        gdrive_link = f"https://drive.google.com/uc?id={gid2}&export=download"
                        gdrive_public = _is_gdrive_public(gid2)
                        break
        if gdrive_link:
            break

    # 2. Query indexDownlaod (index direct mirror + fallback Google Drive ID)
    for base in bases:
        api1 = f"{base}/api/file/downlaod/"
        api2 = f"{base}/api/file/downlaod2/"
        j_idx = _post(api1, {"id": file_id, "method": "indexDownlaod"}, timeout=12)
        if j_idx and j_idx.get("status") and j_idx.get("data"):
            tok = j_idx["data"]
            first_tok = tok[0] if isinstance(tok, list) and tok else tok
            if isinstance(first_tok, str):
                j_idx2 = _post(api2, {"id": first_tok, "method": "indexDownlaod"}, timeout=10)
                if j_idx2 and j_idx2.get("status") and j_idx2.get("data"):
                    tok2 = j_idx2["data"]
                    u = _first_url(tok2)
                    if u:
                        index_link = u
                    if not gdrive_link:
                        gid = _extract_gdrive_id(tok2)
                        if gid:
                            gdrive_link = f"https://drive.google.com/uc?id={gid}&export=download"
                            gdrive_public = _is_gdrive_public(gid)
        if index_link:
            break

    # 3. Query StreamTape download mirror
    for base in bases:
        api1 = f"{base}/api/file/downlaod/"
        j_st = _post(api1, {"id": file_id, "method": "streamTapeDownload"}, timeout=8)
        if j_st and j_st.get("status") and j_st.get("data"):
            st_val = _first_url(j_st["data"]) or (j_st["data"] if isinstance(j_st["data"], str) and j_st["data"].startswith("http") else None)
            if st_val:
                streamtape_raw = st_val
                try:
                    streamtape_direct = resolve_streamtape(st_val, timeout=8)
                except Exception as err:
                    logger.debug("StreamTape extraction failed: %s", err)
                break

    # 4. If cookie provided and still no gdrive_link, try publicUserDownlaod
    if effective_cookie and not gdrive_link:
        for base in bases:
            api1 = f"{base}/api/file/downlaod/"
            api2 = f"{base}/api/file/downlaod2/"
            j_u = _post(api1, {"id": file_id, "method": "publicUserDownlaod"}, timeout=12)
            if j_u and j_u.get("status") and j_u.get("data"):
                tok = j_u["data"]
                first_tok = tok[0] if isinstance(tok, list) and tok else tok
                if isinstance(first_tok, str):
                    j_u2 = _post(api2, {"id": first_tok, "method": "publicUserDownlaod"}, timeout=10)
                    if j_u2 and j_u2.get("status") and j_u2.get("data"):
                        gid = _extract_gdrive_id(j_u2["data"])
                        if gid:
                            gdrive_link = f"https://drive.google.com/uc?id={gid}&export=download"
                            gdrive_public = _is_gdrive_public(gid)
                            break
            if gdrive_link:
                break

    # Build links dictionary
    links = {}
    valid_index = index_link if index_link and "404page" not in index_link.lower() else None

    # Determine Direct Link
    direct_link = valid_index or streamtape_direct or streamtape_raw
    if not direct_link and gdrive_link and gdrive_public:
        direct_link = gdrive_link

    if direct_link:
        links["Direct"] = direct_link
    if gdrive_link:
        links["GoogleDrive"] = gdrive_link
    if valid_index:
        links["Index"] = valid_index
    elif index_link:
        links["Index_Mirror"] = index_link
    if streamtape_raw:
        links["StreamTape"] = streamtape_raw
    if streamtape_direct:
        links["StreamTape_Direct"] = streamtape_direct

    # Primary URL:
    # If Google Drive is verified public, prefer Google Drive; otherwise prefer Direct/StreamTape link
    primary = (gdrive_link if gdrive_link and gdrive_public else None) or direct_link or gdrive_link or streamtape_raw

    if not primary:
        if last_err_code == "FILE_NOT_FOUND":
            raise ValueError("Filepress error: File not found or deleted on Filepress (FILE_NOT_FOUND)")
        err_msg = last_err_msg or last_err_code or "Failed to generate download link from Filepress"
        raise ValueError(f"Filepress error: {err_msg}")

    return {
        "success": True,
        "url": primary,
        "direct_url": direct_link or primary,
        "gdrive_url": gdrive_link,
        "streamtape_url": streamtape_raw,
        "file_id": file_id,
        "links": links,
    }
