"""Machine-readable visual evidence and metadata-grounding checks."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from metadata_core import clean_text

FACTS_SCHEMA_VERSION = 1
OBSERVATION_STATES = {"yes", "no", "unknown"}
SELECTION_STATES = {"selected", "review", "reject"}
TECHNICAL_QUALITY_STATES = {"pass", "review", "reject"}
COMMERCIAL_POTENTIAL_STATES = {"high", "medium", "low"}
MAX_SELECTED_PER_BURST = 3

VISUAL_FACT_FIELDS = (
    "schema_version",
    "primary_subjects_en",
    "primary_subjects_zh",
    "required_terms_en",
    "required_terms_zh",
    "forbidden_claims_en",
    "forbidden_claims_zh",
    "water_visible",
    "trail_visible",
    "people_visible",
    "recognizable_people_visible",
    "structures_visible",
    "vehicles_visible",
    "animals_visible",
    "reflection_visible",
    "text_visible",
    "logo_or_trademark_visible",
    "copyrighted_content_visible",
    "private_property_visible",
    "copy_space_visible",
    "scene_signature",
    "burst_group_id",
    "burst_rank",
    "technical_quality",
    "commercial_potential",
    "commercial_strengths_en",
    "selection_status",
    "uncertain_details",
)

_LIST_FIELDS = {
    "primary_subjects_en",
    "primary_subjects_zh",
    "required_terms_en",
    "required_terms_zh",
    "forbidden_claims_en",
    "forbidden_claims_zh",
    "uncertain_details",
    "commercial_strengths_en",
}
_OBSERVATION_FIELDS = {
    "water_visible",
    "trail_visible",
    "people_visible",
    "recognizable_people_visible",
    "structures_visible",
    "vehicles_visible",
    "animals_visible",
    "reflection_visible",
    "text_visible",
    "logo_or_trademark_visible",
    "copyrighted_content_visible",
    "private_property_visible",
    "copy_space_visible",
}

_STATE_CLAIMS = {
    "water_visible": {
        "en": (
            "lake", "river", "stream", "creek", "pond", "waterfall",
            "ocean", "sea", "shoreline", "waterfront", "water reflection",
        ),
        "zh": ("湖", "河流", "溪流", "小溪", "池塘", "瀑布", "海洋", "海岸", "水面", "水中倒影"),
    },
    "trail_visible": {
        "en": ("trail", "footpath", "hiking path", "hiking route", "walking path"),
        "zh": ("步道", "小径", "徒步道", "山径", "人行道"),
    },
    "people_visible": {
        "en": ("person", "people", "man", "woman", "hiker", "tourist", "visitor", "couple", "family", "crowd"),
        "zh": ("人物", "人群", "男人", "女人", "游客", "徒步者", "访客", "情侣", "家庭"),
    },
    "structures_visible": {
        "en": ("chapel", "church", "cabin", "barn", "building", "house", "bridge", "visitor center"),
        "zh": ("教堂", "礼拜堂", "木屋", "小屋", "谷仓", "建筑", "房屋", "桥梁", "游客中心"),
    },
    "vehicles_visible": {
        "en": ("aircraft", "airplane", "plane", "helicopter", "car", "truck", "vehicle", "motorcycle", "rv", "camper", "boat"),
        "zh": ("飞机", "直升机", "汽车", "卡车", "车辆", "摩托车", "房车", "露营车", "船只"),
    },
    "animals_visible": {
        "en": ("animal", "wildlife", "fox", "bear", "bison", "elk", "moose", "deer", "bird"),
        "zh": ("动物", "野生动物", "狐狸", "熊", "野牛", "麋鹿", "驼鹿", "鹿", "鸟"),
    },
    "reflection_visible": {
        "en": ("reflection", "reflected"),
        "zh": ("倒影", "反射", "映照"),
    },
    "copy_space_visible": {
        "en": ("copy space", "text space", "negative space"),
        "zh": ("留白", "文案空间", "文字空间"),
    },
}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        text = clean_text(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def normalize_visual_facts(value: object) -> dict:
    """Return a complete, canonical visual-facts object."""
    raw = value if isinstance(value, dict) else {}
    normalized = {"schema_version": raw.get("schema_version", 0)}
    for field in _LIST_FIELDS:
        normalized[field] = _string_list(raw.get(field, []))
    for field in _OBSERVATION_FIELDS:
        state = clean_text(raw.get(field, "unknown")).lower()
        normalized[field] = state if state in OBSERVATION_STATES else "unknown"
    normalized["scene_signature"] = clean_text(raw.get("scene_signature", ""))
    normalized["burst_group_id"] = clean_text(raw.get("burst_group_id", ""))
    burst_rank = raw.get("burst_rank", 0)
    normalized["burst_rank"] = (
        burst_rank
        if isinstance(burst_rank, int) and not isinstance(burst_rank, bool)
        else -1
    )
    technical_quality = clean_text(
        raw.get("technical_quality", "review")
    ).lower()
    normalized["technical_quality"] = (
        technical_quality
        if technical_quality in TECHNICAL_QUALITY_STATES
        else "review"
    )
    commercial_potential = clean_text(
        raw.get("commercial_potential", "")
    ).lower()
    normalized["commercial_potential"] = (
        commercial_potential
        if commercial_potential in COMMERCIAL_POTENTIAL_STATES
        else ""
    )
    selection = clean_text(raw.get("selection_status", "review")).lower()
    normalized["selection_status"] = (
        selection if selection in SELECTION_STATES else "review"
    )
    return {field: normalized[field] for field in VISUAL_FACT_FIELDS}


def validate_visual_facts(value: object) -> list[str]:
    """Validate that a reviewer completed the full visual-facts checklist."""
    if not isinstance(value, dict):
        return ["visual_facts must be an object"]
    errors = []
    missing = [field for field in VISUAL_FACT_FIELDS if field not in value]
    if missing:
        errors.append("visual_facts is missing fields: " + ", ".join(missing))
    unexpected = sorted(set(value) - set(VISUAL_FACT_FIELDS))
    if unexpected:
        errors.append(
            "visual_facts contains unsupported fields: " + ", ".join(unexpected)
        )
    facts = normalize_visual_facts(value)
    if type(value.get("schema_version")) is not int or facts[
        "schema_version"
    ] != FACTS_SCHEMA_VERSION:
        errors.append(
            f"visual_facts.schema_version must be {FACTS_SCHEMA_VERSION}"
        )
    for field in _LIST_FIELDS:
        if field in value and not isinstance(value[field], list):
            errors.append(f"visual_facts.{field} must be an array")
    for field in _OBSERVATION_FIELDS:
        if field in value and clean_text(value[field]).lower() not in OBSERVATION_STATES:
            errors.append(
                f"visual_facts.{field} must be yes, no, or unknown"
            )
    if not facts["primary_subjects_en"]:
        errors.append("visual_facts.primary_subjects_en must identify the main subject")
    if not facts["primary_subjects_zh"]:
        errors.append("visual_facts.primary_subjects_zh must identify the main subject")
    if not facts["scene_signature"]:
        errors.append("visual_facts.scene_signature is required")
    if facts["technical_quality"] != "pass":
        errors.append(
            "visual_facts.technical_quality must be pass before persistence"
        )
    if facts["commercial_potential"] not in COMMERCIAL_POTENTIAL_STATES:
        errors.append(
            "visual_facts.commercial_potential must be high, medium, or low"
        )
    if not facts["commercial_strengths_en"]:
        errors.append(
            "visual_facts.commercial_strengths_en must explain buyer value"
        )
    if facts["burst_group_id"] and facts["burst_rank"] < 1:
        errors.append("visual_facts.burst_rank must be positive inside a burst group")
    if not facts["burst_group_id"] and facts["burst_rank"] != 0:
        errors.append("visual_facts.burst_rank must be 0 outside a burst group")
    if facts["selection_status"] != "selected":
        errors.append(
            "visual_facts.selection_status must be selected before metadata persistence"
        )
    if (
        facts["people_visible"] == "no"
        and facts["recognizable_people_visible"] != "no"
    ):
        errors.append(
            "recognizable_people_visible must be no when people_visible is no"
        )
    return errors


def visual_facts_sha256(value: object) -> str:
    canonical = json.dumps(
        normalize_visual_facts(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _metadata_text(metadata: dict, language: str, *, keywords: bool = True) -> str:
    fields = (
        ("title_en", "description_en", "keywords_en")
        if language == "en"
        else ("title_zh", "description_zh", "keywords_zh")
    )
    if not keywords:
        fields = fields[:2]
    values = []
    for field in fields:
        value = metadata.get(field, "")
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        else:
            values.append(str(value))
    return clean_text(" ".join(values)).casefold()


def _contains_term(text: str, term: str, language: str) -> bool:
    needle = clean_text(term).casefold()
    if not needle:
        return False
    if language == "zh":
        return needle in text
    return bool(
        re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", text)
    )


def _strip_negative_people_phrases(text: str, language: str) -> str:
    if language == "en":
        return re.sub(
            r"\b(?:no|without)\s+(?:recognizable\s+)?(?:people|persons?)\b",
            "",
            text,
        )
    return re.sub(r"(?:无人|没有人物|没有人|无可识别人物)", "", text)


def validate_metadata_against_visual_facts(
    metadata: dict, value: object
) -> list[str]:
    """Detect deterministic omissions and claims contradicted by visual facts."""
    facts = normalize_visual_facts(value)
    issues = []
    texts = {language: _metadata_text(metadata, language) for language in ("en", "zh")}
    title_desc = {
        language: _metadata_text(metadata, language, keywords=False)
        for language in ("en", "zh")
    }

    for language in ("en", "zh"):
        primary = facts[f"primary_subjects_{language}"]
        keyword_values = metadata.get(f"keywords_{language}", [])[:10]
        keyword_text = clean_text(" ".join(str(v) for v in keyword_values)).casefold()
        for term in primary:
            if not _contains_term(title_desc[language], term, language):
                issues.append(
                    f"primary visual subject is missing from {language} title/description: {term}"
                )
            if not _contains_term(keyword_text, term, language):
                issues.append(
                    f"primary visual subject is missing from first 10 {language} keywords: {term}"
                )
        for term in facts[f"required_terms_{language}"]:
            if not _contains_term(texts[language], term, language):
                issues.append(f"required visible {language} term is missing: {term}")
        for term in facts[f"forbidden_claims_{language}"]:
            if _contains_term(texts[language], term, language):
                issues.append(f"metadata contains visually unsupported {language} claim: {term}")

    for state_field, claims in _STATE_CLAIMS.items():
        if facts[state_field] != "no":
            continue
        for language in ("en", "zh"):
            text = texts[language]
            if state_field == "people_visible":
                text = _strip_negative_people_phrases(text, language)
            matched = [
                term
                for term in claims[language]
                if _contains_term(text, term, language)
            ]
            if matched:
                issues.append(
                    f"{state_field}=no contradicts {language} metadata claim: {matched[0]}"
                )

    no_people_text = texts["en"] + " " + texts["zh"]
    if facts["people_visible"] == "yes" and (
        re.search(r"\bno\s+(?:recognizable\s+)?people\b", no_people_text)
        or any(term in no_people_text for term in ("无人", "没有人物", "没有人"))
    ):
        issues.append("people_visible=yes contradicts a no-people metadata claim")
    if (
        facts["recognizable_people_visible"] == "yes"
        and metadata.get("model_release_status") == "not_required"
    ):
        issues.append("recognizable people require model release review")
    if (
        facts["recognizable_people_visible"] == "unknown"
        and metadata.get("model_release_status") == "not_required"
    ):
        issues.append(
            "unknown person recognizability cannot use model_release_status=not_required"
        )
    if (
        facts["private_property_visible"] == "yes"
        and metadata.get("property_release_status") == "not_required"
    ):
        issues.append("visible private property requires property release review")
    if (
        facts["private_property_visible"] == "unknown"
        and metadata.get("property_release_status") == "not_required"
    ):
        issues.append(
            "unknown private-property evidence cannot use property_release_status=not_required"
        )
    if (
        facts["logo_or_trademark_visible"] == "yes"
        and metadata.get("logo_trademark_status") == "none"
    ):
        issues.append(
            "visible logo/trademark contradicts logo_trademark_status=none"
        )
    if (
        facts["logo_or_trademark_visible"] == "unknown"
        and metadata.get("logo_trademark_status") == "none"
    ):
        issues.append(
            "unknown logo/trademark evidence cannot use logo_trademark_status=none"
        )
    if (
        facts["copyrighted_content_visible"] == "yes"
        and metadata.get("copyrighted_content_status") == "none"
    ):
        issues.append(
            "visible copyrighted content contradicts copyrighted_content_status=none"
        )
    if (
        facts["copyrighted_content_visible"] == "unknown"
        and metadata.get("copyrighted_content_status") == "none"
    ):
        issues.append(
            "unknown copyrighted-content evidence cannot use copyrighted_content_status=none"
        )
    return issues


def validate_visual_fact_batch(
    items: list[dict],
    *,
    require_complete_ranking: bool = True,
    max_selected_per_burst: int | None = MAX_SELECTED_PER_BURST,
) -> dict[int, list[str]]:
    """Validate burst grouping, ranking, and an optional curation limit."""
    issues: dict[int, list[str]] = defaultdict(list)
    groups: dict[str, list[int]] = defaultdict(list)
    facts_by_index = {}
    for index, item in enumerate(items, 1):
        facts = normalize_visual_facts(item.get("visual_facts"))
        facts_by_index[index] = facts
        if facts["burst_group_id"] and facts["selection_status"] == "selected":
            groups[facts["burst_group_id"]].append(index)
    for group, indexes in groups.items():
        if (
            max_selected_per_burst is not None
            and len(indexes) > max_selected_per_burst
        ):
            for index in indexes:
                issues[index].append(
                    f"burst group {group!r} has {len(indexes)} selected frames; "
                    f"maximum is {max_selected_per_burst}"
                )
        signatures = {facts_by_index[index]["scene_signature"] for index in indexes}
        if len(signatures) > 1:
            for index in indexes:
                issues[index].append(
                    f"burst group {group!r} contains conflicting scene signatures"
                )
        ranks = [facts_by_index[index]["burst_rank"] for index in indexes]
        expected_ranks = list(range(1, len(indexes) + 1))
        ranks_valid = (
            sorted(ranks) == expected_ranks
            if require_complete_ranking
            else len(ranks) == len(set(ranks)) and all(rank > 0 for rank in ranks)
        )
        if not ranks_valid:
            for index in indexes:
                requirement = (
                    f"unique consecutive ranks 1-{len(indexes)}"
                    if require_complete_ranking
                    else "unique positive ranks"
                )
                issues[index].append(
                    f"burst group {group!r} must use {requirement}"
                )
    return dict(issues)


def repetition_allowed_for_curated_burst(
    sources: list[str], visual_facts_by_source: dict[str, dict]
) -> bool:
    """Allow exact copy only for a small, explicitly identified same-scene burst."""
    if not 1 < len(sources) <= MAX_SELECTED_PER_BURST:
        return False
    facts = [normalize_visual_facts(visual_facts_by_source.get(source)) for source in sources]
    groups = {item["burst_group_id"] for item in facts}
    signatures = {item["scene_signature"] for item in facts}
    return (
        len(groups) == 1
        and "" not in groups
        and len(signatures) == 1
        and "" not in signatures
        and all(item["selection_status"] == "selected" for item in facts)
    )


def repetition_allowed_for_full_coverage_burst(
    sources: list[str], visual_facts_by_source: dict[str, dict]
) -> bool:
    """Allow truthful exact copy across a fully ranked same-scene burst."""
    if len(sources) < 2:
        return False
    facts = [normalize_visual_facts(visual_facts_by_source.get(source)) for source in sources]
    groups = {item["burst_group_id"] for item in facts}
    signatures = {item["scene_signature"] for item in facts}
    ranks = [item["burst_rank"] for item in facts]
    return (
        len(groups) == 1
        and "" not in groups
        and len(signatures) == 1
        and "" not in signatures
        and len(ranks) == len(set(ranks))
        and all(rank > 0 for rank in ranks)
        and all(item["selection_status"] == "selected" for item in facts)
    )
