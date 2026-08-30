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

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in
from .confirmation import wait_for_success_text
from .status import UploadStatus
from metadata_core import commercial_submission_review_reason, platform_category

LOGIN_URL  = "https://contributor.tuchong.com/"
UPLOAD_URL = "https://contributor.tuchong.com/contribute?category=0"

# Map Shutterstock category1 → Tuchong photo-category tags (max 2)
_CATEGORY_MAP: dict[str, list[str]] = {
    "Nature":       ["自然风光"],
    "Travel":       ["自然风光", "城市风光"],
    "Architecture": ["城市风光"],
    "Buildings":    ["城市风光"],
    "Interiors":    ["室内空间"],
    "Religion":     ["其他"],
    "Backgrounds/Textures": ["自然风光"],
    "Industrial":   ["城市风光"],
    "Parks/Outdoor": ["自然风光"],
    "Signs/Symbols": ["自然风光"],
    "Transportation": ["自然风光"],
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


def _login_page_session_ready(page: Page) -> bool:
    """Read the SPA's in-place login state without navigating or opening a tab."""
    try:
        return bool(
            page.evaluate(
                """() => {
                    const data = window.commonData || {};
                    return Boolean(
                        data.userId && data.qualified === 2 && data.bound === 1
                    );
                }"""
            )
        )
    except Exception:
        return False


def ensure_login(context: BrowserContext) -> None:
    """Check login once before batch upload."""
    login_page = context.new_page()
    try:
        if _is_logged_in(login_page):
            return

        def open_login_form() -> None:
            login_link = login_page.get_by_text("登录", exact=True)
            login_link.first.wait_for(state="visible", timeout=30_000)
            login_link.first.click()
            login_page.get_by_placeholder(
                "请输入手机号/用户名/邮箱"
            ).wait_for(state="visible", timeout=10_000)

        ensure_logged_in(
            login_page,
            lambda: False,
            LOGIN_URL,
            poll_logged_in=lambda: _login_page_session_ready(login_page),
            prepare_login=open_login_form,
        )
    finally:
        login_page.close()


def _resolve_categories(category1: str) -> list[str]:
    """Map Shutterstock category1 to Tuchong photo-category tags."""
    for key, tags in _CATEGORY_MAP.items():
        if key.lower() in category1.lower():
            return tags[:2]
    return []


def _categories_for_metadata(metadata: dict) -> list[str]:
    explicit = platform_category(metadata, "tuchong")
    if isinstance(explicit, list) and explicit:
        return [str(value) for value in explicit[:2]]
    categories = []
    for field in ("category1", "category2"):
        for value in _resolve_categories(str(metadata.get(field, ""))):
            if value not in categories:
                categories.append(value)
    return categories[:2]


@dataclass(frozen=True)
class _MetadataFillResult:
    fields_verified: bool
    submission_ready: bool

    def __bool__(self) -> bool:
        return self.submission_ready


def _fill_metadata(page: Page, metadata: dict) -> _MetadataFillResult:
    """Fill required metadata and report whether the draft is submission-ready.

    Release, logo, copyright, and commercial-eligibility warnings must not leave
    a draft blank.  They require contributor review before submission, while the
    factual description, keywords, and category are still safe and useful draft
    metadata.
    """
    description = metadata.get("description_zh", "")[:50]
    keywords = metadata.get("keywords_zh", [])[:30]
    if not description or not keywords:
        print("  [review] description or keywords are missing")
        return _MetadataFillResult(False, False)
    commercial_reason = commercial_submission_review_reason(metadata)
    if commercial_reason:
        print(f"  [review] {commercial_reason}")

    fields_verified = True
    submission_ready = not bool(commercial_reason)
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
    cats = _categories_for_metadata(metadata)
    try:
        page.wait_for_function(
            "() => {"
            "  const el = document.querySelector(\"form.contribute__sider-form input.ant-input[placeholder='请选择']\");"
            "  return el && !el.disabled && !el.classList.contains('ant-input-disabled');"
            "}",
            timeout=30_000,
        )
        category_input = form.locator(
            "input.ant-input[placeholder='请选择']"
        ).first
        current_categories = category_input.input_value()
        if cats and all(cat in current_categories for cat in cats):
            selected_categories = len(cats)
        else:
            category_input.click(timeout=5_000)
            # Wait for the modal itself. Its heading text has changed across
            # Tuchong releases, while the accessible dialog role is stable.
            dialog = page.locator("[role='dialog']:visible").last
            dialog.wait_for(state="visible", timeout=10_000)
            page.wait_for_timeout(600)
            selected_categories = 0
            for cat in cats:
                try:
                    target = dialog.get_by_text(cat, exact=True).first
                    target.click(timeout=5_000)
                    selected_categories += 1
                    page.wait_for_timeout(400)
                except PWTimeout:
                    pass
            dialog.locator(
                "button:has-text('确认'), button:has-text('确 认')"
            ).first.click(timeout=5_000)
            page.wait_for_timeout(1_000)
        if selected_categories == 0:
            fields_verified = False
            print("  [warn] no image category could be selected")
    except PWTimeout as e:
        print(f"  [warn] category field failed: {e}")
        fields_verified = False
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

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
        fields_verified = False

    # Keywords — Ant Design Select (tags/multiple mode)
    # .ant-select-selection--multiple contains a hidden input.ant-select-search__field
    try:
        kw_sel = form.locator(".ant-select-selection--multiple").first
        kw_sel.scroll_into_view_if_needed()
        remove_buttons = kw_sel.locator(".ant-select-selection__choice__remove")
        for _ in range(35):
            if remove_buttons.count() == 0:
                break
            remove_buttons.first.click(force=True, timeout=5_000)
            page.wait_for_timeout(80)
        # Removing a tag opens Ant Design's suggestion overlay.  Focus the
        # actual input directly so that overlay cannot intercept the click.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        kw_input = kw_sel.locator("input.ant-select-search__field")
        kw_input.click(force=True, timeout=5_000)
        for kw in keywords:
            kw_input.type(kw)
            kw_input.press("Enter")
            page.wait_for_timeout(80)
    except Exception as e:
        print(f"  [warn] keywords field failed: {e}")
        fields_verified = False

    # A successful fill/click call is not enough: Ant Design can silently drop
    # changes while the form is initializing.  Read the active form back before
    # any draft is saved so blank or partial metadata cannot be reported ready.
    try:
        actual_description = form.locator("textarea.ant-input").first.input_value().strip()
        actual_category = form.locator(
            "input.ant-input[placeholder='请选择']"
        ).first.input_value().strip()
        actual_keywords = {
            value.strip()
            for value in form.locator(
                ".ant-select-selection--multiple .ant-select-selection__choice"
            ).all_inner_texts()
            if value.strip()
        }
        missing_keywords = [kw for kw in keywords if kw not in actual_keywords]
        missing_categories = [cat for cat in cats if cat not in actual_category]
        if actual_description != description:
            print("  [warn] description did not remain in the active form")
            fields_verified = False
        if not actual_category or missing_categories:
            print("  [warn] category did not remain in the active form")
            fields_verified = False
        if len(actual_keywords) < 5 or missing_keywords:
            print("  [warn] keywords did not remain in the active form")
            fields_verified = False
    except Exception as e:
        print(f"  [warn] metadata read-back failed: {e}")
        fields_verified = False

    return _MetadataFillResult(
        fields_verified=fields_verified,
        submission_ready=fields_verified and submission_ready,
    )


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
    # so fall back to the stem. Never edit by position because a failed or
    # deduplicated upload can shift cards and attach metadata to the wrong file.
    for locator in [
        page.locator(".contribute__image__item").filter(has=page.get_by_text(img.name, exact=False)).first,
        page.locator(".contribute__image__item").filter(has=page.get_by_text(img.stem, exact=False)).first,
    ]:
        if locator.count() > 0:
            card = locator
            break
    else:
        raise PWTimeout(f"upload card not found for {img.name}")

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


def _upload_status_is_pending(status: str) -> bool:
    """Return whether a Tuchong card is still queued or being processed."""
    return "等待上传中" in status or "上传中" in status


def _wait_for_uploads(page: Page, count: int) -> None:
    """Wait until every upload card leaves its queued/processing state."""
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
        # Tuchong keeps the form disabled while a card says either
        # "等待上传中" or "上传中 100%".  The latter means transfer reached
        # 100%, not that server-side processing and form initialization ended.
        pending = sum(1 for status in statuses if _upload_status_is_pending(status))
        if pending == 0:
            break
        status_summary = ", ".join(dict.fromkeys(statuses))
        print(f"  [wait] {pending}/{count} queued/processing: {status_summary}", flush=True)
        page.wait_for_timeout(check_ms)
        elapsed_ms += check_ms
    else:
        print(f"  [warn] upload wait timed out after {deadline_ms // 1000}s", flush=True)
    page.wait_for_timeout(2_000)


def _card_error(page: Page, filename: str) -> Optional[str]:
    """Return the error text on a card, or None if the upload succeeded."""
    status = page.evaluate(
        """(filename) => {
            const cards = [...document.querySelectorAll('.contribute__image__item')];
            const card = cards.find(c => c.innerText.includes(filename));
            if (!card) return 'upload card not found';
            const el = card.querySelector('.upload-process-each__text');
            if (!el) return null;
            return el.textContent.trim() || null;
        }""",
        filename,
    )
    # A lingering queue/progress label is not success, including "上传中 100%".
    # Successful cards remove the status element; other non-empty labels are
    # platform errors and should also remain retryable/reviewable.
    return status or None


def _saved_draft_status(
    filename: str,
    metadata_ready: set[str],
    metadata_populated: set[str],
) -> UploadStatus:
    if filename in metadata_ready:
        return UploadStatus.DRAFT_SAVED
    if filename in metadata_populated:
        return UploadStatus.DRAFT_SAVED_NEEDS_REVIEW
    return UploadStatus.UPLOADED


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
        metadata_populated: set[str] = set()
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

            fill_result = _fill_metadata(page, metadata)
            if fill_result.fields_verified:
                metadata_populated.add(img.name)
            if fill_result.submission_ready:
                metadata_ready.add(img.name)
                print(f"  [{fill_idx + 1}/{len(ok_pairs)}] ready {img.name}", flush=True)
            elif fill_result.fields_verified:
                print(
                    f"  [{fill_idx + 1}/{len(ok_pairs)}] metadata saved; "
                    f"submission review required {img.name}",
                    flush=True,
                )
            else:
                print(
                    f"  [{fill_idx + 1}/{len(ok_pairs)}] metadata incomplete {img.name}",
                    flush=True,
                )

        if ok_pairs:
            _check_pledge(page)
            try:
                # Save once at the end. Selecting the batch here is only for the
                # save action; no metadata fields are modified after this point.
                _select_all_for_save(page, len(ok_pairs))
                save_button = page.locator("button:has-text('保存草稿')").first
                save_response = None
                try:
                    with page.expect_response(
                        lambda response: (
                            "/api/creative/groups" in response.url
                            and response.request.method != "GET"
                        ),
                        timeout=15_000,
                    ) as response_info:
                        save_button.click(timeout=5_000)
                    save_response = response_info.value
                except PWTimeout:
                    # Older Tuchong versions reported success only through a
                    # visible toast, so retain that path as a fallback.
                    pass

                api_confirmed = False
                if save_response is not None and save_response.ok:
                    try:
                        payload = save_response.json()
                        data = payload.get("data") or {}
                        api_confirmed = (
                            payload.get("code") == 0
                            and data.get("success_num") == len(ok_pairs)
                        )
                    except Exception:
                        api_confirmed = False

                toast_confirmed = wait_for_success_text(
                    page, ["保存成功", "草稿已保存", "操作成功"]
                )
                if api_confirmed or toast_confirmed:
                    for img, _ in ok_pairs:
                        results[img.name] = _saved_draft_status(
                            img.name, metadata_ready, metadata_populated
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
