import re
import html as html_lib
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def resolve_multicloud(url: str, timeout: int = 15) -> dict:
    """Resolve multicloudlinks.com/view/<id> into direct download link."""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://savelinks.me/",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    html_text = resp.text

    links = {}

    # 1. Direct multidownload.click
    dl_m = (
        re.search(r'href=[\'"](https?://dr\d+\.multidownload\.click/d/[^\'"]+)[\'"]', html_text)
        or re.search(r'(https?://dr\d+\.multidownload\.click/d/[^\s"\'<>]+)', html_text)
    )
    if dl_m:
        raw_dl = html_lib.unescape(dl_m.group(1))
        if 'action=download' not in raw_dl:
            raw_dl = f"{raw_dl}&action=download" if '?' in raw_dl else f"{raw_dl}?action=download"
        links["Direct_CDN"] = raw_dl

    # 2. Pixeldrain bridge
    px_m = (
        re.search(r'href=[\'"](https?://pixeldra\.multicloudlinks\.com/\?pid=[^\'"]+)[\'"]', html_text)
        or re.search(r'(https?://pixeldra\.multicloudlinks\.com/\?pid=[^\s"\'<>]+)', html_text)
    )
    if px_m:
        px_url = html_lib.unescape(px_m.group(1))
        try:
            head_resp = requests.get(px_url, headers={"User-Agent": USER_AGENT}, timeout=6, allow_redirects=False)
            loc = head_resp.headers.get("Location") or head_resp.headers.get("location")
            if loc:
                m_pid = re.search(r"/u/([a-zA-Z0-9]+)", loc)
                if m_pid:
                    links["Pixeldrain"] = f"https://pixeldrain.com/api/file/{m_pid.group(1)}?download"
                else:
                    links["Pixeldrain"] = loc
        except Exception:
            links["Pixeldrain_Bridge"] = px_url

    # 3. GDFlix bridge
    gdf_m = re.search(r'href=[\'"](https?://(?:[a-zA-Z0-9-]+\.)?gdflix\.[a-z]+/file/[a-zA-Z0-9]+)[\'"]', html_text)
    if gdf_m:
        links["GDFlix"] = gdf_m.group(1)

    # 4. Filebee bridge
    fb_m = re.search(r'href=[\'"](https?://(?:[a-zA-Z0-9-]+\.)?filebee\.[a-z]+/file/[a-zA-Z0-9]+)[\'"]', html_text)
    if fb_m:
        links["Filebee"] = fb_m.group(1)

    if not links:
        raise ValueError("Could not extract any download links from MultiCloud")

    primary = links.get("Direct_CDN") or links.get("Pixeldrain") or next(iter(links.values()))

    return {
        "success": True,
        "url": primary,
        "links": links
    }
