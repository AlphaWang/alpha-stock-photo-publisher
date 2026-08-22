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
  11. For returned assets, switch to Editorial and click Submit; require the
      asset card to show Resubmitted before recording success
"""

from __future__ import annotations

from pathlib import Path
import json
import re
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, TimeoutError as PWTimeout

from .browser import ensure_logged_in
from .confirmation import wait_for_success_text
from .status import UploadStatus
from metadata_core import (
    EDITORIAL_DATE_SOURCES,
    LOCATION_SOURCES,
    commercial_submission_review_reason,
    platform_category,
)

PORTFOLIO_URL = "https://submit.shutterstock.com/portfolio/not_submitted/photo"
CORRECTION_URL = "https://submit.shutterstock.com/portfolio/recently_reviewed/photo/returned"
LOGIN_URL = "https://submit.shutterstock.com/"

CATEGORY_LABELS_ZH = {
    "Abstract": "抽象",
    "Animals/Wildlife": "动物/野生生物",
    "Arts": "艺术",
    "Backgrounds/Textures": "背景/素材",
    "Beauty/Fashion": "美容/時尚",
    "Buildings/Landmarks": "建筑物/地标",
    "Business/Finance": "商业/金融",
    "Celebrities": "名流",
    "Education": "教育",
    "Food and drink": "食品与饮料",
    "Healthcare/Medical": "医疗保健",
    "Holidays": "假日",
    "Industrial": "工业",
    "Interiors": "室内",
    "Miscellaneous": "其他",
    "Nature": "自然",
    "Objects": "物体",
    "Parks/Outdoor": "公园/户外",
    "People": "人物",
    "Religion": "宗教",
    "Science": "科学",
    "Signs/Symbols": "标识/符号",
    "Sports/Recreation": "运动/娱乐",
    "Technology": "科技",
    "Transportation": "运输",
    "Vintage": "复古风格",
}


def _has_logged_in_session(page) -> bool:
    url = page.url.lower()
    return (
        url.startswith("https://submit.shutterstock.com")
        and "login" not in url
        and "/next-oauth/" not in url
        and page.locator("[role='tab']").count() > 0
    )


def _is_logged_in(page) -> bool:
    try:
        page.goto(PORTFOLIO_URL, wait_until="domcontentloaded", timeout=20_000)
        return _has_logged_in_session(page)
    except PWTimeout:
        return False


def _dismiss_cookie_consent(page) -> None:
    """Close OneTrust without failing when the banner is absent."""
    for selector in (
        "#onetrust-reject-all-handler",
        "#onetrust-accept-btn-handler",
        "button:has-text('Reject All')",
        "button:has-text('Accept All Cookies')",
    ):
        button = page.locator(selector).first
        try:
            if button.count() > 0 and button.is_visible():
                button.click(force=True)
                page.locator("#onetrust-consent-sdk").wait_for(
                    state="hidden", timeout=5_000
                )
                return
        except Exception:
            continue


def _card_has_exact_filename(card, image_name: str) -> bool:
    if card.get_by_text(image_name, exact=True).count() > 0:
        return True
    return image_name in {
        line.strip() for line in card.inner_text().splitlines() if line.strip()
    }


def _find_asset_card(page, image_name: str):
    """Return one exact filename match, rejecting ambiguous platform cards."""
    cards = page.locator(".MuiCard-root")
    matches = []
    for index in range(cards.count()):
        card = cards.nth(index)
        if _card_has_exact_filename(card, image_name):
            matches.append(card)
    if len(matches) > 1:
        raise RuntimeError(
            f"multiple Shutterstock cards have the exact filename {image_name!r}"
        )
    return matches[0] if matches else None


def _canonical_category(label: str) -> str:
    cleaned = label.strip().replace("\u200b", "")
    for category, localized in CATEGORY_LABELS_ZH.items():
        if cleaned in {category, localized}:
            return category
    return cleaned


def _asset_card_is_ready(text: str) -> bool:
    normalized = " ".join(text.split()).casefold()
    return any(
        marker in normalized
        for marker in ("ready to submit", "可提交", "可以提交")
    )


def _keyword_count_from_text(text: str) -> int:
    match = re.search(r"(\d+)\s*/\s*50\s*(?:Keywords|关键词)", text, re.I)
    return int(match.group(1)) if match else 0


def _validation_payload_is_ready(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    statuses = payload.get("mediaStatus")
    return bool(statuses) and all(
        isinstance(item, dict) and item.get("status") == "ready"
        for item in statuses
    )


def _correction_is_editorial_eligible(text: str) -> bool:
    normalized = " ".join(text.split()).casefold()
    reason_count = re.search(r"\bcorrection needed\s*\((\d+)\)", normalized)
    return bool(
        reason_count
        and int(reason_count.group(1)) == 1
        and "eligible for editorial use" in normalized
    )


def _correction_was_resubmitted(text: str) -> bool:
    normalized = " ".join(text.split()).casefold()
    return "resubmitted" in normalized or "已重新提交" in normalized


def _submission_mode(meta: dict) -> tuple[str | None, str]:
    eligibility = str(meta.get("commercial_eligibility", "review")).strip().lower()
    if eligibility == "editorial_only":
        missing = [
            field
            for field in (
                "editorial_caption_en",
                "editorial_date",
                "editorial_location_en",
            )
            if not str(meta.get(field, "")).strip()
        ]
        if missing:
            return None, "editorial metadata is missing: " + ", ".join(missing)
        date_source = str(meta.get("editorial_date_source", "unknown")).strip().lower()
        if date_source not in EDITORIAL_DATE_SOURCES - {"unknown"}:
            return None, "editorial date has no evidence source"
        location_source = str(meta.get("location_source", "unknown")).strip().lower()
        if location_source not in LOCATION_SOURCES - {"unknown"}:
            return None, "editorial location has no evidence source"
        if str(meta.get("location_confidence", "unknown")).strip().lower() not in {
            "medium",
            "high",
        }:
            return None, "editorial location confidence is below medium"
        return "editorial", ""

    reason = commercial_submission_review_reason(meta)
    if reason:
        return None, reason
    return "commercial", ""


def _ensure_english_metadata_language(page) -> None:
    control = page.locator("[aria-label='select_language']").first
    if "English" in control.inner_text():
        return
    control.click()
    english = page.get_by_text("English", exact=True).last
    english.wait_for(state="visible", timeout=5_000)
    english.click()
    control.filter(has_text="English").wait_for(state="visible", timeout=5_000)


def _set_category(page, field: str, category: str) -> bool:
    control = page.locator(f"[data-testid='{field}']")
    if _canonical_category(control.inner_text()) == category:
        return True

    button = control.locator("div[role='button']")
    for _ in range(25):
        if button.is_enabled():
            break
        page.wait_for_timeout(200)
    else:
        print(f"  [review] Shutterstock category control disabled: {field}")
        return False
    button.click(timeout=5_000)
    options = page.locator("li.MuiMenuItem-root:visible")
    option = options.filter(has_text=category).first
    if option.count() == 0:
        localized = CATEGORY_LABELS_ZH.get(category, category)
        option = options.filter(has_text=localized).first
    if option.count() == 0 or not option.is_enabled():
        page.keyboard.press("Escape")
        print(f"  [review] Shutterstock category unavailable: {category}")
        return False
    option.click(timeout=5_000)
    for _ in range(25):
        if _canonical_category(control.inner_text()) == category:
            return True
        page.wait_for_timeout(200)
    print(f"  [review] Shutterstock category was not applied: {category}")
    return False


def _set_categories(page, category1: str, category2: str) -> bool:
    current1 = _canonical_category(
        page.locator("[data-testid='category1']").inner_text()
    )
    current2 = _canonical_category(
        page.locator("[data-testid='category2']").inner_text()
    )
    desired = [value for value in (category1, category2) if value]
    current = [value for value in (current1, current2) if value]
    if desired == current or (len(desired) == 2 and set(desired) == set(current)):
        return True

    # Shutterstock disables a category while it is selected in the other slot.
    # Move category 2 first when that frees the desired primary category.
    if category1 and current2 == category1 and category2:
        if not _set_category(page, "category2", category2):
            return False
    if category1 and not _set_category(page, "category1", category1):
        return False
    if category2 and not _set_category(page, "category2", category2):
        return False
    return True


def _set_usage(page, usage: str) -> bool:
    test_id = "button-editorial" if usage == "editorial" else "button-commercial"
    control = page.locator(f"form [data-testid='{test_id}']").last
    if control.count() == 0:
        print("  [review] Shutterstock usage control was not found", flush=True)
        return False
    if control.get_attribute("aria-pressed") == "true":
        return True

    control.click(timeout=5_000)
    page.wait_for_timeout(250)
    return control.get_attribute("aria-pressed") == "true"


def _normalized_keyword_values(values) -> list[str]:
    return [
        " ".join(str(value).split()).casefold()
        for value in values
        if " ".join(str(value).split())
    ]


def _selected_keyword_values(page) -> list[str]:
    chips = page.locator("form [data-testid^='selected-keyword-']")
    return _normalized_keyword_values(
        chips.nth(index).inner_text() for index in range(chips.count())
    )


def _wait_for_selected_keywords(
    page,
    expected: list[str],
    *,
    timeout_ms: int = 5_000,
) -> list[str]:
    elapsed = 0
    interval_ms = 100
    while elapsed < timeout_ms:
        actual = _selected_keyword_values(page)
        if actual == expected:
            return actual
        page.wait_for_timeout(interval_ms)
        elapsed += interval_ms
    return _selected_keyword_values(page)


def _replace_keywords(page, keywords: list[str]) -> None:
    expected = _normalized_keyword_values(keywords)
    keyword_count = _keyword_count_from_text(page.locator("form").inner_text())
    chips = page.locator("form [data-testid^='selected-keyword-']")
    if keyword_count or chips.count() > 0:
        actions = page.locator("button[aria-label='More keyword actions']").last
        erased = False
        if actions.count() > 0:
            actions.click(timeout=5_000)
            erase = page.get_by_text(
                re.compile(
                    r"^(Erase all keywords|Clear all keywords|清除所有关键词)$",
                    re.I,
                )
            ).last
            if erase.count() > 0 and erase.is_visible():
                erase.click(timeout=5_000)
                erased = _wait_for_selected_keywords(page, []) == []
            else:
                page.keyboard.press("Escape")
        if not erased:
            for _ in range(50):
                if chips.count() == 0:
                    erased = True
                    break
                before = chips.count()
                chips.first.press("Delete")
                page.wait_for_timeout(100)
                if chips.count() >= before:
                    break
            erased = _selected_keyword_values(page) == []
        if not erased:
            raise RuntimeError("existing Shutterstock keywords could not be cleared")
        # The keyword input is briefly replaced after the final chip disappears.
        page.wait_for_timeout(250)

    kw_input = page.locator(
        "input[placeholder*='Add keyword'], input[placeholder*='添加关键词']"
    ).first
    kw_input.click()
    kw_input.fill(", ".join(keywords))
    kw_input.press("Enter")
    actual = _wait_for_selected_keywords(page, expected)
    if actual != expected:
        raise RuntimeError(
            "Shutterstock keyword replacement did not preserve the expected "
            f"ordered values: produced {actual!r}, expected {expected!r}"
        )


def _wait_for_resubmitted_asset(
    page,
    image_name: str,
    *,
    timeout_ms: int = 10_000,
) -> bool:
    elapsed = 0
    interval_ms = 250
    while elapsed < timeout_ms:
        card = _find_asset_card(page, image_name)
        if card is not None and _correction_was_resubmitted(card.inner_text()):
            return True
        page.wait_for_timeout(interval_ms)
        elapsed += interval_ms
    return False


def _fill_metadata(page, img: Path, meta: dict, *, correction: bool = False) -> bool:
    """Fill description, keywords, and categories for the currently open edit panel."""
    usage, review_reason = _submission_mode(meta)
    if review_reason:
        print(f"  [review] {img.name}: {review_reason}")
        return False
    # Wait for the panel to show THIS image's title before filling anything.
    # Without this, a React re-render caused by the card transition can clear
    # a description we already filled.
    filename = json.dumps(img.name, ensure_ascii=False)
    page.wait_for_selector(f"h3:has-text({filename})", timeout=20_000)
    page.wait_for_timeout(400)  # let React finish rendering the freshly opened panel
    _ensure_english_metadata_language(page)

    desc_text = (
        meta.get("editorial_caption_en", "")
        if usage == "editorial"
        else meta.get("description_en", "")
    )
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

    _replace_keywords(page, meta.get("keywords_en", []))

    if not _set_usage(page, usage):
        print(f"  [review] {img.name}: Shutterstock usage was not set to {usage}")
        return False

    platform_categories = platform_category(meta, "shutterstock")
    if isinstance(platform_categories, list) and platform_categories:
        cat1 = platform_categories[0]
        cat2 = platform_categories[1] if len(platform_categories) > 1 else ""
    else:
        cat1, cat2 = meta.get("category1", ""), meta.get("category2", "")
    if not _set_categories(page, cat1, cat2):
        return False

    action_test_id = (
        "edit-dialog-submit-button" if correction else "edit-dialog-save-button"
    )
    save_button = page.locator(f"[data-testid='{action_test_id}']")
    save_response = None
    try:
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path.endswith("/api/next/media/validate")
            ),
            timeout=3_000,
        ) as response_info:
            save_button.click()
        save_response = response_info.value
    except PWTimeout:
        pass
    if save_response is not None:
        if not save_response.ok:
            return False
        try:
            response_ready = _validation_payload_is_ready(save_response.json())
        except Exception:
            return False
        if not response_ready:
            return False

    if correction:
        # A successful correction may not emit the normal validation response.
        # The returned-asset card is authoritative and changes to Resubmitted.
        return _wait_for_resubmitted_asset(page, img.name)

    if save_response is not None:
        return True

    page.wait_for_timeout(1_200)
    card = _find_asset_card(page, img.name)
    if card is not None and _asset_card_is_ready(card.inner_text()):
        return True

    # The portfolio card can lag behind a successful save until the next reload.
    # Accept the persisted form state when all required fields remain intact and
    # Shutterstock shows no validation alert.
    categories_match = (
        _canonical_category(page.locator("[data-testid='category1']").inner_text())
        == cat1
        and _canonical_category(page.locator("[data-testid='category2']").inner_text())
        == cat2
    )
    keyword_count = _keyword_count_from_text(page.locator("body").inner_text())
    validation_error = page.locator(
        ".MuiAlert-standardError:visible, [role='alert']:visible"
    ).count()
    if (
        desc_area.input_value() == desc_text
        and categories_match
        and keyword_count >= 7
        and validation_error == 0
    ):
        return True

    if card is not None:
        try:
            card.wait_for(state="visible", timeout=4_000)
            if _asset_card_is_ready(card.inner_text()):
                return True
        except PWTimeout:
            pass
    if wait_for_success_text(
        page, ["saved", "changes saved", "asset saved", "已保存"], timeout=1_000
    ):
        return True
    try:
        page.wait_for_function(
            """() => {
                const button = document.querySelector(
                    '[data-testid="edit-dialog-save-button"]'
                );
                return !button || button.disabled || button.getAttribute('aria-disabled') === 'true';
            }""",
            timeout=2_000,
        )
        return True
    except PWTimeout:
        return False


def upload_batch(pairs: list[tuple[Path, dict]], context: BrowserContext) -> dict[str, UploadStatus]:
    """Upload all images in one file-chooser call, then fill metadata card by card."""
    page = context.new_page()
    try:
        ensure_logged_in(
            page,
            lambda: _is_logged_in(page),
            LOGIN_URL,
            poll_logged_in=lambda: _has_logged_in_session(page),
        )
        page.goto(PORTFOLIO_URL, wait_until="domcontentloaded", timeout=20_000)
        _dismiss_cookie_consent(page)

        # Resume assets already present in Not submitted, uploading only missing files.
        pre_count = page.locator(".MuiCard-root").count()
        missing_pairs = []
        results: dict[str, UploadStatus] = {}
        for img, meta in pairs:
            if _find_asset_card(page, img.name) is not None:
                results[img.name] = UploadStatus.UPLOADED
                print(f"  Resuming existing Shutterstock asset: {img.name}")
            else:
                missing_pairs.append((img, meta))

        if missing_pairs:
            page.locator("button.MuiButton-contained:has-text('Upload')").click()
            page.wait_for_selector("button:has-text('Upload assets')", timeout=10_000)
            with page.expect_file_chooser() as fc_info:
                page.locator("button:has-text('Upload assets')").click()
            fc_info.value.set_files([str(img) for img, _ in missing_pairs])
            print(f"  Uploading {len(missing_pairs)} missing file(s)...")

            page.wait_for_function(
                "() => /Upload complete|上传完成/i.test(document.body.innerText)",
                timeout=300_000,
            )
            page.goto(PORTFOLIO_URL, wait_until="networkidle", timeout=60_000)
            _dismiss_cookie_consent(page)
            expected = pre_count + len(missing_pairs)
            page.wait_for_function(
                f"() => document.querySelectorAll('.MuiCard-root').length >= {expected}",
                timeout=300_000,
            )
            for img, _ in missing_pairs:
                results[img.name] = UploadStatus.UPLOADED
        else:
            print("  All files already exist in Shutterstock; skipping transfer")

        # Fill metadata for each image by locating its card by filename
        for img, meta in pairs:
            for attempt in range(2):
                try:
                    _dismiss_cookie_consent(page)
                    card = _find_asset_card(page, img.name)
                    if card is None:
                        raise RuntimeError("asset card was not found by exact filename")
                    if _asset_card_is_ready(card.inner_text()):
                        print(f"  ✓ Shutterstock draft already ready: {img.name}")
                        results[img.name] = UploadStatus.DRAFT_SAVED
                        break
                    card.scroll_into_view_if_needed()
                    bbox = card.bounding_box()
                    page.mouse.click(
                        bbox["x"] + bbox["width"] / 2,
                        bbox["y"] + bbox["height"] * 0.35,
                    )

                    if not _fill_metadata(page, img, meta):
                        raise RuntimeError("save was not confirmed")
                    print(f"  ✓ Shutterstock draft saved: {img.name}")
                    results[img.name] = UploadStatus.DRAFT_SAVED
                    break
                except Exception as e:
                    if attempt == 0 and not page.is_closed():
                        print(
                            f"  [retry] Shutterstock {img.name}: {e}",
                            flush=True,
                        )
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                        continue
                    print(f"  ✗ Shutterstock: {img.name} — {e}")
                    results[img.name] = UploadStatus.UPLOADED

        return results

    except Exception as e:
        print(f"  ✗ Shutterstock batch upload failed — {e}")
        return {img.name: UploadStatus.FAILED for img, _ in pairs}
    finally:
        page.close()


def repair_corrections_batch(
    pairs: list[tuple[Path, dict]], context: BrowserContext
) -> dict[str, UploadStatus]:
    """Repair editorial-eligible Shutterstock returns without re-uploading files."""
    page = context.new_page()
    try:
        ensure_logged_in(
            page,
            lambda: _is_logged_in(page),
            LOGIN_URL,
            poll_logged_in=lambda: _has_logged_in_session(page),
        )
        page.goto(CORRECTION_URL, wait_until="domcontentloaded", timeout=30_000)
        _dismiss_cookie_consent(page)
        results: dict[str, UploadStatus] = {}
        for img, meta in pairs:
            try:
                card = _find_asset_card(page, img.name)
                if card is None:
                    print(
                        f"  [review] Shutterstock correction not found: {img.name}",
                        flush=True,
                    )
                    results[img.name] = UploadStatus.NEEDS_REVIEW
                    continue
                card_text = card.inner_text()
                if _correction_was_resubmitted(card_text):
                    print(
                        f"  ✓ Shutterstock correction already submitted: {img.name}",
                        flush=True,
                    )
                    results[img.name] = UploadStatus.SUBMITTED
                    continue
                if not _correction_is_editorial_eligible(card_text):
                    print(
                        f"  [review] Unsupported Shutterstock correction: {img.name}",
                        flush=True,
                    )
                    results[img.name] = UploadStatus.NEEDS_REVIEW
                    continue
                mode, reason = _submission_mode(meta)
                if mode != "editorial":
                    print(
                        f"  [review] {img.name}: {reason or 'editorial metadata is required'}",
                        flush=True,
                    )
                    results[img.name] = UploadStatus.NEEDS_REVIEW
                    continue

                card.locator("button:has-text('Make changes')").click(timeout=5_000)
                if not _fill_metadata(page, img, meta, correction=True):
                    raise RuntimeError("editorial correction save was not confirmed")
                print(f"  ✓ Shutterstock correction submitted: {img.name}", flush=True)
                results[img.name] = UploadStatus.SUBMITTED
                page.wait_for_timeout(500)
            except Exception as error:
                print(f"  ✗ Shutterstock correction: {img.name} — {error}", flush=True)
                results[img.name] = UploadStatus.FAILED
                if not page.is_closed():
                    page.keyboard.press("Escape")
        return results
    except Exception as error:
        print(f"  ✗ Shutterstock correction repair failed — {error}", flush=True)
        return {img.name: UploadStatus.FAILED for img, _ in pairs}
    finally:
        page.close()


def upload(image_path: Path, metadata: dict, context: BrowserContext) -> bool:
    """Single-image upload (kept for compatibility). Delegates to upload_batch."""
    results = upload_batch([(image_path, metadata)], context)
    return results.get(image_path.name, UploadStatus.FAILED).completed
