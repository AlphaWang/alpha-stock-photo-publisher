"""
contributor.gettyimages.com upload automation (iStock + Getty Images).

Uploading here automatically distributes content to both iStock and Getty Images.

Upload flow (contributor.gettyimages.com):
  1. Navigate to the upload page
  2. Click the "Add files" button → file chooser; select ALL images at once
  3. Wait for all uploads to complete
  4. For each image: click thumbnail → fill Title and Keywords in the side panel
  5. Leave prepared assets for contributor review; automatic submission is disabled

NOTE: Selectors based on contributor.gettyimages.com UI as of 2026-04.
      Run `python3 debug_selectors.py istock` to verify/update them if the site changes.
"""

import json
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in
from .status import UploadStatus

LOGIN_URL  = "https://esp.gettyimages.com/"
UPLOAD_URL = "https://esp.gettyimages.com/"

# Map Shutterstock category1 → Getty Images category label
_CATEGORY_MAP: dict[str, str] = {
    "Nature":       "Nature",
    "Travel":       "Travel",
    "Architecture": "Buildings & Architecture",
    "Buildings":    "Buildings & Architecture",
    "Animals":      "Animals/Wildlife",
    "Wildlife":     "Animals/Wildlife",
    "Food":         "Food and Drink",
    "Lifestyle":    "People",
    "Sports":       "Sports",
    "Medical":      "Healthcare & Medical",
    "Holidays":     "Holidays",
    "Business":     "Business",
    "People":       "People",
}
def _has_logged_in_session(page: Page) -> bool:
    url = page.url.lower()
    return (
        url.startswith("https://esp.gettyimages.com")
        and "login" not in url
        and "signin" not in url
    )


def _is_logged_in(page: Page) -> bool:
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15_000)
        return _has_logged_in_session(page)
    except PWTimeout:
        return False


def ensure_login(context: BrowserContext) -> None:
    """Check login once before batch upload. Opens a temp page, then closes it."""
    page = context.new_page()
    try:
        ensure_logged_in(
            page,
            lambda: _is_logged_in(page),
            LOGIN_URL,
            poll_logged_in=lambda: _has_logged_in_session(page),
        )
    finally:
        page.close()


def _resolve_category(category1: str) -> Optional[str]:
    for key, cat in _CATEGORY_MAP.items():
        if key.lower() in category1.lower():
            return cat
    return None


def _auto_review_reason(metadata: dict) -> str:
    title = metadata.get("title_en") or metadata.get("description_en", "")
    if not str(title).strip():
        return "title is empty"
    if not metadata.get("keywords_en", [])[:50]:
        return "keywords are empty"
    release_notes = str(metadata.get("release_notes", "")).strip()
    release_status = str(metadata.get("release_status", "unknown")).strip().lower()
    if release_status != "clear":
        return f"release status is {release_status or 'unknown'}"
    if release_notes:
        return f"release review required — {release_notes}"
    if _resolve_category(str(metadata.get("category1", ""))) is None:
        return "category cannot be mapped to Getty/iStock"
    return ""


def _wait_for_uploads(page: Page, count: int) -> None:
    """Wait for all uploads to finish (progress indicators appear then disappear)."""
    # Wait for upload indicators to appear
    try:
        page.wait_for_function(
            # TODO: replace selector with actual upload-progress indicator found via debug_selectors.py
            "() => document.querySelector('[class*=\"progress\"], [class*=\"uploading\"]') !== null",
            timeout=30_000,
        )
    except PWTimeout:
        pass  # upload completed before we could detect it starting

    timeout = max(600_000, count * 5 * 60 * 1000)
    page.wait_for_function(
        # TODO: replace selector with actual upload-progress indicator found via debug_selectors.py
        "() => document.querySelector('[class*=\"progress\"], [class*=\"uploading\"]') === null",
        timeout=timeout,
    )
    page.wait_for_timeout(2_000)


def _find_asset_card(page: Page, img: Path):
    """Return a card only when it can be tied to this filename."""
    filename = json.dumps(img.name, ensure_ascii=False)
    stem = json.dumps(img.stem, ensure_ascii=False)
    return page.locator(
        f"[data-filename={filename}], [title={filename}], [alt={filename}], "
        f"[data-testid*='asset']:has-text({stem})"
    ).first


def _fill_metadata(page: Page, img: Path, metadata: dict) -> bool:
    """Fill required metadata, returning False if any required field fails."""
    title = (metadata.get("title_en") or metadata.get("description_en", ""))[:200]
    keywords = metadata.get("keywords_en", [])[:50]
    release_notes = str(metadata.get("release_notes", "")).strip()
    release_status = str(metadata.get("release_status", "unknown")).strip().lower()
    if not title or not keywords:
        print(f"  [review] {img.name}: title or keywords are empty", flush=True)
        return False
    if release_status != "clear":
        print(f"  [review] {img.name}: release status is {release_status or 'unknown'}", flush=True)
        return False
    if release_notes:
        print(f"  [review] {img.name}: release review required — {release_notes}", flush=True)
        return False

    try:
        # TODO: verify selector via debug_selectors.py istock
        ta = page.locator("input[name='title'], textarea[name='title'], [data-testid='title-input']").first
        ta.wait_for(state="visible", timeout=10_000)
        ta.click()
        ta.fill(title)
        # Force React to register the value if fill() raced with a re-render
        if ta.input_value() != title:
            ta.evaluate(
                """(el, val) => {
                    const setter = Object.getOwnPropertyDescriptor(
                        el.tagName === 'TEXTAREA'
                            ? window.HTMLTextAreaElement.prototype
                            : window.HTMLInputElement.prototype,
                        'value'
                    ).set;
                    setter.call(el, val);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                title,
            )
        page.wait_for_timeout(200)
    except Exception as e:
        print(f"  [warn] title field failed for {img.name}: {e}", flush=True)
        return False

    # Keywords — up to 50, comma-separated
    try:
        # TODO: verify selector via debug_selectors.py istock
        kw_input = page.locator(
            "input[name='keywords'], [data-testid='keywords-input'], input[placeholder*='keyword' i]"
        ).first
        kw_input.wait_for(state="visible", timeout=10_000)
        kw_input.click()
        kw_input.fill(", ".join(keywords))
        kw_input.press("Enter")
        page.wait_for_timeout(300)
    except Exception as e:
        print(f"  [warn] keywords field failed for {img.name}: {e}", flush=True)
        return False

    # Category — single select
    category = _resolve_category(metadata.get("category1", ""))
    if category is None:
        print(f"  [review] category cannot be mapped for {img.name}", flush=True)
        return False
    try:
        # TODO: verify selector via debug_selectors.py istock
        cat_btn = page.locator("[data-testid='category-select'], [aria-label*='category' i]").first
        if cat_btn.count() == 0:
            print(f"  [warn] category field not found for {img.name}", flush=True)
            return False
        cat_btn.click()
        page.locator(f"li:has-text('{category}'), option:has-text('{category}')").first.click(timeout=5_000)
        page.wait_for_timeout(300)
    except Exception as e:
        print(f"  [warn] category field failed for {img.name}: {e}", flush=True)
        return False
    return True


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, UploadStatus]:
    """Upload all images, fill metadata per image, then submit the batch."""
    results = {img.name: UploadStatus.FAILED for img, _ in pairs}
    eligible_pairs = []
    for img, metadata in pairs:
        reason = _auto_review_reason(metadata)
        if reason:
            print(f"  [review] Getty/iStock skipped {img.name}: {reason}", flush=True)
            results[img.name] = UploadStatus.NEEDS_REVIEW
        else:
            eligible_pairs.append((img, metadata))
    if not eligible_pairs:
        return results

    pairs = eligible_pairs
    page = context.new_page()
    total = len(pairs)
    fill_idx = -1

    try:
        # Navigate to upload page (may redirect to dashboard if UPLOAD_URL doesn't exist)
        for attempt in range(3):
            try:
                page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=20_000)
                break
            except PWTimeout:
                if attempt == 2:
                    raise
                page.wait_for_timeout(2_000)

        # Trigger file chooser via the "Add files" / "Upload" button
        # TODO: verify selector via debug_selectors.py istock
        upload_btn = page.locator(
            "button:has-text('Add files'), button:has-text('Add Files'), "
            "button:has-text('Upload'), [data-testid='upload-button'], "
            "[data-testid='add-files-button'], label[for*='file'], label[for*='upload']"
        )
        upload_btn.first.wait_for(state="visible", timeout=15_000)
        with page.expect_file_chooser(timeout=10_000) as fc_info:
            upload_btn.first.click()
        fc_info.value.set_files([str(img) for img, _ in pairs])

        print(f"  Uploading {total} image(s) to Getty Images / iStock...", flush=True)
        _wait_for_uploads(page, total)
        # Fill metadata only after tying a visible asset card to the exact filename.
        ready_names: list[str] = []
        for fill_idx, (img, metadata) in enumerate(pairs):
            # Locate the image card/thumbnail by filename
            # TODO: verify card selector via debug_selectors.py istock
            try:
                card = _find_asset_card(page, img)
                if card.count() == 0:
                    print(f"  [review] could not identify asset card for {img.name}", flush=True)
                    results[img.name] = UploadStatus.NEEDS_REVIEW
                    continue
                card.scroll_into_view_if_needed()
                card.click()
                page.wait_for_timeout(800)
                results[img.name] = UploadStatus.UPLOADED
            except Exception as e:
                print(f"  [warn] could not locate card for {img.name}: {e}", flush=True)
                results[img.name] = UploadStatus.NEEDS_REVIEW
                continue

            if _fill_metadata(page, img, metadata):
                ready_names.append(img.name)
                print(f"  [{fill_idx + 1}/{total}] ready {img.name}", flush=True)
            else:
                print(f"  [{fill_idx + 1}/{total}] review required {img.name}", flush=True)

        # Selectors and submission scope remain experimental. Preserve prepared
        # work as a draft and require contributor review instead of auto-submit.
        if ready_names:
            print(
                "  [review] Getty/iStock metadata prepared; automatic submission is disabled",
                flush=True,
            )

    except Exception as e:
        step = f"at image {fill_idx + 1}" if fill_idx >= 0 else "before fill loop"
        print(f"  ✗ Getty/iStock batch failed {step}: {e}", flush=True)
    finally:
        page.close()

    return results


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    """Single-image upload. Delegates to upload_batch."""
    results = upload_batch([(image_path, metadata)], context)
    return results.get(image_path.name, UploadStatus.FAILED).completed
