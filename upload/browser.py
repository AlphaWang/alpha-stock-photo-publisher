from pathlib import Path
from typing import Callable

from playwright.sync_api import BrowserContext, Page

try:
    from playwright_stealth import stealth_sync
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False

SESSION_DIR = Path(__file__).parent.parent / ".session"

# Suppress navigator.webdriver and other automation markers that trigger bot detection.
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
window.chrome = {runtime: {}};
"""


def get_context(platform: str, playwright) -> BrowserContext:
    user_data = SESSION_DIR / platform
    user_data.mkdir(parents=True, exist_ok=True)
    ctx = playwright.chromium.launch_persistent_context(
        str(user_data),
        channel="chrome",          # use real Chrome, not Chromium
        headless=False,
        slow_mo=80,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    # Inject stealth patches into every new page
    ctx.add_init_script(_STEALTH_SCRIPT)
    return ctx


def ensure_logged_in(page: Page, is_logged_in: Callable[[], bool], login_url: str) -> None:
    if not is_logged_in():
        print(f"Browser opened. Please log in at: {login_url}")
        print("Press Enter here when done...")
        page.goto(login_url)
        input()
        if not is_logged_in():
            raise RuntimeError("Login not detected after user confirmation. Aborting.")
