import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photo_desc import main, process_one


def complete_metadata():
    return {
        "title_en": "Sunlit mountain above green meadow",
        "title_zh": "绿色草地上方的阳光山峰",
        "description_en": "A sunlit mountain rises above a green summer meadow.",
        "description_zh": "阳光照亮山峰和绿色夏季草地。",
        "keywords_en": [f"keyword-{index}" for index in range(20)],
        "keywords_zh": [f"关键词{index}" for index in range(10)],
        "category1": "Nature",
        "category2": "Parks/Outdoor",
        "location_zh": "",
        "core_keywords_zh": [f"关键词{index}" for index in range(5)],
        "commercial_uses_en": ["travel marketing"],
        "release_status": "clear",
        "release_notes": "",
    }


class PhotoDescriptionTests(unittest.TestCase):
    def test_process_one_writes_only_after_visual_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image = directory / "mountain.jpg"
            image.write_bytes(b"image-content")

            with patch("photo_desc.analyze_image", return_value=complete_metadata()):
                with patch("photo_desc.verify_metadata", return_value=(True, [])):
                    _, ok, output = process_one(image, directory, object())

            self.assertTrue(ok)
            payload = json.loads(Path(output).read_text(encoding="utf-8"))
            self.assertEqual(payload["visual_review_status"], "verified")
            self.assertEqual(
                payload["visual_review_method"], "anthropic-second-pass"
            )

    def test_process_one_does_not_write_after_two_failed_reviews(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image = directory / "mountain.jpg"
            image.write_bytes(b"image-content")

            with patch("photo_desc.analyze_image", return_value=complete_metadata()):
                with patch(
                    "photo_desc.verify_metadata",
                    return_value=(False, ["lake is not visible"]),
                ):
                    _, ok, error = process_one(image, directory, object())

            self.assertFalse(ok)
            self.assertIn("visual metadata verification failed", error)
            self.assertEqual(list(directory.glob("mountain.jpg_*.json")), [])

    def test_batch_does_not_write_repeated_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            images = [directory / "one.jpg", directory / "two.jpg"]
            for image in images:
                image.touch()

            def generated(image, _client, _context):
                return image, True, complete_metadata()

            with patch("photo_desc.make_client", return_value=object()):
                with patch("photo_desc.generate_one", side_effect=generated):
                    with patch.object(sys, "argv", ["photo_desc.py", str(directory)]):
                        result = main()

            self.assertEqual(result, 1)
            self.assertEqual(list(directory.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
