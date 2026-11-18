import asyncio
import logging
import re
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup as BS

logger = logging.getLogger(__name__)

async def _ouo_step(session, url: str, max_retries: int = 5):
    """Fetch an ouo page with Cloudflare bypass retries and extract the form data."""
    headers = {
        "authority": "ouo.press",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
    }
    
    response = None
    for attempt in range(max_retries):
        try:
            response = await session.get(url, headers=headers, timeout=30)
            if response and "Just a moment..." not in response.text:
                break
        except Exception as e:
            logger.debug(f"ouo attempt {attempt} error: {e}")
        await asyncio.sleep(0.5)

    if not response or "Just a moment..." in response.text:
        raise ValueError("Could not solve Cloudflare challenge on ouo")

    soup = BS(response.text, "html.parser")
    form = soup.find("form")
    if not form:
        # Check if already redirected or page has direct link
        raise ValueError("Could not find form on ouo page")

    data = {
        inp.get("name"): inp.get("value")
        for inp in (form or soup).find_all("input")
        if inp.get("name") and inp.get("value")
    }

    data.pop("v-token", None)
    data["x-token"] = ""

    action = form.get("action", "")
    purl = action.replace("/go/", "/xreallcygo/").replace("go", "xreallcygo")
    if not purl.startswith("http"):
        purl = urljoin(str(response.url), purl)

    post_headers = {
        "authority": "ouo.press",
        "Referer": str(response.url),
        "origin": "https://ouo.press",
    }

    res_post = await session.post(
        purl,
        data=data,
        allow_redirects=False,
        headers=post_headers,
        timeout=30,
    )

    location = res_post.headers.get("Location") or res_post.headers.get("location")
    return location, response.url

async def resolve_ouo_async(url: str, max_retries: int = 5) -> dict:
    """Async resolver for ouo.io / ouo.press / ouo.today."""
    try:
        from curl_cffi.requests import AsyncSession
        use_cffi = True
    except ImportError:
        use_cffi = False

    url = url.replace("ouo.io", "ouo.press").replace("ouo.today", "ouo.press")
    if not url.startswith("http"):
        url = "https://" + url

    headers = {"authority": "ouo.press"}

    if use_cffi:
        async with AsyncSession(headers=headers, impersonate="chrome") as session:
            # Step 1
            loc, last_url = await _ouo_step(session, url, max_retries=max_retries)
            if not loc:
                raise ValueError("Final link not found in ouo step 1")

            # If ouo redirects to a second ouo step (/go/...)
            if any(k in loc for k in ("ouo.press", "ouo.io", "/go/")):
                if not loc.startswith("http"):
                    loc = urljoin("https://ouo.press", loc)
                loc2, _ = await _ouo_step(session, loc, max_retries=max_retries)
                if loc2:
                    loc = loc2

            if not loc or any(k in loc for k in ("ouo.press/go", "ouo.io/go")):
                raise ValueError("Could not extract final destination link from ouo")

            return {
                "success": True,
                "url": loc,
                "target_url": loc,
                "original_url": url,
            }
    else:
        # Fallback to requests if curl_cffi not present
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        r = s.get(url, timeout=15)
        soup = BS(r.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise ValueError("No form found on ouo page")
        data = {inp.get("name"): inp.get("value") for inp in form.find_all("input") if inp.get("name") and inp.get("value")}
        data.pop("v-token", None)
        data["x-token"] = ""
        purl = form.get("action", "").replace("go", "xreallcygo")
        if not purl.startswith("http"):
            purl = urljoin(r.url, purl)
        r2 = s.post(purl, data=data, allow_redirects=False, headers={"Referer": r.url})
        loc = r2.headers.get("Location")
        if not loc:
            raise ValueError("Could not extract Location from ouo response")
        return {
            "success": True,
            "url": loc,
            "target_url": loc,
            "original_url": url,
        }

def resolve_ouo(url: str, max_retries: int = 5) -> dict:
    """Synchronous wrapper for resolve_ouo_async."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(resolve_ouo_async(url, max_retries))
        else:
            return loop.run_until_complete(resolve_ouo_async(url, max_retries))
    except RuntimeError:
        return asyncio.run(resolve_ouo_async(url, max_retries))
