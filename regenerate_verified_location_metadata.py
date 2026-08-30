#!/usr/bin/env python3
"""Regenerate verified sidecars so buyer-facing copy includes known locations.

This is a deterministic, location-only rewrite. It reuses visual facts only
after verifying the source hash, facts digest, review status, and location
provenance. The command is read-only unless ``--execute`` is supplied.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from metadata_core import (
    TITLE_EN_MAX,
    TITLE_ZH_MAX,
    PX500_DESC_MAX,
    enforce_limits,
    find_batch_quality_issues,
    image_sha256,
    validate_metadata,
    validate_metadata_quality,
    write_metadata,
)
from upload_photos import (
    SUPPORTED_EXTS,
    find_pairs,
    load_metadata,
)
from visual_facts import (
    validate_metadata_against_visual_facts,
    validate_visual_fact_batch,
    validate_visual_facts,
    visual_facts_sha256,
)


@dataclass(frozen=True)
class Prepared:
    image: Path
    old_path: Path
    metadata: dict
    visual_facts: dict
    changed_fields: tuple[str, ...]
    source_sha256: str
    source_size: int


def _directories(target: Path, leaf_directory: str = "") -> list[Path]:
    if target.is_file():
        return [target.parent]
    directories = sorted(
        {
            path.parent
            for path in target.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
        }
    )
    if leaf_directory:
        directories = [
            directory for directory in directories if directory.name == leaf_directory
        ]
    return directories


def _contains(value: str, phrase: str) -> bool:
    return phrase.casefold() in value.casefold()


def _pairs_for_scope(
    directory: Path, requested_image: Path | None = None
) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """Return exact metadata pairs and missing images for the requested scope."""
    pairs = find_pairs(directory)
    if requested_image is None:
        paired_images = {image.resolve() for image, _ in pairs}
        missing = sorted(
            (
                path
                for path in directory.iterdir()
                if path.is_file()
                and path.suffix.lower() in SUPPORTED_EXTS
                and path.resolve() not in paired_images
            ),
            key=lambda path: path.name,
        )
        return pairs, missing

    requested_image = requested_image.resolve()
    scoped = [pair for pair in pairs if pair[0].resolve() == requested_image]
    return scoped, [] if scoped else [requested_image]


def _english_location_components(location: str, broad: str) -> list[str]:
    specific = location.split(",", 1)[0].strip()
    values = [specific]
    if broad and broad.casefold() != specific.casefold():
        values.append(broad)
    return [value for value in values if value]


def _short_chinese_location(location: str, broad: str) -> str:
    if broad and broad in location:
        return location[location.index(broad) :]
    return location


def _rewrite(
    metadata: dict,
    visual_facts: dict,
    *,
    broad_en: str,
    broad_zh: str,
    title_short_en: str,
) -> tuple[dict, tuple[str, ...]]:
    revised = dict(metadata)
    changed = []
    location_en = str(metadata.get("location_en") or "").strip()
    location_zh = str(metadata.get("location_zh") or "").strip()
    confidence = str(metadata.get("location_confidence") or "unknown")
    if not location_en or not location_zh or confidence not in {"medium", "high"}:
        raise ValueError("location-only regeneration requires bilingual medium/high location")

    description_en = str(metadata.get("description_en") or "").strip()
    required_en = _english_location_components(location_en, broad_en)
    if not all(_contains(description_en, value) for value in required_en):
        revised["description_en"] = (
            description_en.rstrip(" .") + f", photographed at {location_en}."
        )
        changed.append("description_en")

    title_en = str(metadata.get("title_en") or "").strip()
    if title_short_en and not _contains(title_en, title_short_en):
        candidate = title_en.rstrip(" .") + f" in {title_short_en}"
        if len(candidate) <= TITLE_EN_MAX:
            revised["title_en"] = candidate
            changed.append("title_en")

    original_title_zh = str(metadata.get("title_zh") or "").strip()
    if broad_zh and broad_zh not in original_title_zh:
        candidate = original_title_zh.rstrip("。") + f"·{broad_zh}"
        if len(candidate) > TITLE_ZH_MAX:
            raise ValueError("title_zh cannot fit the verified destination")
        revised["title_zh"] = candidate
        changed.append("title_zh")

    description_zh = str(metadata.get("description_zh") or "").strip()
    short_zh = _short_chinese_location(location_zh, broad_zh)
    required_zh = [value for value in (broad_zh, short_zh) if value]
    if not all(value in description_zh for value in required_zh):
        candidate = description_zh.rstrip("。") + f"，摄于{short_zh}。"
        if len(candidate) > PX500_DESC_MAX:
            missing_primary = [
                str(value)
                for value in visual_facts.get("primary_subjects_zh", [])
                if str(value) not in original_title_zh
            ]
            visible = (
                f"，可见{'、'.join(missing_primary)}" if missing_primary else ""
            )
            candidate = (
                original_title_zh.rstrip("。")
                + visible
                + f"，摄于{short_zh}。"
            )
        if len(candidate) > PX500_DESC_MAX:
            raise ValueError("description_zh cannot fit the verified destination")
        revised["description_zh"] = candidate
        changed.append("description_zh")

    return enforce_limits(revised), tuple(changed)


def _prepare_directory(
    directory: Path,
    *,
    broad_en: str,
    broad_zh: str,
    title_short_en: str,
    requested_image: Path | None = None,
) -> list[Prepared]:
    pairs, missing = _pairs_for_scope(directory, requested_image)
    if missing:
        names = ", ".join(path.name for path in missing)
        raise ValueError(f"images missing exact-source metadata: {names}")

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(pairs)))) as executor:
        digests = dict(
            zip(
                (image for image, _metadata_path in pairs),
                executor.map(image_sha256, (image for image, _metadata_path in pairs)),
            )
        )

    prepared = []
    batch_items = []
    original_records = []
    for image, metadata_path in pairs:
        metadata = load_metadata(metadata_path)
        if metadata.get("source") != image.name:
            raise ValueError(f"source mismatch for {image.name}")
        actual_digest = digests[image]
        if metadata.get("source_sha256") != actual_digest:
            raise ValueError(f"source SHA-256 mismatch for {image.name}")
        if metadata.get("visual_review_status") != "verified":
            raise ValueError(f"metadata is not visually verified for {image.name}")
        if metadata.get("location_source") not in {
            "context",
            "exif",
            "manual",
            "visible_landmark",
        }:
            raise ValueError(f"location provenance is unresolved for {image.name}")
        visual_facts = metadata.get("visual_facts")
        if not isinstance(visual_facts, dict):
            raise ValueError(f"visual facts are missing for {image.name}")
        if metadata.get("visual_facts_sha256") != visual_facts_sha256(visual_facts):
            raise ValueError(f"visual-facts digest mismatch for {image.name}")

        revised, changed = _rewrite(
            metadata,
            visual_facts,
            broad_en=broad_en,
            broad_zh=broad_zh,
            title_short_en=title_short_en,
        )
        errors = (
            validate_metadata(revised)
            + validate_metadata_quality(revised)
            + validate_visual_facts(visual_facts)
            + validate_metadata_against_visual_facts(revised, visual_facts)
        )
        if errors:
            raise ValueError(f"{image.name}: " + "; ".join(errors))
        prepared.append(
            Prepared(
                image,
                metadata_path,
                revised,
                visual_facts,
                changed,
                actual_digest,
                image.stat().st_size,
            )
        )
        original_records.append((str(image), enforce_limits(metadata)))
        batch_items.append(
            {"image": str(image), "metadata": revised, "visual_facts": visual_facts}
        )

    fact_issues = validate_visual_fact_batch(
        batch_items,
        require_complete_ranking=False,
        max_selected_per_burst=None,
    )
    if fact_issues:
        first_index = sorted(fact_issues)[0]
        raise ValueError(
            f"visual-fact batch issue at item {first_index}: "
            + "; ".join(fact_issues[first_index])
        )

    facts_by_source = {
        str(item.image): item.visual_facts for item in prepared
    }
    original_repeated = find_batch_quality_issues(
        original_records,
        visual_facts_by_source=facts_by_source,
        allow_full_coverage_bursts=True,
    )
    repeated = find_batch_quality_issues(
        [(str(item.image), item.metadata) for item in prepared],
        visual_facts_by_source=facts_by_source,
        allow_full_coverage_bursts=True,
    )
    worsened = {
        source: sorted(set(issues) - set(original_repeated.get(source, [])))
        for source, issues in repeated.items()
        if set(issues) - set(original_repeated.get(source, []))
    }
    if worsened:
        first_source = sorted(worsened)[0]
        raise ValueError(
            f"location rewrite introduced a batch issue for {Path(first_source).name}: "
            + "; ".join(worsened[first_source])
        )
    if original_repeated:
        print(
            f"  [advisory] preserved pre-existing batch issues for "
            f"{len(original_repeated)} image(s) in {directory.name}",
            flush=True,
        )
    return prepared


def _coverage(prepared: list[Prepared], broad_en: str, broad_zh: str) -> tuple[int, int]:
    missing_en = 0
    missing_zh = 0
    for item in prepared:
        location_en = str(item.metadata.get("location_en") or "")
        required_en = _english_location_components(location_en, broad_en)
        if not all(
            _contains(str(item.metadata.get("description_en") or ""), value)
            for value in required_en
        ):
            missing_en += 1
        location_zh = _short_chinese_location(
            str(item.metadata.get("location_zh") or ""), broad_zh
        )
        description_zh = str(item.metadata.get("description_zh") or "")
        if broad_zh not in description_zh or location_zh not in description_zh:
            missing_zh += 1
    return missing_en, missing_zh


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate verified sidecars with buyer-facing location copy"
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--broad-location-en", required=True)
    parser.add_argument("--broad-location-zh", required=True)
    parser.add_argument("--title-short-en", required=True)
    parser.add_argument(
        "--leaf-directory",
        default="",
        help="only process image directories with this final path component",
    )
    parser.add_argument(
        "--execute", action="store_true", help="write new timestamped JSON sidecars"
    )
    args = parser.parse_args()

    target = args.path.expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"path does not exist: {target}")
    directories = _directories(target, args.leaf_directory)
    if not directories:
        raise SystemExit("no supported images found")

    all_prepared = []
    by_directory = {}
    for index, directory in enumerate(directories, start=1):
        prepared = _prepare_directory(
            directory,
            broad_en=args.broad_location_en,
            broad_zh=args.broad_location_zh,
            title_short_en=args.title_short_en,
            requested_image=target if target.is_file() else None,
        )
        by_directory[directory] = prepared
        all_prepared.extend(prepared)
        print(
            f"[{index}/{len(directories)}] preflighted {len(prepared)} image(s): {directory}",
            flush=True,
        )

    missing_en, missing_zh = _coverage(
        all_prepared, args.broad_location_en, args.broad_location_zh
    )
    changes = Counter(
        field for item in all_prepared for field in item.changed_fields
    )
    print(f"Inventory: {len(all_prepared)} image(s)", flush=True)
    print(
        "Changed fields: "
        + ", ".join(f"{field}={changes[field]}" for field in sorted(changes)),
        flush=True,
    )
    print(
        f"Destination coverage gaps: description_en={missing_en}, description_zh={missing_zh}",
        flush=True,
    )
    if missing_en or missing_zh:
        raise SystemExit("destination coverage preflight failed")
    if not args.execute:
        print("Preview only; no JSON files were written. Add --execute to regenerate.")
        return 0

    written = []
    for index, item in enumerate(all_prepared, start=1):
        output = write_metadata(
            item.metadata,
            item.image,
            item.image.parent,
            visual_review_status="verified",
            visual_review_method="agent-native",
            visual_facts=item.visual_facts,
            source_sha256=item.source_sha256,
            source_size=item.source_size,
        )
        written.append(output)
        if index % 25 == 0 or index == len(all_prepared):
            print(f"  wrote {index}/{len(all_prepared)} JSON files", flush=True)

    print(f"Regenerated: {len(written)}/{len(all_prepared)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
