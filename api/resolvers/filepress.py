import os
import re
import logging
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

def resolve_filepress(url: str, cookie: str = "") -> dict:
    """Resolve Filepress / Filebee link into direct download links."""
    raw = urlparse(url)
    file_id = raw.path.strip("/").split("/")[-1].split("?")[0].split("#")[0]
    if not file_id:
        raise ValueError("Invalid Filepress URL: could not extract file ID")

    # If cookie not passed, check environment variable FILEPRESS_COOKIE
    effective_cookie = _normalize_cookie(cookie) or _normalize_cookie(os.environ.get("FILEPRESS_COOKIE", ""))

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://new4.filepress.lat/file/{file_id}",
        "Origin": "https://new4.filepress.lat",
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
        # Fallback to requests
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

    index_link = None
    streamtape_link = None
    streamtape_raw = None
    alt_links = {}
    gdrive_link = None

    # 1. Index Download (Index step 1 + step 2)
    for base in FILEPRESS_BASES:
        api1 = f"{base}/api/file/downlaod/"
        api2 = f"{base}/api/file/downlaod2/"
        j1 = _post(api1, {"id": file_id, "method": "indexDownlaod"}, timeout=12)
        if j1 and j1.get("status") and j1.get("data"):
            token = j1["data"]
            direct = _first_url(token)
            if direct:
                index_link = direct
                break
            # Step 2
            j2 = _post(api2, {"id": token, "method": "indexDownlaod"}, timeout=12)
            if j2 and j2.get("status") and j2.get("data"):
                direct2 = _first_url(j2["data"])
                if direct2:
                    index_link = direct2
                    break
        if index_link:
            break

    # 2. StreamTape Download
    for base in FILEPRESS_BASES:
        api1 = f"{base}/api/file/downlaod/"
        j_st = _post(api1, {"id": file_id, "method": "streamTapeDownload"}, timeout=10)
        if j_st and j_st.get("status") and j_st.get("data"):
            st_val = _first_url(j_st["data"]) or (j_st["data"] if isinstance(j_st["data"], str) and j_st["data"].startswith("http") else None)
            if st_val:
                streamtape_raw = st_val
                try:
                    streamtape_link = resolve_streamtape(st_val, timeout=10)
                except Exception as err:
                    logger.debug("StreamTape extraction failed: %s", err)
                    streamtape_link = st_val
                break

    # 3. Alternative Mirrors (DoodStream / StreamWish)
    for method in ["doodStreamDownload", "streamWishDownload"]:
        for base in FILEPRESS_BASES:
            j_alt = _post(f"{base}/api/file/downlaod/", {"id": file_id, "method": method}, timeout=8)
            if j_alt and j_alt.get("status") and j_alt.get("data"):
                val = _first_url(j_alt["data"]) or (j_alt["data"] if isinstance(j_alt["data"], str) and j_alt["data"].startswith("http") else None)
                if val:
                    alt_links[method] = val
                    break

    # 4. Google Drive Download (requires cookie)
    if effective_cookie and not index_link and not streamtape_link:
        for base in FILEPRESS_BASES:
            api1 = f"{base}/api/file/downlaod/"
            api2 = f"{base}/api/file/downlaod2/"
            for method in ["publicUserDownlaod", "publicDownlaod"]:
                j_gd = _post(api1, {"id": file_id, "method": method}, timeout=12)
                if j_gd and j_gd.get("status") and j_gd.get("data"):
                    gd_val = _first_url(j_gd["data"])
                    if gd_val:
                        gdrive_link = gd_val
                        break
                    # 2-step MongoDB ID to Google Drive ID
                    tok = j_gd["data"]
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

    links = {}
    if index_link:
        links["Direct"] = index_link
        links["Index"] = index_link
    if streamtape_link:
        links["StreamTape_Direct"] = streamtape_link
    if streamtape_raw:
        links["StreamTape"] = streamtape_raw
    if gdrive_link:
        links["GoogleDrive"] = gdrive_link
    for k, v in alt_links.items():
        links[k] = v

    primary = index_link or streamtape_link or streamtape_raw or gdrive_link or next(iter(alt_links.values()), None)
    if not primary:
        if last_err_code == "FILE_NOT_FOUND":
            raise ValueError("Filepress error: File not found or deleted on Filepress (FILE_NOT_FOUND)")
        if last_err_code == "DRIVE_NOT_CONNECTED":
            raise ValueError("Filepress error: Google Drive is not connected to your Filepress account (DRIVE_NOT_CONNECTED)")
        if last_err_code == "LOGIN_REQUIRED":
            raise ValueError("Filepress error: Login cookie required for this file. Public mirrors (Index/StreamTape) are unavailable.")
        if last_err_code == "INDEX_CLONE_FAILED":
            if not effective_cookie:
                raise ValueError("Filepress error: Index mirror clone failed (INDEX_CLONE_FAILED). A Filepress login cookie is required to access Google Download.")
            else:
                raise ValueError(f"Filepress error: Index mirror failed and Google Download returned: {last_err_msg or last_err_code}")
        err_msg = last_err_msg or last_err_code or "No downloadable mirror returned by Filepress"
        raise ValueError(f"Filepress error: {err_msg}")

    return {
        "success": True,
        "url": primary,
        "direct_url": index_link or primary,
        "streamtape_url": streamtape_link or streamtape_raw,
        "gdrive_url": gdrive_link,
        "file_id": file_id,
        "links": links,
    }
