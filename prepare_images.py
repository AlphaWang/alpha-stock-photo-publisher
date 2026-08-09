#!/usr/bin/env python3
"""Create privacy-reduced image previews for agent-native visual analysis."""

import argparse
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from metadata_core import SUPPORTED_EXTS

PREVIEW_PREFIX = "stock-photo-previews-"
MARKER_NAME = ".stock-photo-preview-cache"
MANIFEST_NAME = "preview_manifest.json"
MARKER_CONTENT = "alpha-stock-photo-publisher preview cache\n"


def collect_images(target: Path):
    if target.is_file():
        if target.suffix.lower() not in SUPPORTED_EXTS:
            raise ValueError(f"unsupported image format: {target.suffix}")
        return [target]
    if target.is_dir():
        images = sorted(
            path
            for path in target.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
        )
        if not images:
            raise ValueError(f"no supported images found in: {target}")
        return images
    raise ValueError(f"path does not exist: {target}")


def _load_pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise RuntimeError(
            "Pillow is required for local previews. Install it with: pip install pillow"
        )
    return Image, ImageOps


def _to_rgb(image, Image):
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._")
    return stem or "image"


def _make_output_dir(output: Path = None) -> Path:
    if output is None:
        directory = Path(tempfile.mkdtemp(prefix=PREVIEW_PREFIX)).resolve()
    else:
        directory = output.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=False)
    (directory / MARKER_NAME).write_text(MARKER_CONTENT, encoding="utf-8")
    return directory


def prepare_previews(target: Path, output: Path = None, max_edge: int = 1024, quality: int = 80):
    Image, ImageOps = _load_pillow()
    images = collect_images(target)
    directory = _make_output_dir(output)
    items = []
    errors = []
    resampling = getattr(Image, "Resampling", Image).LANCZOS

    for index, source in enumerate(images, 1):
        preview = directory / f"{index:04d}_{_safe_stem(source)}.jpg"
        try:
            with Image.open(source) as opened:
                opened.seek(0)
                image = ImageOps.exif_transpose(opened)
                original_size = image.size
                image = _to_rgb(image, Image)
                image.thumbnail((max_edge, max_edge), resampling)
                preview_size = image.size
                image.save(preview, "JPEG", quality=quality, optimize=True)
            items.append(
                {
                    "source": str(source),
                    "preview": str(preview),
                    "original_size": list(original_size),
                    "preview_size": list(preview_size),
                }
            )
            print(f"[{index}/{len(images)}] prepared {preview}", flush=True)
        except Exception as error:
            errors.append({"source": str(source), "error": str(error)})
            print(
                f"[{index}/{len(images)}] failed {source}: {error}",
                file=sys.stderr,
                flush=True,
            )

    manifest = directory / MANIFEST_NAME
    manifest.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "settings": {"max_edge": max_edge, "jpeg_quality": quality},
                "items": items,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Preview manifest: {manifest}", flush=True)
    return manifest, errors


def cleanup_previews(value: Path) -> Path:
    path = value.expanduser().resolve()
    directory = path.parent if path.is_file() else path
    marker = directory / MARKER_NAME
    if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER_CONTENT:
        raise ValueError(f"refusing to delete unrecognized preview directory: {directory}")
    shutil.rmtree(directory)
    return directory


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create temporary, metadata-free JPEG previews for visual analysis"
    )
    parser.add_argument("target", nargs="?", help="Image file or directory")
    parser.add_argument("--output", type=Path, help="Output directory (default: system temp)")
    parser.add_argument(
        "--max-edge", type=int, default=1024, help="Maximum preview edge (default: 1024)"
    )
    parser.add_argument(
        "--quality", type=int, default=80, help="JPEG quality from 40 to 95 (default: 80)"
    )
    parser.add_argument(
        "--cleanup", type=Path, help="Delete a preview manifest or marked preview directory"
    )
    args = parser.parse_args()

    if args.cleanup:
        if args.target or args.output:
            parser.error("target and --output cannot be used with --cleanup")
        try:
            removed = cleanup_previews(args.cleanup)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(f"Removed preview directory: {removed}")
        return 0

    if not args.target:
        parser.error("target is required unless --cleanup is used")
    if not 256 <= args.max_edge <= 2048:
        parser.error("--max-edge must be between 256 and 2048")
    if not 40 <= args.quality <= 95:
        parser.error("--quality must be between 40 and 95")

    try:
        _, errors = prepare_previews(
            Path(args.target).expanduser().resolve(),
            output=args.output,
            max_edge=args.max_edge,
            quality=args.quality,
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
