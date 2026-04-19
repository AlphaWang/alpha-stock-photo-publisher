"""
contributor.tuchong.com creative-photo upload automation.

Upload flow (contributor.tuchong.com):
  1. Navigate to creative-image upload page ("创意图片")
  2. Click "添加图片" → file chooser; select ALL images at once
  3. Wait for all uploads to complete (no "上传中" indicators remaining)
  4. For each image: click thumbnail → fill right-panel metadata
  5. Select all → "提交选中的素材"

NOTE: Selectors based on contributor.tuchong.com UI as of 2026-04. Update if the site changes.
"""

from pathlib import Path

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in

LOGIN_URL  = "https://contributor.tuchong.com/"
UPLOAD_URL = "https://contributor.tuchong.com/contribute?category=0"

# Map Shutterstock category1 → 图虫创意 摄影图片类 tags (max 2)
_CATEGORY_MAP: dict[str, list[str]] = {
    "Nature":       ["自然风光"],
    "Travel":       ["自然风光", "城市风光"],
    "Architecture": ["城市风光"],
    "Buildings":    ["城市风光"],
    "Animals":      ["野生动物"],
    "Wildlife":     ["野生动物"],
    "Food":         ["静物美食"],
    "Lifestyle":    ["生活方式"],
    "Sports":       ["运动健康"],
    "Medical":      ["生物医疗"],
    "Holidays":     ["节日假日"],
    "Business":     ["商务肖像"],
    "People":       ["商务肖像"],
}
_DEFAULT_CATEGORIES = ["自然风光"]


def _is_logged_in(page: Page) -> bool:
    try:
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=15_000)
        # If redirected to login page, we're not logged in
        return "login" not in page.url and page.url.startswith("https://contributor.tuchong.com")
    except PWTimeout:
        return False


def ensure_login(context: BrowserContext) -> None:
    """Check login once before batch upload. Opens a temp page, then closes it."""
    page = context.new_page()
    try:
        ensure_logged_in(page, lambda: _is_logged_in(page), LOGIN_URL)
    finally:
        page.close()


def _resolve_categories(category1: str) -> list[str]:
    """Map Shutterstock category1 to 图虫 摄影图片类 tags."""
    for key, tags in _CATEGORY_MAP.items():
        if key.lower() in category1.lower():
            return tags[:2]
    return _DEFAULT_CATEGORIES


def _fill_metadata(page: Page, metadata: dict) -> None:
    """Fill right-panel metadata for the currently-selected image."""
    # Scope all lookups to the sider form to avoid stray element matches
    form = page.locator("form.contribute__sider-form")
    try:
        form.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        form = page  # fallback

    # 是否独家 → 否  (span.btn-default, not <button>)
    try:
        form.locator("span.btn-default").filter(has_text="否").first.click(timeout=5_000)
        page.wait_for_timeout(200)
    except PWTimeout:
        pass

    # 图片用途: already "商业广告类" by default — no action needed

    # 图片分类 — <input class="ant-input" placeholder="请选择"> opens a modal
    cats = _resolve_categories(metadata.get("category1", ""))
    try:
        form.locator("input.ant-input[placeholder='请选择']").click(timeout=5_000)
        # Wait for modal to appear AND let its CSS animation finish before clicking.
        # page.locator("text=摄影图片类") resolves as soon as the DOM node exists,
        # but clicks during the slide-in animation are often dropped by the browser.
        page.wait_for_selector("text=摄影图片类", timeout=10_000)
        page.wait_for_timeout(600)
        for cat in cats:
            try:
                # Scope to [role='dialog'] so we don't hit page elements that
                # happen to contain the same text before the modal in DOM order.
                dialog = page.locator("[role='dialog']")
                target = (
                    dialog.locator(f"text={cat}").first
                    if dialog.count() > 0
                    else page.locator(f"text={cat}").first
                )
                target.click(timeout=5_000)
                page.wait_for_timeout(400)
            except PWTimeout:
                pass
        page.locator("button:has-text('确认'), button:has-text('确 认')").first.click(timeout=5_000)
        page.wait_for_timeout(1_000)  # wait for modal to close fully
    except PWTimeout as e:
        print(f"  [warn] 图片分类 failed: {e}")

    # 图片说明 — <textarea class="ant-input contribute-form-model" maxlength="50">
    desc = metadata.get("description_zh", "")[:50]
    try:
        ta = form.locator("textarea.ant-input").first
        ta.wait_for(state="visible", timeout=10_000)
        # Wait for React to remove the disabled attribute
        page.wait_for_function(
            "() => {"
            "  const el = document.querySelector('form.contribute__sider-form textarea.ant-input');"
            "  return el && !el.disabled;"
            "}",
            timeout=15_000,
        )
        ta.scroll_into_view_if_needed()
        ta.click()
        ta.type(desc, delay=20)
        page.wait_for_timeout(200)
    except Exception as e:
        print(f"  [warn] 图片说明 failed: {e}")

    # 关键词 — Ant Design Select (tags/multiple mode)
    # .ant-select-selection--multiple contains a hidden input.ant-select-search__field
    keywords = metadata.get("keywords_zh", [])[:30]
    if keywords:
        try:
            kw_sel = form.locator(".ant-select-selection--multiple").first
            kw_sel.scroll_into_view_if_needed()
            kw_sel.click()
            page.wait_for_timeout(300)
            kw_input = kw_sel.locator("input.ant-select-search__field")
            for kw in keywords:
                kw_input.type(kw)
                kw_input.press("Enter")
                page.wait_for_timeout(80)
        except Exception as e:
            print(f"  [warn] 关键词 failed: {e}")


def _check_pledge(page: Page) -> None:
    """Tick the 本人郑重承诺 checkbox before submitting."""
    try:
        # The checkbox is in a label block at the bottom of the page
        chk = page.locator("input[type='checkbox']").filter(has=page.locator("text=本人郑重承诺")).first
        if chk.count() == 0:
            chk = page.locator("label:has-text('本人郑重承诺') input[type='checkbox']").first
        if chk.count() > 0 and not chk.is_checked():
            chk.check()
    except Exception:
        try:
            page.locator("text=本人郑重承诺").first.click(timeout=3_000)
        except Exception:
            pass


def _wait_for_uploads(page: Page, count: int) -> None:
    """Wait for a batch of uploads to complete (appear then disappear)."""
    try:
        page.wait_for_function(
            "() => document.body.innerText.includes('上传中')",
            timeout=30_000,
        )
    except PWTimeout:
        pass  # upload completed before we could detect it starting
    timeout = max(600_000, count * 5 * 60 * 1000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('上传中')",
        timeout=timeout,
    )
    page.wait_for_timeout(2_000)


def _card_error(page: Page, filename: str) -> str | None:
    """Return the error text on a card, or None if the upload succeeded."""
    return page.evaluate(
        """(filename) => {
            const cards = [...document.querySelectorAll('.contribute__image__item')];
            const card = cards.find(c => c.innerText.includes(filename));
            if (!card) return null;
            const el = card.querySelector('.upload-process-each__text');
            if (!el) return null;
            const text = el.textContent.trim();
            return text.includes('上传中') ? null : text;
        }""",
        filename,
    )


def _delete_card(page: Page, filename: str) -> None:
    """Click the 删除 button on an error card."""
    page.evaluate(
        """(filename) => {
            const cards = [...document.querySelectorAll('.contribute__image__item')];
            const card = cards.find(c => c.innerText.includes(filename));
            if (!card) return;
            const btn = card.querySelector('.retry-btn');
            if (btn) btn.click();
        }""",
        filename,
    )
    page.wait_for_timeout(300)


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, bool]:
    """Upload all images, fill metadata per image, then submit."""
    page = context.new_page()
    results = {img.name: False for img, _ in pairs}
    total = len(pairs)
    fill_idx = -1  # track progress for error reporting in outer except

    try:
        for attempt in range(3):
            try:
                page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=20_000)
                break
            except PWTimeout:
                if attempt == 2:
                    raise
                page.wait_for_timeout(2_000)

        # --- Upload phase with Network Error retry (up to 3 rounds) ---
        to_upload = list(pairs)
        ok_pairs: list[tuple[Path, dict]] = []

        for upload_round in range(3):
            if not to_upload:
                break

            page.wait_for_selector("button:has-text('添加图片')", timeout=10_000)
            with page.expect_file_chooser(timeout=10_000) as fc_info:
                page.locator("button:has-text('添加图片')").first.click()
            fc_info.value.set_files([str(img) for img, _ in to_upload])

            if upload_round == 0:
                print(f"  Uploading {total} image(s) to 图虫创意...")
            else:
                print(f"  Retrying {len(to_upload)} image(s) after Network Error...")

            _wait_for_uploads(page, len(to_upload))

            # Inspect each card; delete Network Error ones and queue for retry
            retry: list[tuple[Path, dict]] = []
            for img, metadata in to_upload:
                err = _card_error(page, img.name)
                if err is None:
                    ok_pairs.append((img, metadata))
                elif "Network Error" in err:
                    _delete_card(page, img.name)
                    retry.append((img, metadata))
                else:
                    print(f"  [skip] {img.name}: {err}")

            to_upload = retry
            if retry and upload_round < 2:
                page.wait_for_timeout(2_000)

        for img, _ in to_upload:
            print(f"  [fail] {img.name}: Network Error after 3 attempts")

        # --- Metadata fill phase ---
        # Cards are looked up by filename, not by index, because deletions and
        # retries may change card order on the page.
        for fill_idx, (img, metadata) in enumerate(ok_pairs):
            # Deselect all selected cards so this card is edited in isolation.
            # page.evaluate(el.click()) does NOT fire mousedown/mouseup, which Ant
            # Design's checkbox relies on — use Playwright's locator.click() instead,
            # which sends the full mouse event sequence React expects.
            checked = page.locator(
                ".contribute__image__item .pop-top .ant-checkbox-wrapper-checked"
            )
            while checked.count() > 0:
                try:
                    checked.first.click(timeout=2_000)
                    page.wait_for_timeout(150)
                except Exception:
                    break
            page.wait_for_timeout(200)

            card = (
                page.locator(".contribute__image__item")
                .filter(has=page.locator(f"text={img.name}"))
                .first
            )
            try:
                card.wait_for(state="visible", timeout=30_000)
                card.scroll_into_view_if_needed()
                card.click()
                page.wait_for_timeout(800)
            except PWTimeout:
                print(f"  [warn] could not locate card for {img.name}")

            # Wait until React removes the disabled attribute from the form fields
            try:
                page.wait_for_function(
                    "() => {"
                    "  const ta = document.querySelector('form.contribute__sider-form textarea.ant-input');"
                    "  return ta && !ta.disabled && !ta.classList.contains('ant-input-disabled');"
                    "}",
                    timeout=20_000,
                )
            except PWTimeout:
                print(f"  [warn] form still disabled for {img.name}")
            page.wait_for_timeout(300)

            _fill_metadata(page, metadata)
            print(f"  [{fill_idx + 1}/{len(ok_pairs)}] ✓ {img.name}")
            results[img.name] = True

        # After all images are filled, select all and save draft once.
        # Each card's metadata is already in React state from the individual fills;
        # 保存草稿 with all selected persists all of them in one shot.
        _check_pledge(page)
        try:
            all_chk = page.locator("label:has-text('全选') input[type='checkbox']").first
            if all_chk.count() > 0 and not all_chk.is_checked():
                all_chk.check()
            else:
                page.locator("text=全选").first.click()
            page.wait_for_timeout(500)
        except Exception:
            pass
        try:
            page.locator("button:has-text('保存草稿')").first.click(timeout=5_000)
            page.wait_for_timeout(2_000)
        except PWTimeout:
            print("  [warn] 保存草稿 failed")

    except Exception as e:
        step = f"at image {fill_idx + 1}" if fill_idx >= 0 else "before fill loop"
        print(f"  ✗ 图虫创意 batch failed {step}: {e}")
    finally:
        page.close()

    return results


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    """Upload a single image. Delegates to upload_batch."""
    results = upload_batch([(image_path, metadata)], context)
    return results.get(image_path.name, False)
