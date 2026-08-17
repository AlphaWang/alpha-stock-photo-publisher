import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photo_desc import main, process_one, verify_metadata
from test_visual_facts import complete_visual_facts


def complete_metadata():
    return {
        "title_en": "Sunlit mountain above green meadow",
        "title_zh": "绿色草地上方的阳光山峰",
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
    }


def mountain_visual_facts():
    return {
        **complete_visual_facts(),
        "primary_subjects_en": ["mountain"],
        "primary_subjects_zh": ["山峰"],
        "scene_signature": "mountain-meadow",
    }


class PhotoDescriptionTests(unittest.TestCase):
    def test_visual_verifier_uses_crops_without_shooting_context(self):
        captured = {}

        class Messages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return type(
                    "Response",
                    (),
                    {
                        "content": [
                            type(
                                "Block",
                                (),
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            "verdict": "pass",
                                            "issues": [],
                                            "visual_facts": mountain_visual_facts(),
                                        }
                                    ),
                                },
                            )()
                        ]
                    },
                )()

        client = type("Client", (), {"messages": Messages()})()
        with patch("photo_desc.load_image", return_value=("full", "image/jpeg")):
            with patch(
                "photo_desc.load_image_crops",
                return_value=[("crop-1", "image/jpeg"), ("crop-2", "image/jpeg")],
            ):
                passed, issues, visual_facts = verify_metadata(
                    Path("photo.jpg"),
                    complete_metadata(),
                    client,
                    context="SECRET SHOOTING CONTEXT",
                )

        self.assertTrue(passed)
        self.assertEqual(issues, [])
        self.assertEqual(visual_facts["primary_subjects_en"], ["mountain"])
        content = captured["messages"][0]["content"]
        self.assertEqual(sum(item["type"] == "image" for item in content), 3)
        self.assertNotIn("SECRET SHOOTING CONTEXT", str(content))

    def test_process_one_writes_only_after_visual_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image = directory / "mountain.jpg"
            image.write_bytes(b"image-content")

            with patch("photo_desc.analyze_image", return_value=complete_metadata()):
                with patch(
                    "photo_desc.verify_metadata",
                    return_value=(True, [], mountain_visual_facts()),
                ):
                    _, ok, output = process_one(image, directory, object())

            self.assertTrue(ok)
            payload = json.loads(Path(output).read_text(encoding="utf-8"))
            self.assertEqual(payload["visual_review_status"], "verified")
            self.assertEqual(
                payload["visual_review_method"], "anthropic-second-pass"
            )
            self.assertIn("visual_facts_sha256", payload)

    def test_process_one_does_not_write_after_two_failed_reviews(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image = directory / "mountain.jpg"
            image.write_bytes(b"image-content")

            with patch("photo_desc.analyze_image", return_value=complete_metadata()):
                with patch(
                    "photo_desc.verify_metadata",
                    return_value=(False, ["lake is not visible"], None),
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
                return image, True, {
                    "metadata": complete_metadata(),
                    "visual_facts": complete_visual_facts(),
                }

            with patch("photo_desc.make_client", return_value=object()):
                with patch("photo_desc.generate_one", side_effect=generated):
                    with patch.object(sys, "argv", ["photo_desc.py", str(directory)]):
                        result = main()

            self.assertEqual(result, 1)
            self.assertEqual(list(directory.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
