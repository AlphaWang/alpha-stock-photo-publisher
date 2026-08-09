import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from metadata_core import (
    assess_metadata_quality,
    enforce_limits,
    validate_metadata,
    write_metadata,
)


def sample_metadata():
    return {
        "title_en": "Sunset road through the desert",
        "title_zh": "沙漠公路日落",
        "description_en": "A quiet desert highway leads toward distant mountains at sunset.",
        "description_zh": "夕阳下的沙漠公路通向远山，展现宁静旅途氛围。",
        "keywords_en": [
            "desert road",
            "sunset",
            "road trip",
            "highway",
            "mountains",
        ],
        "keywords_zh": ["沙漠公路", "日落", "自驾旅行", "高速公路", "远山"],
        "category1": "Transportation",
        "category2": "Parks/Outdoor",
        "location_zh": "",
        "core_keywords_zh": ["沙漠公路", "日落"],
        "commercial_uses_en": ["travel marketing", "road trip editorial"],
        "release_status": "clear",
        "release_notes": "",
    }


class MetadataCoreTests(unittest.TestCase):
    def test_enforce_limits_deduplicates_and_normalizes(self):
        metadata = sample_metadata()
        metadata["title_en"] = "A " + ("very " * 30) + "long title"
        metadata["keywords_en"] = [
            "Sunset",
            "sunset",
            " ROAD TRIP ",
            "Highway",
            "Mountains",
            "Desert",
        ]
        metadata["unexpected"] = "discard me"

        normalized = enforce_limits(metadata)

        self.assertLessEqual(len(normalized["title_en"]), 70)
        self.assertEqual(normalized["keywords_en"][0], "sunset")
        self.assertEqual(normalized["keywords_en"].count("sunset"), 1)
        self.assertEqual(normalized["keywords_en"][1], "road trip")
        self.assertNotIn("unexpected", normalized)

    def test_validate_metadata_reports_incomplete_output(self):
        errors = validate_metadata(enforce_limits({}))

        self.assertIn("title_en is required", errors)
        self.assertIn("keywords_en must contain at least 5 unique keywords", errors)

    def test_invalid_categories_are_not_silently_replaced(self):
        metadata = sample_metadata()
        metadata["category1"] = "Travel"
        metadata["category2"] = "Outdoors"

        normalized = enforce_limits(metadata)
        errors = validate_metadata(normalized)

        self.assertEqual(normalized["category1"], "Travel")
        self.assertIn("category1 is invalid", errors)
        self.assertIn("category2 is invalid", errors)

    def test_missing_release_status_defaults_to_unknown(self):
        metadata = sample_metadata()
        del metadata["release_status"]

        self.assertEqual(enforce_limits(metadata)["release_status"], "unknown")

    def test_quality_warnings_flag_thin_keyword_sets(self):
        warnings = assess_metadata_quality(enforce_limits(sample_metadata()))

        self.assertTrue(any("English keywords" in warning for warning in warnings))
        self.assertTrue(any("Chinese keywords" in warning for warning in warnings))

    def test_write_metadata_adds_source_and_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image = directory / "road.jpg"
            image.touch()

            output = write_metadata(sample_metadata(), image, directory)
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(payload["source"], "road.jpg")
            self.assertTrue(payload["source_sha256"])
            self.assertTrue(payload["quality_warnings"])
            self.assertEqual(payload["category1"], "Transportation")
            self.assertTrue(payload["generated_at"])

    def test_manifest_writer_processes_multiple_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            images = [directory / "one.jpg", directory / "two.png"]
            for image in images:
                image.touch()
            manifest = directory / "manifest.json"
            manifest.write_text(
                json.dumps(
                    [
                        {"image": str(image), "metadata": sample_metadata()}
                        for image in images
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "metadata_writer.py"),
                    "--manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(directory.glob("one.jpg_*.json"))), 1)
            self.assertEqual(len(list(directory.glob("two.png_*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
