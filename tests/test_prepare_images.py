import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from metadata_contact_sheet import build_contact_sheets
from metadata_review_finalize import REVIEWED_FIELDS, issue_audit_receipt
from prepare_images import cleanup_previews, prepare_previews


PIL_AVAILABLE = importlib.util.find_spec("PIL") is not None


@unittest.skipUnless(PIL_AVAILABLE, "Pillow is not installed")
class PrepareImagesTests(unittest.TestCase):
    def complete_visual_facts(self):
        return {
            "schema_version": 1,
            "primary_subjects_en": ["mountain"],
            "primary_subjects_zh": ["山峰"],
            "required_terms_en": [],
            "required_terms_zh": [],
            "forbidden_claims_en": ["lake", "trail"],
            "forbidden_claims_zh": ["湖泊", "步道"],
            "water_visible": "no",
            "trail_visible": "no",
            "people_visible": "no",
            "recognizable_people_visible": "no",
            "structures_visible": "no",
            "vehicles_visible": "no",
            "animals_visible": "no",
            "reflection_visible": "no",
            "text_visible": "no",
            "logo_or_trademark_visible": "no",
            "copyrighted_content_visible": "no",
            "private_property_visible": "no",
            "copy_space_visible": "yes",
            "scene_signature": "mountain-meadow-blue-sky",
            "burst_group_id": "",
            "burst_rank": 0,
            "technical_quality": "pass",
            "commercial_potential": "medium",
            "commercial_strengths_en": ["clear travel landscape"],
            "selection_status": "selected",
            "uncertain_details": [],
        }

    def manifest_item(self, source, metadata=None):
        return {
            "image": str(source),
            "visual_facts": self.complete_visual_facts(),
            "metadata": metadata or self.complete_metadata(),
        }

    def finalize_review(self, review_pack):
        pack = json.loads(review_pack.read_text(encoding="utf-8"))
        decisions = review_pack.parent / "review_decisions.json"
        decisions.write_text(
            json.dumps(
                {
                    "review_decision_schema_version": 1,
                    "review_pack": str(review_pack),
                    "review_pack_sha256": hashlib.sha256(
                        review_pack.read_bytes()
                    ).hexdigest(),
                    "independent_review": True,
                    "reviewer": "unit-test-native-verifier",
                    "reviewed_fields": list(REVIEWED_FIELDS),
                    "items": [
                        {
                            "image": item["image"],
                            "verdict": "pass",
                            "visual_facts_verdict": "pass",
                            "metadata_verdict": "pass",
                            "release_ip_verdict": "pass",
                            "issues": [],
                            "reviewed_evidence": [
                                "overview",
                                "visual_facts",
                                "metadata",
                                *(
                                    ["detail_crops"]
                                    if item["detail_previews"]
                                    else []
                                ),
                            ],
                        }
                        for item in pack["items"]
                    ],
                }
            ),
            encoding="utf-8",
        )
        return issue_audit_receipt(review_pack, decisions)

    def complete_metadata(self):
        return {
            "title_en": "Blue mountain landscape under summer sky",
            "title_zh": "夏日蓝天下的山峰景观",
            "description_en": "A blue mountain landscape rises beneath a clear summer sky.",
            "description_zh": "蓝色山峰景观延伸在晴朗夏日天空下。",
            "keywords_en": [
                "mountain", "blue sky", "landscape", "sunlight", "outdoors",
                "nature", "scenic", "wilderness", "alpine", "grassland",
                "daylight", "tranquil", "travel destination", "natural beauty",
                "copy space", "horizontal", "environment", "rural", "panoramic",
                "summer",
            ],
            "keywords_zh": [
                "山峰", "蓝天", "风景", "阳光", "户外",
                "自然", "高山", "宁静", "旅行", "夏季",
            ],
            "category1": "Nature",
            "category2": "Parks/Outdoor",
            "location_zh": "",
            "core_keywords_zh": ["山峰", "蓝天", "风景", "阳光", "户外"],
            "commercial_uses_en": ["travel marketing"],
            "release_status": "clear",
            "release_notes": "",
        }

    def test_prepare_and_cleanup_preview(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "source"
            source_dir.mkdir()
            source = source_dir / "wide photo.png"
            Image.new("RGBA", (2000, 1000), (0, 120, 255, 128)).save(source)

            manifest, errors = prepare_previews(source, max_edge=1024, quality=80)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            preview = Path(payload["items"][0]["preview"])

            self.assertEqual(errors, [])
            self.assertEqual(payload["items"][0]["original_size"], [2000, 1000])
            self.assertEqual(payload["items"][0]["preview_size"], [1024, 512])
            with Image.open(preview) as image:
                self.assertEqual(image.size, (1024, 512))
                self.assertEqual(image.mode, "RGB")
                self.assertFalse(image.getexif())

            preview_dir = manifest.parent
            removed = cleanup_previews(manifest)
            self.assertEqual(removed, preview_dir)
            self.assertFalse(preview_dir.exists())

    def test_prepare_generates_overlapping_detail_crops(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "wide.jpg"
            Image.new("RGB", (2400, 1200), "green").save(source)

            manifest, errors = prepare_previews(source, detail_crops=True)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            details = payload["items"][0]["detail_previews"]

            self.assertEqual(errors, [])
            self.assertEqual(len(details), 4)
            self.assertTrue(all(Path(detail).is_file() for detail in details))
            self.assertTrue(payload["settings"]["detail_crops"])
            cleanup_previews(manifest)

    def test_cleanup_refuses_unmarked_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "refusing to delete"):
                cleanup_previews(Path(temp_dir))

    def test_preview_applies_exif_orientation(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "portrait.jpg"
            exif = Image.Exif()
            exif[274] = 6
            Image.new("RGB", (400, 800), "red").save(source, exif=exif)

            manifest, errors = prepare_previews(source)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            preview = Path(payload["items"][0]["preview"])

            self.assertEqual(errors, [])
            self.assertEqual(payload["items"][0]["original_size"], [800, 400])
            with Image.open(preview) as image:
                self.assertEqual(image.size, (800, 400))
                self.assertFalse(image.getexif())
            cleanup_previews(manifest)

    def test_contact_sheet_review_pack_binds_facts_and_metadata_manifest(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source, detail_crops=True)
            metadata_manifest = Path(temp_dir) / "metadata.json"
            metadata_manifest.write_text(
                json.dumps(
                    [
                        {
                            "image": str(source),
                            "visual_facts": self.complete_visual_facts(),
                            "metadata": {
                                "title_en": "Blue mountain landscape",
                                "description_en": "A blue mountain landscape under clear sky.",
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )

            review_pack_path = build_contact_sheets(
                preview_manifest, metadata_manifest
            )
            review_pack = json.loads(
                review_pack_path.read_text(encoding="utf-8")
            )

            self.assertEqual(review_pack["source_count"], 1)
            self.assertEqual(review_pack["review_pack_schema_version"], 3)
            self.assertIn("keywords_zh", review_pack["audited_fields"])
            self.assertIn("water_visible", review_pack["visual_fact_fields"])
            self.assertEqual(len(review_pack["sheets"]), 1)
            self.assertTrue(Path(review_pack["sheets"][0]).is_file())
            self.assertIn(
                review_pack["sheets"][0], review_pack["sheet_sha256"]
            )
            cleanup_previews(preview_manifest)

    def test_writer_accepts_matching_agent_audit_receipt(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source, detail_crops=True)
            metadata_manifest = directory / "metadata.json"
            metadata_manifest.write_text(
                json.dumps(
                    [self.manifest_item(source)]
                ),
                encoding="utf-8",
            )
            review_pack = build_contact_sheets(preview_manifest, metadata_manifest)
            receipt = self.finalize_review(review_pack)

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "metadata_writer.py"),
                    "--manifest",
                    str(metadata_manifest),
                    "--strict-quality",
                    "--visual-reviewed",
                    "--review-method",
                    "agent-native",
                    "--audit-receipt",
                    str(receipt),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = next(directory.glob("landscape.jpg_*.json"))
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["visual_review_status"], "verified")
            self.assertIn("visual_facts_sha256", payload)
            cleanup_previews(preview_manifest)

    def test_finalize_rejects_failed_per_image_decision(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source, detail_crops=True)
            metadata_manifest = directory / "metadata.json"
            metadata_manifest.write_text(
                json.dumps([self.manifest_item(source)]), encoding="utf-8"
            )
            review_pack = build_contact_sheets(preview_manifest, metadata_manifest)
            pack = json.loads(review_pack.read_text(encoding="utf-8"))
            decisions = directory / "failed-decisions.json"
            decisions.write_text(
                json.dumps(
                    {
                        "review_decision_schema_version": 1,
                        "review_pack": str(review_pack),
                        "review_pack_sha256": hashlib.sha256(
                            review_pack.read_bytes()
                        ).hexdigest(),
                        "independent_review": True,
                        "reviewer": "unit-test-verifier",
                        "reviewed_fields": list(REVIEWED_FIELDS),
                        "items": [
                            {
                                "image": pack["items"][0]["image"],
                                "verdict": "fail",
                                "visual_facts_verdict": "pass",
                                "metadata_verdict": "fail",
                                "release_ip_verdict": "pass",
                                "issues": ["invented lake"],
                                "reviewed_evidence": [
                                    "overview", "visual_facts", "metadata"
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "did not pass"):
                issue_audit_receipt(review_pack, decisions)
            cleanup_previews(preview_manifest)

    def test_writer_rejects_receipt_after_manifest_changes(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source, detail_crops=True)
            metadata_manifest = directory / "metadata.json"
            metadata_manifest.write_text(
                json.dumps(
                    [self.manifest_item(source)]
                ),
                encoding="utf-8",
            )
            review_pack = build_contact_sheets(preview_manifest, metadata_manifest)
            receipt = self.finalize_review(review_pack)
            metadata_manifest.write_text("[]", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "metadata_writer.py"),
                    "--manifest",
                    str(metadata_manifest),
                    "--visual-reviewed",
                    "--audit-receipt",
                    str(receipt),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match", result.stderr)
            cleanup_previews(preview_manifest)

    def test_writer_rejects_changed_contact_sheet(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source, detail_crops=True)
            metadata_manifest = directory / "metadata.json"
            metadata_manifest.write_text(
                json.dumps(
                    [self.manifest_item(source)]
                ),
                encoding="utf-8",
            )
            review_pack = build_contact_sheets(preview_manifest, metadata_manifest)
            receipt = self.finalize_review(review_pack)
            review_pack_data = json.loads(
                review_pack.read_text(encoding="utf-8")
            )
            Path(review_pack_data["sheets"][0]).write_bytes(b"changed")

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "metadata_writer.py"),
                    "--manifest",
                    str(metadata_manifest),
                    "--visual-reviewed",
                    "--audit-receipt",
                    str(receipt),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("review sheet has changed", result.stderr)
            cleanup_previews(preview_manifest)

    def test_writer_rejects_changed_review_decisions(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source, detail_crops=True)
            metadata_manifest = directory / "metadata.json"
            metadata_manifest.write_text(
                json.dumps([self.manifest_item(source)]), encoding="utf-8"
            )
            review_pack = build_contact_sheets(preview_manifest, metadata_manifest)
            receipt = self.finalize_review(review_pack)
            decisions = review_pack.parent / "review_decisions.json"
            decisions.write_text("{}", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "metadata_writer.py"),
                    "--manifest",
                    str(metadata_manifest),
                    "--visual-reviewed",
                    "--audit-receipt",
                    str(receipt),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("review decisions have changed", result.stderr)
            cleanup_previews(preview_manifest)


if __name__ == "__main__":
    unittest.main()
