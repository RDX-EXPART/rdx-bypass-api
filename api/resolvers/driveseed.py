import re
import html as html_lib
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def resolve_driveseed(url: str, timeout: int = 15) -> dict:
    """Resolve DriveSeed / HubDrive page to direct download links."""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://driveseed.org/",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    links = {}

    # Look for hubcloud / direct buttons
    for a in soup.find_all("a"):
        h = a.get("href", "").strip()
        txt = a.get_text(" ", strip=True)
        if not h.startswith("http"):
            continue
        if any(ign in h for ign in ("about-us", "privacy", "terms", "t.me", "telegram", "contact", "login")):
            continue
        if "hubcloud" in h:
            links["HubCloud"] = h
        elif any(k in h for k in ("r2.dev", "r2.cloudflarestorage", "googleusercontent.com")):
            links["Direct_CDN"] = h
        elif "pixeldrain" in h:
            links["Pixeldrain"] = h
        elif "gofile" in h:
            links["GoFile"] = h

    if not links:
        # Search form actions or redirect scripts
        m = re.search(r'href=[\'"](https?://[^\s\'"]+(?:hubcloud|drivehub|r2)[^\s\'"]*)[\'"]', html)
        if m:
            links["Target"] = m.group(1)

    if not links:
        raise ValueError("Could not extract any download links from DriveSeed/HubDrive")

    primary = links.get("Direct_CDN") or links.get("HubCloud") or links.get("Pixeldrain") or next(iter(links.values()))

    return {
        "success": True,
        "url": primary,
        "links": links
    }
