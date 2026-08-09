import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from prepare_images import cleanup_previews, prepare_previews


PIL_AVAILABLE = importlib.util.find_spec("PIL") is not None


@unittest.skipUnless(PIL_AVAILABLE, "Pillow is not installed")
class PrepareImagesTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
