import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

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
from upload.px500 import _resolve_path
import upload.px500 as px500_module
from upload.status import UploadStatus
import upload.browser as browser_module
from upload.confirmation import wait_for_success_text
from upload.shutterstock import _has_logged_in_session as shutterstock_session_ready
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


class UploadLogicTests(unittest.TestCase):
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
        self.assertIn("unknown shooting location", px500_review_reason(metadata))

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
            metadata = {"source": image.name, "source_sha256": _image_digest(image)}
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
            metadata = {"source": image.name}

            with self.assertRaisesRegex(ValueError, "no source_sha256"):
                _validate_metadata_binding(image, metadata, False)
            _validate_metadata_binding(image, metadata, True)

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
