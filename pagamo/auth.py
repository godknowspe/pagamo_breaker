"""
Pagamo authentication via Playwright browser login.

Login requires reCAPTCHA, so we use a real browser. After login we capture
all cookies from the browser context and reuse them in httpx for API calls.
Cookies are cached to .pagamo_cookies.json so subsequent runs skip the browser.
"""
import asyncio
import json
from pathlib import Path
import httpx
from playwright.async_api import async_playwright

BASE_URL = "https://www.pagamo.org"
COOKIE_CACHE = Path(".pagamo_cookies.json")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/",
}


async def _browser_login(account: str, password: str) -> list[dict]:
    """Opens browser, logs in, returns list of cookie dicts."""
    cookies_box: list[list] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        logged_in = asyncio.Event()

        async def on_response(response):
            if "/api/sign_in" in response.url and response.status == 200:
                try:
                    body = await response.json()
                    if body.get("status") == "ok":
                        print("[auth] Login response captured!")
                        logged_in.set()
                except Exception:
                    pass

        page.on("response", on_response)
        await page.goto(f"{BASE_URL}/sign_in")

        # Auto-fill if selectors match; user can fill manually if not
        try:
            await page.fill('input[name="account"]', account, timeout=3000)
            await page.fill('input[type="password"]', password, timeout=3000)
            await page.click('button[type="submit"]', timeout=3000)
        except Exception:
            print("[auth] Auto-fill failed — please log in manually in the browser")

        # Wait up to 60s for successful login
        try:
            await asyncio.wait_for(logged_in.wait(), timeout=60)
        except asyncio.TimeoutError:
            raise RuntimeError("Login timed out — did not detect successful sign_in response")

        # Small delay to let session cookies settle
        await asyncio.sleep(1)
        cookies = await context.cookies()
        await browser.close()

    return cookies


def _save_cookies(cookies: list[dict]):
    COOKIE_CACHE.write_text(json.dumps(cookies))


def _load_cookies() -> list[dict] | None:
    if COOKIE_CACHE.exists():
        try:
            return json.loads(COOKIE_CACHE.read_text())
        except Exception:
            return None
    return None


def _make_session(cookies: list[dict]) -> httpx.Client:
    session = httpx.Client(base_url=BASE_URL, follow_redirects=True, headers=_HEADERS)
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", "").lstrip("."))
    return session


def _verify_session(session: httpx.Client) -> bool:
    try:
        r = session.post("/users/get_user_info_for_websocket")
        data = r.json()
        if r.status_code == 200 and data.get("id"):
            print(f"[auth] Session valid — nickname: {data.get('nickname')}")
            return True
    except Exception:
        pass
    return False


def login(account: str, password: str) -> httpx.Client:
    """
    Returns an authenticated httpx.Client.
    Uses cached cookies if still valid; otherwise opens browser for login.
    """
    cached = _load_cookies()
    if cached:
        session = _make_session(cached)
        if _verify_session(session):
            print("[auth] Using cached session")
            return session
        print("[auth] Cached session expired, re-logging in...")

    print("[auth] Opening browser for login (handles reCAPTCHA automatically)...")
    cookies = asyncio.run(_browser_login(account, password))
    _save_cookies(cookies)

    session = _make_session(cookies)
    if not _verify_session(session):
        raise RuntimeError("Session verification failed after login")
    return session
