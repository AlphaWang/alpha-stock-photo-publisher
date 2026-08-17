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

ADOBE_CATEGORIES = [
    "Animals", "Buildings and Architecture", "Business", "Culture and Religion",
    "Food", "Graphic Resources", "Hobbies and Leisure", "Industry",
    "Landscapes", "Lifestyle", "People", "Plants and Flowers", "Science",
    "Social Issues", "Sports", "States of Mind", "Technology", "The Environment", "Transport",
    "Travel",
]

TUCHONG_CATEGORIES = [
    "自然风光", "城市风光", "野生动物", "静物美食", "生活方式", "运动健康",
    "生物医疗", "节日假日", "商务肖像",
]

ISTOCK_CATEGORIES = [
    "Nature", "Travel", "Buildings & Architecture", "Animals/Wildlife",
    "Food and Drink", "People", "Sports", "Healthcare & Medical", "Holidays",
    "Business", "Transport", "Technology",
]

LOCATION_SOURCES = {"unknown", "context", "exif", "manual", "visible_landmark"}
LOCATION_CONFIDENCE = {"unknown", "low", "medium", "high"}
RELEASE_DOCUMENT_STATUS = {"not_required", "required", "provided", "unknown"}
VISUAL_IP_STATUS = {"none", "visible", "unknown"}
COMMERCIAL_ELIGIBILITY = {"clear", "review", "editorial_only"}

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
    "platform_categories",
    "location_en",
    "location_zh",
    "location_source",
    "location_confidence",
    "core_keywords_zh",
    "commercial_uses_en",
    "model_release_status",
    "property_release_status",
    "logo_trademark_status",
    "copyrighted_content_status",
    "commercial_eligibility",
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
- First identify visible facts, then derive buyer metadata. Include subject, action, setting, composition/viewpoint, color, copy space, and commercially useful concepts only when genuinely supported. Do not infer a season, time, mood, or use case from color alone.
- Put the most important search terms first. The first 10 English keywords should carry the core subject and buyer intent.
- Prefer specific terms over filler. Avoid keyword stuffing, repeated word stems, near-duplicates, camera/gear terms, file info, links, emojis, and unrelated trends.
- Avoid trademarks, brand/product names, artist names, fictional characters, and private personal information for commercial submissions.
- Put visible logos, recognizable private property, or recognizable people that may need review only in release_notes, never in keywords.
- Use neutral, respectful language. Do not infer sensitive identity traits unless clearly visible or supplied by context.
- Keep descriptions factual and image-specific. Do not pad them with generic phrases such as "Presented as" or rotate adjectives to simulate variation.

Platform targets:
- title_en: natural phrase, max {TITLE_EN_MAX} characters
- title_zh: natural Chinese stock title, max {TITLE_ZH_MAX} characters; this is the Chinese-platform title
- description_en: complete factual English sentence, at least 5 words, max {SHUTTERSTOCK_DESC_MAX} characters
- description_zh: max {PX500_DESC_MAX} characters; factual Chinese description, not a duplicate keyword list
- keywords_en: normally 15-25 relevant lowercase terms; minimum 7 and maximum {SHUTTERSTOCK_KW_MAX}; use fewer rather than pad
- keywords_zh: normally 8-20 relevant terms; minimum 5 and maximum {PX500_KW_MAX}; use fewer rather than pad
- Keep the first 10 English keywords especially strong; Adobe uses the first {ADOBE_KW_MAX}
- Order English keywords as: exact primary subject first, then action/setting, then visual attributes and well-supported concepts. The first three must identify the primary subject.

Choose category1 and optional category2 exactly from:
{", ".join(SHUTTERSTOCK_CATEGORIES)}

Choose platform_categories.adobestock exactly from these values, or empty:
{", ".join(ADOBE_CATEGORIES)}

Choose up to two platform_categories.tuchong values exactly from:
{", ".join(TUCHONG_CATEGORIES)}

Choose platform_categories.istock exactly from these values, or empty:
{", ".join(ISTOCK_CATEGORIES)}

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
  "platform_categories": {{
    "shutterstock": ["category1", "optional category2"],
    "adobestock": "one exact Adobe category or empty string",
    "tuchong": ["up to two exact Tuchong categories"],
    "istock": "one exact Getty/iStock category or empty string"
  }},
  "location_en": "Reliable English location or empty string",
  "location_zh": "Reliable city-level location or empty string",
  "location_source": "unknown, context, exif, manual, or visible_landmark",
  "location_confidence": "unknown, low, medium, or high",
  "core_keywords_zh": ["up to five objective terms from keywords_zh"],
  "commercial_uses_en": ["up to five realistic buyer use cases"],
  "model_release_status": "not_required, required, provided, or unknown",
  "property_release_status": "not_required, required, provided, or unknown",
  "logo_trademark_status": "none, visible, or unknown",
  "copyrighted_content_status": "none, visible, or unknown",
  "commercial_eligibility": "clear, review, or editorial_only",
  "release_status": "legacy summary: clear, required, or unknown",
  "release_notes": "Release, logo, property, or IP review note, otherwise empty string"
}}"""


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


_ADOBE_CATEGORY_MAP = {
    "Abstract": "States of Mind",
    "Animals/Wildlife": "Animals",
    "Arts": "Culture and Religion",
    "Backgrounds/Textures": "Graphic Resources",
    "Beauty/Fashion": "Lifestyle",
    "Buildings/Landmarks": "Buildings and Architecture",
    "Business/Finance": "Business",
    "Celebrities": "People",
    "Education": "Science",
    "Food and drink": "Food",
    "Healthcare/Medical": "Science",
    "Holidays": "Culture and Religion",
    "Industrial": "Industry",
    "Interiors": "Buildings and Architecture",
    "Miscellaneous": "Lifestyle",
    "Nature": "The Environment",
    "Objects": "Lifestyle",
    "Parks/Outdoor": "Landscapes",
    "People": "People",
    "Religion": "Culture and Religion",
    "Science": "Science",
    "Signs/Symbols": "Graphic Resources",
    "Sports/Recreation": "Sports",
    "Technology": "Technology",
    "Transportation": "Transport",
    "Vintage": "Lifestyle",
}

_TUCHONG_CATEGORY_MAP = {
    "Animals/Wildlife": ["野生动物"],
    "Buildings/Landmarks": ["城市风光"],
    "Business/Finance": ["商务肖像"],
    "Celebrities": ["生活方式"],
    "Food and drink": ["静物美食"],
    "Healthcare/Medical": ["生物医疗"],
    "Holidays": ["节日假日"],
    "Industrial": ["城市风光"],
    "Nature": ["自然风光"],
    "Parks/Outdoor": ["自然风光"],
    "People": ["生活方式"],
    "Sports/Recreation": ["运动健康"],
}

_ISTOCK_CATEGORY_MAP = {
    "Animals/Wildlife": "Animals/Wildlife",
    "Buildings/Landmarks": "Buildings & Architecture",
    "Business/Finance": "Business",
    "Food and drink": "Food and Drink",
    "Healthcare/Medical": "Healthcare & Medical",
    "Holidays": "Holidays",
    "Nature": "Nature",
    "Parks/Outdoor": "Nature",
    "People": "People",
    "Sports/Recreation": "Sports",
    "Technology": "Technology",
    "Transportation": "Transport",
}


def default_platform_categories(category1: str, category2: str = "") -> dict:
    """Conservatively derive platform categories for legacy metadata."""
    shutterstock = [value for value in (category1, category2) if value]
    adobe = ""
    if "Parks/Outdoor" in shutterstock:
        adobe = "Landscapes"
    else:
        adobe = _ADOBE_CATEGORY_MAP.get(category1, "")

    tuchong = []
    for category in shutterstock:
        for value in _TUCHONG_CATEGORY_MAP.get(category, []):
            if value not in tuchong:
                tuchong.append(value)
            if len(tuchong) >= 2:
                break
        if len(tuchong) >= 2:
            break

    istock = ""
    for category in shutterstock:
        istock = _ISTOCK_CATEGORY_MAP.get(category, "")
        if istock:
            break
    return {
        "shutterstock": shutterstock[:2],
        "adobestock": adobe,
        "tuchong": tuchong,
        "istock": istock,
    }


def normalize_platform_categories(
    value: object, *, category1: str, category2: str
) -> dict:
    defaults = default_platform_categories(category1, category2)
    if not isinstance(value, dict):
        return defaults

    shutterstock = normalize_keywords(value.get("shutterstock", []), limit=2)
    if "shutterstock" not in value or not shutterstock:
        shutterstock = defaults["shutterstock"]
    tuchong = normalize_keywords(value.get("tuchong", []), limit=2)
    return {
        "shutterstock": shutterstock,
        "adobestock": (
            clean_text(value.get("adobestock", ""))
            if "adobestock" in value
            else defaults["adobestock"]
        ),
        "tuchong": tuchong if "tuchong" in value else defaults["tuchong"],
        "istock": (
            clean_text(value.get("istock", ""))
            if "istock" in value
            else defaults["istock"]
        ),
    }


def platform_category(metadata: dict, platform: str):
    categories = metadata.get("platform_categories", {})
    if not isinstance(categories, dict):
        categories = default_platform_categories(
            clean_text(metadata.get("category1", "")),
            clean_text(metadata.get("category2", "")),
        )
    return categories.get(platform, [] if platform in {"shutterstock", "tuchong"} else "")


def commercial_submission_review_reason(metadata: dict) -> str:
    structured_fields = {
        "model_release_status",
        "property_release_status",
        "logo_trademark_status",
        "copyrighted_content_status",
        "commercial_eligibility",
    }
    if not structured_fields.intersection(metadata):
        legacy_status = clean_text(metadata.get("release_status", "unknown")).lower()
        legacy_notes = clean_text(metadata.get("release_notes", ""))
        if legacy_status == "clear" and not legacy_notes:
            return ""
        return (
            f"release review required — {legacy_notes}"
            if legacy_notes
            else f"release status is {legacy_status or 'unknown'}"
        )
    for label, field in (
        ("model release", "model_release_status"),
        ("property release", "property_release_status"),
    ):
        status = clean_text(metadata.get(field, "unknown")).lower()
        if status != "not_required":
            return f"{label} status is {status or 'unknown'}; manual attachment/review required"
    for label, field in (
        ("logo/trademark", "logo_trademark_status"),
        ("copyrighted content", "copyrighted_content_status"),
    ):
        status = clean_text(metadata.get(field, "unknown")).lower()
        if status != "none":
            return f"{label} status is {status or 'unknown'}"
    eligibility = clean_text(metadata.get("commercial_eligibility", "review")).lower()
    if eligibility != "clear":
        return f"commercial eligibility is {eligibility or 'review'}"
    return ""


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
        if limit and len(cleaned) >= limit:
            break
    return cleaned


def enforce_limits(result: dict) -> dict:
    """Normalize model or agent output to the shared platform contract."""
    normalized = dict(result)
    # Preserve complete model output so over-limit metadata is rejected and
    # regenerated instead of being silently truncated into an inaccurate phrase.
    normalized["title_en"] = clean_text(normalized.get("title_en", ""))
    normalized["title_zh"] = clean_text(normalized.get("title_zh", ""))
    normalized["description_en"] = clean_text(normalized.get("description_en", ""))
    normalized["description_zh"] = clean_text(normalized.get("description_zh", ""))
    normalized["keywords_en"] = normalize_keywords(
        normalized.get("keywords_en", []), limit=0, lowercase=True
    )
    normalized["keywords_zh"] = normalize_keywords(
        normalized.get("keywords_zh", []), limit=0
    )
    normalized["core_keywords_zh"] = normalize_keywords(
        normalized.get("core_keywords_zh", []), limit=0
    )
    if not normalized["core_keywords_zh"]:
        normalized["core_keywords_zh"] = normalized["keywords_zh"][:5]

    category1 = clean_text(normalized.get("category1", ""))
    category2 = clean_text(normalized.get("category2", ""))
    normalized["category1"] = category1
    normalized["category2"] = category2
    normalized["platform_categories"] = normalize_platform_categories(
        normalized.get("platform_categories"),
        category1=category1,
        category2=category2,
    )
    normalized["location_en"] = clean_text(normalized.get("location_en", ""))
    normalized["location_zh"] = clean_text(normalized.get("location_zh", ""))
    has_location = bool(normalized["location_en"] or normalized["location_zh"])
    location_source = clean_text(normalized.get("location_source", "unknown")).lower()
    normalized["location_source"] = (
        location_source if location_source in LOCATION_SOURCES else "unknown"
    )
    location_confidence = clean_text(
        normalized.get("location_confidence", "unknown")
    ).lower()
    normalized["location_confidence"] = (
        location_confidence
        if location_confidence in LOCATION_CONFIDENCE
        else "unknown"
    )
    if not has_location:
        normalized["location_source"] = "unknown"
        normalized["location_confidence"] = "unknown"
    normalized["commercial_uses_en"] = normalize_keywords(
        normalized.get("commercial_uses_en", []), limit=0
    )

    structured_release_fields = (
        "model_release_status",
        "property_release_status",
        "logo_trademark_status",
        "copyrighted_content_status",
        "commercial_eligibility",
    )
    has_structured_release = any(field in normalized for field in structured_release_fields)
    legacy_release = clean_text(normalized.get("release_status", "unknown")).lower()
    if legacy_release not in {"clear", "required", "unknown"}:
        legacy_release = "unknown"
    if has_structured_release:
        model_release = clean_text(
            normalized.get("model_release_status", "unknown")
        ).lower()
        property_release = clean_text(
            normalized.get("property_release_status", "unknown")
        ).lower()
        logo_status = clean_text(
            normalized.get("logo_trademark_status", "unknown")
        ).lower()
        copyright_status = clean_text(
            normalized.get("copyrighted_content_status", "unknown")
        ).lower()
        eligibility = clean_text(
            normalized.get("commercial_eligibility", "review")
        ).lower()
    elif legacy_release == "clear":
        model_release = property_release = "not_required"
        logo_status = copyright_status = "none"
        eligibility = "clear"
    else:
        model_release = property_release = "unknown"
        logo_status = copyright_status = "unknown"
        eligibility = "review"

    normalized["model_release_status"] = (
        model_release if model_release in RELEASE_DOCUMENT_STATUS else "unknown"
    )
    normalized["property_release_status"] = (
        property_release if property_release in RELEASE_DOCUMENT_STATUS else "unknown"
    )
    normalized["logo_trademark_status"] = (
        logo_status if logo_status in VISUAL_IP_STATUS else "unknown"
    )
    normalized["copyrighted_content_status"] = (
        copyright_status if copyright_status in VISUAL_IP_STATUS else "unknown"
    )
    normalized["commercial_eligibility"] = (
        eligibility if eligibility in COMMERCIAL_ELIGIBILITY else "review"
    )

    release_values = {
        normalized["model_release_status"],
        normalized["property_release_status"],
    }
    ip_values = {
        normalized["logo_trademark_status"],
        normalized["copyrighted_content_status"],
    }
    if "required" in release_values or "visible" in ip_values:
        normalized["release_status"] = "required"
    elif (
        "unknown" in release_values
        or "unknown" in ip_values
        or normalized["commercial_eligibility"] != "clear"
    ):
        normalized["release_status"] = "unknown"
    else:
        normalized["release_status"] = "clear"
    normalized["release_notes"] = clean_text(normalized.get("release_notes", ""))
    return {field: normalized[field] for field in METADATA_FIELDS}


_ENGLISH_STOPWORDS = {
    "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with", "view", "scene", "image", "photo", "photography",
}


def _english_stem(token: str) -> str:
    token = token.casefold()
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _significant_english_stems(value: str) -> set[str]:
    return {
        _english_stem(token)
        for token in re.findall(r"[a-zA-Z][a-zA-Z'-]*", value)
        if token.casefold() not in _ENGLISH_STOPWORDS and len(token) > 2
    }


def _keyword_stem_spam(keywords: list[str]) -> list[str]:
    occurrences: dict[str, int] = defaultdict(int)
    for keyword in keywords:
        for stem in _significant_english_stems(keyword):
            occurrences[stem] += 1
    return sorted(stem for stem, count in occurrences.items() if count >= 5)


def _first_keywords_match_subject(result: dict) -> bool:
    subject_stems = _significant_english_stems(
        clean_text(result.get("title_en", ""))
        + " "
        + clean_text(result.get("description_en", ""))
    )
    first_stems = set()
    for keyword in result.get("keywords_en", [])[:3]:
        first_stems.update(_significant_english_stems(keyword))
    return bool(subject_stems & first_stems)


def validate_metadata(result: dict) -> list[str]:
    """Return human-readable contract violations after normalization."""
    errors = []
    for field in ("title_en", "title_zh", "description_en", "description_zh"):
        if not clean_text(result.get(field, "")):
            errors.append(f"{field} is required")
    if len(result.get("description_en", "").split()) < 5:
        errors.append("description_en must contain at least 5 words")
    for field, limit in (
        ("title_en", TITLE_EN_MAX),
        ("title_zh", TITLE_ZH_MAX),
        ("description_en", SHUTTERSTOCK_DESC_MAX),
        ("description_zh", PX500_DESC_MAX),
        ("location_en", 80),
        ("location_zh", 80),
        ("release_notes", 240),
    ):
        if len(result.get(field, "")) > limit:
            errors.append(f"{field} exceeds {limit} characters")
    if len(result.get("keywords_en", [])) < 7:
        errors.append("keywords_en must contain at least 7 unique keywords")
    if len(result.get("keywords_zh", [])) < 5:
        errors.append("keywords_zh must contain at least 5 unique keywords")
    if len(result.get("keywords_en", [])) > SHUTTERSTOCK_KW_MAX:
        errors.append(f"keywords_en exceeds {SHUTTERSTOCK_KW_MAX} keywords")
    if len(result.get("keywords_zh", [])) > PX500_KW_MAX:
        errors.append(f"keywords_zh exceeds {PX500_KW_MAX} keywords")
    if len(result.get("core_keywords_zh", [])) > 5:
        errors.append("core_keywords_zh exceeds 5 keywords")
    if len(result.get("commercial_uses_en", [])) > 5:
        errors.append("commercial_uses_en exceeds 5 values")
    if result.get("category1") not in SHUTTERSTOCK_CATEGORIES:
        errors.append("category1 is invalid")
    if result.get("category2") and result.get("category2") not in SHUTTERSTOCK_CATEGORIES:
        errors.append("category2 is invalid")
    platform_categories = result.get("platform_categories", {})
    if not isinstance(platform_categories, dict):
        errors.append("platform_categories must be an object")
    else:
        shutterstock = platform_categories.get("shutterstock", [])
        if not isinstance(shutterstock, list) or not shutterstock:
            errors.append("platform_categories.shutterstock must contain category1")
        elif any(value not in SHUTTERSTOCK_CATEGORIES for value in shutterstock):
            errors.append("platform_categories.shutterstock contains an invalid category")
        adobe = platform_categories.get("adobestock", "")
        if adobe and adobe not in ADOBE_CATEGORIES:
            errors.append("platform_categories.adobestock is invalid")
        tuchong = platform_categories.get("tuchong", [])
        if not isinstance(tuchong, list) or any(
            value not in TUCHONG_CATEGORIES for value in tuchong
        ):
            errors.append("platform_categories.tuchong contains an invalid category")
        istock = platform_categories.get("istock", "")
        if istock and istock not in ISTOCK_CATEGORIES:
            errors.append("platform_categories.istock is invalid")
    return errors


def validate_metadata_quality(result: dict) -> list[str]:
    """Return quality defects that should block persistence and upload."""
    errors = []
    description_en = clean_text(result.get("description_en", ""))
    if re.search(r"\bpresented as\b", description_en, flags=re.IGNORECASE):
        errors.append("description_en contains generic 'Presented as' filler")

    if result.get("keywords_en") and not _first_keywords_match_subject(result):
        errors.append(
            "the first three English keywords must identify a subject named in the title or description"
        )
    repeated_stems = _keyword_stem_spam(result.get("keywords_en", []))
    if repeated_stems:
        errors.append(
            "keywords_en repeats word stems across five or more keywords: "
            + ", ".join(repeated_stems)
        )

    if result.get("title_zh") and not re.search(r"[\u3400-\u9fff]", result["title_zh"]):
        errors.append("title_zh must contain Chinese text")
    if result.get("description_zh") and not re.search(
        r"[\u3400-\u9fff]", result["description_zh"]
    ):
        errors.append("description_zh must contain Chinese text")

    has_location = bool(result.get("location_en") or result.get("location_zh"))
    if has_location and result.get("location_source") == "unknown":
        errors.append("a supplied location requires a known location_source")
    if has_location and result.get("location_confidence") == "unknown":
        errors.append("a supplied location requires location_confidence")

    core = set(result.get("core_keywords_zh", []))
    if not core.issubset(set(result.get("keywords_zh", []))):
        errors.append("core_keywords_zh must be selected from keywords_zh")

    release_status = result.get("release_status")
    release_notes = clean_text(result.get("release_notes", ""))
    if release_status == "clear" and release_notes:
        errors.append("release_notes must be empty when release_status is clear")
    if release_status in {"required", "unknown"} and not release_notes:
        errors.append(
            "release_notes must explain required or unknown release status"
        )
    if result.get("commercial_eligibility") == "clear":
        unresolved_releases = {
            result.get("model_release_status"),
            result.get("property_release_status"),
        } - {"not_required", "provided"}
        unresolved_ip = {
            result.get("logo_trademark_status"),
            result.get("copyrighted_content_status"),
        } - {"none"}
        if unresolved_releases or unresolved_ip:
            errors.append(
                "commercial_eligibility cannot be clear with unresolved release or IP risk"
            )
    elif not release_notes:
        errors.append("commercial review or editorial-only metadata requires release_notes")
    return errors


def assess_metadata_quality(result: dict) -> list[str]:
    warnings = []
    if len(result.get("keywords_en", [])) < 15:
        warnings.append(
            "fewer than 15 English keywords: add more only when they remain directly relevant"
        )
    if len(result.get("keywords_zh", [])) < 8:
        warnings.append(
            "fewer than 8 Chinese keywords: add more only when they remain directly relevant"
        )
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
