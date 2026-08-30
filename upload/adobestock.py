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
import warnings
from typing import Optional

from PIL import Image
from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in
from .confirmation import wait_for_success_text
from .status import UploadStatus
from metadata_core import commercial_submission_review_reason, platform_category

PORTAL_URL = "https://contributor.stock.adobe.com/"
LOGIN_URL = PORTAL_URL

_MIN_PIXELS = 4_000_000
_MAX_PIXELS = 100_000_000
_MAX_FILE_BYTES = 45_000_000

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
def _resolve_category(category1: str) -> Optional[str]:
    for key, val in _CATEGORY_MAP.items():
        if key.lower() in category1.lower():
            return val
    return None


def _category_for_metadata(meta: dict) -> Optional[str]:
    explicit = platform_category(meta, "adobestock")
    if explicit:
        return str(explicit)
    return _resolve_category(str(meta.get("category1", "")))


def _auto_review_reason(meta: dict) -> str:
    if not str(meta.get("title_en", "")).strip():
        return "title is empty"
    keyword_count = len(meta.get("keywords_en", [])[:49])
    if keyword_count < 5:
        return f"only {keyword_count} keywords (min 5 required)"
    commercial_reason = commercial_submission_review_reason(meta)
    if commercial_reason:
        return commercial_reason
    if _category_for_metadata(meta) is None:
        return "category cannot be mapped to Adobe Stock"
    return ""


def _technical_review_reason(image_path: Path) -> str:
    """Return an Adobe photo-spec violation that requires manual preparation."""
    try:
        file_size = image_path.stat().st_size
    except OSError as exc:
        return f"image cannot be read ({exc})"
    if file_size > _MAX_FILE_BYTES:
        return f"file is {file_size / 1_000_000:.1f}MB (Adobe maximum is 45MB)"

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(image_path) as image:
                image_format = image.format
                width, height = image.size
    except Exception as exc:
        return f"image cannot be inspected ({exc})"

    if image_format != "JPEG":
        return f"file format is {image_format or 'unknown'} (Adobe photos require JPEG)"
    pixels = width * height
    if pixels < _MIN_PIXELS:
        return f"image is {pixels / 1_000_000:.2f}MP (Adobe minimum is 4MP)"
    if pixels > _MAX_PIXELS:
        return f"image is {pixels / 1_000_000:.2f}MP (Adobe maximum is 100MP)"
    return ""


def _has_logged_in_session(page: Page) -> bool:
    url = page.url.lower()
    if "contributor.stock.adobe.com" not in url or "login" in url:
        return False
    try:
        # Adobe first renders the contributor shell, then may asynchronously
        # redirect to federated sign-in.  Require contributor UI as well as
        # the URL so that transient shell is not mistaken for a session.
        return page.locator(
            "button:has-text('Upload'), a[href*='/uploads']"
        ).count() > 0
    except Exception:
        return False


def _is_logged_in(page: Page) -> bool:
    try:
        page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=20_000)
        if "login" in page.url or "account.adobe.com" in page.url:
            return False
        return _has_logged_in_session(page)
    except PWTimeout:
        return False


def _navigate_to_uploads(page: Page) -> None:
    """Navigate to the uploads page without starting a new upload."""
    from urllib.parse import urlparse
    page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=20_000)
    page.wait_for_timeout(2_000)

    # Extract locale from the redirected URL (e.g. /en/, /de/)
    parsed = urlparse(page.url)
    parts = parsed.path.strip("/").split("/")
    locale = parts[0] if parts and 2 <= len(parts[0]) <= 5 else "en"
    uploads_url = f"{parsed.scheme}://{parsed.netloc}/{locale}/uploads"
    page.goto(uploads_url, wait_until="domcontentloaded", timeout=20_000)


def _open_upload_modal(page: Page) -> None:
    """Click Upload and wait for Adobe's file-drop modal."""
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


def _total_asset_count(page: Page) -> int:
    """Read the gallery total, falling back to the current page's tile count."""
    try:
        text = page.locator("button:has-text('File types: All')").first.inner_text()
        match = re.search(r"\((\d+)\)", text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return _count_tiles(page)


def _wait_for_uploaded_tiles(
    page: Page,
    pre_count: int,
    requested_count: int,
    *,
    timeout_ms: int = 180_000,
    stable_ms: int = 30_000,
    poll_ms: int = 2_000,
) -> int:
    """Wait for accepted uploads without requiring every file to become a tile."""
    expected = pre_count + requested_count
    last_count = pre_count
    stable_for = 0
    elapsed = 0
    while elapsed <= timeout_ms:
        current = _total_asset_count(page)
        if current >= expected:
            return current
        if current != last_count:
            last_count = current
            stable_for = 0
        elif current > pre_count and stable_for >= stable_ms:
            print(
                f"  [warn] Adobe created {current - pre_count}/{requested_count} "
                "new tile(s); continuing with accepted files",
                flush=True,
            )
            return current
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
        stable_for += poll_ms

    current = _total_asset_count(page)
    if current > pre_count:
        print(
            f"  [warn] Adobe created {current - pre_count}/{requested_count} "
            "new tile(s) before timeout; continuing with accepted files",
            flush=True,
        )
        return current
    raise TimeoutError("Adobe did not create any upload tiles before timeout")


def _extract_original_filename(footer: str) -> Optional[str]:
    match = re.search(
        r"Original name\(s\):\s*(.+?)(?:\s*Actions:|[\r\n]|$)", footer
    )
    return match.group(1).strip() if match else None


def _go_to_tile_page(page: Page, page_number: int) -> None:
    if page_number == 1 and _total_asset_count(page) <= 100:
        return
    page_input = page.locator("input[name='searchPage']").first
    page_input.fill(str(page_number))
    page_input.press("Enter")
    page.wait_for_timeout(1_500)


def _build_current_page_tile_map(page: Page, page_number: int) -> dict[str, tuple[int, int]]:
    """Scan the visible page and return filename → (page, tile index)."""
    mapping: dict[str, tuple[int, int]] = {}
    tiles = page.locator(_TILE_SEL)
    for idx in range(tiles.count()):
        try:
            tiles.nth(idx).click()
            page.wait_for_timeout(250)
            footer = page.locator("[data-t='asset-sidebar-footer']").inner_text(timeout=3_000)
            filename = _extract_original_filename(footer)
            if filename:
                mapping[filename] = (page_number, idx)
        except Exception:
            pass
    return mapping


def _build_tile_map(page: Page) -> dict[str, tuple[int, int]]:
    """Scan every Adobe gallery page, not just the first 100 tiles."""
    total = _total_asset_count(page)
    page_count = max(1, (total + 99) // 100)
    mapping: dict[str, tuple[int, int]] = {}
    for page_number in range(1, page_count + 1):
        _go_to_tile_page(page, page_number)
        mapping.update(_build_current_page_tile_map(page, page_number))
    _go_to_tile_page(page, 1)
    return mapping


def _upload_button_enabled(page: Page) -> bool:
    button = page.locator("button:has-text('Upload')").first
    if button.count() == 0:
        return False
    classes = button.get_attribute("class") or ""
    return not button.is_disabled() and "is-disabled" not in classes


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
    if not title:
        print(f"  [review] {img.name}: title is empty")
        return False
    if len(keywords) < 5:
        print(f"  [review] {img.name}: only {len(keywords)} keywords (min 5 required)")
        return False
    commercial_reason = commercial_submission_review_reason(meta)
    if commercial_reason:
        print(f"  [review] {img.name}: {commercial_reason}")
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
    category = _category_for_metadata(meta)
    if category is None:
        print(f"  [review] {img.name}: category cannot be mapped to Adobe Stock")
        return False
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
        try:
            # The current Adobe UI no longer shows the old Saved toast.  Once
            # persistence completes, Save work returns to its disabled state.
            page.wait_for_function(
                "() => { const b = document.querySelector('[data-t=\"save-work\"]'); return b && b.disabled; }",
                timeout=10_000,
            )
            return True
        except PWTimeout:
            return wait_for_success_text(page, ["saved", "work saved", "已保存"])
    except PWTimeout:
        print(f"  [warn] {img.name}: Save work still disabled — check required fields")
        return False


def _fill_mapped_metadata(
    page: Page,
    pairs: list[tuple[Path, dict]],
    tile_map: dict[str, tuple[int, int]],
    results: dict[str, UploadStatus],
) -> list[str]:
    """Fill metadata for mapped assets, navigating Adobe's gallery pages."""
    saved_names: list[str] = []
    current_page = 0
    for count, (img, meta) in enumerate(pairs, 1):
        location = tile_map.get(img.name)
        if location is None:
            print(
                f"  [{count}/{len(pairs)}] ✗ {img.name} — tile not found in map",
                flush=True,
            )
            continue
        page_number, tile_idx = location
        try:
            if page_number != current_page:
                _go_to_tile_page(page, page_number)
                current_page = page_number
            page.locator(_TILE_SEL).nth(tile_idx).click()
            page.wait_for_timeout(1_000)
            results[img.name] = UploadStatus.UPLOADED
            if _fill_metadata(page, img, meta):
                saved_names.append(img.name)
                print(f"  [{count}/{len(pairs)}] saved {img.name}", flush=True)
            else:
                print(
                    f"  [{count}/{len(pairs)}] review required {img.name}",
                    flush=True,
                )
        except Exception as exc:
            print(f"  [{count}/{len(pairs)}] ✗ {img.name} — {exc}", flush=True)
    return saved_names


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, UploadStatus]:
    """Upload all images via the hidden file input, then fill metadata tile by tile."""
    results = {img.name: UploadStatus.FAILED for img, _ in pairs}
    eligible_pairs = []
    for img, meta in pairs:
        reason = _technical_review_reason(img) or _auto_review_reason(meta)
        if reason:
            print(f"  [review] Adobe skipped {img.name}: {reason}", flush=True)
            results[img.name] = UploadStatus.NEEDS_REVIEW
        else:
            eligible_pairs.append((img, meta))
    if not eligible_pairs:
        return results

    pairs = eligible_pairs
    page = context.new_page()

    try:
        ensure_logged_in(
            page,
            lambda: _is_logged_in(page),
            LOGIN_URL,
            poll_logged_in=lambda: _has_logged_in_session(page),
        )
        _navigate_to_uploads(page)

        pre_count = _total_asset_count(page)
        tile_map = _build_tile_map(page)
        existing_pairs = [(img, meta) for img, meta in pairs if img.name in tile_map]
        missing_pairs = [(img, meta) for img, meta in pairs if img.name not in tile_map]
        saved_names: list[str] = []

        # Always repair/resume assets already accepted by Adobe before trying
        # new transfers. Otherwise a disabled Upload button or a rejected file
        # leaves accepted assets with empty metadata.
        if existing_pairs:
            print(
                f"  Resuming {len(existing_pairs)} existing Adobe Stock upload(s)...",
                flush=True,
            )
            saved_names.extend(
                _fill_mapped_metadata(page, existing_pairs, tile_map, results)
            )

        if missing_pairs:
            _go_to_tile_page(page, 1)
            if not _upload_button_enabled(page):
                print(
                    f"  [review] Adobe Upload is disabled; {len(missing_pairs)} "
                    "file(s) remain local until ready drafts are submitted or removed",
                    flush=True,
                )
            else:
                _open_upload_modal(page)
                # Trigger file chooser via Browse. Setting the hidden input directly
                # does not fire Adobe's React change handler.
                browse_btn = page.locator(
                    "button._9-Xiq_spectrum-Link, a:has-text('Browse'), "
                    "button:has-text('Browse')"
                ).first
                browse_btn.wait_for(state="visible", timeout=10_000)
                with page.expect_file_chooser(timeout=10_000) as fc_info:
                    browse_btn.click()
                fc_info.value.set_files([str(img) for img, _ in missing_pairs])
                print(
                    f"  Uploading {len(missing_pairs)} file(s) to Adobe Stock...",
                    flush=True,
                )

                _wait_for_uploaded_tiles(page, pre_count, len(missing_pairs))
                page.wait_for_timeout(2_000)
                # Adobe inserts recent uploads at the front, so rebuild across
                # every gallery page and fill only files actually accepted.
                tile_map = _build_tile_map(page)
                accepted_pairs = [
                    (img, meta) for img, meta in missing_pairs if img.name in tile_map
                ]
                saved_names.extend(
                    _fill_mapped_metadata(page, accepted_pairs, tile_map, results)
                )

        # A global submit action may include pre-existing drafts. Leave this batch
        # saved for review unless the uploads page was empty before this run.
        try:
            if not saved_names:
                print("  [warn] No Adobe assets were ready to submit", flush=True)
                return results
            if pre_count > 0:
                for name in saved_names:
                    results[name] = UploadStatus.DRAFT_SAVED
                print(
                    "  [review] Adobe had pre-existing drafts; new work was saved but not submitted",
                    flush=True,
                )
                return results
            page.wait_for_function(
                "() => { const b = document.querySelector('[data-t=\"submit-moderation-button\"]'); return b && !b.disabled; }",
                timeout=10_000,
            )
            page.locator("button[data-t='submit-moderation-button']").first.click()
            if wait_for_success_text(
                page, ["submitted", "submission successful", "已提交"]
            ):
                for name in saved_names:
                    results[name] = UploadStatus.SUBMITTED
                print("  Submitted to Adobe Stock moderation.", flush=True)
            else:
                for name in saved_names:
                    results[name] = UploadStatus.DRAFT_SAVED
                print("  [review] Adobe submission was not confirmed; work remains saved", flush=True)
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
    return upload_batch([(image_path, metadata)], context).get(
        image_path.name, UploadStatus.FAILED
    ).completed
