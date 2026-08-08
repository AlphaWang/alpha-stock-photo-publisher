import sys
import tempfile
import types
import unittest
from pathlib import Path

# Pure upload rules should remain testable without launching or installing a browser.
if "playwright.sync_api" not in sys.modules:
    playwright = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.BrowserContext = object
    sync_api.Page = object
    sync_api.TimeoutError = TimeoutError
    playwright.sync_api = sync_api
    sys.modules["playwright"] = playwright
    sys.modules["playwright.sync_api"] = sync_api

from upload.adobestock import _auto_review_reason as adobe_review_reason
from upload.adobestock import _resolve_category as resolve_adobe_category
from upload.adobestock import upload_batch as upload_adobe_batch
from upload.istock import _auto_review_reason as istock_review_reason
from upload.px500 import _auto_review_reason as px500_review_reason
from upload.px500 import _resolve_path
from upload_photos import _image_digest, _load_history, _platform_enabled, _save_history
from upload_photos import _result_counts


class UploadLogicTests(unittest.TestCase):
    def test_all_enables_stable_platforms_only(self):
        self.assertTrue(_platform_enabled("all", "adobestock"))
        self.assertTrue(_platform_enabled("all", "tuchong"))
        self.assertFalse(_platform_enabled("all", "istock"))
        self.assertTrue(_platform_enabled("istock", "istock"))

    def test_result_counts_are_per_platform(self):
        self.assertEqual(_result_counts({"a.jpg": True, "b.jpg": False}), (1, 1))

    def test_known_500px_location_is_mapped(self):
        self.assertEqual(_resolve_path("美国旧金山湾区"), ["美国", "加利福尼亚", "旧金山"])

    def test_unknown_500px_location_requires_review(self):
        self.assertIsNone(_resolve_path("未知地点"))
        self.assertIsNone(_resolve_path(""))

    def test_adobe_category_mapping(self):
        self.assertEqual(resolve_adobe_category("Business/Finance"), "Business")

    def test_release_notes_block_automatic_submission(self):
        metadata = {
            "title_en": "City street",
            "description_en": "A city street in daylight.",
            "keywords_en": ["city", "street", "travel", "urban", "daylight"],
            "release_notes": "Visible logo may require cleanup",
        }
        self.assertIn("release review required", adobe_review_reason(metadata))
        self.assertIn("release review required", istock_review_reason(metadata))

        class NoBrowserContext:
            def new_page(self):
                raise AssertionError("review items must be filtered before browser upload")

        result = upload_adobe_batch([(Path("city.jpg"), metadata)], NoBrowserContext())
        self.assertEqual(result, {"city.jpg": False})

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


if __name__ == "__main__":
    unittest.main()
