#!/usr/bin/env python3
"""Validate agent-generated stock metadata and write timestamped JSON files."""

from __future__ import annotations

import argparse
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
from metadata_review_finalize import verify_audit_receipt
from visual_facts import (
    normalize_visual_facts,
    validate_metadata_against_visual_facts,
    validate_visual_fact_batch,
    validate_visual_facts,
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
    visual_facts: dict | None = None,
) -> Path:
    destination = output_dir or image.parent
    destination.mkdir(parents=True, exist_ok=True)
    return write_metadata(
        metadata,
        image,
        destination,
        visual_review_status=visual_review_status,
        visual_review_method=visual_review_method,
        visual_facts=visual_facts,
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
        help="Receipt from metadata_review_finalize.py required for agent-native review",
    )
    parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Compatibility flag; critical quality checks are always enforced",
    )
    parser.add_argument(
        "--allow-repeated-metadata",
        action="store_true",
        help="Allow repeated titles/descriptions after explicit visual review",
    )
    parser.add_argument(
        "--preserve-all-frames",
        action="store_true",
        help=(
            "Keep every explicitly requested, technically usable frame while "
            "still validating burst grouping and ranking"
        ),
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
            verify_audit_receipt(receipt_path, input_path)
        except (OSError, json.JSONDecodeError) as error:
            parser.error(str(error))
        except ValueError as error:
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
            visual_facts = item.get("visual_facts")
            facts_required = (
                args.visual_reviewed and args.review_method == "agent-native"
            )
            if facts_required and not isinstance(visual_facts, dict):
                raise ValueError(
                    "agent-native verified metadata requires visual_facts"
                )
            if visual_facts is not None:
                fact_errors = validate_visual_facts(visual_facts)
                if fact_errors:
                    raise ValueError("; ".join(fact_errors))
            normalized = enforce_limits(metadata)
            errors = validate_metadata(normalized) + validate_metadata_quality(normalized)
            if visual_facts is not None:
                errors += validate_metadata_against_visual_facts(
                    normalized, visual_facts
                )
            warnings = assess_metadata_quality(normalized)
            if warnings:
                print(
                    f"[{index}/{len(items)}] quality advisory: " + "; ".join(warnings),
                    file=sys.stderr,
                    flush=True,
                )
            if errors:
                raise ValueError("; ".join(errors))
            prepared.append(
                (
                    index,
                    image,
                    normalized,
                    normalize_visual_facts(visual_facts)
                    if visual_facts is not None
                    else None,
                )
            )
        except (OSError, ValueError, json.JSONDecodeError) as e:
            failures.append(index)
            print(f"[{index}/{len(items)}] failed: {e}", file=sys.stderr, flush=True)

    if failures:
        print(f"Failed manifest items: {failures}", file=sys.stderr)
        return 1

    fact_batch_issues = validate_visual_fact_batch(
        items,
        require_complete_ranking=not args.preserve_all_frames,
        max_selected_per_burst=None if args.preserve_all_frames else 3,
    )
    if fact_batch_issues:
        for index, issues in sorted(fact_batch_issues.items()):
            print(
                f"[batch] failed item {index}: " + "; ".join(issues),
                file=sys.stderr,
                flush=True,
            )
        return 1

    visual_facts_by_source = {
        str(image): facts
        for _index, image, _metadata, facts in prepared
        if facts is not None
    }
    repeated = find_batch_quality_issues(
        [(str(image), metadata) for _, image, metadata, _facts in prepared],
        visual_facts_by_source=visual_facts_by_source,
        allow_full_coverage_bursts=args.preserve_all_frames,
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
    for index, image, metadata, visual_facts in prepared:
        try:
            out_file = _write_one(
                image,
                metadata,
                output_dir,
                visual_review_status=review_status,
                visual_review_method=review_method,
                visual_facts=visual_facts,
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
