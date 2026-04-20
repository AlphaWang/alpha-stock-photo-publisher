"""
contributor.gettyimages.com upload automation (iStock + Getty Images).

Uploading here automatically distributes content to both iStock and Getty Images.

Upload flow (contributor.gettyimages.com):
  1. Navigate to the upload page
  2. Click the "Add files" button → file chooser; select ALL images at once
  3. Wait for all uploads to complete
  4. For each image: click thumbnail → fill Title and Keywords in the side panel
  5. Submit the batch

NOTE: Selectors based on contributor.gettyimages.com UI as of 2026-04.
      Run `python3 debug_selectors.py istock` to verify/update them if the site changes.
"""

from pathlib import Path

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in

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
_DEFAULT_CATEGORY = "Nature"


def _is_logged_in(page: Page) -> bool:
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15_000)
        return (
            page.url.startswith("https://esp.gettyimages.com")
            and "login" not in page.url.lower()
            and "signin" not in page.url.lower()
        )
    except PWTimeout:
        return False


def ensure_login(context: BrowserContext) -> None:
    """Check login once before batch upload. Opens a temp page, then closes it."""
    page = context.new_page()
    try:
        ensure_logged_in(page, lambda: _is_logged_in(page), LOGIN_URL)
    finally:
        page.close()


def _resolve_category(category1: str) -> str:
    for key, cat in _CATEGORY_MAP.items():
        if key.lower() in category1.lower():
            return cat
    return _DEFAULT_CATEGORY


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


def _fill_metadata(page: Page, img: Path, metadata: dict) -> None:
    """Fill Title and Keywords for the currently-selected image."""
    # Title — ≤200 chars; prefer description_en (richer), fall back to title_en
    title = metadata.get("description_en", metadata.get("title_en", ""))[:200]
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

    # Keywords — up to 50, comma-separated
    keywords = metadata.get("keywords_en", [])[:50]
    if keywords:
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

    # Category — single select
    category = _resolve_category(metadata.get("category1", ""))
    try:
        # TODO: verify selector via debug_selectors.py istock
        cat_btn = page.locator("[data-testid='category-select'], [aria-label*='category' i]").first
        if cat_btn.count() > 0:
            cat_btn.click()
            page.locator(f"li:has-text('{category}'), option:has-text('{category}')").first.click(timeout=5_000)
            page.wait_for_timeout(300)
    except Exception as e:
        print(f"  [warn] category field failed for {img.name}: {e}", flush=True)


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, bool]:
    """Upload all images, fill metadata per image, then submit the batch."""
    page = context.new_page()
    results = {img.name: False for img, _ in pairs}
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

        # Fill metadata per image
        for fill_idx, (img, metadata) in enumerate(pairs):
            # Locate the image card/thumbnail by filename
            # TODO: verify card selector via debug_selectors.py istock
            try:
                card = page.locator(
                    f"[data-filename='{img.name}'], [title='{img.name}'], "
                    f"[alt='{img.name}'], [data-testid*='asset']:has-text('{img.stem}')"
                ).first
                if card.count() == 0:
                    card = page.locator(f"text={img.stem}").first
                card.scroll_into_view_if_needed()
                card.click()
                page.wait_for_timeout(800)
            except Exception as e:
                print(f"  [warn] could not locate card for {img.name}: {e}", flush=True)

            _fill_metadata(page, img, metadata)
            print(f"  [{fill_idx + 1}/{total}] ✓ {img.name}", flush=True)
            results[img.name] = True

        # Submit the batch
        try:
            # TODO: verify submit button selector via debug_selectors.py istock
            page.locator(
                "button:has-text('Submit'), [data-testid='submit-button']"
            ).first.click(timeout=5_000)
            page.wait_for_timeout(2_000)
        except PWTimeout:
            print("  [warn] submit button not found — batch may need manual submission", flush=True)

    except Exception as e:
        step = f"at image {fill_idx + 1}" if fill_idx >= 0 else "before fill loop"
        print(f"  ✗ Getty/iStock batch failed {step}: {e}", flush=True)
    finally:
        page.close()

    return results


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    """Single-image upload. Delegates to upload_batch."""
    results = upload_batch([(image_path, metadata)], context)
    return results.get(image_path.name, False)
