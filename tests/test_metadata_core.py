import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from metadata_core import (
    assess_metadata_quality,
    commercial_submission_review_reason,
    default_platform_categories,
    enforce_limits,
    find_batch_quality_issues,
    validate_metadata,
    validate_metadata_quality,
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
            "arid landscape",
            "travel",
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

        self.assertGreater(len(normalized["title_en"]), 70)
        self.assertIn(
            "title_en exceeds 70 characters", validate_metadata(normalized)
        )
        self.assertEqual(normalized["keywords_en"][0], "sunset")
        self.assertEqual(normalized["keywords_en"].count("sunset"), 1)
        self.assertEqual(normalized["keywords_en"][1], "road trip")
        self.assertNotIn("unexpected", normalized)

    def test_validate_metadata_reports_incomplete_output(self):
        errors = validate_metadata(enforce_limits({}))

        self.assertIn("title_en is required", errors)
        self.assertIn("keywords_en must contain at least 7 unique keywords", errors)

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

    def test_quality_validation_rejects_generic_description_filler(self):
        metadata = enforce_limits(sample_metadata())
        metadata["description_en"] += " Presented as a wide view."

        errors = validate_metadata_quality(metadata)

        self.assertIn("description_en contains generic 'Presented as' filler", errors)

    def test_quality_validation_rejects_clear_release_boilerplate(self):
        metadata = enforce_limits(sample_metadata())
        metadata["release_notes"] = "No recognizable people or logos are visible."

        errors = validate_metadata_quality(metadata)

        self.assertIn(
            "release_notes must be empty when release_status is clear", errors
        )

    def test_quality_validation_requires_notes_for_unknown_release(self):
        metadata = enforce_limits(sample_metadata())
        metadata["release_status"] = "unknown"

        self.assertIn(
            "release_notes must explain required or unknown release status",
            validate_metadata_quality(metadata),
        )

    def test_quality_validation_requires_primary_subject_in_first_keywords(self):
        metadata = sample_metadata()
        metadata["keywords_en"][:3] = ["wallpaper", "advertising", "background"]

        errors = validate_metadata_quality(enforce_limits(metadata))

        self.assertTrue(any("first three English keywords" in error for error in errors))

    def test_quality_validation_rejects_repeated_keyword_stems(self):
        metadata = sample_metadata()
        metadata["keywords_en"] = [
            "mountain", "mountain road", "mountain travel", "mountain scenery",
            "mountain landscape", "sunset", "highway",
        ]
        metadata["title_en"] = "Mountain road at sunset"

        errors = validate_metadata_quality(enforce_limits(metadata))

        self.assertTrue(any("repeats word stems" in error for error in errors))

    def test_chinese_fields_must_contain_chinese_text(self):
        metadata = sample_metadata()
        metadata["title_zh"] = "Desert road"

        self.assertIn(
            "title_zh must contain Chinese text",
            validate_metadata_quality(enforce_limits(metadata)),
        )

    def test_location_requires_source_and_confidence(self):
        metadata = sample_metadata()
        metadata["location_en"] = "Grand Teton National Park"
        metadata["location_zh"] = "大提顿国家公园"

        errors = validate_metadata_quality(enforce_limits(metadata))

        self.assertIn("a supplied location requires a known location_source", errors)
        self.assertIn("a supplied location requires location_confidence", errors)

    def test_platform_defaults_do_not_misclassify_transport_as_nature(self):
        categories = default_platform_categories("Transportation", "")

        self.assertEqual(categories["adobestock"], "Transport")
        self.assertEqual(categories["tuchong"], [])

    def test_structured_logo_risk_blocks_automatic_commercial_submission(self):
        metadata = sample_metadata()
        metadata.update(
            {
                "model_release_status": "not_required",
                "property_release_status": "not_required",
                "logo_trademark_status": "visible",
                "copyrighted_content_status": "none",
                "commercial_eligibility": "editorial_only",
                "release_notes": "Visible trademark requires editorial review.",
            }
        )
        normalized = enforce_limits(metadata)

        self.assertEqual(normalized["release_status"], "required")
        self.assertIn("logo/trademark", commercial_submission_review_reason(normalized))

    def test_batch_quality_detects_repeated_metadata(self):
        first = enforce_limits(sample_metadata())
        second = enforce_limits(sample_metadata())

        issues = find_batch_quality_issues(
            [("one.jpg", first), ("two.jpg", second)]
        )

        self.assertIn("duplicate title_en shared by 2 images", issues["one.jpg"])
        self.assertIn("duplicate description_en shared by 2 images", issues["two.jpg"])

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
            self.assertEqual(payload["visual_review_status"], "unreviewed")
            self.assertEqual(payload["visual_reviewed_at"], "")
            self.assertEqual(payload["category1"], "Transportation")
            self.assertTrue(payload["generated_at"])

    def test_write_metadata_records_verified_review_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image = directory / "road.jpg"
            image.touch()

            output = write_metadata(
                sample_metadata(),
                image,
                directory,
                visual_review_status="verified",
                visual_review_method="manual",
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(payload["visual_review_status"], "verified")
            self.assertEqual(payload["visual_review_method"], "manual")
            self.assertTrue(payload["visual_reviewed_at"])

    def test_manifest_writer_processes_multiple_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            images = [directory / "one.jpg", directory / "two.png"]
            for image in images:
                image.touch()
            manifest = directory / "manifest.json"
            first = sample_metadata()
            second = sample_metadata()
            second["title_en"] = "Mountain road beneath a clear sky"
            second["description_en"] = (
                "A mountain road curves beneath a clear blue summer sky."
            )
            manifest.write_text(
                json.dumps(
                    [
                        {"image": str(images[0]), "metadata": first},
                        {"image": str(images[1]), "metadata": second},
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
