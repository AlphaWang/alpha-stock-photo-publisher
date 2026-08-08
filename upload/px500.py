"""
500px.com.cn contributor upload automation.

Upload flow (creatorstudio.500px.com.cn):
  1. Click the submit-content button → modal opens
  2. Click the photo-type button → triggers file chooser; select ALL images at once
  3. Each image redirects to /draft/detail/{id} in sequence
  4. Fill title (≤50 chars), keywords (5–35), save draft, repeat

NOTE: Selectors based on 500px.com.cn creator studio UI as of 2026-04. Update if the site changes.
"""

from pathlib import Path
import json
from typing import Optional

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in

LOGIN_URL = "https://500px.com.cn/"
UPLOAD_URL = "https://creatorstudio.500px.com.cn/index"


def _is_logged_in(page: Page) -> bool:
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15_000)
        return page.locator(".avatar, [class*='userAvatar'], a[href*='/profile']").count() > 0
    except PWTimeout:
        return False


def ensure_login(context: BrowserContext) -> None:
    """Check login once before batch upload. Opens a temp page, then closes it."""
    page = context.new_page()
    try:
        ensure_logged_in(page, lambda: _is_logged_in(page), LOGIN_URL)
    finally:
        page.close()


# Cascader path: [country, state, city] for known locations.
# Structure observed: US > California > {San Francisco, Los Angeles County, San Diego, Other}
_LOCATION_PATHS: list[tuple[list[str], list[str]]] = [
    (["洛杉矶", "LA"],              ["美国", "加利福尼亚", "洛杉矶县"]),
    (["圣地亚哥", "San Diego"],     ["美国", "加利福尼亚", "圣地亚哥"]),
    (["旧金山", "San Francisco"],   ["美国", "加利福尼亚", "旧金山"]),
    (["蒙特雷", "Monterey", "卡梅尔"], ["美国", "加利福尼亚", "其他"]),
    (["加利福尼亚", "加州", "California"], ["美国", "加利福尼亚", "其他"]),
]
def _resolve_path(location_zh: str) -> Optional[list[str]]:
    """Map a free-form location string to a cascader path."""
    for keywords, path in _LOCATION_PATHS:
        if any(kw in location_zh for kw in keywords):
            return path
    return None


def _auto_review_reason(metadata: dict) -> str:
    title = metadata.get("description_zh") or metadata.get("title_zh", "")
    if not str(title).strip():
        return "title is empty"
    keyword_count = len(metadata.get("keywords_zh", [])[:35])
    if keyword_count < 5:
        return f"only {keyword_count} keywords (min 5 required)"
    location = str(metadata.get("location_zh", "")).strip()
    if _resolve_path(location) is None:
        return f"unknown shooting location: {location or '(empty)'}"
    return ""


def _navigate_cascader(page: Page, path: list[str]) -> bool:
    """Click through the 3-level location cascader. Returns True on success."""
    # Open the cascader
    picker = page.locator(".ant-cascader-picker, [class*='cascader']").first
    picker.click()
    page.wait_for_timeout(500)

    for level_idx, label in enumerate(path):
        try:
            # Wait for menu at this level to appear
            page.wait_for_selector(".ant-cascader-menu", timeout=5_000)
        except PWTimeout:
            return False

        menus = page.locator(".ant-cascader-menu")
        if menus.count() <= level_idx:
            return False

        menu = menus.nth(level_idx)
        item = menu.locator(f".ant-cascader-menu-item:has-text('{label}')").first
        if item.count() == 0:
            return False
        item.click()
        page.wait_for_timeout(300)

    return True


def _fill_location(page: Page, location_zh: str) -> bool:
    """Fill a known shooting location without inventing a fallback location."""
    path = _resolve_path(location_zh) if location_zh else None
    return bool(path and _navigate_cascader(page, path))


def _fill_metadata(page: Page, metadata: dict) -> bool:
    """Fill and save one draft, returning False when manual review is required."""
    # Dismiss any info popup
    try:
        page.locator("button:has-text('我知道了')").first.click(timeout=5_000)
    except PWTimeout:
        pass

    title = (metadata.get("description_zh") or metadata.get("title_zh", ""))[:50]
    keywords = metadata.get("keywords_zh", [])[:35]
    location = metadata.get("location_zh", "")
    if not title or len(keywords) < 5:
        print("  [review] title or required keywords are missing", flush=True)
        return False
    if _resolve_path(location) is None:
        print(f"  [review] unknown shooting location: {location or '(empty)'}", flush=True)
        return False

    # Title
    title_sel = "input[placeholder*='一句话描述'], input.right-form-title"
    page.wait_for_selector(title_sel, timeout=30_000)
    page.locator(title_sel).first.fill(title)

    # Keywords — fill input then press Enter to commit all tags at once
    kw_sel = "input[placeholder*='关键词']"
    kw_input = page.locator(kw_sel).first
    if kw_input.count() > 0:
        kw_input.fill(",".join(keywords))
        kw_input.press("Enter")
        page.wait_for_timeout(800)

    # Mark core keywords with star (non-fatal: star UI may not be present)
    core_kws = metadata.get("core_keywords_zh", [])[:5]
    for kw in core_kws:
        try:
            star_sel = f"span.ant-tag:has-text('{kw}') svg, span.ant-tag:has-text('{kw}') [class*='star']"
            page.locator(star_sel).first.click(timeout=3_000)
            page.wait_for_timeout(200)
        except PWTimeout:
            pass

    # Location — required field; try quick buttons then cascader search
    if not _fill_location(page, location):
        print(f"  [review] could not select shooting location: {location}", flush=True)
        return False

    # Accept pledge checkbox if shown
    try:
        pledge_check = page.locator("label:has-text('我已仔细阅读并承诺以上事项') input[type='checkbox']")
        if pledge_check.count() > 0 and not pledge_check.first.is_checked():
            pledge_check.first.check()
    except Exception:
        pass

    # Save as draft
    page.locator("button:has-text('保存草稿')").first.click()
    page.wait_for_timeout(2_000)
    return True


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, bool]:
    """Upload all images in one file-chooser call, then fill metadata per draft page."""
    results = {img.name: False for img, _ in pairs}
    eligible_pairs = []
    for img, metadata in pairs:
        reason = _auto_review_reason(metadata)
        if reason:
            print(f"  [review] 500px skipped {img.name}: {reason}", flush=True)
        else:
            eligible_pairs.append((img, metadata))
    if not eligible_pairs:
        return results

    pairs = eligible_pairs
    page = context.new_page()
    total = len(pairs)

    try:
        for attempt in range(3):
            try:
                page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=20_000)
                break
            except PWTimeout:
                if attempt == 2:
                    raise
                page.wait_for_timeout(2_000)

        # Open upload modal
        page.locator("button.button_cmp_main").first.click()

        # Trigger file chooser and select ALL images at once
        page.wait_for_selector("div._col:not(.disabled):has(div._qiu.picture)", timeout=10_000)
        with page.expect_file_chooser(timeout=10_000) as fc_info:
            page.locator("div._col:not(.disabled):has(div._qiu.picture)").first.click()
        fc_info.value.set_files([str(img) for img, _ in pairs])

        # Wait for the batch draft page and all image spans to be in the DOM
        page.wait_for_url("**/draft/detail/**", timeout=120_000)
        last_img = json.dumps(pairs[-1][0].name, ensure_ascii=False)
        page.wait_for_selector(f"span[title={last_img}]", timeout=60_000)

        print(f"  Uploading {total} images...")

        # Clear pre-selection: select all → deselect all → exit multi-select if active
        page.locator("text=全选").first.click()
        page.wait_for_timeout(300)
        page.locator("text=取消全选").first.click()
        page.wait_for_timeout(300)
        multisel_chk = page.locator("label:has-text('多选') input[type='checkbox']")
        if multisel_chk.count() > 0 and multisel_chk.first.is_checked():
            page.locator("text=多选").first.click()
            page.wait_for_timeout(300)

        i = -1
        for i, (img, metadata) in enumerate(pairs):
            filename = json.dumps(img.name, ensure_ascii=False)
            page.locator(f"span[title={filename}]").click()
            page.wait_for_timeout(600)
            if _fill_metadata(page, metadata):
                print(f"  [{i + 1}/{total}] saved {img.name}")
                results[img.name] = True
            else:
                print(f"  [{i + 1}/{total}] review required {img.name}")

    except Exception as e:
        step = f"at image {i + 1}" if i >= 0 else "before upload loop"
        print(f"  ✗ 500px batch failed {step}: {e}")
    finally:
        page.close()

    return results
