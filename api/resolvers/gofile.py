import re
import time
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

_TOKEN_CACHE = None
_TOKEN_EXPIRY = 0

def _get_account_token() -> str:
    global _TOKEN_CACHE, _TOKEN_EXPIRY
    now = time.time()
    if _TOKEN_CACHE and now < _TOKEN_EXPIRY:
        return _TOKEN_CACHE
    try:
        r = requests.post("https://api.gofile.io/accounts", headers={"User-Agent": USER_AGENT}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            tok = data.get("data", {}).get("token")
            if tok:
                _TOKEN_CACHE = tok
                _TOKEN_EXPIRY = now + 1800  # 30 min cache
                return tok
    except Exception:
        pass
    return ""

def resolve_gofile(url: str, password: str = "", timeout: int = 15) -> dict:
    """Resolve GoFile link to direct download link."""
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        raise ValueError("Invalid GoFile URL: could not extract content ID")
    content_id = m.group(1)

    token = _get_account_token()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {}
    if password:
        import hashlib
        params["password"] = hashlib.sha256(password.encode()).hexdigest()

    api_url = f"https://api.gofile.io/contents/{content_id}"
    resp = requests.get(api_url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "ok":
        raise ValueError(f"GoFile API error: {data.get('status')}")

    content_data = data.get("data", {})
    children = content_data.get("children", {})

    # If it's a direct file
    if content_data.get("type") == "file":
        dl = content_data.get("link")
        if dl:
            return {
                "success": True,
                "url": dl,
                "filename": content_data.get("name", "GoFile_File"),
                "filesize": content_data.get("size", 0),
                "direct_url": dl
            }

    # If it's a folder/children
    if isinstance(children, dict) and children:
        files = []
        for child_id, item in children.items():
            if item.get("type") == "file" and item.get("link"):
                files.append(item)
        if files:
            first = files[0]
            return {
                "success": True,
                "url": first.get("link"),
                "filename": first.get("name", "GoFile_File"),
                "filesize": first.get("size", 0),
                "total_files": len(files),
                "direct_url": first.get("link")
            }

    direct_link = content_data.get("link")
    if direct_link:
        return {
            "success": True,
            "url": direct_link,
            "filename": content_data.get("name", "GoFile_File"),
            "filesize": content_data.get("size", 0)
        }

    raise ValueError("No direct download link returned from GoFile")
