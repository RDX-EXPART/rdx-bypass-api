"""
VCloud Bypass API v1.2 (Standalone Heroku Edition)
===================================================
শুধুমাত্র vcloud.beer / hubcloud লিংক বাইপাস করে ক্লিন ডাইরেক্ট ডাউনলোড URL বের করার
ডেডিকেটেড API সার্ভার।

বৈশিষ্ট্য:
  - Heroku-তে Chrome TLS/HTTP2 ইমপার্সোনেশনের জন্য `curl_cffi` সাপোর্ট (ইনস্টল না থাকলে built-in `urllib` ফলব্যাক)
  - `PROXY_URL` / `HTTPS_PROXY` (HTTP/HTTPS/SOCKS5) সাপোর্ট
  - `403` এলে Cloudflare ডায়াগনস্টিক (`cf_ray`, `cf_mitigated`, `tls_engine`) দেখায়
  - কোনো `dl.php?link=` র‍্যাপার ছাড়া ক্লিন ডাইরেক্ট URL দেয়

সাপোর্টেড সার্ভার:
  - FSLv2 Server  (r2.cloudflarestorage.com)
  - FSL Server    (pub-xxx.r2.dev)
  - PixelServer   (pixeldrain.dev → pixeldrain.com/api/file/)
  - Server 10Gbps (gpdl2.hubcloud.pw → workers.dev → Google Drive raw)
  - VegaDrive     (one.vegadrive.me → Vegadrop 10Gbps / mirrors)
  - GoFile / TransferIt / Buzzheavier / VikingFile

Endpoints:
  GET  /bypass?url=https://vcloud.beer/HASH
  POST /bypass  (JSON body: {"url": "https://vcloud.beer/HASH"})
  GET  /health
"""

import base64
import json
import os
import re
import ssl
import sys
import io
import time
import http.cookiejar
from email.message import Message
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse, parse_qs
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener, HTTPSHandler, HTTPCookieProcessor
from urllib.error import HTTPError
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer as HTTPServer, BaseHTTPRequestHandler

try:
    from curl_cffi import requests as _cf_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _cf_requests = None
    _HAS_CURL_CFFI = False

# ─── কনফিগ ───
HOST = "0.0.0.0"
PORT = int(os.environ.get("VCLOUD_PORT", os.environ.get("PORT", 8081)))
TIMEOUT = 25
MAX_WORKERS = 8
_TLS_ENGINE = "curl_cffi (chrome)" if _HAS_CURL_CFFI else "urllib"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
}


# ─── Proxy, SSL & Opener Helpers ───
def _get_proxy():
    for key in ("PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return ""


def _cf_proxies():
    p = _get_proxy()
    return {"http": p, "https": p} if p else None


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _build_opener(*extra_handlers):
    """PROXY_URL / HTTPS_PROXY / HTTP_PROXY এবং SSL context সহ urllib opener বানায়।"""
    handlers = [HTTPSHandler(context=_ssl_ctx()), *extra_handlers]
    proxy = _get_proxy()
    if proxy:
        handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
    return build_opener(*handlers)


def _make_http_error(url, status_code, headers_dict=None):
    hdrs = Message()
    if headers_dict:
        for k, v in headers_dict.items():
            hdrs[str(k)] = str(v)
    return HTTPError(url, status_code, "HTTP {}".format(status_code), hdrs, None)


def _unwrap_dl_php(url):
    """dl.php?link=... র‍্যাপার থাকলে আসল ফাইনাল ডাউনলোড URL বের করে।"""
    if not url:
        return url
    ul = url.lower()
    if "dl.php" in ul and "link=" in ul:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        link_val = qs.get("link", [None])[0]
        if link_val:
            return link_val
    return url


# ─── NoRedirect Handler (10Gbps bypass এ লাগে) ───
class _NoRedirect(HTTPRedirectHandler):
    """Redirect follow না করে Location header ধরে।"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _cf_get(url, referer=None, allow_redirects=True, session=None, extra_headers=None, timeout=TIMEOUT):
    """curl_cffi দিয়ে Chrome TLS/HTTP2 রিকোয়েস্ট চালায় (পুরানো ভার্সনে impersonate ফলব্যাক সহ)।"""
    req_headers = {"Accept-Language": "en-US,en;q=0.9"}
    if referer:
        req_headers["Referer"] = referer
    if extra_headers:
        req_headers.update(extra_headers)

    caller = session if session is not None else _cf_requests
    last_exc = None
    for imp in ("chrome", "chrome120"):
        try:
            return caller.get(
                url,
                headers=req_headers,
                impersonate=imp,
                timeout=timeout,
                verify=False,
                allow_redirects=allow_redirects,
                proxies=_cf_proxies(),
            )
        except Exception as e:
            msg = str(e).lower()
            if "impersonat" in msg or "browser" in msg or "not supported" in msg:
                last_exc = e
                continue
            raise
    raise last_exc


# ─── HTTP ফেচ ───
def fetch(url, referer=None, session=None, retries=1):
    """URL ফেচ করে (HTML, final_url) রিটার্ন করে। আগে curl_cffi (থাকলে), নাহলে urllib ব্যবহার করে।"""
    if _HAS_CURL_CFFI:
        last_err = None
        for attempt in range(retries + 1):
            try:
                r = _cf_get(url, referer=referer, allow_redirects=True, session=session)
                if r.status_code >= 400:
                    raise _make_http_error(r.url or url, r.status_code, r.headers)
                return r.text, (r.url or url)
            except HTTPError as e:
                if e.code in (403, 404, 410) or attempt >= retries:
                    raise
                last_err = e
                time.sleep(0.8)
            except Exception as e:
                last_err = e
                if attempt >= retries:
                    break
                time.sleep(0.8)
        # curl_cffi কোনো নন-HTTP ত্রুটি দিলে urllib ফলব্যাক

    last_err = None
    for attempt in range(retries + 1):
        req = Request(url)
        for k, v in HEADERS.items():
            req.add_header(k, v)
        if referer:
            req.add_header("Referer", referer)
        try:
            resp = _build_opener().open(req, timeout=TIMEOUT)
            final_url = resp.geturl()
            raw = resp.read()
            resp.close()

            ct = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in ct:
                charset = ct.split("charset=")[-1].split(";")[0].strip()
            try:
                html = raw.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                html = raw.decode("utf-8", errors="replace")
            return html, final_url
        except HTTPError as e:
            if e.code in (403, 404, 410) or attempt >= retries:
                raise
            last_err = e
            time.sleep(0.8)
        except Exception as e:
            last_err = e
            if attempt >= retries:
                raise
            time.sleep(0.8)
    raise last_err


def fetch_redirect_location(url, referer=None):
    """
    Redirect follow না করে শুধু Location header রিটার্ন করে।
    10Gbps server bypass এ ব্যবহৃত।
    """
    if _HAS_CURL_CFFI:
        try:
            r = _cf_get(url, referer=referer, allow_redirects=False)
            loc = r.headers.get("Location") or r.headers.get("location")
            if loc:
                return loc
            if r.status_code < 400:
                return r.url or url
        except Exception:
            pass

    opener = _build_opener(_NoRedirect())
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    if referer:
        req.add_header("Referer", referer)

    try:
        resp = opener.open(req, timeout=TIMEOUT)
        return resp.geturl()
    except HTTPError as e:
        loc = e.headers.get("Location")
        if loc:
            return loc
        raise


# ─── HTML Link Parser ───
class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []
        self._id = ""
        self._in_a = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            href = d.get("href", "")
            if href:
                self._in_a = True
                self._href = href
                self._id = d.get("id", "")
                self._text = []

    def handle_data(self, data):
        if self._in_a:
            self._text.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            self.links.append({
                "href": self._href,
                "id": self._id,
                "text": " ".join(self._text).strip(),
            })
            self._in_a = False


def parse_links(html, base_url):
    """HTML থেকে সব লিংক বের করে"""
    parser = _LinkParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    results = []
    seen = set()
    for item in parser.links:
        href = item["href"].strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen or not absolute.startswith(("http://", "https://")):
            continue
        seen.add(absolute)
        results.append({"url": absolute, "text": item["text"], "id": item.get("id", "")})
    return results


def _apply_js_overrides(html, links):
    """
    ভিক্লাউড পেজের JavaScript ওভাররাইড (যেমন var pxl = "..." -> #pxl-1) প্রয়োগ করে।
    ডিকয়/ডামি pixeldrain লিংক (negn6f) সরিয়ে আসল লিংক বসায়।
    """
    pxl_override = None
    m = re.search(r'(?:var|let|const)\s+pxl\s*=\s*["\'](https?://[^"\']+)["\']', html)
    if not m:
        m = re.search(r'getElementById\s*\(\s*["\']pxl-1["\']\s*\)\.href\s*=\s*["\'](https?://[^"\']+)["\']', html)
    if m:
        pxl_override = m.group(1).replace("\\/", "/").strip()

    if not pxl_override:
        return links

    updated = []
    replaced = False
    for link in links:
        l_copy = dict(link)
        if l_copy.get("id") == "pxl-1" or "pixeldrain" in l_copy["url"].lower():
            l_copy["url"] = pxl_override
            replaced = True
        updated.append(l_copy)

    if not replaced:
        updated.append({"url": pxl_override, "text": "Download [PixelServer : 2]", "id": "pxl-1"})
    return updated


# ════════════════════════════════════════════════════════════
#  SERVER LINK DETECTION
# ════════════════════════════════════════════════════════════

_JUNK_KEYWORDS = [
    "terms", "contact", "copyright", "privacy", "policy", "login",
    "signup", "register", "about", "/faq", "dmca", "google.com/search",
    "t.me/", "telegram"
]

_SERVER_TEXT_KW = [
    "server", "fsl", "pixel", "10gbps", "download", "direct",
    "gdrive", "gofile", "filepress"
]

_SERVER_URL_KW = [
    "pixeldrain.com/api/", "pixeldrain.dev/u/", "gofile.io/d/",
    "filepress", "mediafire.com/file/", "drive.google.com/",
    "workers.dev/", "dl.php", "fastdl", "filebee", ".r2.dev/",
    "vegadrive.me/", "vegadrive.app/", "vegadrive.co/",
    "vcloud.beer/", "gpdl", "hubcloud", "r2.cloudflarestorage.com"
]


def _is_server_link(text, url):
    """ডাউনলোড সার্ভার লিংক কি না চেক"""
    text_lower = text.lower()
    url_lower = url.lower()

    if any(jk in url_lower for jk in _JUNK_KEYWORDS):
        return False
    if any(jk in text_lower for jk in _JUNK_KEYWORDS):
        return False

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path and not parsed.query:
        return False

    return (
        any(kw in text_lower for kw in _SERVER_TEXT_KW)
        or any(kw in url_lower for kw in _SERVER_URL_KW)
    )


def _detect_server_name(text, url):
    """সার্ভারের নাম ডিটেক্ট"""
    tl = text.lower()
    ul = url.lower()

    if "fslv2" in tl or "r2.cloudflarestorage.com" in ul:
        return "FSLv2 Server"
    if "fsl" in tl and "v2" not in tl:
        return "FSL Server"
    if ".r2.dev/" in ul:
        return "FSL Server"
    if "pixel" in tl or "pixeldrain" in ul:
        return "PixelServer"
    if "10gbps" in tl or "gpdl" in ul or "cryptonewz" in ul:
        return "Server 10Gbps"
    if "vegadrop" in tl or "vegadrive" in ul:
        return "Vegadrop"
    if "gofile" in tl or "gofile" in ul:
        return "GoFile"
    if "transferit" in tl or "transfer.it" in ul:
        return "TransferIt"
    if "buzzheavier" in tl or "bzzhr.co" in ul or "buzzheavier" in ul:
        return "Buzzheavier"
    if "vikingfile" in tl or "vikingfile" in ul:
        return "VikingFile"
    if "filepress" in tl or "filebee" in ul:
        return "Filepress"
    if "drive.google" in ul or "googleusercontent" in ul:
        return "Google Drive"
    if "mediafire" in ul:
        return "MediaFire"

    server_match = re.search(r'Server\s*[:\s]*(\S+)', text, re.IGNORECASE)
    if server_match:
        return "Server " + server_match.group(1)
    if "download" in tl:
        return "Download Server"
    return "Unknown"


# ════════════════════════════════════════════════════════════
#  RESOLVE FUNCTIONS — প্রতিটি সার্ভার টাইপের জন্য
# ════════════════════════════════════════════════════════════

def _probe_download_url(url, timeout=6):
    """
    ফাইনাল ডাউনলোড URL আসলেই ডাউনলোডযোগ্য কিনা (403/404 দেয় কিনা) তা চেক করে।
    Range: bytes=0-15 ব্যবহার করে (টোকেন খরচ হয় না এবং খুব দ্রুত)।
    """
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-15"})
        resp = _build_opener().open(req, timeout=timeout)
        status = resp.status
        ct = resp.headers.get("Content-Type", "").lower()
        resp.read(16)
        resp.close()
        if "text/html" in ct and ("r2." in url.lower() or "googleusercontent" in url.lower() or "pixeldrain" in url.lower()):
            return status, False, "Server returned HTML page instead of file"
        return status, True, ""
    except HTTPError as e:
        code = e.code
        if code == 403 and "pixeldrain" in url.lower():
            try:
                body = e.read(400).decode("utf-8", "replace").lower()
                if "rate_limit" in body or "captcha" in body or "limit" in body:
                    return code, True, ""
            except Exception:
                pass
        if code in (403, 404, 410):
            return code, False, "HTTP {} (লিংকটি বর্তমানে বন্ধ বা ব্লকড)".format(code)
        return code, True, ""
    except Exception:
        return None, True, ""


def resolve_pixeldrain(url):
    """pixeldrain.dev/u/ID → pixeldrain.com/api/file/ID (ডাইরেক্ট ডাউনলোড + চেক)"""
    file_id = url.rstrip("/").split("/u/")[-1].split("/")[0].split("?")[0]
    candidates = [
        "https://pixeldrain.com/api/file/{}".format(file_id),
        "https://pixeldrain.dev/api/file/{}".format(file_id),
    ]
    last_code = None
    last_err = ""
    for api_url in candidates:
        status, ok, err = _probe_download_url(api_url)
        last_code = status
        last_err = err
        if ok:
            return {
                "success": True,
                "direct_url": api_url,
                "page_url": url,
                "server": "PixelServer",
                **({"http_status": status} if status else {}),
            }
    return {
        "success": False,
        "direct_url": candidates[0],
        "page_url": url,
        "server": "PixelServer",
        "http_status": last_code,
        "error": last_err or "PixelDrain file not found",
    }


def resolve_10gbps(url, referer=None):
    """
    10Gbps server bypass:
    gpdl2.hubcloud.pw/?id=HASH
      → 302 → gpdl2.rohitkiskk.workers.dev/?id=HASH
        → 302 → cryptonewz.online/dl.php?link=GOOGLE_DRIVE_URL
    dl.php?link= থেকে শুধু আসল Google Drive ডাইরেক্ট URL বের করে (কোনো dl.php র‍্যাপার ছাড়া)।
    """
    try:
        cur = url
        ref = referer
        for _ in range(4):
            nxt = fetch_redirect_location(cur, referer=ref)
            if not nxt:
                break
            nxt = urljoin(cur, nxt)
            if nxt == cur:
                break
            if "dl.php" in nxt.lower() and "link=" in nxt.lower():
                link_val = _unwrap_dl_php(nxt)
                if link_val and link_val != nxt:
                    status, ok, err = _probe_download_url(link_val)
                    res = {"success": ok, "direct_url": link_val, "server": "Server 10Gbps"}
                    if status:
                        res["http_status"] = status
                    if not ok:
                        res["error"] = err
                    return res
            ref = cur
            cur = nxt

        if cur == url:
            return {"success": False, "error": "10Gbps: no redirect from hubcloud"}

        clean_cur = _unwrap_dl_php(cur)
        status, ok, err = _probe_download_url(clean_cur)
        res = {"success": ok, "direct_url": clean_cur, "server": "Server 10Gbps"}
        if status:
            res["http_status"] = status
        if not ok:
            res["error"] = err
        return res
    except Exception as e:
        return {"success": False, "error": "10Gbps bypass error: {}".format(str(e))}


def resolve_r2_direct(url):
    """R2 CDN / Cloudflare Storage — ডাইরেক্ট লিংক ভ্যালিডেট সহ"""
    server = "FSLv2 Server" if "r2.cloudflarestorage.com" in url else "FSL Server"
    status, ok, err = _probe_download_url(url)
    res = {"success": ok, "direct_url": url, "server": server}
    if status:
        res["http_status"] = status
    if not ok:
        res["error"] = err
    return res


def resolve_dl_php(url):
    """dl.php?link=... থেকে আসল ডাউনলোড URL extract + ভ্যালিডেট"""
    link_val = _unwrap_dl_php(url)
    if link_val and link_val != url:
        status, ok, err = _probe_download_url(link_val)
        res = {"success": ok, "direct_url": link_val, "server": "Download Proxy"}
        if status:
            res["http_status"] = status
        if not ok:
            res["error"] = err
        return res
    return {"success": True, "direct_url": url, "server": "Download Proxy"}


def resolve_gofile(url):
    """GoFile — keep as-is"""
    return {"success": True, "direct_url": url, "server": "GoFile"}


def resolve_server_link(url, text="", referer=None):
    """URL দেখে সঠিক resolver দিয়ে ডাইরেক্ট ডাউনলোড লিংক বের করে।"""
    ul = url.lower()

    if "pixeldrain" in ul and "/u/" in url:
        return resolve_pixeldrain(url)

    if "gpdl" in ul and "hubcloud" in ul:
        return resolve_10gbps(url, referer=referer)

    if "r2.cloudflarestorage.com" in ul or ".r2.dev/" in ul:
        return resolve_r2_direct(url)

    if "dl.php" in ul and "link=" in ul:
        return resolve_dl_php(url)

    if "gofile.io" in ul:
        return resolve_gofile(url)

    if "googleusercontent.com" in ul:
        status, ok, err = _probe_download_url(url)
        res = {"success": ok, "direct_url": url, "server": "Google Drive"}
        if status:
            res["http_status"] = status
        if not ok:
            res["error"] = err
        return res
    if "drive.google.com" in ul:
        return {"success": True, "direct_url": url, "server": "Google Drive"}

    if "workers.dev" in ul:
        try:
            loc = fetch_redirect_location(url, referer=referer)
            if loc and "dl.php" in loc and "link=" in loc:
                return resolve_dl_php(loc)
            return {"success": True, "direct_url": loc or url, "server": "CDN Workers"}
        except Exception:
            return {"success": True, "direct_url": url, "server": "CDN Workers"}

    if "vegadrive" in ul:
        try:
            cj = http.cookiejar.CookieJar()
            op_follow = _build_opener(HTTPCookieProcessor(cj))
            op_nr = _build_opener(_NoRedirect(), HTTPCookieProcessor(cj))

            def _vg(u, ref=None, accept="text/html,*/*"):
                req = Request(u, headers={"User-Agent": USER_AGENT, "Accept": accept})
                if ref:
                    req.add_header("Referer", ref)
                r = op_follow.open(req, timeout=TIMEOUT)
                return r.read().decode("utf-8", "replace"), r.geturl()

            v_html, v_final = _vg(url, ref=referer)
            m = re.search(r"https?://([^/]+)/(?:s|d)/([A-Za-z0-9]+)", v_final)
            if m:
                host, fid = m.group(1), m.group(2)
                if "/{}/skydrop".format(fid) in v_html or "provider=skydrop" in v_html or '["skydrop","ready"]' in v_html:
                    sky_url = "https://{}/d/{}/skydrop".format(host, fid)
                    sky_html, _ = _vg(sky_url, ref=v_final)
                    prep_m = re.search(r'prepareUrl\s*=\s*"([^"]+)"', sky_html)
                    link_m = re.search(r'linkUrl\s*=\s*"([^"]+)"', sky_html)
                    if prep_m and link_m:
                        prep = prep_m.group(1).replace("\\/", "/")
                        link_ep = link_m.group(1).replace("\\/", "/")
                        for attempt in range(6):
                            try:
                                pdata = json.loads(_vg(prep, ref=sky_url, accept="application/json")[0])
                            except Exception:
                                if attempt + 1 < 6:
                                    time.sleep(1.5)
                                continue
                            if pdata.get("ready") is True:
                                if not pdata.get("download_url"):
                                    try:
                                        pdata = json.loads(_vg(link_ep, ref=sky_url, accept="application/json")[0])
                                    except Exception:
                                        if attempt + 1 < 6:
                                            time.sleep(1.5)
                                        continue
                                dl_url = pdata.get("download_url")
                                if dl_url:
                                    status, ok, err = _probe_download_url(dl_url)
                                    if ok:
                                        res = {"success": True, "direct_url": dl_url, "server": "Vegadrop 10Gbps"}
                                        if status:
                                            res["http_status"] = status
                                        return res
                                    break
                            if attempt + 1 < 6:
                                time.sleep(max(1.5, min(3.0, (pdata.get("retry_after_ms") or 2000) / 1000.0)))
                for prov, label in [
                    ("pixeldrain", "PixelServer"),
                    ("gofile", "GoFile"),
                    ("transferit", "TransferIt"),
                    ("buzzheavier", "Buzzheavier"),
                    ("vikingfile", "VikingFile"),
                ]:
                    if "/{}/{}".format(fid, prov) in v_html:
                        cur = "https://{}/d/{}/{}".format(host, fid, prov)
                        for _ in range(5):
                            try:
                                op_nr.open(Request(cur, headers={"User-Agent": USER_AGENT, "Referer": v_final}), timeout=8)
                                break
                            except HTTPError as he:
                                loc = he.headers.get("Location")
                                if he.code in (301, 302, 303, 307, 308) and loc:
                                    loc = urljoin(cur, loc)
                                    if "vegadrive" in loc.lower():
                                        cur = loc
                                        continue
                                    if "pixeldrain" in loc.lower() and "/u/" in loc:
                                        return resolve_pixeldrain(loc)
                                    return {"success": True, "direct_url": loc, "server": label}
                                break
            return {"success": False, "direct_url": url, "error": "VegaDrive direct link not ready", "server": "VegaDrive"}
        except Exception as e:
            return {"success": False, "direct_url": url, "error": str(e), "server": "VegaDrive"}

    server = _detect_server_name(text, url)
    return {"success": True, "direct_url": url, "server": server}


# ════════════════════════════════════════════════════════════
#  DOUBLE BASE64 DECODE
# ════════════════════════════════════════════════════════════

def _decode_double_base64(encoded):
    """Double base64 decode: atob(atob('...'))"""
    try:
        d1 = base64.b64decode(encoded).decode("utf-8", errors="replace")
        d2 = base64.b64decode(d1).decode("utf-8", errors="replace")
        return d2
    except Exception:
        try:
            return base64.b64decode(encoded).decode("utf-8", errors="replace")
        except Exception:
            return None


# ════════════════════════════════════════════════════════════
#  MAIN BYPASS FUNCTION
# ════════════════════════════════════════════════════════════

def bypass_vcloud(url):
    """
    vcloud.beer / hubcloud পেজ বাইপাস:
    1. পেজ ফেচ করে (curl_cffi Chrome TLS + session cookie সহ)
    2. Double base64 decode করে token URL বের করে
    3. Token URL ফেচ করে সার্ভার লিংক বের করে (+ JS var pxl ওভাররাইড)
    4. প্রতিটি সার্ভার লিংক resolve + ভ্যালিডেট করে ডাইরেক্ট URL দেয়
    """
    import uuid

    parsed_orig = urlparse(url)
    orig_netloc = parsed_orig.netloc.lower()
    code = parsed_orig.path.strip("/").split("/")[-1]

    # ─── Modern VCloud Direct Resolver (dl.php) ───
    ordered_d = []
    if any(k in orig_netloc for k in ("vcloud", "fastdl.beer")) and code and not code.startswith("?"):
        domains = [parsed_orig.netloc, "vcloud.beer"]
        seen_d = set()
        ordered_d = [d for d in domains if d and not (d in seen_d or seen_d.add(d))]

        for domain in ordered_d:
            page_url = f"https://{domain}/{code}"
            rnd_hash = uuid.uuid4().hex
            rnd_cfs = uuid.uuid4().hex
            dl_api_url = f"https://{domain}/dl.php?code={code}&prepare=1&hash={rnd_hash}&cfs={rnd_cfs}"
            headers = {
                "User-Agent": USER_AGENT,
                "Referer": page_url,
                "X-Requested-With": "XMLHttpRequest",
            }
            try:
                if _HAS_CURL_CFFI:
                    r_dl = _cf_get(dl_api_url, referer=page_url, extra_headers={"X-Requested-With": "XMLHttpRequest"}, timeout=8)
                    if r_dl.status_code == 200:
                        res_json = r_dl.json()
                        direct_url = res_json.get("url") or res_json.get("direct_url") or res_json.get("download_url")
                        if direct_url:
                            server_name = _detect_server_name("V-Cloud Direct", direct_url)
                            return {
                                "success": True,
                                "source": url,
                                "file_name": "VCloud_File",
                                "servers": [{"name": server_name, "direct_url": direct_url, "source_url": url, "success": True}],
                            }
                else:
                    req = Request(dl_api_url, headers=headers)
                    resp = _build_opener().open(req, timeout=8)
                    data_text = resp.read().decode("utf-8", "replace")
                    resp.close()
                    res_json = json.loads(data_text)
                    direct_url = res_json.get("url") or res_json.get("direct_url") or res_json.get("download_url")
                    if direct_url:
                        server_name = _detect_server_name("V-Cloud Direct", direct_url)
                        return {
                            "success": True,
                            "source": url,
                            "file_name": "VCloud_File",
                            "servers": [{"name": server_name, "direct_url": direct_url, "source_url": url, "success": True}],
                        }
            except Exception:
                pass

    sess = _cf_requests.Session() if _HAS_CURL_CFFI else None
    try:
        html = None
        final_url = url
        last_fetch_err = None
        target_domains = ordered_d if ordered_d else [parsed_orig.netloc]
        for d in target_domains:
            cand_url = f"https://{d}/{code}" if (code and not code.startswith("?")) else url
            try:
                html, final_url = fetch(cand_url, session=sess)
                if html and "Just a moment..." not in html:
                    break
            except Exception as fe:
                last_fetch_err = fe

        if not html:
            if last_fetch_err:
                raise last_fetch_err
            raise RuntimeError("Failed to fetch VCloud page")

        file_info = _extract_file_info(html)
        server_links = []

        # Method 1: Double base64 decode → token URL
        b64_match = re.search(r"atob\s*\(\s*atob\s*\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)", html)
        if b64_match:
            decoded_url = _decode_double_base64(b64_match.group(1))
            if decoded_url and decoded_url.startswith("http"):
                try:
                    inner_html, inner_final = fetch(decoded_url, referer=url, session=sess)
                    parsed = _apply_js_overrides(inner_html, parse_links(inner_html, inner_final))
                    for link in parsed:
                        if _is_server_link(link["text"], link["url"]):
                            server_links.append(link)
                    if not file_info.get("file_name"):
                        file_info = _extract_file_info(inner_html)
                except Exception:
                    pass

        # Method 2: Single base64
        if not server_links:
            b64_single = re.search(r"atob\s*\(\s*['\"]([A-Za-z0-9+/=]{20,})['\"]\s*\)", html)
            if b64_single:
                try:
                    decoded = base64.b64decode(b64_single.group(1)).decode("utf-8", errors="replace")
                    if decoded.startswith("http"):
                        inner_html, inner_final = fetch(decoded, referer=url, session=sess)
                        parsed = _apply_js_overrides(inner_html, parse_links(inner_html, inner_final))
                        for link in parsed:
                            if _is_server_link(link["text"], link["url"]):
                                server_links.append(link)
                        if not file_info.get("file_name"):
                            file_info = _extract_file_info(inner_html)
                except Exception:
                    pass

        # Method 3: Direct page links
        if not server_links:
            parsed = _apply_js_overrides(html, parse_links(html, final_url))
            for link in parsed:
                if _is_server_link(link["text"], link["url"]) and link["url"] != url:
                    server_links.append(link)

        # Method 4: JS redirects
        for js_url in re.findall(
            r'(?:window\.location(?:\.href)?\s*=|href\s*=)\s*["\'](https?://[^\s"\'<>]+)["\']', html
        ):
            jl = js_url.lower()
            if any(d in jl for d in [
                "pixeldrain", "gofile", "filepress", "drive.google",
                "workers.dev", "dl.php", "fastdl", ".r2.dev",
                "gpdl", "r2.cloudflarestorage"
            ]):
                if not any(s["url"] == js_url for s in server_links):
                    server_links.append({"url": js_url, "text": "JS Redirect"})

        if not server_links:
            return {
                "success": False,
                "source": url,
                "tls_engine": _TLS_ENGINE,
                "error": "কোনো সার্ভার লিংক পাওয়া যায়নি",
                **file_info,
            }

        results = []

        def _resolve_one(link):
            try:
                res = resolve_server_link(link["url"], link["text"], referer=url)
                return {
                    "name": res.get("server", _detect_server_name(link["text"], link["url"])),
                    "direct_url": res.get("direct_url", link["url"]),
                    "source_url": link["url"],
                    "success": res.get("success", True),
                    **({k: res[k] for k in ["http_status", "page_url", "error"]
                        if k in res and res[k] is not None and res[k] != ""}),
                }
            except Exception as e:
                return {
                    "name": _detect_server_name(link["text"], link["url"]),
                    "source_url": link["url"],
                    "success": False,
                    "error": str(e),
                }

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(_resolve_one, link) for link in server_links]
            for f in futures:
                try:
                    results.append(f.result())
                except Exception as e:
                    results.append({"name": "Unknown", "success": False, "error": str(e)})

        results.sort(key=lambda x: (0 if x.get("success") else 1))
        working_count = sum(1 for r in results if r.get("success"))

        return {
            "success": working_count > 0,
            "source": url,
            "tls_engine": _TLS_ENGINE,
            "total_servers": len(results),
            "working_servers": working_count,
            "servers": results,
            **file_info,
        }
    except HTTPError as e:
        cf_ray = e.headers.get("CF-RAY") if e.headers else None
        cf_mitigated = e.headers.get("cf-mitigated") if e.headers else None
        res = {
            "success": False,
            "source": url,
            "http_status": e.code,
            "tls_engine": _TLS_ENGINE,
            "proxy_used": bool(_get_proxy()),
            "error": "VCloud bypass error: HTTP Error {}: {}".format(e.code, e.reason),
        }
        if cf_ray:
            res["cf_ray"] = cf_ray
        if cf_mitigated:
            res["cf_mitigated"] = cf_mitigated
        if e.code == 403:
            if cf_mitigated:
                res["hint"] = (
                    "Cloudflare Turnstile/Managed Challenge ({}) ট্রিগার হয়েছে এই সার্ভার IP-তে। "
                    "Heroku Config Vars-এ PROXY_URL (রেসিডেনশিয়াল HTTP/SOCKS5 প্রক্সি) দিন অথবা PC/Termux/অ-ব্লকড VPS থেকে চালান।"
                ).format(cf_mitigated)
            else:
                res["hint"] = (
                    "Cloudflare থেকে HTTP 403 ব্লক এসেছে। Heroku-তে কাজ না করলে Config Vars-এ PROXY_URL দিন "
                    "অথবা রেসিডেনশিয়াল/অ-AWS IP থেকে চালান।"
                )
        return res
    except Exception as e:
        return {
            "success": False,
            "source": url,
            "tls_engine": _TLS_ENGINE,
            "error": "VCloud bypass error: {}".format(str(e)),
        }
    finally:
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass


def _extract_file_info(html):
    """HTML থেকে ফাইলের নাম, সাইজ, MIME type extract করে"""
    info = {}

    fn_match = re.search(
        r'([A-Za-z0-9._\-\[\]()+ ]{5,}\.(?:mkv|mp4|zip|rar|avi|webm|flv|wmv|m4v|ts|srt))',
        html, re.IGNORECASE
    )
    if fn_match:
        info["file_name"] = fn_match.group(1).strip()

    size_match = re.search(
        r'(?:Size|ফাইল সাইজ)\s*(?:</[^>]+>)?\s*(?:<[^>]+>)?\s*'
        r'([\d.,]+\s*(?:KB|MB|GB|TB|B))',
        html, re.IGNORECASE
    )
    if size_match:
        info["file_size"] = size_match.group(1).strip()

    mime_match = re.search(
        r'(?:MimeType|Content.?Type)\s*(?:</[^>]+>)?\s*(?:<[^>]+>)?\s*'
        r'([a-z]+/[a-z0-9._\-+]+)',
        html, re.IGNORECASE
    )
    if mime_match:
        info["mime_type"] = mime_match.group(1).strip()

    return info


# ════════════════════════════════════════════════════════════
#  API SERVER
# ════════════════════════════════════════════════════════════

class VCloudHandler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_url_param(self):
        query = urlparse(self.path).query
        params = parse_qs(query)
        return params.get("url", [None])[0]

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self._send_json({
                "app": "VCloud Bypass API",
                "version": "1.2.0",
                "tls_engine": _TLS_ENGINE,
                "proxy_configured": bool(_get_proxy()),
                "endpoints": {
                    "/bypass?url=<vcloud_url>": "vcloud/hubcloud bypass -> clean direct download URLs",
                    "/health": "health check",
                },
                "supported": [
                    "vcloud.beer", "hubcloud", "fastdl.beer",
                    "gpdl2.hubcloud.pw (10Gbps)", "pixeldrain",
                    "R2 CDN (FSL/FSLv2)", "vegadrive", "gofile"
                ],
            })
            return

        if path == "/health":
            self._send_json({"ok": True, "tls_engine": _TLS_ENGINE, "proxy_configured": bool(_get_proxy())})
            return

        if path == "/bypass":
            url = self._get_url_param()
            if not url:
                self._send_json({"success": False, "error": "url parameter required"}, 400)
                return
            self._send_json(bypass_vcloud(url))
            return

        self._send_json({"error": "Not Found. Use /bypass?url=<vcloud_url>"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/bypass":
            self._send_json({"error": "Not Found. Use /bypass"}, 404)
            return
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len else "{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}
        url = data.get("url") or self._get_url_param()
        if not url:
            self._send_json({"success": False, "error": "url parameter required"}, 400)
            return
        self._send_json(bypass_vcloud(url))

    def log_message(self, format, *args):
        print("  [{}] {}".format(self.log_date_time_string(), args[0]))


# ─── CLI Mode ───
def cli_bypass(url):
    """কমান্ড লাইন থেকে bypass করা"""
    result = bypass_vcloud(url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


# ─── Start Server ───
def start_server():
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    server = HTTPServer((HOST, PORT), VCloudHandler)
    print("=" * 60)
    print("  VCloud Bypass API v1.2 (Standalone)")
    print("  TLS Engine: {} | Proxy: {}".format(_TLS_ENGINE, "ON" if _get_proxy() else "OFF"))
    print("=" * 60)
    print("  Server: http://localhost:{}".format(PORT))
    print("  Endpoint: GET /bypass?url=<vcloud_url>")
    print("  Stop: Ctrl+C")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server shutting down...")
        server.shutdown()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.startswith("http"):
            cli_bypass(arg)
        elif arg in ("--server", "-s", "server"):
            start_server()
        else:
            print("Usage: python vcloud.py [<vcloud_url> | --server]")
    else:
        start_server()
