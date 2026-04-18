"""
500px.com.cn contributor upload automation.

Upload flow: click upload button → select file → fill metadata → publish.

NOTE: Selectors based on 500px.com.cn UI as of 2026-04. Update if the site changes.
"""

from pathlib import Path

from playwright.sync_api import BrowserContext, TimeoutError as PWTimeout

from .browser import ensure_logged_in

LOGIN_URL = "https://500px.com.cn/"
UPLOAD_URL = "https://500px.com.cn/"


def _is_logged_in(page) -> bool:
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15_000)
        # Logged-in users see an avatar/profile menu; guests see a login button.
        return page.locator(".avatar, [class*='userAvatar'], a[href*='/profile']").count() > 0
    except PWTimeout:
        return False


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    page = context.new_page()
    try:
        ensure_logged_in(page, lambda: _is_logged_in(page), LOGIN_URL)

        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=20_000)

        # Trigger upload via hidden file input
        with page.expect_file_chooser() as fc_info:
            page.locator("input[type='file']").first.set_input_files(str(image_path))

        print(f"  Uploading {image_path.name}...")

        # Wait for metadata form / edit dialog
        page.wait_for_selector("input[name='title'], input[placeholder*='标题']", timeout=120_000)

        # Title (Chinese)
        title_input = page.locator("input[name='title'], input[placeholder*='标题']").first
        title_input.fill(metadata.get("title_zh", ""))

        # Description (Chinese, ≤50 chars enforced by photo_desc.py)
        desc_selector = "textarea[name='description'], textarea[placeholder*='描述']"
        if page.locator(desc_selector).count() > 0:
            page.locator(desc_selector).first.fill(metadata.get("description_zh", ""))

        # Tags / keywords (Chinese, ≤35, space or comma separated)
        tag_selector = "input[name='tags'], input[placeholder*='标签'], input[placeholder*='关键词']"
        if page.locator(tag_selector).count() > 0:
            tags = " ".join(metadata.get("keywords_zh", []))
            page.locator(tag_selector).first.fill(tags)

        # Publish / submit
        page.locator("button:has-text('发布'), button:has-text('上传'), button[type='submit']").first.click()
        page.wait_for_selector(".success, [class*='success'], [data-status='published']", timeout=30_000)

        print(f"  ✓ 500px: {image_path.name}")
        return True

    except Exception as e:
        print(f"  ✗ 500px: {image_path.name} — {e}")
        return False
    finally:
        page.close()
