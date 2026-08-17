#!/usr/bin/env python3
"""Build filename-and-metadata contact sheets for mandatory visual review."""

import argparse
import hashlib
import json
import textwrap
from pathlib import Path

from metadata_core import METADATA_FIELDS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise RuntimeError("Pillow is required: pip install pillow") from error
    return Image, ImageDraw, ImageFont


def _audit_font(ImageFont):
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, 14)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrapped(label: str, value: object, *, width: int = 132) -> list[str]:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value or "")
    return textwrap.wrap(
        f"{label}: {text or '(empty)'}",
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [f"{label}: (empty)"]


def _metadata_lines(source: Path, metadata: dict) -> list[str]:
    lines = [source.name]
    fields = (
        ("Title EN", "title_en"),
        ("Title ZH", "title_zh"),
        ("Description EN", "description_en"),
        ("Description ZH", "description_zh"),
        ("Keywords EN (all)", "keywords_en"),
        ("Keywords ZH (all)", "keywords_zh"),
        ("Shutterstock category 1", "category1"),
        ("Shutterstock category 2", "category2"),
        ("Platform categories", "platform_categories"),
        ("Location EN", "location_en"),
        ("Location ZH", "location_zh"),
        ("Location source", "location_source"),
        ("Location confidence", "location_confidence"),
        ("Core keywords ZH", "core_keywords_zh"),
        ("Commercial uses", "commercial_uses_en"),
        ("Model release", "model_release_status"),
        ("Property release", "property_release_status"),
        ("Logo/trademark", "logo_trademark_status"),
        ("Copyrighted content", "copyrighted_content_status"),
        ("Commercial eligibility", "commercial_eligibility"),
        ("Release summary", "release_status"),
        ("Release notes", "release_notes"),
    )
    for label, field in fields:
        lines.extend(_wrapped(label, metadata.get(field)))
    return lines


def _resolve_path(value: object, base: Path) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def build_contact_sheets(preview_manifest: Path, metadata_manifest: Path) -> Path:
    Image, ImageDraw, ImageFont = _load_pillow()
    preview_manifest = preview_manifest.expanduser().resolve()
    metadata_manifest = metadata_manifest.expanduser().resolve()
    preview_data = _load_json(preview_manifest)
    metadata_data = _load_json(metadata_manifest)
    if not isinstance(preview_data, dict) or not isinstance(
        preview_data.get("items"), list
    ):
        raise ValueError("preview manifest must contain an items array")
    if not isinstance(metadata_data, list):
        raise ValueError("metadata manifest must contain a JSON array")

    previews = {}
    for item in preview_data["items"]:
        if not isinstance(item, dict):
            raise ValueError("invalid preview manifest item")
        if not item.get("source") or not item.get("preview"):
            raise ValueError("preview manifest item requires source and preview")
        source = str(
            _resolve_path(item.get("source"), preview_manifest.parent)
        )
        if source in previews:
            raise ValueError(f"duplicate preview source: {source}")
        previews[source] = _resolve_path(
            item.get("preview"), preview_manifest.parent
        )

    records = []
    seen = set()
    for item in metadata_data:
        if not isinstance(item, dict) or not isinstance(item.get("metadata"), dict):
            raise ValueError("invalid metadata manifest item")
        if not item.get("image"):
            raise ValueError("metadata manifest item requires image")
        source = str(
            _resolve_path(item.get("image"), metadata_manifest.parent)
        )
        if source in seen:
            raise ValueError(f"duplicate metadata source: {source}")
        seen.add(source)
        preview = previews.get(source)
        if preview is None or not preview.is_file():
            raise ValueError(f"no prepared preview for metadata source: {source}")
        records.append((Path(source), preview, item["metadata"]))

    unmatched = sorted(set(previews) - seen)
    if unmatched:
        raise ValueError(
            f"preview manifest has {len(unmatched)} source(s) missing from metadata manifest"
        )
    if not records:
        raise ValueError("no matched preview and metadata records")

    metadata_digest = _sha256(metadata_manifest)
    output_dir = preview_manifest.parent / f"metadata-audit-{metadata_digest[:12]}"
    output_dir.mkdir(exist_ok=True)
    font = _audit_font(ImageFont)
    sheet_paths = []
    # One image per sheet leaves enough room to display every keyword and all
    # bilingual/risk fields without silently clipping the audit evidence.
    columns, rows = 1, 1
    cell_width, cell_height = 1200, 1600
    per_sheet = columns * rows

    for page, start in enumerate(range(0, len(records), per_sheet), 1):
        page_records = records[start : start + per_sheet]
        line_count = max(
            len(_metadata_lines(source, metadata))
            for source, _preview, metadata in page_records
        )
        rendered_height = max(cell_height, 710 + line_count * 18)
        sheet = Image.new(
            "RGB", (columns * cell_width, rows * rendered_height), "white"
        )
        draw = ImageDraw.Draw(sheet)
        for offset, (source, preview, metadata) in enumerate(
            page_records
        ):
            row, column = divmod(offset, columns)
            x, y = column * cell_width, row * rendered_height
            with Image.open(preview) as opened:
                image = opened.convert("RGB")
                image.thumbnail((1160, 650))
                sheet.paste(image, (x + (1160 - image.width) // 2 + 20, y + 5))
            label = "\n".join(_metadata_lines(source, metadata))
            draw.multiline_text(
                (x + 18, y + 670),
                label,
                fill="black",
                font=font,
                spacing=2,
            )
        sheet_path = output_dir / f"metadata-audit-{page:03d}.jpg"
        sheet.save(sheet_path, "JPEG", quality=90)
        sheet_paths.append(str(sheet_path))
        print(sheet_path, flush=True)

    receipt = preview_manifest.parent / "metadata_audit_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "preview_manifest": str(preview_manifest),
                "preview_manifest_sha256": _sha256(preview_manifest),
                "metadata_manifest": str(metadata_manifest),
                "metadata_manifest_sha256": metadata_digest,
                "source_count": len(records),
                "audit_schema_version": 2,
                "audited_fields": list(METADATA_FIELDS),
                "sheets": sheet_paths,
                "sheet_sha256": {
                    sheet_path: _sha256(Path(sheet_path)) for sheet_path in sheet_paths
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Audit receipt: {receipt}", flush=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create contact sheets that pair previews with proposed metadata"
    )
    parser.add_argument("--preview-manifest", type=Path, required=True)
    parser.add_argument("--metadata-manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_contact_sheets(
            args.preview_manifest.expanduser().resolve(),
            args.metadata_manifest.expanduser().resolve(),
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
