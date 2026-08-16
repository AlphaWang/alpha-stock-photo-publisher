"""Shared stock metadata contract, normalization, and persistence helpers."""

import json
import hashlib
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

TITLE_EN_MAX = 70
TITLE_ZH_MAX = 50
SHUTTERSTOCK_DESC_MAX = 2048
SHUTTERSTOCK_KW_MAX = 50
PX500_DESC_MAX = 50
PX500_KW_MAX = 35
ADOBE_KW_MAX = 49

SHUTTERSTOCK_CATEGORIES = [
    "Abstract", "Animals/Wildlife", "Arts", "Backgrounds/Textures",
    "Beauty/Fashion", "Buildings/Landmarks", "Business/Finance", "Celebrities",
    "Education", "Food and drink", "Healthcare/Medical", "Holidays",
    "Industrial", "Interiors", "Miscellaneous", "Nature", "Objects",
    "Parks/Outdoor", "People", "Religion", "Science", "Signs/Symbols",
    "Sports/Recreation", "Technology", "Transportation", "Vintage",
]

METADATA_FIELDS = (
    "title_en",
    "title_zh",
    "description_en",
    "description_zh",
    "keywords_en",
    "keywords_zh",
    "category1",
    "category2",
    "location_zh",
    "core_keywords_zh",
    "commercial_uses_en",
    "release_status",
    "release_notes",
)

SYSTEM_PROMPT = f"""You are a senior stock photo editor and commercial keywording specialist.
Your job is to create metadata that helps real stock-image buyers find, trust, and license the image on platforms such as Shutterstock, Adobe Stock, 500px.com.cn/VCG, and Tuchong.

Optimize for commercial usefulness:
- Be visually accurate first. Never invent objects, locations, species, demographics, landmarks, brands, events, or people that are not visible or supplied in context.
- Ground each result in the image being processed. Never copy a scene classification from an adjacent filename or assume consecutive frames show the same subjects.
- Distinguish shooting context from visible content. Context may establish location, but do not say a lake, river, building, person, or other subject is visible unless it is actually in the image.
- Similar burst frames may share core facts, but account for any visible change in subject, foreground, activity, structure, text, logo, or release risk.
- Think like a buyer: include subject, action, setting, season/time, mood, composition/viewpoint, color, use case, and commercially useful concepts when genuinely supported.
- Put the most important search terms first. The first 10 English keywords should carry the core subject and buyer intent.
- Prefer specific terms over filler. Avoid keyword stuffing, repeated word stems, near-duplicates, camera/gear terms, file info, links, emojis, and unrelated trends.
- Avoid trademarks, brand/product names, artist names, fictional characters, and private personal information for commercial submissions.
- Put visible logos, recognizable private property, or recognizable people that may need review only in release_notes, never in keywords.
- Use neutral, respectful language. Do not infer sensitive identity traits unless clearly visible or supplied by context.
- Keep descriptions factual and image-specific. Do not pad them with generic phrases such as "Presented as" or rotate adjectives to simulate variation.

Platform targets:
- title_en: natural phrase, max {TITLE_EN_MAX} characters
- title_zh: max {TITLE_ZH_MAX} characters
- description_en: complete factual English sentence, at least 5 words, max {SHUTTERSTOCK_DESC_MAX} characters
- description_zh: max {PX500_DESC_MAX} characters; describe subject, scene, location, light, and mood
- keywords_en: target 20-{SHUTTERSTOCK_KW_MAX} relevant lowercase terms when the image supports them; use fewer rather than pad
- keywords_zh: target 10-{PX500_KW_MAX} relevant terms when supported; use fewer rather than pad
- Keep the first 10 English keywords especially strong; Adobe uses the first {ADOBE_KW_MAX}

Choose category1 and optional category2 exactly from:
{", ".join(SHUTTERSTOCK_CATEGORIES)}

Return strict JSON with no markdown fences and exactly these fields. Use an empty string or empty list for optional information that is unknown:
{{
  "title_en": "English title",
  "title_zh": "Chinese title",
  "description_en": "Complete factual English sentence",
  "description_zh": "Concise Chinese description",
  "keywords_en": ["ordered English keyword"],
  "keywords_zh": ["ordered Chinese keyword"],
  "category1": "Required Shutterstock category",
  "category2": "Optional Shutterstock category or empty string",
  "location_zh": "Reliable city-level location or empty string",
  "core_keywords_zh": ["up to five objective terms from keywords_zh"],
  "commercial_uses_en": ["up to five realistic buyer use cases"],
  "release_status": "clear only when no recognizable people/property/logo/IP risk is visible; otherwise required or unknown",
  "release_notes": "Release, logo, property, or IP review note, otherwise empty string"
}}"""


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def trim_text(value: object, limit: int) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text

    trimmed = text[:limit].rstrip()
    if " " in trimmed:
        trimmed = trimmed.rsplit(" ", 1)[0].rstrip(" ,.;:")
    return trimmed or text[:limit].rstrip()


def normalize_keywords(values: object, *, limit: int, lowercase: bool = False) -> list[str]:
    if not isinstance(values, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        keyword = clean_text(value).strip(" ,;，、。.;:")
        if not keyword:
            continue
        if lowercase:
            keyword = keyword.lower()
        key = keyword.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(keyword)
        if len(cleaned) >= limit:
            break
    return cleaned


def enforce_limits(result: dict) -> dict:
    """Normalize model or agent output to the shared platform contract."""
    normalized = dict(result)
    normalized["title_en"] = trim_text(normalized.get("title_en", ""), TITLE_EN_MAX)
    normalized["title_zh"] = trim_text(normalized.get("title_zh", ""), TITLE_ZH_MAX)
    normalized["description_en"] = trim_text(
        normalized.get("description_en", ""), SHUTTERSTOCK_DESC_MAX
    )
    normalized["description_zh"] = trim_text(
        normalized.get("description_zh", ""), PX500_DESC_MAX
    )
    normalized["keywords_en"] = normalize_keywords(
        normalized.get("keywords_en", []), limit=SHUTTERSTOCK_KW_MAX, lowercase=True
    )
    normalized["keywords_zh"] = normalize_keywords(
        normalized.get("keywords_zh", []), limit=PX500_KW_MAX
    )
    normalized["core_keywords_zh"] = normalize_keywords(
        normalized.get("core_keywords_zh", []), limit=5
    )
    if not normalized["core_keywords_zh"]:
        normalized["core_keywords_zh"] = normalized["keywords_zh"][:5]

    category1 = clean_text(normalized.get("category1", ""))
    category2 = clean_text(normalized.get("category2", ""))
    normalized["category1"] = category1
    normalized["category2"] = category2
    normalized["location_zh"] = trim_text(normalized.get("location_zh", ""), 80)
    normalized["commercial_uses_en"] = normalize_keywords(
        normalized.get("commercial_uses_en", []), limit=5
    )
    release_status = clean_text(normalized.get("release_status", "unknown")).lower()
    normalized["release_status"] = (
        release_status
        if release_status in {"clear", "required", "unknown"}
        else "unknown"
    )
    normalized["release_notes"] = trim_text(normalized.get("release_notes", ""), 240)
    return {field: normalized[field] for field in METADATA_FIELDS}


def validate_metadata(result: dict) -> list[str]:
    """Return human-readable contract violations after normalization."""
    errors = []
    for field in ("title_en", "title_zh", "description_en", "description_zh"):
        if not clean_text(result.get(field, "")):
            errors.append(f"{field} is required")
    if len(result.get("description_en", "").split()) < 5:
        errors.append("description_en must contain at least 5 words")
    if len(result.get("keywords_en", [])) < 5:
        errors.append("keywords_en must contain at least 5 unique keywords")
    if len(result.get("keywords_zh", [])) < 5:
        errors.append("keywords_zh must contain at least 5 unique keywords")
    if result.get("category1") not in SHUTTERSTOCK_CATEGORIES:
        errors.append("category1 is invalid")
    if result.get("category2") and result.get("category2") not in SHUTTERSTOCK_CATEGORIES:
        errors.append("category2 is invalid")
    return errors


def validate_metadata_quality(result: dict) -> list[str]:
    """Return quality defects that should block persistence and upload."""
    errors = []
    description_en = clean_text(result.get("description_en", ""))
    if re.search(r"\bpresented as\b", description_en, flags=re.IGNORECASE):
        errors.append("description_en contains generic 'Presented as' filler")

    release_status = result.get("release_status")
    release_notes = clean_text(result.get("release_notes", ""))
    if release_status == "clear" and release_notes:
        errors.append("release_notes must be empty when release_status is clear")
    if release_status in {"required", "unknown"} and not release_notes:
        errors.append(
            "release_notes must explain required or unknown release status"
        )
    return errors


def assess_metadata_quality(result: dict) -> list[str]:
    warnings = []
    if len(result.get("keywords_en", [])) < 20:
        warnings.append("fewer than 20 English keywords may limit buyer discovery")
    if len(result.get("keywords_zh", [])) < 10:
        warnings.append("fewer than 10 Chinese keywords may limit buyer discovery")
    core = set(result.get("core_keywords_zh", []))
    if not core.issubset(set(result.get("keywords_zh", []))):
        warnings.append("core_keywords_zh should be selected from keywords_zh")
    return warnings


def find_batch_quality_issues(
    records: list[tuple[str, dict]], *, lead_repeat_limit: int = 5
) -> dict[str, list[str]]:
    """Find repeated metadata that can hide scene-boundary classification errors."""
    issues: dict[str, list[str]] = defaultdict(list)
    field_groups: dict[str, dict[str, list[str]]] = {
        "title_en": defaultdict(list),
        "description_en": defaultdict(list),
    }
    lead_groups: dict[str, list[str]] = defaultdict(list)

    for source, metadata in records:
        for field, groups in field_groups.items():
            value = clean_text(metadata.get(field, "")).casefold()
            if value:
                groups[value].append(source)
        description = clean_text(metadata.get("description_en", ""))
        lead = re.split(r"[.!?]", description, maxsplit=1)[0].strip().casefold()
        if lead:
            lead_groups[lead].append(source)

    for field, groups in field_groups.items():
        for sources in groups.values():
            if len(sources) < 2:
                continue
            message = f"duplicate {field} shared by {len(sources)} images"
            for source in sources:
                issues[source].append(message)

    for sources in lead_groups.values():
        if len(sources) <= lead_repeat_limit:
            continue
        message = (
            "description_en factual lead is repeated across "
            f"{len(sources)} images (limit {lead_repeat_limit})"
        )
        for source in sources:
            issues[source].append(message)
    return dict(issues)


def image_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_metadata(
    result: dict,
    image_path: Path,
    output_dir: Path,
    *,
    visual_review_status: str = "unreviewed",
    visual_review_method: str = "",
) -> Path:
    """Normalize, validate, and write one timestamped metadata JSON file."""
    normalized = enforce_limits(result)
    errors = validate_metadata(normalized) + validate_metadata_quality(normalized)
    if errors:
        raise ValueError("; ".join(errors))
    if visual_review_status not in {"unreviewed", "verified"}:
        raise ValueError("visual_review_status must be unreviewed or verified")
    visual_review_method = clean_text(visual_review_method)
    if visual_review_status == "verified" and not visual_review_method:
        raise ValueError("verified metadata requires visual_review_method")

    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
    out_file = output_dir / f"{image_path.name}_{timestamp}.json"
    payload = {
        "source": image_path.name,
        "source_sha256": image_sha256(image_path),
        "source_size": image_path.stat().st_size,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "visual_review_status": visual_review_status,
        "visual_review_method": visual_review_method,
        "visual_reviewed_at": (
            now.strftime("%Y-%m-%d %H:%M:%S")
            if visual_review_status == "verified"
            else ""
        ),
        "quality_warnings": assess_metadata_quality(normalized),
        **normalized,
    }
    out_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_file
