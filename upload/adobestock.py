"""
Adobe Stock contributor upload automation.
Portal: https://contributor.stock.adobe.com/

Upload flow:
  1. Navigate to uploads page (locale prefix varies — let Adobe redirect)
  2. Click Upload button → modal opens → set files on hidden input[name='file']
  3. Wait for 'File types: All (N)' to reach expected count
  4. For each image: click tile by index → fill textarea[name='title'], #content-keywords-ui-textarea,
     category FieldButton → Save work
  5. Click Submit

NOTE: Selectors based on contributor.stock.adobe.com UI as of 2026-04. Update if the site changes.
Adobe uses the Spectrum design system; category picker is a custom FieldButton, not a native <select>.
"""

from pathlib import Path
import re

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in

PORTAL_URL = "https://contributor.stock.adobe.com/"
LOGIN_URL = PORTAL_URL

# Adobe Stock categories (21 options as of 2026-04)
_CATEGORY_MAP: dict[str, str] = {
    "Abstract":             "States of Mind",
    "Animals/Wildlife":     "Animals",
    "Arts":                 "Culture and Religion",
    "Backgrounds/Textures": "The Environment",
    "Beauty/Fashion":       "Lifestyle",
    "Buildings/Landmarks":  "Buildings and Architecture",
    "Business/Finance":     "Business",
    "Celebrities":          "People",
    "Education":            "Science",
    "Food and drink":       "Food",
    "Healthcare/Medical":   "Science",
    "Holidays":             "Culture and Religion",
    "Industrial":           "Industry",
    "Interiors":            "Buildings and Architecture",
    "Miscellaneous":        "Lifestyle",
    "Nature":               "The Environment",
    "Objects":              "Lifestyle",
    "Parks/Outdoor":        "Landscapes",
    "People":               "People",
    "Religion":             "Culture and Religion",
    "Science":              "Science",
    "Signs/Symbols":        "Graphic Resources",
    "Sports/Recreation":    "Sports",
    "Technology":           "Technology",
    "Transportation":       "Transport",
    "Travel":               "Travel",
    "Vintage":              "Lifestyle",
}
_DEFAULT_CATEGORY = "The Environment"


def _resolve_category(category1: str) -> str:
    for key, val in _CATEGORY_MAP.items():
        if key.lower() in category1.lower():
            return val
    return _DEFAULT_CATEGORY


def _auto_review_reason(meta: dict) -> str:
    if not str(meta.get("title_en", "")).strip():
        return "title is empty"
    keyword_count = len(meta.get("keywords_en", [])[:49])
    if keyword_count < 5:
        return f"only {keyword_count} keywords (min 5 required)"
    release_notes = str(meta.get("release_notes", "")).strip()
    if release_notes:
        return f"release review required — {release_notes}"
    return ""


def _is_logged_in(page: Page) -> bool:
    try:
        page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=20_000)
        if "login" in page.url or "account.adobe.com" in page.url:
            return False
        return "contributor.stock.adobe.com" in page.url
    except PWTimeout:
        return False


def _navigate_to_uploads(page: Page) -> None:
    """Navigate to the uploads page, then click Upload to open the file-drop modal."""
    from urllib.parse import urlparse
    page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=20_000)
    page.wait_for_timeout(2_000)

    # Extract locale from the redirected URL (e.g. /en/, /de/)
    parsed = urlparse(page.url)
    parts = parsed.path.strip("/").split("/")
    locale = parts[0] if parts and 2 <= len(parts[0]) <= 5 else "en"
    uploads_url = f"{parsed.scheme}://{parsed.netloc}/{locale}/uploads"
    page.goto(uploads_url, wait_until="domcontentloaded", timeout=20_000)

    # Click Upload button to open the modal (exposes the hidden file input).
    # Adobe Spectrum adds is-disabled class while previous uploads are still processing.
    # Poll for up to 3 min, then try anyway (click will fail gracefully if still disabled).
    upload_btn = page.locator("button:has-text('Upload')").first
    upload_btn.wait_for(state="visible", timeout=30_000)
    for _ in range(60):
        cls = upload_btn.get_attribute("class") or ""
        if "is-disabled" not in cls:
            break
        page.wait_for_timeout(3_000)
    else:
        print(
            "  [warn] Upload button still disabled after 3 min — "
            "clear pending drafts at https://contributor.stock.adobe.com/en/uploads",
            flush=True,
        )
    upload_btn.click()
    page.wait_for_timeout(1_000)


_TILE_SEL = "div[role='option'][title='Content tile']"


def _count_tiles(page: Page) -> int:
    return page.locator(_TILE_SEL).count()


def _build_tile_map(page: Page, start: int, total: int) -> dict[str, int]:
    """Scan newly uploaded tiles and return filename → tile-index mapping."""
    mapping: dict[str, int] = {}
    tiles = page.locator(_TILE_SEL)
    for idx in range(start, total):
        try:
            tiles.nth(idx).click()
            page.wait_for_timeout(400)
            footer = page.locator("[data-t='asset-sidebar-footer']").inner_text(timeout=3_000)
            m = re.search(r"Original name\(s\): (.+)", footer)
            if m:
                mapping[m.group(1).strip()] = idx
        except Exception:
            pass
    return mapping


def _set_category(page: Page, category: str) -> bool:
    """Select the category via the Spectrum FieldButton dropdown."""
    page.locator("[data-t='content-tagger-category-select']").click()
    page.wait_for_timeout(500)
    option = page.locator(f"[role='option']:has-text('{category}')").first
    try:
        option.click(timeout=5_000)
    except PWTimeout:
        print(f"  [warn] category option '{category}' not found in dropdown")
        return False
    page.wait_for_timeout(300)
    return True


def _fill_metadata(page: Page, img: Path, meta: dict) -> bool:
    """Fill and save one tile, returning True only after Save work succeeds."""
    page.wait_for_timeout(600)

    # Title — data-t="asset-title-content-tagger", max 200 chars
    title = meta.get("title_en", "")[:200]
    keywords = meta.get("keywords_en", [])[:49]
    release_notes = str(meta.get("release_notes", "")).strip()
    if not title:
        print(f"  [review] {img.name}: title is empty")
        return False
    if len(keywords) < 5:
        print(f"  [review] {img.name}: only {len(keywords)} keywords (min 5 required)")
        return False
    if release_notes:
        print(f"  [review] {img.name}: release review required — {release_notes}")
        return False

    try:
        title_ta = page.locator("[data-t='asset-title-content-tagger']").first
        title_ta.wait_for(state="visible", timeout=15_000)
        title_ta.fill(title)
    except PWTimeout:
        print(f"  [warn] {img.name}: title textarea not found")
        return False

    # "Recognizable people or property?" — required before Save is enabled; click "No" switch
    try:
        no_switch = page.locator("label:has([data-t='has-release-no']) span.switch__body").first
        if no_switch.count() == 0:
            print(f"  [warn] {img.name}: release declaration control not found")
            return False
        no_switch.click()
        page.wait_for_timeout(200)
    except Exception as e:
        print(f"  [warn] {img.name}: release declaration failed — {e}")
        return False

    # Keywords — erase Sensei pre-fills, then paste ours (min 5, max 49)
    try:
        kw_ta = page.locator("[data-t='content-keywords-ui-textarea']").first
        kw_ta.wait_for(state="visible", timeout=10_000)

        def _erase() -> None:
            btn = page.locator("[data-t='erase-all-keywords']").first
            if btn.count() > 0:
                btn.click()

        # Erase once, wait for Sensei to settle, then erase again to catch late-loaded chips
        _erase()
        page.wait_for_timeout(1_500)
        _erase()
        page.wait_for_timeout(500)

        kw_ta.click()
        kw_ta.fill(", ".join(keywords))
        kw_ta.press("Enter")
        page.wait_for_timeout(1_000)
    except PWTimeout:
        print(f"  [warn] {img.name}: keywords textarea not found")
        return False

    # Category — try hidden native <select> first (force), fall back to Spectrum FieldButton
    category = _resolve_category(meta.get("category1", ""))
    try:
        cat_select = page.locator("select[name='category']").first
        if cat_select.count() > 0:
            cat_select.select_option(label=category, force=True)
            page.wait_for_timeout(300)
        elif not _set_category(page, category):
            return False
    except Exception as e:
        print(f"  [warn] {img.name}: category via native select failed ({e}), trying FieldButton")
        try:
            if not _set_category(page, category):
                return False
        except Exception as e2:
            print(f"  [warn] {img.name}: category FieldButton also failed — {e2}")
            return False

    page.wait_for_timeout(300)

    # Save — button is disabled until title + keywords + property-release are all filled
    try:
        page.wait_for_function(
            "() => { const b = document.querySelector('[data-t=\"save-work\"]'); return b && !b.disabled; }",
            timeout=15_000,
        )
        page.locator("[data-t='save-work']").first.click()
        page.wait_for_timeout(2_000)
        return True
    except PWTimeout:
        print(f"  [warn] {img.name}: Save work still disabled — check required fields")
        return False


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, bool]:
    """Upload all images via the hidden file input, then fill metadata tile by tile."""
    results = {img.name: False for img, _ in pairs}
    eligible_pairs = []
    for img, meta in pairs:
        reason = _auto_review_reason(meta)
        if reason:
            print(f"  [review] Adobe skipped {img.name}: {reason}", flush=True)
        else:
            eligible_pairs.append((img, meta))
    if not eligible_pairs:
        return results

    pairs = eligible_pairs
    page = context.new_page()

    try:
        ensure_logged_in(page, lambda: _is_logged_in(page), LOGIN_URL)
        _navigate_to_uploads(page)

        pre_count = _count_tiles(page)

        # Trigger file chooser via the Browse button in the modal, then set files.
        # set_input_files() on the hidden input alone doesn't fire React's change handler.
        browse_btn = page.locator("button._9-Xiq_spectrum-Link, a:has-text('Browse'), button:has-text('Browse')").first
        browse_btn.wait_for(state="visible", timeout=10_000)
        with page.expect_file_chooser(timeout=10_000) as fc_info:
            browse_btn.click()
        fc_info.value.set_files([str(img) for img, _ in pairs])
        print(f"  Uploading {len(pairs)} file(s) to Adobe Stock...", flush=True)

        # Wait for all new tiles to appear
        expected = pre_count + len(pairs)
        page.wait_for_function(
            f"() => document.querySelectorAll(\"{_TILE_SEL}\").length >= {expected}",
            timeout=600_000,
        )
        page.wait_for_timeout(2_000)

        # Build filename→tile-index mapping (tile order may differ from upload order)
        tile_map = _build_tile_map(page, pre_count, expected)

        # Fill metadata using the correct tile for each image
        saved_names: list[str] = []
        for count, (img, meta) in enumerate(pairs):
            tile_idx = tile_map.get(img.name)
            if tile_idx is None:
                print(f"  [{count + 1}/{len(pairs)}] ✗ {img.name} — tile not found in map", flush=True)
                continue
            try:
                page.locator(_TILE_SEL).nth(tile_idx).click()
                page.wait_for_timeout(1_000)
                if _fill_metadata(page, img, meta):
                    saved_names.append(img.name)
                    print(f"  [{count + 1}/{len(pairs)}] saved {img.name}", flush=True)
                else:
                    print(f"  [{count + 1}/{len(pairs)}] review required {img.name}", flush=True)
            except Exception as e:
                print(f"  [{count + 1}/{len(pairs)}] ✗ {img.name} — {e}", flush=True)

        # Submit all tiles (button is disabled until at least one file is saved)
        try:
            if not saved_names:
                print("  [warn] No Adobe assets were ready to submit", flush=True)
                return results
            page.wait_for_function(
                "() => { const b = document.querySelector('[data-t=\"submit-moderation-button\"]'); return b && !b.disabled; }",
                timeout=10_000,
            )
            page.locator("button[data-t='submit-moderation-button']").first.click()
            page.wait_for_timeout(3_000)
            for name in saved_names:
                results[name] = True
            print("  Submitted to Adobe Stock moderation.", flush=True)
        except PWTimeout:
            print("  [warn] Submit button still disabled — check that at least one file was saved", flush=True)
        except Exception as e:
            print(f"  [warn] Submit failed: {e}", flush=True)

    except Exception as e:
        print(f"  ✗ Adobe Stock batch upload failed — {e}", flush=True)
    finally:
        page.close()

    return results


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    """Single-image upload. Delegates to upload_batch."""
    return upload_batch([(image_path, metadata)], context).get(image_path.name, False)
