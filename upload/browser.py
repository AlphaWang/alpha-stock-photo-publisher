import os
import socket
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeout,
)

try:
    from playwright_stealth import stealth_sync
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False

SESSION_DIR = Path(__file__).parent.parent / ".session"
PX500_CREATOR_HOST = "creatorstudio.500px.com.cn"

# Suppress navigator.webdriver and other automation markers that trigger bot detection.
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
window.chrome = {runtime: {}};
"""


def _browser_args(platform: str) -> list[str]:
    args = ["--disable-blink-features=AutomationControlled"]
    if platform != "px500":
        return args

    try:
        addresses = socket.getaddrinfo(
            PX500_CREATOR_HOST,
            443,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return args

    candidates = list(dict.fromkeys(item[4][0] for item in addresses))
    address = _first_reachable_ipv4(candidates)
    if address:
        args.append(f"--host-resolver-rules=MAP {PX500_CREATOR_HOST} {address}")
    return args


def _first_reachable_ipv4(addresses: list[str]) -> Optional[str]:
    for address in addresses:
        connection = None
        try:
            connection = socket.create_connection((address, 443), timeout=0.75)
            return address
        except OSError:
            continue
        finally:
            if connection is not None:
                connection.close()
    return addresses[0] if addresses else None


def get_context(platform: str, playwright, *, prefer_system_chrome: bool = True) -> BrowserContext:
    user_data = SESSION_DIR / platform
    user_data.mkdir(parents=True, exist_ok=True)
    os.chmod(user_data, 0o700)
    options = {
        "headless": False,
        "slow_mo": 80,
        "viewport": {"width": 1280, "height": 900},
        "args": _browser_args(platform),
        "ignore_default_args": ["--enable-automation"],
    }
    try:
        if not prefer_system_chrome:
            raise PlaywrightError("bundled Chromium requested")
        ctx = playwright.chromium.launch_persistent_context(
            str(user_data), channel="chrome", **options
        )
    except PlaywrightError as chrome_error:
        try:
            ctx = playwright.chromium.launch_persistent_context(str(user_data), **options)
        except PlaywrightError:
            raise RuntimeError(
                "Could not launch Google Chrome or Playwright Chromium. "
                "Install one with `python -m playwright install chromium`."
            ) from chrome_error
    # Inject stealth patches into every new page
    ctx.add_init_script(_STEALTH_SCRIPT)
    return ctx


def ensure_logged_in(
    page: Page,
    is_logged_in: Callable[[], bool],
    login_url: str,
    *,
    poll_logged_in: Optional[Callable[[], bool]] = None,
    prepare_login: Optional[Callable[[], None]] = None,
) -> None:
    poll_check = poll_logged_in or is_logged_in
    if not is_logged_in():
        print(f"Browser opened. Please log in at: {login_url}", flush=True)
        try:
            page.goto(login_url, wait_until="commit", timeout=30_000)
        except PlaywrightTimeout:
            # Some contributor portals never finish the load event. Once
            # navigation has started, keep the browser open for manual login.
            pass
        if prepare_login is not None:
            prepare_login()
        try:
            print("Press Enter here when done...", flush=True)
            input()
        except EOFError:
            # No TTY (background process) — poll until the user logs in via the browser.
            print("Waiting for login in browser (up to 5 minutes)...", flush=True)
            for _ in range(60):
                page.wait_for_timeout(5_000)
                if poll_check():
                    return
        if not poll_check():
            raise RuntimeError("Login not detected. Please log in and retry.")
