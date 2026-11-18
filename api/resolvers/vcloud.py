import base64
import html as html_lib
import os
import re
from urllib.parse import urlparse
import requests

SOLVER_API = os.environ.get("BYPARR_API", "http://127.0.0.1:8191/v1")
SOLVER_RETRIES = 2

def _is_valid_url(url):
    p = urlparse(url or "")
    return p.scheme in ("http", "https") and bool(p.netloc)

def _solve(url):
    payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
    last = None
    for attempt in range(1, SOLVER_RETRIES + 1):
        try:
            r = requests.post(SOLVER_API, json=payload, timeout=90)
            data = r.json()
        except requests.exceptions.ConnectionError as e:
            raise ValueError(
                "Solver unreachable. Set BYPARR_API config var to a running Byparr/FlareSolverr URL."
            ) from e
        except Exception as e:
            last = e
            continue
        sol = data.get("solution") or {}
        if sol.get("response"):
            return sol["response"], sol.get("status")
        last = ValueError(data.get("message") or "Solver returned an empty response")
    if isinstance(last, Exception):
        raise last
    raise ValueError(f"Solver failed: {last}")

def _links(body):
    out, seen = [], set()
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", body, re.S | re.I):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        label = re.match(r"Download\s*\[([^\]]+)\]", text, re.I)
        href = re.search(r'href=["\']([^"\']+)["\']', m.group(1))
        if not (label and href):
            continue
        url = html_lib.unescape(href.group(1))
        if url.startswith("http") and url not in seen:
            seen.add(url)
            out.append({"server": label.group(1).strip(), "url": url})
    return out

def resolve_vcloud(url: str) -> dict:
    if not _is_valid_url(url):
        raise ValueError("Invalid V-Cloud URL")

    page, status = _solve(url)
    tok = re.search(r"atob\(atob\('([^']+)'\)\)", page)
    if not tok:
        raise ValueError(f"Token not found on page (HTTP {status})")
    try:
        token_url = base64.b64decode(base64.b64decode(tok.group(1))).decode()
    except Exception as e:
        raise ValueError("Token could not be decoded") from e
    if not _is_valid_url(token_url):
        raise ValueError("Token did not contain a valid URL")

    body, status = _solve(token_url)
    links = _links(body)
    if not links:
        raise ValueError(f"No download links found (HTTP {status})")

    name = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
    size = re.search(r'id=["\']size["\'][^>]*>([^<]+)<', body)
    filename = html_lib.unescape(name.group(1)).strip() if name else "Unknown_File"
    filesize = size.group(1).strip() if size else "Unknown"
    return {
        "success": True,
        "filename": filename,
        "filesize": filesize,
        "url": links[0]["url"] if links else "",
        "download_links": links,
        "links": {l["server"]: l["url"] for l in links},
    }
