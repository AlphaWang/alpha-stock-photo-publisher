#!/usr/bin/env python3
"""Validate independent review decisions and issue a bound audit receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from metadata_core import METADATA_FIELDS
from visual_facts import VISUAL_FACT_FIELDS, visual_facts_sha256

REVIEW_PACK_SCHEMA_VERSION = 3
REVIEW_DECISION_SCHEMA_VERSION = 1
AUDIT_SCHEMA_VERSION = 3
REVIEWED_FIELDS = (*METADATA_FIELDS, "visual_facts", "release_ip")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(value: object, base: Path) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _verify_hashed_files(
    values: object, hashes: object, base: Path, label: str
) -> list[Path]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} list is empty or invalid")
    if not isinstance(hashes, dict):
        raise ValueError(f"{label} hashes are invalid")
    resolved = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} path is invalid")
        path = _resolve(value, base)
        if not path.is_file():
            raise ValueError(f"{label} is missing: {path}")
        if hashes.get(value) != _sha256(path):
            raise ValueError(f"{label} has changed: {path}")
        resolved.append(path)
    return resolved


def validate_review_pack(
    review_pack_path: Path, metadata_manifest_path: Path | None = None
) -> tuple[dict, list[dict]]:
    """Validate every artifact bound into a generated review pack."""
    review_pack_path = review_pack_path.expanduser().resolve()
    pack = _load_json(review_pack_path)
    if not isinstance(pack, dict):
        raise ValueError("review pack must contain an object")
    if pack.get("review_pack_schema_version") != REVIEW_PACK_SCHEMA_VERSION:
        raise ValueError("review pack does not cover the current audit schema")
    audited_fields = pack.get("audited_fields")
    if not isinstance(audited_fields, list) or not set(METADATA_FIELDS).issubset(
        set(audited_fields)
    ):
        raise ValueError("review pack is missing metadata fields")
    visual_fact_fields = pack.get("visual_fact_fields")
    if not isinstance(visual_fact_fields, list) or not set(
        VISUAL_FACT_FIELDS
    ).issubset(set(visual_fact_fields)):
        raise ValueError("review pack is missing visual-fact fields")

    preview_manifest = _resolve(
        pack.get("preview_manifest"), review_pack_path.parent
    )
    if not preview_manifest.is_file():
        raise ValueError("review pack preview manifest is missing")
    if pack.get("preview_manifest_sha256") != _sha256(preview_manifest):
        raise ValueError("review pack preview manifest has changed")

    metadata_manifest = _resolve(
        pack.get("metadata_manifest"), review_pack_path.parent
    )
    if metadata_manifest_path is not None and metadata_manifest != (
        metadata_manifest_path.expanduser().resolve()
    ):
        raise ValueError("review pack does not match the metadata manifest")
    if not metadata_manifest.is_file():
        raise ValueError("review pack metadata manifest is missing")
    if pack.get("metadata_manifest_sha256") != _sha256(metadata_manifest):
        raise ValueError("review pack metadata manifest has changed")
    metadata_items = _load_json(metadata_manifest)
    if not isinstance(metadata_items, list):
        raise ValueError("metadata manifest must contain an array")
    if pack.get("source_count") != len(metadata_items):
        raise ValueError("review pack source count does not match the manifest")

    resolved_sheets = _verify_hashed_files(
        pack.get("sheets"),
        pack.get("sheet_sha256"),
        review_pack_path.parent,
        "review sheet",
    )
    if len(resolved_sheets) != len(metadata_items):
        raise ValueError("review pack must contain one sheet per source")
    sheet_paths = {str(path) for path in resolved_sheets}
    pack_items = pack.get("items")
    if not isinstance(pack_items, list) or len(pack_items) != len(metadata_items):
        raise ValueError("review pack item coverage is incomplete")

    metadata_by_source = {}
    for item in metadata_items:
        if not isinstance(item, dict) or not item.get("image"):
            raise ValueError("invalid metadata manifest item")
        source = str(_resolve(item["image"], metadata_manifest.parent))
        if source in metadata_by_source:
            raise ValueError(f"duplicate metadata source: {source}")
        metadata_by_source[source] = item

    seen = set()
    seen_sheets = set()
    for item in pack_items:
        if not isinstance(item, dict) or not item.get("image"):
            raise ValueError("invalid review pack item")
        source = str(_resolve(item["image"], review_pack_path.parent))
        if source in seen or source not in metadata_by_source:
            raise ValueError(f"review pack source mismatch: {source}")
        seen.add(source)
        sheet = _resolve(item.get("sheet"), review_pack_path.parent)
        if str(sheet) not in sheet_paths or sheet in seen_sheets:
            raise ValueError(f"review pack item has an unknown sheet: {source}")
        seen_sheets.add(sheet)
        preview = _resolve(item.get("preview"), review_pack_path.parent)
        if not preview.is_file() or item.get("preview_sha256") != _sha256(preview):
            raise ValueError(f"review preview has changed: {preview}")
        details = item.get("detail_previews", [])
        detail_hashes = item.get("detail_preview_sha256", {})
        if not isinstance(details, list) or not isinstance(detail_hashes, dict):
            raise ValueError(f"invalid detail previews for {source}")
        for detail_value in details:
            detail = _resolve(detail_value, review_pack_path.parent)
            if not detail.is_file() or detail_hashes.get(detail_value) != _sha256(detail):
                raise ValueError(f"review detail preview has changed: {detail}")
        expected_facts = visual_facts_sha256(
            metadata_by_source[source].get("visual_facts")
        )
        if item.get("visual_facts_sha256") != expected_facts:
            raise ValueError(f"visual facts have changed for {source}")
    if seen != set(metadata_by_source):
        raise ValueError("review pack does not cover every metadata source")
    return pack, metadata_items


def validate_review_decisions(
    decisions_path: Path, review_pack_path: Path, pack: dict
) -> dict:
    """Require explicit, per-image pass decisions from an independent review."""
    decisions_path = decisions_path.expanduser().resolve()
    review_pack_path = review_pack_path.expanduser().resolve()
    decisions = _load_json(decisions_path)
    if not isinstance(decisions, dict):
        raise ValueError("review decisions must contain an object")
    if decisions.get("review_decision_schema_version") != REVIEW_DECISION_SCHEMA_VERSION:
        raise ValueError("review decisions use an unsupported schema")
    bound_pack = _resolve(decisions.get("review_pack"), decisions_path.parent)
    if bound_pack != review_pack_path:
        raise ValueError("review decisions do not match the review pack")
    if decisions.get("review_pack_sha256") != _sha256(review_pack_path):
        raise ValueError("review pack changed after decisions were recorded")
    if decisions.get("independent_review") is not True:
        raise ValueError("review decisions must declare independent_review=true")
    if not str(decisions.get("reviewer", "")).strip():
        raise ValueError("review decisions require reviewer provenance")
    reviewed_fields = decisions.get("reviewed_fields")
    if not isinstance(reviewed_fields, list) or not set(REVIEWED_FIELDS).issubset(
        set(reviewed_fields)
    ):
        raise ValueError("review decisions do not cover every required field")

    expected = {
        str(_resolve(item["image"], review_pack_path.parent)): item
        for item in pack["items"]
    }
    decision_items = decisions.get("items")
    if not isinstance(decision_items, list) or len(decision_items) != len(expected):
        raise ValueError("review decisions do not cover every source")
    seen = set()
    for item in decision_items:
        if not isinstance(item, dict) or not item.get("image"):
            raise ValueError("invalid review decision item")
        source = str(_resolve(item["image"], decisions_path.parent))
        if source in seen or source not in expected:
            raise ValueError(f"review decision source mismatch: {source}")
        seen.add(source)
        issues = item.get("issues")
        if not isinstance(issues, list):
            raise ValueError(f"review decision issues must be an array: {source}")
        verdicts = (
            item.get("verdict"),
            item.get("visual_facts_verdict"),
            item.get("metadata_verdict"),
            item.get("release_ip_verdict"),
        )
        if verdicts != ("pass", "pass", "pass", "pass") or issues:
            raise ValueError(f"review did not pass for {source}: {issues}")
        evidence_values = item.get("reviewed_evidence")
        if not isinstance(evidence_values, list):
            raise ValueError(f"review evidence must be an array for {source}")
        evidence = set(evidence_values)
        required_evidence = {"overview", "visual_facts", "metadata"}
        if expected[source].get("detail_previews"):
            required_evidence.add("detail_crops")
        if not required_evidence.issubset(evidence):
            raise ValueError(f"review evidence is incomplete for {source}")
    if seen != set(expected):
        raise ValueError("review decisions do not cover every source")
    return decisions


def issue_audit_receipt(review_pack_path: Path, decisions_path: Path) -> Path:
    review_pack_path = review_pack_path.expanduser().resolve()
    decisions_path = decisions_path.expanduser().resolve()
    pack, _items = validate_review_pack(review_pack_path)
    decisions = validate_review_decisions(decisions_path, review_pack_path, pack)
    receipt = review_pack_path.parent / "metadata_audit_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "audit_schema_version": AUDIT_SCHEMA_VERSION,
                "issued_at": datetime.now(timezone.utc).isoformat(),
                "review_method": "agent-native-independent",
                "reviewer": decisions["reviewer"],
                "source_count": pack["source_count"],
                "metadata_manifest": pack["metadata_manifest"],
                "metadata_manifest_sha256": pack["metadata_manifest_sha256"],
                "review_pack": str(review_pack_path),
                "review_pack_sha256": _sha256(review_pack_path),
                "review_decisions": str(decisions_path),
                "review_decisions_sha256": _sha256(decisions_path),
                "reviewed_fields": list(REVIEWED_FIELDS),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt


def verify_audit_receipt(
    receipt_path: Path, metadata_manifest_path: Path
) -> dict:
    """Revalidate a receipt and all artifacts instead of trusting its presence."""
    receipt_path = receipt_path.expanduser().resolve()
    metadata_manifest_path = metadata_manifest_path.expanduser().resolve()
    receipt = _load_json(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("audit_schema_version") != AUDIT_SCHEMA_VERSION:
        raise ValueError("audit receipt does not cover independent review schema v3")
    if receipt.get("metadata_manifest_sha256") != _sha256(metadata_manifest_path):
        raise ValueError("audit receipt does not match the metadata manifest")
    review_pack = _resolve(receipt.get("review_pack"), receipt_path.parent)
    decisions = _resolve(receipt.get("review_decisions"), receipt_path.parent)
    if receipt.get("review_pack_sha256") != _sha256(review_pack):
        raise ValueError("audit review pack has changed")
    if receipt.get("review_decisions_sha256") != _sha256(decisions):
        raise ValueError("audit review decisions have changed")
    pack, metadata_items = validate_review_pack(review_pack, metadata_manifest_path)
    validate_review_decisions(decisions, review_pack, pack)
    if receipt.get("source_count") != len(metadata_items):
        raise ValueError("audit receipt source count does not match the manifest")
    reviewed_fields = receipt.get("reviewed_fields")
    if not isinstance(reviewed_fields, list) or not set(REVIEWED_FIELDS).issubset(
        set(reviewed_fields)
    ):
        raise ValueError("audit receipt is missing required reviewed fields")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Issue an audit receipt from explicit independent review decisions"
    )
    parser.add_argument("--review-pack", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = issue_audit_receipt(args.review_pack, args.decisions)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(f"Audit receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
