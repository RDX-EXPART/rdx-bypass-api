import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def resolve_gdflix(url: str, timeout: int = 15) -> dict:
    """Resolve GDFlix URL into direct cloud/CDN download links."""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://gdflix.dev/",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Extract file title if possible
    title = "GDFlix_File"
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        c = og_desc["content"].strip()
        if c.startswith("Download "):
            c = c[9:]
        if " - " in c:
            c = c.rsplit(" - ", 1)[0].strip()
        title = c
    elif soup.title and soup.title.string:
        t_str = soup.title.string.strip()
        title = t_str.split("|", 1)[-1].strip() if "|" in t_str else t_str

    links = {}

    # Check direct links on page
    for a in soup.find_all("a"):
        h = a.get("href", "").strip()
        txt = a.get_text(" ", strip=True)
        if not h.startswith("http"):
            continue
        if any(ign in h for ign in ("about-us", "privacy", "terms", "t.me", "telegram", "contact", "login", "pages.dev", "loading.gif")):
            continue
        if any(k in h for k in ("r2.dev", "r2.cloudflarestorage", "googleusercontent.com")):
            links["Direct_CDN"] = h
        elif any(k in h for k in ("cloudpaglu", "workers.dev")):
            links["Cloud_Fast"] = h
        elif "gofile.io" in h:
            links["GoFile"] = h
        elif "pixeldrain" in h:
            links["Pixeldrain"] = h

    # Check /cloud/ button
    cloud_a = soup.find("a", href=re.compile(r"/cloud/"))
    if cloud_a:
        cloud_url = urljoin(resp.url, cloud_a["href"])
        try:
            c_resp = requests.get(cloud_url, headers=headers, timeout=timeout)
            c_soup = BeautifulSoup(c_resp.text, "html.parser")
            for a in c_soup.find_all("a"):
                h = a.get("href", "").strip()
                if not h.startswith("http"):
                    continue
                if any(ign in h for ign in ("about-us", "privacy", "terms", "t.me", "telegram", "contact", "login", "pages.dev")):
                    continue
                if any(k in h for k in ("r2.dev", "r2.cloudflarestorage", "googleusercontent.com")):
                    links["Cloud_R2"] = h
                elif any(k in h for k in ("cloudpaglu", "workers.dev")):
                    links["Cloud_Fast"] = h
        except Exception:
            pass

    # Check GoFlix mirror button
    goflix_a = soup.find("a", href=re.compile(r"goflix\.[a-z]+/en/mirror/"))
    if goflix_a:
        gf_url = goflix_a["href"]
        try:
            g_resp = requests.get(gf_url, headers=headers, timeout=timeout)
            m_gf = re.search(r'href=[\'"](https://gofile\.io/d/[a-zA-Z0-9]+)[\'"]', g_resp.text)
            if m_gf:
                links["GoFile"] = m_gf.group(1)
            m_1fic = re.search(r'href=[\'"](https?://1fichier\.com/[^\s\'">]+)[\'"]', g_resp.text)
            if m_1fic:
                links["1fichier"] = m_1fic.group(1)
        except Exception:
            pass

    if not links:
        raise ValueError("Could not extract any download links from GDFlix")

    primary = (
        links.get("Direct_CDN")
        or links.get("Cloud_R2")
        or links.get("Cloud_Fast")
        or links.get("GoFile")
        or links.get("Pixeldrain")
        or next(iter(links.values()))
    )

    return {
        "success": True,
        "title": title,
        "filename": title,
        "url": primary,
        "links": links
    }
