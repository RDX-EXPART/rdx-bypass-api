import re
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def resolve_gdxfiles(url: str, timeout: int = 15) -> dict:
    """Resolve GDXFiles link into direct download links."""
    m = re.search(r'/file/(?:(?:r2|gofile|pixeldrain|multiup)/)?([a-zA-Z0-9_-]+)', url)
    if not m:
        raise ValueError("Invalid GDXFiles URL: could not extract file ID")
    file_id = m.group(1)

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://gdxfiles.com/",
    }
    resp = requests.get(f"https://gdxfiles.com/file/{file_id}", headers=headers, timeout=timeout)
    resp.raise_for_status()
    html = resp.text

    links = {}

    # Check for direct pixeldrain
    pd_m = re.search(r'href=[\'"](https?://pixeldra(?:in)?[a-z.]*/[^\'"]+)[\'"]', html)
    if pd_m:
        links["Pixeldrain"] = pd_m.group(1)

    # Check for hash endpoints
    servers = ['pixeldrain', 'gofile', 'r2', 'multiup']
    for srv in servers:
        hm = re.search(rf'/file/{srv}/{file_id}\?hash=([a-f0-9]+)', html)
        if hm:
            sub_url = f"https://gdxfiles.com/file/{srv}/{file_id}?hash={hm.group(1)}"
            try:
                sub_r = requests.get(sub_url, headers=headers, timeout=6, allow_redirects=False)
                loc = sub_r.headers.get("Location") or sub_r.headers.get("location")
                if loc:
                    links[srv] = loc
            except Exception:
                links[srv] = sub_url

    if not links:
        # Search for any outgoing download URLs
        all_urls = re.findall(r'href=[\'"](https?://[^\s\'"]+)[\'"]', html)
        for u in all_urls:
            if any(k in u for k in ('pixeldrain', 'gofile.io', 'r2.cloudflarestorage', 'r2.dev')):
                links['Direct'] = u

    if not links:
        raise ValueError("Could not extract any download links from GDXFiles")

    primary = links.get("r2") or links.get("Pixeldrain") or links.get("gofile") or next(iter(links.values()))

    return {
        "success": True,
        "url": primary,
        "links": links
    }
