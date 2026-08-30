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
from regenerate_verified_location_metadata import _pairs_for_scope


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
    def test_location_regeneration_file_scope_excludes_sibling_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            requested = directory / "requested.jpg"
            sibling = directory / "sibling.jpg"
            requested.write_bytes(b"requested")
            sibling.write_bytes(b"sibling")
            for image in (requested, sibling):
                (directory / f"{image.name}.json").write_text(
                    json.dumps({"source": image.name}), encoding="utf-8"
                )

            pairs, missing = _pairs_for_scope(directory, requested)

            self.assertEqual([image.name for image, _ in pairs], ["requested.jpg"])
            self.assertEqual(missing, [])

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

    def test_quality_advisory_detects_verified_location_missing_from_description(self):
        metadata = sample_metadata()
        metadata.update(
            {
                "location_en": "Grand Canyon of the Yellowstone, Yellowstone National Park",
                "location_zh": "黄石国家公园黄石大峡谷",
                "location_source": "context",
                "location_confidence": "high",
            }
        )
        normalized = enforce_limits(metadata)

        warnings = assess_metadata_quality(normalized)
        self.assertTrue(any("Grand Canyon of the Yellowstone" in value for value in warnings))

        normalized["description_en"] += (
            " Photographed at Grand Canyon of the Yellowstone, Yellowstone National Park."
        )
        warnings = assess_metadata_quality(normalized)
        self.assertFalse(any("most specific verified location" in value for value in warnings))

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

    def test_editorial_only_metadata_requires_shutterstock_caption_components(self):
        metadata = sample_metadata()
        metadata.update(
            {
                "commercial_eligibility": "editorial_only",
                "model_release_status": "not_required",
                "property_release_status": "not_required",
                "logo_trademark_status": "visible",
                "copyrighted_content_status": "none",
                "release_notes": "Visible sign requires editorial use.",
            }
        )

        errors = validate_metadata_quality(enforce_limits(metadata))

        self.assertIn("editorial-only metadata requires editorial_caption_en", errors)
        self.assertIn("editorial-only metadata requires editorial_date", errors)
        self.assertIn(
            "editorial-only metadata requires a known editorial_date_source",
            errors,
        )
        self.assertIn("editorial-only metadata requires editorial_location_en", errors)

    def test_valid_editorial_caption_uses_evidenced_date_and_location(self):
        metadata = sample_metadata()
        metadata.update(
            {
                "commercial_eligibility": "editorial_only",
                "model_release_status": "not_required",
                "property_release_status": "not_required",
                "logo_trademark_status": "visible",
                "copyrighted_content_status": "none",
                "release_notes": "Visible sign requires editorial use.",
                "editorial_date": "2026-06-26",
                "editorial_date_source": "exif",
                "editorial_location_en": "Bonneville Salt Flats, Utah, USA",
                "location_source": "context",
                "location_confidence": "high",
                "editorial_caption_en": (
                    "Bonneville Salt Flats, Utah, USA - 26 June 2026: "
                    "A weathered entrance sign covered with stickers stands by the salt plain."
                ),
            }
        )

        self.assertEqual(validate_metadata_quality(enforce_limits(metadata)), [])

    def test_editorial_caption_must_match_structured_date_and_location(self):
        metadata = sample_metadata()
        metadata.update(
            {
                "commercial_eligibility": "editorial_only",
                "model_release_status": "not_required",
                "property_release_status": "not_required",
                "logo_trademark_status": "visible",
                "copyrighted_content_status": "none",
                "release_notes": "Visible sign requires editorial use.",
                "editorial_date": "2026-06-26",
                "editorial_date_source": "context",
                "editorial_location_en": "Bonneville Salt Flats, Utah, USA",
                "location_source": "context",
                "location_confidence": "high",
                "editorial_caption_en": (
                    "Salt Lake City, Utah, USA - 25 June 2026: A sign beside a road."
                ),
            }
        )

        errors = validate_metadata_quality(enforce_limits(metadata))
        self.assertTrue(any("must start" in error for error in errors), errors)
        self.assertTrue(any("must contain the editorial date" in error for error in errors), errors)

    def test_editorial_metadata_requires_date_and_location_provenance(self):
        metadata = sample_metadata()
        metadata.update(
            {
                "commercial_eligibility": "editorial_only",
                "model_release_status": "not_required",
                "property_release_status": "not_required",
                "logo_trademark_status": "visible",
                "copyrighted_content_status": "none",
                "release_notes": "Visible sign requires editorial use.",
                "editorial_date": "2026-06-26",
                "editorial_date_source": "unknown",
                "editorial_location_en": "Invented Place, USA",
                "location_source": "unknown",
                "location_confidence": "unknown",
                "editorial_caption_en": (
                    "Invented Place, USA - 26 June 2026: A sign beside a road."
                ),
            }
        )

        errors = validate_metadata_quality(enforce_limits(metadata))
        self.assertTrue(any("editorial_date_source" in error for error in errors))
        self.assertTrue(any("known location_source" in error for error in errors))
        self.assertTrue(any("location_confidence" in error for error in errors))

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
