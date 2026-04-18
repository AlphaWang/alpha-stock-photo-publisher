"""
Shutterstock contributor upload automation.
Portal: https://submit.shutterstock.com

Confirmed UI flow (from browser inspection sessions):
  1. Navigate to portfolio/not_submitted page
  2. Click top-right "Upload" button → modal opens
  3. Click "Upload assets" inside modal → native file chooser opens
  4. Set image file via file chooser
  5. Wait for "Upload complete" toast (bottom-right)
  6. Navigate back to portfolio with networkidle
  7. Wait for the card showing the filename, click it (force=True bypasses overlay)
  8. Wait for edit panel (textarea[name='description']) to appear
  9. Fill description_en and keywords_en
  10. Fill Category 1 (required) and Category 2 (optional) via MUI Select
  11. Click contained Save button
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


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    page = context.new_page()
    try:
        ensure_logged_in(page, lambda: _is_logged_in(page), LOGIN_URL)
        page.goto(PORTFOLIO_URL, wait_until="domcontentloaded", timeout=20_000)

        # 1. Open upload modal via top-right Upload button
        page.locator("button.MuiButton-contained:has-text('Upload')").click()
        page.wait_for_selector("button:has-text('Upload assets')", timeout=10_000)

        # 2. Click "Upload assets" in modal → triggers native file chooser
        with page.expect_file_chooser() as fc_info:
            page.locator("button:has-text('Upload assets')").click()
        fc_info.value.set_files(str(image_path))
        print(f"  Uploading {image_path.name}...")

        # 3. Wait for server-side upload to complete
        page.wait_for_selector("text='Upload complete'", timeout=120_000)

        # 4. Reload portfolio; wait for at least one image card to appear
        page.goto(PORTFOLIO_URL, wait_until="networkidle", timeout=30_000)
        page.wait_for_selector("li:not(.MuiListItem-root)", timeout=30_000)

        # 5. Click the MuiCard-root (the actual image card element)
        page.wait_for_selector(".MuiCard-root", timeout=30_000)
        card = page.locator(".MuiCard-root").first
        card.scroll_into_view_if_needed()
        bbox = card.bounding_box()
        # Click on the image area (upper portion of card), not the text below
        page.mouse.click(bbox["x"] + bbox["width"] / 2, bbox["y"] + bbox["height"] * 0.35)

        # 6. Fill description
        page.wait_for_selector("textarea[name='description']", timeout=20_000)
        page.locator("textarea[name='description']").fill(metadata.get("description_en", ""))

        # 7. Fill keywords (field accepts comma-separated values in one go)
        kw_input = page.locator("input[placeholder*='Add keyword']")
        kw_input.click()
        kw_input.fill(", ".join(metadata.get("keywords_en", [])))
        kw_input.press("Enter")

        # 8. Fill Category 1 (required) and Category 2 (optional)
        # MUI Select: click the visible div trigger, then pick the li menu item
        cat1 = metadata.get("category1", "")
        cat2 = metadata.get("category2", "")
        selects = page.locator("div[role='button'].MuiSelect-select")

        if cat1:
            selects.nth(0).click()
            page.locator(f"li.MuiMenuItem-root:has-text('{cat1}')").first.click()

        if cat2:
            selects.nth(1).click()
            page.locator(f"li.MuiMenuItem-root:has-text('{cat2}')").first.click()

        # 9. Save (contained variant)
        page.locator("button.MuiButton-contained:has-text('Save')").click()
        page.wait_for_timeout(3_000)

        print(f"  ✓ Shutterstock: {image_path.name}")
        return True

    except Exception as e:
        print(f"  ✗ Shutterstock: {image_path.name} — {e}")
        return False
    finally:
        page.close()
