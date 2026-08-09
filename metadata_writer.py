#!/usr/bin/env python3
"""Validate agent-generated stock metadata and write timestamped JSON files."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from metadata_core import SUPPORTED_EXTS, write_metadata


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_image(value: str, manifest_dir: Path) -> Path:
    image = Path(value).expanduser()
    if not image.is_absolute():
        image = manifest_dir / image
    image = image.resolve()
    if not image.is_file():
        raise ValueError(f"image does not exist: {image}")
    if image.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"unsupported image format: {image.suffix}")
    return image


def _write_one(image: Path, metadata: object, output_dir: Optional[Path]) -> Path:
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a JSON object")
    destination = output_dir or image.parent
    destination.mkdir(parents=True, exist_ok=True)
    return write_metadata(metadata, image, destination)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and persist stock metadata produced by an AI agent"
    )
    parser.add_argument("image", nargs="?", help="Image for single-item mode")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--metadata-file", type=Path, help="Metadata object JSON file")
    source.add_argument(
        "--manifest",
        type=Path,
        help='JSON array of {"image": "...", "metadata": {...}} objects',
    )
    parser.add_argument("--output", type=Path, help="Optional output directory")
    args = parser.parse_args()

    output_dir = args.output.expanduser().resolve() if args.output else None
    failures = []

    try:
        if args.metadata_file:
            if not args.image:
                parser.error("image is required with --metadata-file")
            metadata_file = args.metadata_file.expanduser().resolve()
            items = [{"image": args.image, "metadata": _load_json(metadata_file)}]
            manifest_dir = Path.cwd()
        else:
            if args.image:
                parser.error("image must be omitted with --manifest")
            manifest_path = args.manifest.expanduser().resolve()
            items = _load_json(manifest_path)
            manifest_dir = manifest_path.parent
            if not isinstance(items, list):
                parser.error("manifest must contain a JSON array")
    except (OSError, json.JSONDecodeError) as e:
        parser.error(str(e))

    for index, item in enumerate(items, 1):
        try:
            if not isinstance(item, dict):
                raise ValueError("manifest item must be an object")
            image = _resolve_image(str(item.get("image", "")), manifest_dir)
            out_file = _write_one(image, item.get("metadata"), output_dir)
            print(f"[{index}/{len(items)}] wrote {out_file}", flush=True)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            failures.append(index)
            print(f"[{index}/{len(items)}] failed: {e}", file=sys.stderr, flush=True)

    if failures:
        print(f"Failed manifest items: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
