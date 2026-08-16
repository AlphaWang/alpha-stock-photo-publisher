#!/usr/bin/env python3
"""Validate agent-generated stock metadata and write timestamped JSON files."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

from metadata_core import (
    SUPPORTED_EXTS,
    assess_metadata_quality,
    enforce_limits,
    find_batch_quality_issues,
    validate_metadata,
    validate_metadata_quality,
    write_metadata,
)


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


def _write_one(
    image: Path,
    metadata: dict,
    output_dir: Optional[Path],
    *,
    visual_review_status: str,
    visual_review_method: str,
) -> Path:
    destination = output_dir or image.parent
    destination.mkdir(parents=True, exist_ok=True)
    return write_metadata(
        metadata,
        image,
        destination,
        visual_review_status=visual_review_status,
        visual_review_method=visual_review_method,
    )


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
    parser.add_argument(
        "--visual-reviewed",
        action="store_true",
        help="Mark metadata as visually verified after completing the skill audit",
    )
    parser.add_argument(
        "--review-method",
        default="agent-native",
        choices=["agent-native", "manual"],
        help="Visual review provenance used with --visual-reviewed",
    )
    parser.add_argument(
        "--audit-receipt",
        type=Path,
        help="Receipt from metadata_contact_sheet.py required for agent-native review",
    )
    parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Treat discovery-quality warnings as errors",
    )
    parser.add_argument(
        "--allow-repeated-metadata",
        action="store_true",
        help="Allow repeated titles/descriptions after explicit visual review",
    )
    args = parser.parse_args()

    output_dir = args.output.expanduser().resolve() if args.output else None
    failures = []

    input_path = None
    try:
        if args.metadata_file:
            if not args.image:
                parser.error("image is required with --metadata-file")
            metadata_file = args.metadata_file.expanduser().resolve()
            input_path = metadata_file
            items = [{"image": args.image, "metadata": _load_json(metadata_file)}]
            manifest_dir = Path.cwd()
        else:
            if args.image:
                parser.error("image must be omitted with --manifest")
            manifest_path = args.manifest.expanduser().resolve()
            input_path = manifest_path
            items = _load_json(manifest_path)
            manifest_dir = manifest_path.parent
            if not isinstance(items, list):
                parser.error("manifest must contain a JSON array")
    except (OSError, json.JSONDecodeError) as e:
        parser.error(str(e))

    if args.visual_reviewed and args.review_method == "agent-native":
        if not args.audit_receipt:
            parser.error(
                "--audit-receipt is required for --visual-reviewed agent-native metadata"
            )
        if not args.manifest:
            parser.error("agent-native audit receipts require --manifest mode")
        try:
            receipt_path = args.audit_receipt.expanduser().resolve()
            receipt = _load_json(receipt_path)
            if not isinstance(receipt, dict):
                parser.error("audit receipt must contain a JSON object")
            expected = hashlib.sha256(input_path.read_bytes()).hexdigest()
            if receipt.get("metadata_manifest_sha256") != expected:
                parser.error("audit receipt does not match the metadata manifest")
            if receipt.get("source_count") != len(items):
                parser.error("audit receipt source count does not match the manifest")
            preview_manifest = Path(
                str(receipt.get("preview_manifest", ""))
            ).expanduser().resolve()
            if not preview_manifest.is_file():
                parser.error("audit receipt preview manifest is missing")
            preview_digest = hashlib.sha256(preview_manifest.read_bytes()).hexdigest()
            if receipt.get("preview_manifest_sha256") != preview_digest:
                parser.error("audit receipt preview manifest has changed")
            sheets = receipt.get("sheets", [])
            if not isinstance(sheets, list) or not all(
                isinstance(sheet, str) and sheet for sheet in sheets
            ):
                parser.error("audit receipt contact sheet list is invalid")
            resolved_sheets = [
                Path(str(sheet)).expanduser().resolve() for sheet in sheets
            ]
            if not sheets or not all(sheet.is_file() for sheet in resolved_sheets):
                parser.error("audit receipt contact sheets are missing")
            sheet_hashes = receipt.get("sheet_sha256", {})
            if not isinstance(sheet_hashes, dict) or any(
                sheet_hashes.get(sheet)
                != hashlib.sha256(resolved.read_bytes()).hexdigest()
                for sheet, resolved in zip(sheets, resolved_sheets)
            ):
                parser.error("audit receipt contact sheets have changed")
        except (OSError, json.JSONDecodeError) as error:
            parser.error(str(error))

    prepared = []
    seen_images = set()
    for index, item in enumerate(items, 1):
        try:
            if not isinstance(item, dict):
                raise ValueError("manifest item must be an object")
            image = _resolve_image(str(item.get("image", "")), manifest_dir)
            if image in seen_images:
                raise ValueError(f"duplicate image in manifest: {image}")
            seen_images.add(image)
            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be a JSON object")
            normalized = enforce_limits(metadata)
            errors = validate_metadata(normalized) + validate_metadata_quality(normalized)
            warnings = assess_metadata_quality(normalized)
            if args.strict_quality:
                errors.extend(warnings)
            elif warnings:
                print(
                    f"[{index}/{len(items)}] quality warning: " + "; ".join(warnings),
                    file=sys.stderr,
                    flush=True,
                )
            if errors:
                raise ValueError("; ".join(errors))
            prepared.append((index, image, normalized))
        except (OSError, ValueError, json.JSONDecodeError) as e:
            failures.append(index)
            print(f"[{index}/{len(items)}] failed: {e}", file=sys.stderr, flush=True)

    if failures:
        print(f"Failed manifest items: {failures}", file=sys.stderr)
        return 1

    repeated = find_batch_quality_issues(
        [(str(image), metadata) for _, image, metadata in prepared]
    )
    if repeated and not args.allow_repeated_metadata:
        for source, issues in sorted(repeated.items()):
            print(
                f"[batch] failed {source}: " + "; ".join(issues),
                file=sys.stderr,
                flush=True,
            )
        print(
            "Batch metadata repetition requires correction or "
            "--allow-repeated-metadata after explicit review",
            file=sys.stderr,
        )
        return 1

    review_status = "verified" if args.visual_reviewed else "unreviewed"
    review_method = args.review_method if args.visual_reviewed else ""
    for index, image, metadata in prepared:
        try:
            out_file = _write_one(
                image,
                metadata,
                output_dir,
                visual_review_status=review_status,
                visual_review_method=review_method,
            )
            print(f"[{index}/{len(items)}] wrote {out_file}", flush=True)
        except (OSError, ValueError) as error:
            failures.append(index)
            print(
                f"[{index}/{len(items)}] failed during write: {error}",
                file=sys.stderr,
                flush=True,
            )

    if failures:
        print(f"Failed manifest items: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
