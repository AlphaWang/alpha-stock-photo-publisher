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

from PIL import Image
from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .browser import ensure_logged_in
from .confirmation import wait_for_success_text
from .status import UploadStatus

UPLOAD_URL = "https://creatorstudio.500px.com.cn/index"
LOGIN_URL = (
    "https://500px.com.cn/user/login?"
    "redirect=https%3A%2F%2F500px.com.cn%2Fcommunity%2Findex.html"
)
CONTRIBUTOR_BRIDGE_URL = (
    "https://500px.com.cn/page/contractPhotographer/index?type=0"
)
MIN_PIXEL_COUNT = 6_000_000


def _has_logged_in_session(page: Page) -> bool:
    url = page.url.lower()
    return (
        url.startswith("https://creatorstudio.500px.com.cn")
        and "login" not in url
        and page.locator("button.button_cmp_main").count() > 0
    )


def _context_has_logged_in_session(context: BrowserContext) -> bool:
    """Detect Creator Studio in any tab, including a newly opened bridge tab."""
    for candidate in context.pages:
        try:
            if _has_logged_in_session(candidate):
                return True
        except Exception:
            continue
    return False


def _is_logged_in(page: Page) -> bool:
    try:
        page.goto(UPLOAD_URL, wait_until="commit", timeout=30_000)
    except PWTimeout:
        pass
    try:
        page.wait_for_selector("button.button_cmp_main", timeout=10_000)
    except PWTimeout:
        return False
    return _has_logged_in_session(page)


def _community_session_ready(page: Page) -> bool:
    """Detect either Creator Studio or the signed-in community bridge."""
    if _has_logged_in_session(page):
        return True
    url = page.url.lower()
    return (
        url.startswith("https://500px.com.cn/")
        and "/user/login" not in url
        and (
            page.locator("a[href*='/page/contractPhotographer/index']").count() > 0
            or page.locator("text=前往创作者中心").count() > 0
        )
    )


def _enter_creator_studio(page: Page) -> bool:
    """Follow 500px's contributor bridge into Creator Studio."""
    try:
        page.goto(CONTRIBUTOR_BRIDGE_URL, wait_until="commit", timeout=30_000)
    except PWTimeout:
        pass

    redirect_selector = (
        "a[href*='creatorstudio.500px.com.cn/api/redirect/index?access_token=']"
    )
    redirect_link = page.locator(redirect_selector).first
    if redirect_link.count() == 0:
        creator_button = page.get_by_text("前往创作者中心", exact=True).first
        try:
            creator_button.wait_for(state="visible", timeout=60_000)
            creator_button.click()
            for _ in range(60):
                for candidate in page.context.pages:
                    try:
                        if _has_logged_in_session(candidate):
                            return True
                    except Exception:
                        continue
                page.wait_for_timeout(1_000)
        except PWTimeout:
            return False
        return False

    try:
        redirect_url = redirect_link.get_attribute("href")
        if not redirect_url:
            return False
        try:
            page.goto(redirect_url, wait_until="commit", timeout=30_000)
        except PWTimeout:
            pass
        page.wait_for_selector("button.button_cmp_main", timeout=60_000)
    except PWTimeout:
        return False
    return _has_logged_in_session(page)


def ensure_login(context: BrowserContext) -> None:
    """Check login once before batch upload. Opens a temp page, then closes it."""
    page = context.new_page()
    try:
        ensure_logged_in(
            page,
            lambda: _is_logged_in(page),
            LOGIN_URL,
            poll_logged_in=lambda: (
                _context_has_logged_in_session(context)
                or _community_session_ready(page)
            ),
        )
        if (
            not _context_has_logged_in_session(context)
            and not _enter_creator_studio(page)
        ):
            raise RuntimeError(
                "500px community login succeeded, but Creator Studio authorization failed."
            )
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
    (["盐湖城", "Salt Lake City", "SLC"], ["美国", "犹他", "其他"]),
    (["邦纳维尔", "Bonneville"], ["美国", "犹他", "其他"]),
    (["怀俄明", "大提顿", "Grand Teton", "Wyoming"], ["美国", "怀俄明", "其他"]),
    (["纽约", "New York"], ["美国", "纽约", "纽约"]),
    (["西雅图", "Seattle"], ["美国", "华盛顿", "西雅图"]),
    (["拉斯维加斯", "Las Vegas"], ["美国", "内华达", "拉斯维加斯"]),
]
def _resolve_path(location_zh: str) -> Optional[list[str]]:
    """Map a free-form location string to a cascader path."""
    for keywords, path in _LOCATION_PATHS:
        if any(kw in location_zh for kw in keywords):
            return path
    return None


def _auto_review_reason(metadata: dict) -> str:
    title = metadata.get("title_zh") or metadata.get("description_zh", "")
    if not str(title).strip():
        return "title is empty"
    keyword_count = len(metadata.get("keywords_zh", [])[:35])
    if keyword_count < 5:
        return f"only {keyword_count} keywords (min 5 required)"
    location = str(metadata.get("location_zh", "")).strip()
    if _resolve_path(location) is None:
        return (
            "platform location requires manual selection; verified location is "
            f"{location or '(unknown)'}"
        )
    if metadata.get("location_source", "unknown") == "unknown":
        return "shooting location has no evidence source"
    if metadata.get("location_confidence", "unknown") not in {"medium", "high"}:
        return "shooting location confidence is too low for automatic selection"
    return ""


def _resolution_review_reason(width: int, height: int) -> str:
    pixel_count = width * height
    if pixel_count <= MIN_PIXEL_COUNT:
        return (
            f"resolution is {width}x{height} ({pixel_count} pixels); "
            f"500px requires more than {MIN_PIXEL_COUNT} pixels"
        )
    return ""


def _image_review_reason(image: Path) -> str:
    try:
        with Image.open(image) as opened:
            return _resolution_review_reason(opened.width, opened.height)
    except OSError as error:
        return f"could not inspect image dimensions: {error}"


def _draft_save_is_confirmed(
    acknowledgement_seen: bool,
    error_count: int,
    actual_title: str,
    expected_title: str,
) -> bool:
    """Require an explicit save acknowledgement plus intact form state."""
    return (
        acknowledgement_seen
        and error_count == 0
        and actual_title == expected_title
    )


def _save_response_is_successful(response) -> bool:
    """Accept only the successful draft-save API response."""
    if response is None or not response.ok:
        return False
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("status") == 200


def _navigate_cascader(page: Page, path: list[str]) -> bool:
    """Click through the 3-level location cascader. Returns True on success."""
    # Open the cascader
    modern_picker = page.locator(
        "input.ant-select-selection-search-input[role='combobox']"
    )
    if modern_picker.count() > 0:
        picker = page.locator(
            ".ant-select-selector:has("
            "input.ant-select-selection-search-input[role='combobox'])"
        ).first
    else:
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
        encoded_label = json.dumps(label, ensure_ascii=False)
        item = menu.locator(
            f".ant-cascader-menu-item[title={encoded_label}]"
        ).first
        if item.count() == 0:
            return False
        item.click()
        page.wait_for_timeout(300)

    return True


def _fill_location(page: Page, location_zh: str) -> bool:
    """Fill a known shooting location without inventing a fallback location."""
    path = _resolve_path(location_zh) if location_zh else None
    if path:
        selected = page.locator(".ant-select-selection-item")
        if selected.count() > 0:
            selected_title = (selected.first.get_attribute("title") or "").replace(
                " ", ""
            )
            expected_parts = path[:-1] if path[-1] == "其他" else path
            expected_title = "/".join(expected_parts).replace(" ", "")
            if selected_title == expected_title:
                return True
    return bool(path and _navigate_cascader(page, path))


def _fill_metadata(page: Page, metadata: dict) -> bool:
    """Fill and save one draft, returning False when manual review is required."""
    # Dismiss any info popup
    try:
        page.locator("button:has-text('我知道了')").first.click(timeout=5_000)
    except PWTimeout:
        pass

    title = (metadata.get("title_zh") or metadata.get("description_zh", ""))[:50]
    keywords = metadata.get("keywords_zh", [])[:35]
    location = metadata.get("location_zh", "")
    if not title or len(keywords) < 5:
        print("  [review] title or required keywords are missing", flush=True)
        return False
    if _resolve_path(location) is None:
        print(
            "  [review] platform location requires manual selection; verified "
            f"location is {location or '(unknown)'}",
            flush=True,
        )
        return False
    if metadata.get("location_source", "unknown") == "unknown" or metadata.get(
        "location_confidence", "unknown"
    ) not in {"medium", "high"}:
        print("  [review] shooting location evidence is insufficient", flush=True)
        return False

    # Title
    title_sel = "input[placeholder*='一句话描述'], input.right-form-title"
    page.wait_for_selector(title_sel, timeout=30_000)
    page.locator(title_sel).first.fill(title)

    # Keywords — text mode replaces the complete set, so retries cannot append
    # stale or duplicate tags left by an interrupted edit.
    kw_sel = "input[placeholder*='关键词']"
    text_mode = page.locator("text=文本模式")
    if text_mode.count() > 0:
        text_mode.first.click()
        textarea = page.locator("textarea[placeholder*='关键词']").first
        try:
            textarea.wait_for(state="visible", timeout=5_000)
            textarea.fill(",".join(keywords))
            tag_mode = page.locator("text=标签模式")
            if tag_mode.count() > 0:
                tag_mode.first.click()
            page.wait_for_timeout(800)
        except PWTimeout:
            kw_input = page.locator(kw_sel).first
            kw_input.fill(",".join(keywords))
            kw_input.press("Enter")
            page.wait_for_timeout(800)
    else:
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
    save_response = None
    try:
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and "/api/draftBox/" in response.url
                and response.url.endswith("/save")
            ),
            timeout=90_000,
        ) as response_info:
            page.locator("button:has-text('保存草稿')").first.click()
        save_response = response_info.value
    except PWTimeout:
        # Older UI revisions acknowledged saves only through a transient toast.
        pass

    acknowledgement_seen = _save_response_is_successful(save_response)
    if not acknowledgement_seen:
        acknowledgement_seen = wait_for_success_text(
            page,
            ["保存成功", "草稿已保存", "操作成功"],
            timeout=3_000,
        )
    errors = page.locator(".ant-message-error, .ant-form-item-has-error")
    return _draft_save_is_confirmed(
        acknowledgement_seen,
        errors.count(),
        page.locator(title_sel).first.input_value(),
        title,
    )


def _select_upload_files(page: Page, images: list[Path]) -> None:
    """Open the photo notice, then set files on its generated input."""
    card_selector = "div._col.type_2_1:not(.disabled)"
    page.wait_for_selector(card_selector, state="visible", timeout=10_000)
    page.locator(card_selector).first.click()

    input_selector = (
        "button.webuploader-container input[type='file'][accept*='image/jpeg']"
    )
    page.wait_for_selector(input_selector, state="attached", timeout=10_000)
    page.locator(input_selector).first.set_input_files(
        [str(image) for image in images]
    )


def _wait_for_batch_ready(
    page: Page,
    pairs: list[tuple[Path, dict]],
    *,
    timeout_ms: int = 300_000,
) -> None:
    """Wait for uploads to finish, retrying each interrupted file once."""
    resume_attempts: dict[str, int] = {}
    elapsed = 0
    interval_ms = 5_000

    while elapsed < timeout_ms:
        retry_started = False
        for image, _ in pairs:
            filename = json.dumps(image.name, ensure_ascii=False)
            card = page.locator(f"div.card:has(span[title={filename}])")
            if card.count() == 0:
                continue
            interrupted = card.locator("text=上传中断")
            if interrupted.count() == 0:
                continue
            attempt = resume_attempts.get(image.name, 0)
            if attempt >= 3:
                continue
            print(
                f"  [retry {attempt + 1}/3] resuming interrupted upload: "
                f"{image.name}",
                flush=True,
            )
            resumed = False
            resume_link = card.locator("text=续传")
            if resume_link.count() > 0:
                try:
                    with page.expect_file_chooser(timeout=5_000) as chooser_info:
                        resume_link.first.click()
                    chooser_info.value.set_files(str(image))
                    resumed = True
                except PWTimeout:
                    pass
            if not resumed:
                upload_input = card.locator("input[type='file']")
                if upload_input.count() == 0:
                    continue
                upload_input.first.set_input_files(str(image))
            resume_attempts[image.name] = attempt + 1
            retry_started = True

        if retry_started:
            grace_elapsed = 0
            while grace_elapsed < 15_000:
                page.wait_for_timeout(1_000)
                grace_elapsed += 1_000
                mask = page.locator(".detailHasMask")
                if mask.count() > 0 and mask.first.is_visible():
                    break
                still_interrupted = False
                for image, _ in pairs:
                    if image.name not in resume_attempts:
                        continue
                    filename = json.dumps(image.name, ensure_ascii=False)
                    card = page.locator(
                        f"div.card:has(span[title={filename}])"
                    )
                    if (
                        card.count() > 0
                        and card.locator("text=上传中断").count() > 0
                    ):
                        still_interrupted = True
                        break
                if not still_interrupted:
                    break
            elapsed += grace_elapsed
            continue

        mask = page.locator(".detailHasMask")
        if mask.count() == 0 or not mask.first.is_visible():
            interrupted_names = []
            for image, _ in pairs:
                filename = json.dumps(image.name, ensure_ascii=False)
                card = page.locator(f"div.card:has(span[title={filename}])")
                if (
                    card.count() > 0
                    and card.locator("text=上传中断").count() > 0
                ):
                    interrupted_names.append(image.name)
            if interrupted_names:
                raise PWTimeout(
                    "500px uploads remain interrupted: "
                    + ", ".join(interrupted_names)
                )
            return
        page.wait_for_timeout(interval_ms)
        elapsed += interval_ms

    raise PWTimeout("500px uploads did not become ready before timeout")


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, UploadStatus]:
    """Upload all images in one file-chooser call, then fill metadata per draft page."""
    results = {img.name: UploadStatus.FAILED for img, _ in pairs}
    eligible_pairs = []
    for img, metadata in pairs:
        reason = _auto_review_reason(metadata) or _image_review_reason(img)
        if reason:
            print(f"  [review] 500px skipped {img.name}: {reason}", flush=True)
            results[img.name] = UploadStatus.NEEDS_REVIEW
        else:
            eligible_pairs.append((img, metadata))
    if not eligible_pairs:
        return results

    pairs = eligible_pairs
    page = context.new_page()
    total = len(pairs)
    i = -1

    try:
        for attempt in range(3):
            try:
                page.goto(UPLOAD_URL, wait_until="commit", timeout=30_000)
                page.wait_for_selector("button.button_cmp_main", timeout=60_000)
                break
            except PWTimeout:
                if attempt == 2:
                    raise
                page.wait_for_timeout(2_000)

        # Open upload modal
        page.locator("button.button_cmp_main").first.click()

        # Select all images through the actual input. The visible card no longer
        # reliably emits a file-chooser event in the current Creator Studio UI.
        _select_upload_files(page, [img for img, _ in pairs])

        # Wait for the batch draft page and all image spans to be in the DOM
        page.wait_for_url("**/draft/detail/**", timeout=120_000)
        last_img = json.dumps(pairs[-1][0].name, ensure_ascii=False)
        page.wait_for_selector(f"span[title={last_img}]", timeout=60_000)

        print(f"  Uploading {total} images...")
        _wait_for_batch_ready(page, pairs)
        for img, _ in pairs:
            results[img.name] = UploadStatus.UPLOADED

        # Clear pre-selection: select all → deselect all → exit multi-select if active
        page.locator("text=全选").first.click()
        page.wait_for_timeout(300)
        page.locator("text=取消全选").first.click()
        page.wait_for_timeout(300)
        multisel_chk = page.locator("label:has-text('多选') input[type='checkbox']")
        if multisel_chk.count() > 0 and multisel_chk.first.is_checked():
            page.locator("text=多选").first.click()
            page.wait_for_timeout(300)

        for i, (img, metadata) in enumerate(pairs):
            filename = json.dumps(img.name, ensure_ascii=False)
            page.locator(f"span[title={filename}]").click()
            page.wait_for_timeout(600)
            if _fill_metadata(page, metadata):
                print(f"  [{i + 1}/{total}] saved {img.name}")
                results[img.name] = UploadStatus.DRAFT_SAVED
            else:
                print(f"  [{i + 1}/{total}] review required {img.name}")

    except Exception as e:
        step = f"at image {i + 1}" if i >= 0 else "before upload loop"
        print(f"  ✗ 500px batch failed {step}: {e}")
    finally:
        page.close()

    return results
