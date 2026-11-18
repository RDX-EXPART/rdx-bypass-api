import re
import urllib.parse
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def resolve_streamtape(url: str, timeout: int = 15) -> str:
    """Extract direct video stream URL from a StreamTape link."""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://streamtape.to/",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    html = resp.text

    # 1. Pattern: captchalink
    # document.getElementById("captchalink").innerHTML = "//str"+ ("defgeamtape.to/get_video...").substring(4);
    m1 = re.search(r"getElementById\(['\"]captchalink['\"]\)\.innerHTML\s*=\s*['\"]([^'\"]+)['\"]\s*\+\s*\(?['\"]([^'\"]+)['\"]?\)?\.substring\((\d+)\);", html)
    if m1:
        prefix = m1.group(1)
        sub_str = m1.group(2)
        idx = int(m1.group(3))
        res = "https:" + (prefix if prefix.startswith("//") else "//" + prefix.lstrip("/")) + sub_str[idx:]
        if "get_video" in res:
            return res + ("&stream=1" if "stream=" not in res else "")

    # 2. Pattern: ideoooolink or norobotlink with dual substring calls
    # e.g. "/streamtape.to/ge" + ... + ('xcddt_video...').substring(1).substring(2)
    m2 = re.search(r"getElementById\(['\"](?:ideoooolink|norobotlink)['\"]\)\.innerHTML\s*=\s*['\"]([^'\"]+)['\"][^;]*\(?['\"]([^'\"]+)['\"]?\)?\.substring\((\d+)\)\.substring\((\d+)\);", html)
    if m2:
        prefix = m2.group(1)
        sub_str = m2.group(2)
        idx = int(m2.group(3)) + int(m2.group(4))
        res = "https:" + (prefix if prefix.startswith("//") else "//" + prefix.lstrip("/")) + sub_str[idx:]
        if "get_video" in res:
            return res + ("&stream=1" if "stream=" not in res else "")

    # 3. Pattern: norobotlink single substring
    m3 = re.search(r"getElementById\(['\"](?:norobotlink|ideoooolink)['\"]\)\.innerHTML\s*=\s*['\"]([^'\"]+)['\"]\s*\+\s*\(?['\"]([^'\"]+)['\"]?\)?\.substring\((\d+)\);", html)
    if m3:
        prefix = m3.group(1)
        sub_str = m3.group(2)
        idx = int(m3.group(3))
        res = "https:" + (prefix if prefix.startswith("//") else "//" + prefix.lstrip("/")) + sub_str[idx:]
        if "get_video" in res:
            return res + ("&stream=1" if "stream=" not in res else "")

    # 4. Pattern: extract token and reconstruct
    file_id_m = re.search(r"/(?:v|e)/([a-zA-Z0-9_-]+)", url)
    token_m = re.search(r"(&expires=\d+&ip=[^&'\"]+&token=[^&'\"]+)", html)
    if file_id_m and token_m:
        fid = file_id_m.group(1)
        tok = token_m.group(1)
        return f"https://streamtape.to/get_video?id={fid}{tok}&stream=1"

    # 5. Direct get_video in script/video tag
    gv_m = re.search(r"(?:https?:)?//[^\s'\"<>]*/get_video\?[^\s'\"<>;]+", html)
    if gv_m:
        val = gv_m.group(0)
        if not val.startswith("http"):
            val = "https:" + val
        return val + ("&stream=1" if "stream=" not in val else "")

    raise ValueError("Could not extract StreamTape video link")
