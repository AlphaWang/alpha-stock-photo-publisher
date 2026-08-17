#!/usr/bin/env python3
"""Evaluate generated metadata against a human-labeled golden manifest."""

import argparse
import json
import sys
from pathlib import Path

from metadata_core import clean_text, enforce_limits


def _term(value: object) -> str:
    return clean_text(value).casefold()


def _metadata_text(metadata: dict, language: str) -> str:
    fields = (
        ("title_en", "description_en", "keywords_en")
        if language == "en"
        else ("title_zh", "description_zh", "keywords_zh")
    )
    values = []
    for field in fields:
        value = metadata.get(field, "")
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        else:
            values.append(str(value))
    return _term(" ".join(values))


def evaluate_record(metadata: dict, expected: dict) -> list[str]:
    """Return deterministic mismatches for one labeled image."""
    normalized = enforce_limits(metadata)
    issues = []
    for language in ("en", "zh"):
        haystack = _metadata_text(normalized, language)
        for value in expected.get(f"required_terms_{language}", []):
            if _term(value) not in haystack:
                issues.append(f"missing required {language} term: {value}")
        for value in expected.get(f"forbidden_terms_{language}", []):
            if _term(value) in haystack:
                issues.append(f"contains forbidden {language} term: {value}")

    first_ten = {_term(value) for value in normalized.get("keywords_en", [])[:10]}
    for value in expected.get("first10_terms_en", []):
        if _term(value) not in first_ten:
            issues.append(f"required term is missing from first 10 keywords: {value}")

    for field in (
        "category1",
        "commercial_eligibility",
        "model_release_status",
        "property_release_status",
        "logo_trademark_status",
        "copyrighted_content_status",
    ):
        expected_value = expected.get(field)
        if expected_value is not None and normalized.get(field) != expected_value:
            issues.append(
                f"{field} is {normalized.get(field)!r}, expected {expected_value!r}"
            )
    return issues


def evaluate_manifests(expected_items: list, actual_items: list) -> dict:
    actual_by_image = {
        str(item.get("image", "")): item.get("metadata", {})
        for item in actual_items
        if isinstance(item, dict)
    }
    results = []
    for item in expected_items:
        image = str(item.get("image", ""))
        expected = item.get("expected", {})
        if image not in actual_by_image:
            issues = ["missing generated metadata"]
        elif not isinstance(expected, dict):
            issues = ["expected label must be an object"]
        else:
            issues = evaluate_record(actual_by_image[image], expected)
        results.append({"image": image, "passed": not issues, "issues": issues})
    passed = sum(result["passed"] for result in results)
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": passed / len(results) if results else 0.0,
        "results": results,
    }


def _load_array(path: Path) -> list:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare generated metadata with a human-labeled golden manifest"
    )
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate_manifests(
            _load_array(args.expected.expanduser().resolve()),
            _load_array(args.actual.expanduser().resolve()),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
