"""
Shutterstock contributor upload automation.
Portal: https://submit.shutterstock.com

Confirmed UI flow (from browser inspection sessions):
  1. Navigate to portfolio/not_submitted page
  2. Click top-right "Upload" button → modal opens
  3. Click "Upload assets" inside modal → native file chooser opens
  4. Set ALL image files at once via file chooser (multi-select)
  5. Navigate back to portfolio; wait until N new cards appear
  6. For each image: find card by filename text, click it
  7. Wait for edit panel (textarea[name='description']) to appear
  8. Fill description_en and keywords_en
  9. Fill Category 1 and Category 2 via MUI Select (data-testid scoped)
  10. Click Save button (data-testid='edit-dialog-save-button')
"""

from pathlib import Path

from playwright.sync_api import BrowserContext, TimeoutError as PWTimeout

from .browser import ensure_logged_in

PORTFOLIO_URL = "https://submit.shutterstock.com/portfolio/not_submitted/photo"
LOGIN_URL = "https://submit.shutterstock.com/"


def _is_logged_in(page) -> bool:
    try:
        page.goto(PORTFOLIO_URL, wait_until="domcontentloaded", timeout=20_000)
        return "login" not in page.url and page.locator("[role='tab']").count() > 0
    except PWTimeout:
        return False


def _fill_metadata(page, img: Path, meta: dict) -> None:
    """Fill description, keywords, and categories for the currently open edit panel."""
    # Wait for the panel to show THIS image's title before filling anything.
    # Without this, a React re-render caused by the card transition can clear
    # a description we already filled.
    page.wait_for_selector(f"h3:has-text('{img.name}')", timeout=20_000)
    page.wait_for_timeout(400)  # let React finish rendering the freshly opened panel

    desc_text = meta.get("description_en", "")
    desc_area = page.locator("textarea[name='description']")
    desc_area.click()
    desc_area.fill(desc_text)

    # Verify React actually registered the value.  If fill() raced with a
    # re-render and lost, use the native setter + synthetic events as a fallback.
    if desc_area.input_value() != desc_text:
        desc_area.evaluate(
            """(el, val) => {
                Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set.call(el, val);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            desc_text,
        )

    kw_input = page.locator("input[placeholder*='Add keyword']")
    kw_input.click()
    kw_input.fill(", ".join(meta.get("keywords_en", [])))
    kw_input.press("Enter")

    cat1, cat2 = meta.get("category1", ""), meta.get("category2", "")
    if cat1:
        page.locator("[data-testid='category1'] div[role='button']").click()
        page.locator(f"li.MuiMenuItem-root:has-text('{cat1}')").first.click()
    if cat2:
        page.locator("[data-testid='category2'] div[role='button']").click()
        page.locator(f"li.MuiMenuItem-root:has-text('{cat2}')").first.click()

    page.locator("[data-testid='edit-dialog-save-button']").click()
    page.wait_for_timeout(2_000)


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, bool]:
    """Upload all images in one file-chooser call, then fill metadata card by card."""
    page = context.new_page()
    try:
        ensure_logged_in(page, lambda: _is_logged_in(page), LOGIN_URL)
        page.goto(PORTFOLIO_URL, wait_until="domcontentloaded", timeout=20_000)

        # Record how many "Not submitted" cards exist before this batch
        pre_count = page.locator(".MuiCard-root").count()

        # Open Upload modal and select ALL files at once
        page.locator("button.MuiButton-contained:has-text('Upload')").click()
        page.wait_for_selector("button:has-text('Upload assets')", timeout=10_000)
        with page.expect_file_chooser() as fc_info:
            page.locator("button:has-text('Upload assets')").click()
        fc_info.value.set_files([str(img) for img, _ in pairs])
        print(f"  Uploading {len(pairs)} file(s)...")

        # Wait for the upload-complete toast before navigating away
        page.wait_for_selector("text='Upload complete'", timeout=300_000)

        # Navigate to portfolio and wait until all N new cards appear
        page.goto(PORTFOLIO_URL, wait_until="networkidle", timeout=60_000)
        expected = pre_count + len(pairs)
        page.wait_for_function(
            f"() => document.querySelectorAll('.MuiCard-root').length >= {expected}",
            timeout=300_000,
        )

        # Fill metadata for each image by locating its card by filename
        results: dict[str, bool] = {}
        for img, meta in pairs:
            try:
                card = page.locator(f".MuiCard-root:has-text('{img.name}')").first
                card.scroll_into_view_if_needed()
                bbox = card.bounding_box()
                page.mouse.click(bbox["x"] + bbox["width"] / 2, bbox["y"] + bbox["height"] * 0.35)

                _fill_metadata(page, img, meta)
                print(f"  ✓ Shutterstock: {img.name}")
                results[img.name] = True
            except Exception as e:
                print(f"  ✗ Shutterstock: {img.name} — {e}")
                results[img.name] = False

        return results

    except Exception as e:
        print(f"  ✗ Shutterstock batch upload failed — {e}")
        return {img.name: False for img, _ in pairs}
    finally:
        page.close()


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    """Single-image upload (kept for compatibility). Delegates to upload_batch."""
    results = upload_batch([(image_path, metadata)], context)
    return results.get(image_path.name, False)
