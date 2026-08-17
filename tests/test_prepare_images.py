import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from metadata_contact_sheet import build_contact_sheets
from prepare_images import cleanup_previews, prepare_previews


PIL_AVAILABLE = importlib.util.find_spec("PIL") is not None


@unittest.skipUnless(PIL_AVAILABLE, "Pillow is not installed")
class PrepareImagesTests(unittest.TestCase):
    def complete_metadata(self):
        return {
            "title_en": "Blue mountain landscape under summer sky",
            "title_zh": "夏日蓝天下的山地景观",
            "description_en": "A blue mountain landscape rises beneath a clear summer sky.",
            "description_zh": "蓝色山地景观延伸在晴朗夏日天空下。",
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

    def test_contact_sheet_receipt_binds_metadata_manifest(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source)
            metadata_manifest = Path(temp_dir) / "metadata.json"
            metadata_manifest.write_text(
                json.dumps(
                    [
                        {
                            "image": str(source),
                            "metadata": {
                                "title_en": "Blue mountain landscape",
                                "description_en": "A blue mountain landscape under clear sky.",
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )

            receipt_path = build_contact_sheets(
                preview_manifest, metadata_manifest
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

            self.assertEqual(receipt["source_count"], 1)
            self.assertEqual(receipt["audit_schema_version"], 2)
            self.assertIn("keywords_zh", receipt["audited_fields"])
            self.assertEqual(len(receipt["sheets"]), 1)
            self.assertTrue(Path(receipt["sheets"][0]).is_file())
            self.assertIn(receipt["sheets"][0], receipt["sheet_sha256"])
            cleanup_previews(preview_manifest)

    def test_writer_accepts_matching_agent_audit_receipt(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source)
            metadata_manifest = directory / "metadata.json"
            metadata_manifest.write_text(
                json.dumps(
                    [{"image": str(source), "metadata": self.complete_metadata()}]
                ),
                encoding="utf-8",
            )
            receipt = build_contact_sheets(preview_manifest, metadata_manifest)

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
            cleanup_previews(preview_manifest)

    def test_writer_rejects_receipt_after_manifest_changes(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "landscape.jpg"
            Image.new("RGB", (800, 500), "blue").save(source)
            preview_manifest, _ = prepare_previews(source)
            metadata_manifest = directory / "metadata.json"
            metadata_manifest.write_text(
                json.dumps(
                    [{"image": str(source), "metadata": self.complete_metadata()}]
                ),
                encoding="utf-8",
            )
            receipt = build_contact_sheets(preview_manifest, metadata_manifest)
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
            preview_manifest, _ = prepare_previews(source)
            metadata_manifest = directory / "metadata.json"
            metadata_manifest.write_text(
                json.dumps(
                    [{"image": str(source), "metadata": self.complete_metadata()}]
                ),
                encoding="utf-8",
            )
            receipt = build_contact_sheets(preview_manifest, metadata_manifest)
            receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
            Path(receipt_data["sheets"][0]).write_bytes(b"changed")

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
            self.assertIn("contact sheets have changed", result.stderr)
            cleanup_previews(preview_manifest)


if __name__ == "__main__":
    unittest.main()
