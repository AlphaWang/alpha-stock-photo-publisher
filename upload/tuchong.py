"""
contributor.tuchong.com creative-photo upload automation.

Upload flow (contributor.tuchong.com):
  1. Navigate to the creative-image upload page
  2. Click the add-images button → file chooser; select ALL images at once
  3. Wait for all uploads to complete (no in-progress indicators remaining)
  4. For each image: isolate that thumbnail → fill its own JSON metadata
  5. Save draft once, so the upload batch remains one draft folder

NOTE: Selectors based on contributor.tuchong.com UI as of 2026-04. Update if the site changes.
"""

from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in
from .confirmation import wait_for_success_text
from .status import UploadStatus

LOGIN_URL  = "https://contributor.tuchong.com/"
UPLOAD_URL = "https://contributor.tuchong.com/contribute?category=0"

# Map Shutterstock category1 → Tuchong photo-category tags (max 2)
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
def _is_logged_in(page: Page) -> bool:
    try:
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=15_000)
        if "login" in page.url or not page.url.startswith("https://contributor.tuchong.com"):
            return False
        # Tuchong serves the upload URL even when logged out but hides the upload button.
        page.wait_for_selector("button:has-text('添加图片')", timeout=5_000)
        return True
    except Exception:
        return False


def ensure_login(context: BrowserContext) -> None:
    """Check login once before batch upload."""
    # Poll on a fresh page each time so the login page isn't navigated away from.
    def poll_logged_in() -> bool:
        p = context.new_page()
        try:
            return _is_logged_in(p)
        finally:
            p.close()

    login_page = context.new_page()
    try:
        ensure_logged_in(login_page, poll_logged_in, LOGIN_URL)
    finally:
        login_page.close()


def _resolve_categories(category1: str) -> list[str]:
    """Map Shutterstock category1 to Tuchong photo-category tags."""
    for key, tags in _CATEGORY_MAP.items():
        if key.lower() in category1.lower():
            return tags[:2]
    return []


def _fill_metadata(page: Page, metadata: dict) -> bool:
    """Fill required metadata and report whether every required field succeeded."""
    description = metadata.get("description_zh", "")[:50]
    keywords = metadata.get("keywords_zh", [])[:30]
    if not description or not keywords:
        print("  [review] description or keywords are missing")
        return False

    complete = True
    # Scope all lookups to the sider form to avoid stray element matches
    form = page.locator("form.contribute__sider-form")
    try:
        form.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        form = page  # fallback

    # "Exclusive?" field — select No  (span.btn-default, not <button>)
    try:
        form.locator("span.btn-default").filter(has_text="否").first.click(timeout=5_000)
        page.wait_for_timeout(200)
    except PWTimeout:
        pass

    # Image usage: defaults to commercial/advertising — no action needed

    # Image category — <input class="ant-input" placeholder="请选择"> opens a modal
    cats = _resolve_categories(metadata.get("category1", ""))
    try:
        page.wait_for_function(
            "() => {"
            "  const el = document.querySelector(\"form.contribute__sider-form input.ant-input[placeholder='请选择']\");"
            "  return el && !el.disabled && !el.classList.contains('ant-input-disabled');"
            "}",
            timeout=30_000,
        )
        form.locator("input.ant-input[placeholder='请选择']").click(timeout=5_000)
        # Wait for modal to appear AND let its CSS animation finish before clicking.
        # The locator resolves as soon as the DOM node exists,
        # but clicks during the slide-in animation are often dropped by the browser.
        page.wait_for_selector("text=摄影图片类", timeout=10_000)
        page.wait_for_timeout(600)
        selected_categories = 0
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
                selected_categories += 1
                page.wait_for_timeout(400)
            except PWTimeout:
                pass
        if selected_categories == 0:
            complete = False
            print("  [warn] no image category could be selected")
        page.locator("button:has-text('确认'), button:has-text('确 认')").first.click(timeout=5_000)
        page.wait_for_timeout(1_000)  # wait for modal to close fully
    except PWTimeout as e:
        print(f"  [warn] category field failed: {e}")
        complete = False

    # Image description — <textarea class="ant-input contribute-form-model" maxlength="50">
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
        ta.fill(description)
        page.wait_for_timeout(200)
    except Exception as e:
        print(f"  [warn] description field failed: {e}")
        complete = False

    # Keywords — Ant Design Select (tags/multiple mode)
    # .ant-select-selection--multiple contains a hidden input.ant-select-search__field
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
        print(f"  [warn] keywords field failed: {e}")
        complete = False

    return complete


def _selected_card_count(page: Page) -> int:
    return page.locator(".contribute__image__item .pop-top .ant-checkbox-wrapper-checked").count()


def _deselect_all_cards(page: Page) -> None:
    """Clear selected thumbnails so metadata edits only affect the active image."""
    checked = page.locator(".contribute__image__item .pop-top .ant-checkbox-wrapper-checked")
    while checked.count() > 0:
        try:
            checked.first.click(timeout=2_000)
            page.wait_for_timeout(150)
        except Exception:
            break


def _select_card_for_edit(page: Page, img: Path, idx: int = 0) -> None:
    """Select exactly one thumbnail and open its side-panel metadata form."""
    _deselect_all_cards(page)
    page.wait_for_timeout(200)

    # Try full filename first; Tuchong may truncate long names in the UI,
    # so fall back to stem (no extension), then by position.
    for locator in [
        page.locator(".contribute__image__item").filter(has=page.get_by_text(img.name, exact=False)).first,
        page.locator(".contribute__image__item").filter(has=page.get_by_text(img.stem, exact=False)).first,
        page.locator(".contribute__image__item").nth(idx),
    ]:
        if locator.count() > 0:
            card = locator
            break
    else:
        card = page.locator(".contribute__image__item").nth(idx)

    card.wait_for(state="attached", timeout=30_000)
    card.scroll_into_view_if_needed()
    card.wait_for(state="visible", timeout=10_000)
    card.click()
    page.wait_for_timeout(800)


def _select_all_for_save(page: Page, expected: int) -> None:
    """Select the batch for the final save without changing any metadata fields."""
    if expected <= 0 or _selected_card_count(page) >= expected:
        return

    try:
        all_chk = page.locator("label:has-text('全选') input[type='checkbox']").first
        if all_chk.count() > 0 and not all_chk.is_checked():
            all_chk.check(force=True)
            page.wait_for_timeout(500)
            return
    except Exception:
        pass

    try:
        page.locator("text=全选").first.click(timeout=5_000)
        page.wait_for_timeout(500)
    except Exception:
        pass


def _check_pledge(page: Page) -> None:
    """Tick the pledge/agreement checkbox before submitting."""
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
    """Wait for all upload cards to finish (no per-card uploading indicator)."""
    try:
        page.wait_for_selector(".contribute__image__item", timeout=30_000)
    except PWTimeout:
        return

    deadline_ms = max(180_000, count * 2 * 60 * 1000)
    elapsed_ms = 0
    check_ms = 10_000
    while elapsed_ms < deadline_ms:
        statuses = page.evaluate(
            """() => [...document.querySelectorAll(
                '.contribute__image__item .upload-process-each__text'
            )].map(el => el.textContent.trim())"""
        )
        # Only wait for files actively mid-transfer (X% < 100).
        # '上传中 100%' = fully transferred; '等待上传中' = queued but not started.
        # Both are treated as "done enough to proceed" — _card_error handles the rest.
        in_progress = sum(
            1 for s in statuses
            if '上传中' in s and '100%' not in s and '等待上传中' not in s
        )
        if in_progress == 0:
            break
        status_summary = ", ".join(dict.fromkeys(statuses))
        print(f"  [wait] {in_progress}/{count} mid-transfer: {status_summary}", flush=True)
        page.wait_for_timeout(check_ms)
        elapsed_ms += check_ms
    else:
        print(f"  [warn] upload wait timed out after {deadline_ms // 1000}s", flush=True)
    page.wait_for_timeout(2_000)


def _card_error(page: Page, filename: str) -> Optional[str]:
    """Return the error text on a card, or None if the upload succeeded."""
    return page.evaluate(
        """(filename) => {
            const cards = [...document.querySelectorAll('.contribute__image__item')];
            const card = cards.find(c => c.innerText.includes(filename));
            if (!card) return null;
            const el = card.querySelector('.upload-process-each__text');
            if (!el) return null;
            const text = el.textContent.trim();
            // File is still queued (never started uploading) — treat as not uploaded
            if (text.includes('等待上传中')) return '等待上传中';
            // File is actively uploading or fully transferred — no error
            if (text.includes('上传中')) return null;
            return text;
        }""",
        filename,
    )


def _delete_card(page: Page, filename: str) -> None:
    """Click the delete/retry button on an error card."""
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


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, UploadStatus]:
    """Upload all images, fill metadata per image, then submit."""
    # Close any stale pages that Chrome restored from a previous crashed session.
    for stale in list(context.pages):
        try:
            stale.close()
        except Exception:
            pass
    page = context.new_page()
    results = {img.name: UploadStatus.FAILED for img, _ in pairs}
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

        # Clear localStorage and unregister service workers to flush any upload
        # queue state left by previous crashed sessions. Login lives in cookies,
        # so this is safe.
        page.evaluate("""() => {
            try { localStorage.clear(); } catch(e) {}
            if (navigator.serviceWorker) {
                navigator.serviceWorker.getRegistrations().then(regs =>
                    regs.forEach(r => r.unregister())
                );
            }
        }""")
        page.reload(wait_until="domcontentloaded", timeout=20_000)

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
                print(f"  Uploading {total} image(s) to Tuchong...", flush=True)
            else:
                print(f"  Retrying {len(to_upload)} image(s) after Network Error...", flush=True)

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
                    print(f"  [skip] {img.name}: {err}", flush=True)

            to_upload = retry
            if retry and upload_round < 2:
                page.wait_for_timeout(2_000)

        for img, _ in to_upload:
            print(f"  [fail] {img.name}: Network Error after 3 attempts", flush=True)

        for img, _ in ok_pairs:
            results[img.name] = UploadStatus.UPLOADED

        # --- Metadata fill phase ---
        # Each image has its own JSON metadata. Never edit metadata while the
        # whole batch is selected, because Tuchong applies changed fields to
        # every selected file.
        metadata_ready: set[str] = set()
        for fill_idx, (img, metadata) in enumerate(ok_pairs):
            try:
                _select_card_for_edit(page, img, fill_idx)
            except PWTimeout:
                print(f"  [warn] could not locate card for {img.name}")
                continue

            try:
                page.wait_for_function(
                    "() => {"
                    "  const ta = document.querySelector('form.contribute__sider-form textarea.ant-input');"
                    "  return ta && !ta.disabled && !ta.classList.contains('ant-input-disabled');"
                    "}",
                    timeout=120_000,
                )
            except PWTimeout:
                print(f"  [warn] form still disabled for {img.name}")
            page.wait_for_timeout(300)

            if _fill_metadata(page, metadata):
                metadata_ready.add(img.name)
                print(f"  [{fill_idx + 1}/{len(ok_pairs)}] ready {img.name}", flush=True)
            else:
                print(f"  [{fill_idx + 1}/{len(ok_pairs)}] review required {img.name}", flush=True)

        if ok_pairs:
            _check_pledge(page)
            try:
                # Save once at the end. Selecting the batch here is only for the
                # save action; no metadata fields are modified after this point.
                _select_all_for_save(page, len(ok_pairs))
                page.locator("button:has-text('保存草稿')").first.click(timeout=5_000)
                if wait_for_success_text(page, ["保存成功", "草稿已保存", "操作成功"]):
                    for img, _ in ok_pairs:
                        results[img.name] = (
                            UploadStatus.DRAFT_SAVED
                            if img.name in metadata_ready
                            else UploadStatus.UPLOADED
                        )
                    print(f"  Saved Tuchong draft once for {len(ok_pairs)} image(s)", flush=True)
                else:
                    print("  [warn] Tuchong save was not confirmed", flush=True)
            except PWTimeout:
                print("  [warn] save-draft failed")

    except Exception as e:
        step = f"at image {fill_idx + 1}" if fill_idx >= 0 else "before fill loop"
        print(f"  ✗ Tuchong batch failed {step}: {e}", flush=True)
    finally:
        page.close()

    return results


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    """Upload a single image. Delegates to upload_batch."""
    results = upload_batch([(image_path, metadata)], context)
    return results.get(image_path.name, UploadStatus.FAILED).completed
