import re
import html as html_lib
from urllib.parse import urlparse, urljoin
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def _extract_direct_links(content: str) -> dict:
    links = {}
    if not content:
        return links

    # 1. Cloudflare R2 direct storage
    r2 = re.search(r'href=[\'"](https?://[^\s\'"]+r2\.cloudflarestorage\.com[^\s\'"]+)[\'"]', content)
    if r2:
        links["R2_Storage"] = html_lib.unescape(r2.group(1)).replace('&amp;', '&')

    # 2. R2 dev / Workers / CloudPaglu
    r2_dev = re.search(r'href=[\'"](https?://[^\s\'"]*(?:r2\.dev|workers\.dev|cloudpaglu\.site)[^\s\'"]+)[\'"]', content)
    if r2_dev:
        links["R2_CDN"] = html_lib.unescape(r2_dev.group(1)).replace('&amp;', '&')

    # 3. FuckingFast / FastDL
    ff = re.search(r'href=[\'"](https?://(?:fuckingfast|fastdl)\.[a-z]+/[^\s\'"]+)[\'"]', content)
    if ff:
        links["FastDL"] = html_lib.unescape(ff.group(1))

    # 4. Pixeldrain
    pix = re.search(r'href=[\'"](https?://pixeldrain\.[a-z]+/u/[^\s\'"]+)[\'"]', content)
    if pix:
        links["Pixeldrain"] = html_lib.unescape(pix.group(1))

    # 5. GoFile
    gf = re.search(r'href=[\'"](https?://gofile\.io/d/[^\s\'"]+)[\'"]', content)
    if gf:
        links["GoFile"] = html_lib.unescape(gf.group(1))

    # 6. 1fichier
    fic = re.search(r'href=[\'"](https?://1fichier\.[a-z]+/[^\s\'"]+)[\'"]', content)
    if fic:
        links["1fichier"] = html_lib.unescape(fic.group(1))

    # 7. Any generic direct download button in gamerxyt
    btns = re.findall(r'<a\b[^>]*href=[\'"](https?://[^\s\'"]+)[\'"][^>]*class=[\'"][^\'"]*btn[^\'"]*[\'"][^>]*>(.*?)</a>', content, re.I | re.S)
    for b_url, b_text in btns:
        clean_text = re.sub(r'<[^>]+>', '', b_text).strip()
        if clean_text and 'watch' not in clean_text.lower() and 'telegram' not in clean_text.lower():
            label = clean_text[:30]
            if label not in links:
                links[label] = html_lib.unescape(b_url)

    return links

def resolve_hubcloud(url: str, timeout: int = 15) -> dict:
    """Resolve HubCloud / Gamerxyt URL to direct high-speed download links."""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://hubcloud.one/",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    html = resp.text

    # Check if page already has direct download links
    links = _extract_direct_links(html)
    if not links:
        # Search for next step button: /download/ or gamerxyt or hubcloud.php
        gen_m = (
            re.search(r'href=[\'"](https?://[^\s\'"]+gamerxyt[^\s\'"]*)[\'"]', html)
            or re.search(r'href=[\'"](https?://[^\s\'"]+hubcloud\.php[^\s\'"]*)[\'"]', html)
            or re.search(r'href=[\'"](https?://[^\s\'"]+/download/[^\s\'"]*)[\'"]', html)
        )
        if gen_m:
            next_url = gen_m.group(1)
            g_resp = requests.get(next_url, headers=headers, timeout=timeout)
            g_html = g_resp.text
            links = _extract_direct_links(g_html)
            if not links:
                redir = re.search(r'(?:location\.href|location\.replace)\s*=\s*[\'"]([^\'"]+)[\'"]', g_html)
                if redir:
                    cand = redir.group(1)
                    if cand.startswith('http'):
                        c_resp = requests.get(cand, headers=headers, timeout=timeout)
                        links = _extract_direct_links(c_resp.text)
                        if not links:
                            links["Direct"] = cand

    if not links:
        raise ValueError("Could not extract any download links from HubCloud")

    # Priority picking
    primary = (
        links.get("R2_Storage")
        or links.get("R2_CDN")
        or links.get("FastDL")
        or links.get("Pixeldrain")
        or links.get("GoFile")
        or next(iter(links.values()))
    )

    return {
        "success": True,
        "url": primary,
        "links": links
    }
