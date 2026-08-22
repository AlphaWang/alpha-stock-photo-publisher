import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Pure upload rules should remain testable without launching or installing a browser.
if "playwright.sync_api" not in sys.modules:
    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.BrowserContext = object
    sync_api.Error = Exception
    sync_api.Page = object
    sync_api.TimeoutError = TimeoutError
    sync_api.sync_playwright = object
    playwright.sync_api = sync_api
    sys.modules["playwright"] = playwright
    sys.modules["playwright.sync_api"] = sync_api

from upload.adobestock import _auto_review_reason as adobe_review_reason
from upload.adobestock import _extract_original_filename as adobe_original_filename
from upload.adobestock import _has_logged_in_session as adobe_session_ready
from upload.adobestock import _resolve_category as resolve_adobe_category
from upload.adobestock import upload_batch as upload_adobe_batch
from upload.istock import _auto_review_reason as istock_review_reason
from upload.px500 import _auto_review_reason as px500_review_reason
from upload.px500 import (
    _draft_save_is_confirmed as px500_save_confirmed,
    _save_response_is_successful as px500_response_successful,
)
from upload.px500 import _resolve_path
from upload.px500 import _resolution_review_reason as px500_resolution_review_reason
import upload.px500 as px500_module
from upload.status import UploadStatus
import upload.browser as browser_module
from upload.confirmation import wait_for_success_text
from upload.shutterstock import (
    _asset_card_is_ready,
    _canonical_category,
    _correction_is_editorial_eligible,
    _correction_was_resubmitted,
    _keyword_count_from_text,
    _set_usage,
    _submission_mode,
    _validation_payload_is_ready,
    _has_logged_in_session as shutterstock_session_ready,
)
from upload.tuchong import _login_page_session_ready as tuchong_login_ready
from upload_photos import (
    _image_digest,
    _history_entry_completed,
    _load_history,
    _platform_enabled,
    _save_history,
    _validate_metadata_binding,
    find_pairs,
)
from upload_photos import _result_counts
from cleanup_tuchong_drafts import DraftCard, _delete_card
from test_visual_facts import complete_visual_facts
from visual_facts import visual_facts_sha256


def complete_bound_metadata(image, *, include_hash=True, verified=True):
    metadata = {
        "source": image.name,
        "title_en": "Sunlit mountain landscape",
        "title_zh": "阳光下的山地景观",
        "description_en": "A sunlit mountain rises above a green summer meadow.",
        "description_zh": "阳光照亮山峰和绿色夏季草地。",
        "keywords_en": [
            "mountain", "green meadow", "sunlight", "summer landscape",
            "blue sky", "outdoors", "nature", "scenic", "wilderness",
            "alpine", "grassland", "daylight", "tranquil", "travel destination",
            "natural beauty", "copy space", "horizontal", "environment",
            "rural", "panoramic",
        ],
        "keywords_zh": [
            "山峰", "绿色草地", "阳光", "夏季风景", "蓝天",
            "户外", "自然", "高山", "宁静", "旅行",
        ],
        "category1": "Nature",
        "category2": "Parks/Outdoor",
        "location_zh": "",
        "core_keywords_zh": ["山峰", "绿色草地", "阳光", "夏季风景", "蓝天"],
        "commercial_uses_en": ["travel marketing"],
        "release_status": "clear",
        "release_notes": "",
        "visual_review_status": "verified" if verified else "unreviewed",
    }
    if include_hash:
        metadata["source_sha256"] = _image_digest(image)
    return metadata


class UploadLogicTests(unittest.TestCase):
    def test_agent_native_upload_requires_bound_visual_facts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "photo.jpg"
            image.write_bytes(bytes.fromhex(
                "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
            ))
            metadata = complete_bound_metadata(image)
            metadata["visual_review_method"] = "agent-native"

            with self.assertRaisesRegex(ValueError, "missing machine-readable"):
                _validate_metadata_binding(image, metadata, False)

    def test_upload_rechecks_metadata_against_visual_facts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "photo.jpg"
            image.write_bytes(bytes.fromhex(
                "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
            ))
            metadata = complete_bound_metadata(image)
            metadata["visual_review_method"] = "agent-native"
            metadata["description_en"] = (
                "A sunlit mountain rises above a lake and green meadow."
            )
            facts = {
                **complete_visual_facts(),
                "primary_subjects_en": ["mountain"],
                "primary_subjects_zh": ["山峰"],
                "water_visible": "no",
                "scene_signature": "mountain-meadow",
            }
            metadata["visual_facts"] = facts
            metadata["visual_facts_sha256"] = visual_facts_sha256(facts)

            with self.assertRaisesRegex(ValueError, "water_visible=no"):
                _validate_metadata_binding(image, metadata, False)

    def test_500px_requires_explicit_save_confirmation(self):
        self.assertTrue(px500_save_confirmed(True, 0, "标题", "标题"))
        self.assertFalse(px500_save_confirmed(False, 0, "标题", "标题"))
        self.assertFalse(px500_save_confirmed(True, 1, "标题", "标题"))
        self.assertFalse(px500_save_confirmed(True, 0, "", "标题"))

    def test_500px_accepts_only_successful_save_response(self):
        successful = Mock(ok=True)
        successful.json.return_value = {"status": 200, "data": {}}
        failed = Mock(ok=True)
        failed.json.return_value = {"status": 500, "message": "failed"}
        invalid = Mock(ok=True)
        invalid.json.side_effect = ValueError("not json")

        self.assertTrue(px500_response_successful(successful))
        self.assertFalse(px500_response_successful(failed))
        self.assertFalse(px500_response_successful(invalid))
        self.assertFalse(px500_response_successful(None))

    def test_shutterstock_category_labels_are_canonicalized(self):
        self.assertEqual(_canonical_category("Nature"), "Nature")
        self.assertEqual(_canonical_category("自然"), "Nature")
        self.assertEqual(_canonical_category("\u200b公园/户外\u200b"), "Parks/Outdoor")

    def test_shutterstock_ready_card_supports_localized_status(self):
        self.assertTrue(_asset_card_is_ready("DSC.jpg\nReady to submit"))
        self.assertTrue(_asset_card_is_ready("DSC.jpg\n可提交"))
        self.assertFalse(_asset_card_is_ready("DSC.jpg\nMissing information"))

    def test_shutterstock_keyword_count_supports_localized_text(self):
        self.assertEqual(_keyword_count_from_text("27/50 Keywords"), 27)
        self.assertEqual(_keyword_count_from_text("7 / 50 关键词"), 7)
        self.assertEqual(_keyword_count_from_text("Keywords"), 0)

    def test_shutterstock_validation_requires_ready_media(self):
        self.assertTrue(
            _validation_payload_is_ready(
                {"mediaStatus": [{"id": "1", "status": "ready"}]}
            )
        )
        self.assertFalse(
            _validation_payload_is_ready(
                {"mediaStatus": [{"id": "1", "status": "needs_attention"}]}
            )
        )

    def test_shutterstock_correction_requires_editorial_eligibility_reason(self):
        self.assertTrue(
            _correction_is_editorial_eligible(
                "Correction needed (1) Eligible for Editorial Use"
            )
        )
        self.assertFalse(
            _correction_is_editorial_eligible("Correction needed: add a release")
        )

    def test_shutterstock_correction_requires_resubmitted_card_status(self):
        self.assertTrue(
            _correction_was_resubmitted(
                "DSC02975.jpg Editorial Resubmitted View corrections"
            )
        )
        self.assertTrue(_correction_was_resubmitted("DSC02975.jpg 已重新提交"))
        self.assertFalse(
            _correction_was_resubmitted(
                "DSC02975.jpg Editorial Correction needed Make changes"
            )
        )

    def test_shutterstock_usage_selects_explicit_editorial_button(self):
        class UsageControl:
            pressed = False

            @property
            def last(self):
                return self

            def count(self):
                return 1

            def get_attribute(self, name):
                return "true" if self.pressed else "false"

            def click(self, timeout):
                self.pressed = True

        class Page:
            def __init__(self):
                self.selector = ""
                self.control = UsageControl()

            def locator(self, selector):
                self.selector = selector
                return self.control

            def wait_for_timeout(self, timeout):
                return None

        page = Page()
        self.assertTrue(_set_usage(page, "editorial"))
        self.assertEqual(page.selector, "form [data-testid='button-editorial']")

    def test_shutterstock_editorial_mode_requires_complete_caption_fields(self):
        metadata = {
            "commercial_eligibility": "editorial_only",
            "editorial_caption_en": "",
            "editorial_date": "2026-06-27",
            "editorial_location_en": "Grand Teton National Park, Wyoming, USA",
        }
        mode, reason = _submission_mode(metadata)
        self.assertIsNone(mode)
        self.assertIn("editorial_caption_en", reason)

        metadata["editorial_caption_en"] = (
            "Grand Teton National Park, Wyoming, USA - 27 June 2026: "
            "Kayakers cross a mountain lake below the Teton Range."
        )
        self.assertEqual(_submission_mode(metadata), ("editorial", ""))

    def test_shutterstock_commercial_mode_preserves_release_preflight(self):
        metadata = {
            "model_release_status": "not_required",
            "property_release_status": "not_required",
            "logo_trademark_status": "none",
            "copyrighted_content_status": "none",
            "commercial_eligibility": "clear",
        }
        self.assertEqual(_submission_mode(metadata), ("commercial", ""))
        metadata["logo_trademark_status"] = "visible"
        mode, reason = _submission_mode(metadata)
        self.assertIsNone(mode)
        self.assertIn("logo/trademark", reason)

    def test_adobe_original_filename_ignores_footer_actions(self):
        footer = (
            "File ID(s): 2151393607 - Original name(s): DSC01452.jpg"
            "Actions:Erase all keywordsRefresh auto-category"
        )
        self.assertEqual(adobe_original_filename(footer), "DSC01452.jpg")

    def test_adobe_login_requires_contributor_ui(self):
        class Locator:
            def __init__(self, count):
                self._count = count

            def count(self):
                return self._count

        class Page:
            url = "https://contributor.stock.adobe.com/en/"

            def __init__(self, control_count):
                self.control_count = control_count

            def locator(self, _selector):
                return Locator(self.control_count)

        self.assertFalse(adobe_session_ready(Page(0)))
        self.assertTrue(adobe_session_ready(Page(1)))

    def test_uploaded_history_entry_remains_resumable(self):
        self.assertFalse(_history_entry_completed({"status": "uploaded"}))
        self.assertTrue(_history_entry_completed({"status": "draft_saved"}))
        self.assertTrue(_history_entry_completed({"status": "submitted"}))
        self.assertTrue(_history_entry_completed({"filename": "legacy.jpg"}))

    def test_500px_browser_uses_system_dns_fallback(self):
        address = (
            browser_module.socket.AF_INET,
            browser_module.socket.SOCK_STREAM,
            6,
            "",
            ("220.185.183.29", 443),
        )
        connection = types.SimpleNamespace(close=lambda: None)
        with patch.object(
            browser_module.socket, "getaddrinfo", return_value=[address]
        ):
            with patch.object(
                browser_module.socket,
                "create_connection",
                return_value=connection,
            ):
                args = browser_module._browser_args("px500")
        self.assertIn(
            "--host-resolver-rules=MAP creatorstudio.500px.com.cn 220.185.183.29",
            args,
        )
        self.assertEqual(
            browser_module._browser_args("shutterstock"),
            ["--disable-blink-features=AutomationControlled"],
        )

    def test_all_enables_stable_platforms_only(self):
        self.assertTrue(_platform_enabled("all", "adobestock"))
        self.assertTrue(_platform_enabled("all", "tuchong"))
        self.assertFalse(_platform_enabled("all", "istock"))
        self.assertTrue(_platform_enabled("istock", "istock"))

    def test_result_counts_are_per_platform(self):
        self.assertEqual(_result_counts({"a.jpg": True, "b.jpg": False}), (1, 1))

    def test_known_500px_location_is_mapped(self):
        self.assertEqual(_resolve_path("美国旧金山湾区"), ["美国", "加利福尼亚", "旧金山"])
        self.assertEqual(_resolve_path("SLC road trip"), ["美国", "犹他", "其他"])
        self.assertEqual(
            _resolve_path("美国犹他州邦纳维尔盐滩"), ["美国", "犹他", "其他"]
        )
        self.assertEqual(
            _resolve_path("美国怀俄明州大提顿国家公园"),
            ["美国", "怀俄明", "其他"],
        )

    def test_500px_requires_more_than_six_megapixels(self):
        self.assertIn(
            "requires more than 6000000",
            px500_resolution_review_reason(1701, 2552),
        )
        self.assertEqual(px500_resolution_review_reason(3001, 2000), "")

    def test_500px_creator_studio_uses_community_bridge(self):
        redirect_url = (
            "https://creatorstudio.500px.com.cn/api/redirect/index?access_token=test"
        )

        class Locator:
            @property
            def first(self):
                return self

            def count(self):
                return 1

            def get_attribute(self, name):
                return redirect_url

        class Page:
            def __init__(self):
                self.url = "https://500px.com.cn/community/index.html"
                self.urls = []

            def goto(self, url, **kwargs):
                self.urls.append(url)
                self.url = url
                if url == redirect_url:
                    self.url = px500_module.UPLOAD_URL

            def wait_for_selector(self, selector, timeout):
                return None

            def locator(self, selector):
                return Locator()

        page = Page()
        self.assertTrue(px500_module._enter_creator_studio(page))
        self.assertEqual(
            page.urls,
            [px500_module.CONTRIBUTOR_BRIDGE_URL, redirect_url],
        )

    def test_500px_recognizes_new_creator_center_button(self):
        class Locator:
            def __init__(self, count):
                self._count = count

            def count(self):
                return self._count

        class Page:
            url = "https://500px.com.cn/community/index.html"

            def locator(self, selector):
                return Locator(1 if selector == "text=前往创作者中心" else 0)

        self.assertTrue(px500_module._community_session_ready(Page()))

    def test_500px_detects_creator_studio_opened_in_new_tab(self):
        class Locator:
            def __init__(self, count):
                self._count = count

            def count(self):
                return self._count

        class Page:
            def __init__(self, url, button_count):
                self.url = url
                self.button_count = button_count

            def locator(self, selector):
                return Locator(self.button_count)

        context = types.SimpleNamespace(
            pages=[
                Page("https://500px.com.cn/community/index.html", 0),
                Page(px500_module.UPLOAD_URL, 1),
            ]
        )
        self.assertTrue(px500_module._context_has_logged_in_session(context))

    def test_500px_sets_files_on_active_photo_input(self):
        selected = []

        class Locator:
            @property
            def first(self):
                return self

            def set_input_files(self, files):
                selected.extend(files)

            def click(self):
                return None

        class Page:
            def wait_for_selector(self, selector, **kwargs):
                self.selector = selector

            def locator(self, selector):
                return Locator()

        page = Page()
        px500_module._select_upload_files(
            page,
            [Path("/photos/a.jpg"), Path("/photos/b.jpg")],
        )
        self.assertIn("webuploader-container", page.selector)
        self.assertEqual(selected, ["/photos/a.jpg", "/photos/b.jpg"])

    def test_500px_rejects_interrupted_upload_after_mask_hides(self):
        class Locator:
            @property
            def first(self):
                return self

            def __init__(self, count=0, visible=False, card=False):
                self._count = count
                self._visible = visible
                self._card = card

            def count(self):
                return self._count

            def is_visible(self):
                return self._visible

            def locator(self, selector):
                if self._card and selector == "text=上传中断":
                    return Locator(count=1)
                return Locator()

        class Page:
            def locator(self, selector):
                if selector == ".detailHasMask":
                    return Locator(count=1, visible=False)
                if selector.startswith("div.card:has("):
                    return Locator(count=1, card=True)
                return Locator()

            def wait_for_timeout(self, timeout):
                return None

        with self.assertRaisesRegex(TimeoutError, "remain interrupted: a.jpg"):
            px500_module._wait_for_batch_ready(
                Page(), [(Path("a.jpg"), {})], timeout_ms=1_000
            )

    def test_500px_prefers_modern_location_combobox(self):
        clicks = []

        class Locator:
            @property
            def first(self):
                return self

            def count(self):
                return 1

            def click(self):
                clicks.append(True)

        class EmptyMenus:
            def count(self):
                return 0

        class Page:
            def locator(self, selector):
                if selector == ".ant-cascader-menu":
                    return EmptyMenus()
                return Locator()

            def wait_for_timeout(self, timeout):
                return None

            def wait_for_selector(self, selector, timeout):
                return None

        self.assertFalse(
            px500_module._navigate_cascader(
                Page(), ["美国", "犹他", "其他"]
            )
        )
        self.assertEqual(clicks, [True])

    def test_500px_reuses_matching_selected_location(self):
        class Locator:
            @property
            def first(self):
                return self

            def count(self):
                return 1

            def get_attribute(self, name):
                return "美国 / 犹他"

        class Page:
            def locator(self, selector):
                return Locator()

        with patch.object(px500_module, "_navigate_cascader") as navigate:
            self.assertTrue(
                px500_module._fill_location(
                    Page(), "美国犹他州邦纳维尔盐滩"
                )
            )
        navigate.assert_not_called()

    def test_unknown_500px_location_requires_review(self):
        self.assertIsNone(_resolve_path("未知地点"))
        self.assertIsNone(_resolve_path(""))

    def test_adobe_category_mapping(self):
        self.assertEqual(resolve_adobe_category("Business/Finance"), "Business")
        self.assertIsNone(resolve_adobe_category("Not a category"))

    def test_release_notes_block_automatic_submission(self):
        metadata = {
            "title_en": "City street",
            "description_en": "A city street in daylight.",
            "keywords_en": ["city", "street", "travel", "urban", "daylight"],
            "release_status": "clear",
            "release_notes": "Visible logo may require cleanup",
        }
        self.assertIn("release review required", adobe_review_reason(metadata))
        self.assertIn("release review required", istock_review_reason(metadata))

        class NoBrowserContext:
            def new_page(self):
                raise AssertionError("review items must be filtered before browser upload")

        result = upload_adobe_batch([(Path("city.jpg"), metadata)], NoBrowserContext())
        self.assertEqual(result, {"city.jpg": UploadStatus.NEEDS_REVIEW})

    def test_unknown_location_blocks_500px_upload(self):
        metadata = {
            "description_zh": "山间清晨的自然风景",
            "keywords_zh": ["山", "清晨", "自然", "风景", "旅行"],
            "location_zh": "",
        }
        self.assertIn("manual selection", px500_review_reason(metadata))

    def test_upload_history_round_trip_uses_content_digest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image = directory / "photo.jpg"
            image.write_bytes(b"stock-photo-content")
            digest = _image_digest(image)
            history = {
                "version": 1,
                "uploads": {"adobestock": {digest: {"filename": image.name}}},
            }
            _save_history(directory, history)
            self.assertEqual(_load_history(directory), history)

    def test_metadata_binding_detects_replaced_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "photo.jpg"
            image.write_bytes(bytes.fromhex(
                "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
            ))
            metadata = complete_bound_metadata(image)
            _validate_metadata_binding(image, metadata, False)
            image.write_bytes(bytes.fromhex(
                "47494638396101000100800000ff0000ffffff21f90401000000002c00000000010001000002024401003b"
            ))
            with self.assertRaisesRegex(ValueError, "content changed"):
                _validate_metadata_binding(image, metadata, False)

    def test_legacy_unbound_metadata_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "photo.jpg"
            image.write_bytes(bytes.fromhex(
                "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
            ))
            metadata = complete_bound_metadata(image, include_hash=False)

            with self.assertRaisesRegex(ValueError, "no source_sha256"):
                _validate_metadata_binding(image, metadata, False)
            _validate_metadata_binding(image, metadata, True)

    def test_unreviewed_metadata_is_blocked_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "photo.jpg"
            image.write_bytes(bytes.fromhex(
                "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
            ))
            metadata = complete_bound_metadata(image, verified=False)

            with self.assertRaisesRegex(ValueError, "not visually verified"):
                _validate_metadata_binding(image, metadata, False)
            _validate_metadata_binding(image, metadata, False, True)

    def test_platform_minimum_keywords_are_blocked_even_with_legacy_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "photo.jpg"
            image.write_bytes(bytes.fromhex(
                "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
            ))
            metadata = complete_bound_metadata(image)
            metadata["keywords_en"] = metadata["keywords_en"][:5]
            metadata["keywords_zh"] = metadata["keywords_zh"][:5]

            with self.assertRaisesRegex(ValueError, "at least 7"):
                _validate_metadata_binding(image, metadata, False)
            with self.assertRaisesRegex(ValueError, "at least 7"):
                _validate_metadata_binding(image, metadata, False, False, True)

    def test_advisory_keyword_count_does_not_block_upload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "photo.jpg"
            image.write_bytes(bytes.fromhex(
                "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
            ))
            metadata = complete_bound_metadata(image)
            metadata["keywords_en"] = metadata["keywords_en"][:7]
            metadata["keywords_zh"] = metadata["keywords_zh"][:5]
            metadata["core_keywords_zh"] = metadata["keywords_zh"][:5]

            normalized = _validate_metadata_binding(image, metadata, False)
            self.assertEqual(len(normalized["keywords_en"]), 7)

    def test_find_pairs_keeps_same_stem_with_different_extensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            for name in ("photo.jpg", "photo.png"):
                image = directory / name
                image.write_bytes(name.encode())
                metadata = {
                    "source": name,
                    "source_sha256": _image_digest(image),
                    "generated_at": "2026-08-08 12:00:00",
                }
                (directory / f"{name}_metadata.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
            self.assertEqual([image.name for image, _ in find_pairs(directory)], ["photo.jpg", "photo.png"])

    def test_upload_status_distinguishes_draft_and_submission(self):
        self.assertTrue(UploadStatus.UPLOADED.recordable)
        self.assertFalse(UploadStatus.UPLOADED.completed)
        self.assertTrue(UploadStatus.DRAFT_SAVED.completed)
        self.assertTrue(UploadStatus.SUBMITTED.completed)
        self.assertFalse(UploadStatus.NEEDS_REVIEW.recordable)
        self.assertFalse(UploadStatus.NEEDS_REVIEW.completed)

    def test_tuchong_cleanup_refuses_card_without_asset_id(self):
        class NoPage:
            def locator(self, selector):
                raise AssertionError("must not locate or delete an unbound card")

        card = DraftCard(kind="photo", asset_id="", count_text="1", upload_time="today")
        self.assertFalse(_delete_card(NoPage(), card))

    def test_browser_falls_back_to_bundled_chromium(self):
        class Context:
            def __init__(self):
                self.scripts = []

            def add_init_script(self, script):
                self.scripts.append(script)

        class Chromium:
            def __init__(self):
                self.calls = []
                self.context = Context()

            def launch_persistent_context(self, user_data, **options):
                self.calls.append(options)
                if options.get("channel") == "chrome":
                    raise browser_module.PlaywrightError("Chrome is unavailable")
                return self.context

        class Playwright:
            chromium = Chromium()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(browser_module, "SESSION_DIR", Path(temp_dir)):
                context = browser_module.get_context("test", Playwright())

        self.assertIs(context, Playwright.chromium.context)
        self.assertEqual(len(Playwright.chromium.calls), 2)
        self.assertEqual(Playwright.chromium.calls[0]["channel"], "chrome")
        self.assertNotIn("channel", Playwright.chromium.calls[1])
        self.assertTrue(context.scripts)

    def test_login_poll_does_not_repeat_navigating_check(self):
        class Page:
            def __init__(self):
                self.urls = []
                self.waits = 0

            def goto(self, url, **kwargs):
                self.urls.append(url)

            def wait_for_timeout(self, timeout):
                self.waits += 1

        page = Page()
        initial_calls = []
        prepared = []
        poll_results = iter([False, True])

        def navigating_check():
            initial_calls.append(True)
            return False

        with patch("builtins.input", side_effect=EOFError):
            browser_module.ensure_logged_in(
                page,
                navigating_check,
                "https://example.com/login",
                poll_logged_in=lambda: next(poll_results),
                prepare_login=lambda: prepared.append(page.urls[-1]),
            )

        self.assertEqual(len(initial_calls), 1)
        self.assertEqual(page.urls, ["https://example.com/login"])
        self.assertEqual(prepared, ["https://example.com/login"])
        self.assertEqual(page.waits, 2)

    def test_login_navigation_timeout_keeps_waiting_for_user(self):
        class Page:
            def __init__(self):
                self.waits = 0

            def goto(self, url, **kwargs):
                raise browser_module.PlaywrightTimeout("slow login page")

            def wait_for_timeout(self, timeout):
                self.waits += 1

        page = Page()
        poll_results = iter([False, True])

        with patch("builtins.input", side_effect=EOFError):
            browser_module.ensure_logged_in(
                page,
                lambda: False,
                "https://example.com/login",
                poll_logged_in=lambda: next(poll_results),
            )

        self.assertEqual(page.waits, 2)

    def test_shutterstock_oauth_callback_is_not_ready(self):
        class Locator:
            def count(self):
                return 1

        class Page:
            url = "https://submit.shutterstock.com/next-oauth/callback?code=test"

            def locator(self, selector):
                return Locator()

        self.assertFalse(shutterstock_session_ready(Page()))
        Page.url = "https://submit.shutterstock.com/portfolio/not_submitted/photo"
        self.assertTrue(shutterstock_session_ready(Page()))

    def test_tuchong_login_poll_reads_spa_state_without_navigation(self):
        class Page:
            def __init__(self):
                self.evaluations = 0

            def evaluate(self, expression):
                self.evaluations += 1
                return True

            def goto(self, *args, **kwargs):
                raise AssertionError("login polling must not navigate")

        page = Page()
        self.assertTrue(tuchong_login_ready(page))
        self.assertEqual(page.evaluations, 1)

    def test_success_confirmation_uses_keyword_only_playwright_arg(self):
        class Page:
            def wait_for_function(self, expression, *, arg=None, timeout=None):
                self.arg = arg
                self.timeout = timeout

        page = Page()
        self.assertTrue(wait_for_success_text(page, ["saved"], timeout=123))
        self.assertEqual(page.arg, ["saved"])
        self.assertEqual(page.timeout, 123)


if __name__ == "__main__":
    unittest.main()
