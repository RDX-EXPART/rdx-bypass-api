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

def resolve_filepress(url: str, cookie: str = "") -> dict:
    """Resolve Filepress / Filebee link into direct download links."""
    raw = urlparse(url)
    file_id = raw.path.strip("/").split("/")[-1].split("?")[0].split("#")[0]
    if not file_id:
        raise ValueError("Invalid Filepress URL: could not extract file ID")

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://new4.filepress.lat/file/{file_id}",
        "Origin": "https://new4.filepress.lat",
        "Content-Type": "application/json",
    }
    if cookie:
        headers["Cookie"] = cookie

    def _post(endpoint, payload, timeout=12):
        try:
            r = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 200 and r.text:
                return r.json()
        except Exception as e:
            logger.debug("POST %s failed: %s", endpoint, e)
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

    links = {}
    if index_link:
        links["Direct"] = index_link
        links["Index"] = index_link
    if streamtape_link:
        links["StreamTape_Direct"] = streamtape_link
    if streamtape_raw:
        links["StreamTape"] = streamtape_raw
    for k, v in alt_links.items():
        links[k] = v

    primary = index_link or streamtape_link or streamtape_raw or next(iter(alt_links.values()), None)
    if not primary:
        raise ValueError("Could not extract any downloadable link from Filepress")

    return {
        "success": True,
        "url": primary,
        "direct_url": index_link or primary,
        "streamtape_url": streamtape_link or streamtape_raw,
        "file_id": file_id,
        "links": links,
    }
