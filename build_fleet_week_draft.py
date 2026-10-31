"""Format agent-authored Fleet Week visual observations into a review draft.

The TSV is the visual record. This code only adds platform fields and conservative
release triage; it does not infer visual content from filenames or neighboring frames.
"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OBSERVATIONS = ROOT / ".tmp/fleet_week_native_observations.tsv"
PREVIEWS = Path(
    "/private/var/folders/3p/00bh2_k15s952y77m7y84ft80000gn/T/"
    "stock-photo-previews-b6uojwuc/preview_manifest.json"
)
OUTPUT = ROOT / ".tmp/fleet_week_metadata_draft.json"


def ordered(items):
    return list(dict.fromkeys(item for item in items if item))


def indices(spec):
    result = []
    for token in spec.split(","):
        if "-" in token:
            start, end = map(int, token.split("-", 1))
            result.extend(range(start, end + 1))
        else:
            result.append(int(token))
    return result


def shorten(text, limit):
    if len(text) <= limit:
        return text
    result = text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    for ending in (" with", " above", " below", " and", " the", " a", " of", " against"):
        if result.endswith(ending):
            result = result[: -len(ending)]
    return result


def main():
    preview_items = json.loads(PREVIEWS.read_text())["items"]
    observations = {}
    groups = {}
    for line in OBSERVATIONS.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        spec, en, zh, flag_text = line.split("|", 3)
        sequence = indices(spec)
        for rank, index in enumerate(sequence, 1):
            if index in observations:
                raise ValueError(f"duplicate observation {index}")
            observations[index] = (en, zh, set(flag_text), spec)
            groups[index] = (f"fleet-{sequence[0]:03d}" if len(sequence) > 1 else "", rank if len(sequence) > 1 else 0)
    expected = set(range(1, len(preview_items) + 1))
    if set(observations) != expected:
        raise ValueError(f"inventory mismatch: missing={sorted(expected-set(observations))}, extra={sorted(set(observations)-expected)}")

    output = []
    for index, item in enumerate(preview_items, 1):
        image = item["source"]
        en, zh, flags, group_spec = observations[index]
        lower = en.lower()
        if "helicopter" in lower:
            primary_en, primary_zh = "helicopter", "直升机"
            topics_en, topics_zh = ["military aviation", "aircraft display"], ["军事航空", "飞机展示"]
        elif "streetcar" in lower:
            primary_en, primary_zh = "streetcar", "有轨电车"
            topics_en, topics_zh = ["historic transit", "urban transportation"], ["复古交通", "城市交通"]
        elif "protest sign" in lower:
            primary_en, primary_zh = "protest sign", "抗议标语"
            topics_en, topics_zh = ["political protest", "street scene"], ["政治抗议", "街头场景"]
        elif "sailboat" in lower and "jet" not in lower and "airplane" not in lower:
            primary_en, primary_zh = "sailboat", "帆船"
            topics_en, topics_zh = ["sailing", "bay water"], ["帆船运动", "海湾"]
        elif "passenger jet" in lower or "commercial passenger jet" in lower:
            primary_en, primary_zh = "passenger jet", "民航客机"
            topics_en, topics_zh = ["commercial aviation", "aircraft"], ["民用航空", "飞机"]
        elif "jet" in lower or "aircraft" in lower or "formation" in lower:
            primary_en, primary_zh = "jet", "喷气机"
            topics_en, topics_zh = ["aviation", "air show", "flight formation" if "four" in lower or "five" in lower or "six" in lower else "flight demonstration"], ["航空", "飞行表演", "飞行编队" if "four" in lower or "five" in lower or "six" in lower else "飞行展示"]
        elif "airplane" in lower:
            primary_en, primary_zh = "aerobatic airplane", "特技飞机"
            topics_en, topics_zh = ["aviation", "air show", "aerobatics"], ["航空", "飞行表演", "特技飞行"]
        elif "parade" in lower or "sports car" in lower:
            primary_en, primary_zh = "parade", "游行"
            topics_en, topics_zh = ["street parade", "spectators", "sports cars"], ["街头游行", "观众", "跑车"]
        elif "naval gun" in lower or "mounted gun" in lower:
            primary_en, primary_zh = "naval gun", "舰载机枪"
            topics_en, topics_zh = ["naval ship", "military equipment"], ["军舰", "军事装备"]
        elif "flags" in lower or "signal flags" in lower:
            primary_en, primary_zh = "signal flags", "信号旗"
            topics_en, topics_zh = ["naval ship", "maritime flags"], ["军舰", "海事旗帜"]
        elif "deck" in lower or "shipboard" in lower:
            primary_en, primary_zh = "ship deck", "舰船甲板"
            topics_en, topics_zh = ["naval ship", "maritime equipment"], ["军舰", "船舶设备"]
        elif "smoke" in lower and "deck" not in lower and "ship" not in lower:
            primary_en, primary_zh = "smoke trails", "烟迹"
            topics_en, topics_zh = ["aerial pattern", "blue sky", "air show"], ["空中图案", "蓝天", "飞行表演"]
        else:
            primary_en, primary_zh = "naval equipment", "舰船设备"
            topics_en, topics_zh = ["military display", "ship deck"], ["军事展示", "舰船甲板"]

        if index == 17:
            en = "A person wearing a US flag patch stands beside a protest sign reading FUCK TRUMP on a San Francisco street"
            zh = "旧金山街头一名佩戴美国国旗臂章的人站在写有反特朗普粗口的抗议牌旁"
        if primary_en == "jet" and re.search(r"\bjets\b", en, re.I) and not re.search(r"\bjet\b", en, re.I):
            primary_en = "jets"
        if primary_en == "aerobatic airplane" and "airplanes" in en.lower() and "airplane " not in en.lower():
            primary_en = "aerobatic airplanes"
        if primary_en.lower() not in en.lower():
            for candidate in ("deck hatches", "mounted gun", "signal flags", "Bay Bridge", "helmets", "shipboard equipment", "sports cars", "sports car", "protest sign", "airplanes", "airplane", "aircraft", "aerobatic formation", "smoke trails", "smoke"):
                if candidate.lower() in en.lower():
                    primary_en = candidate
                    break
        if primary_zh not in zh:
            for candidate in ("金属舱盖", "舰载机枪", "信号旗", "海湾大桥", "头盔", "舰载设备", "跑车", "抗议牌", "特技飞行编队", "飞机", "白烟", "烟迹", "客机"):
                if candidate in zh:
                    primary_zh = candidate
                    break
        burst_group, burst_rank = groups[index]
        mentions_golden = "Golden Gate Bridge" in en
        mentions_bay_bridge = "Bay Bridge" in en
        topics_en += ["Golden Gate Bridge"] if mentions_golden else []
        topics_zh += ["金门大桥"] if mentions_golden else []
        topics_en += ["San Francisco-Oakland Bay Bridge"] if mentions_bay_bridge else []
        topics_zh += ["海湾大桥"] if mentions_bay_bridge else []
        if "smoke" in lower:
            topics_en += ["smoke trails"]
            topics_zh += ["烟迹"]
        if "United Airlines" in en:
            topics_en += ["United Airlines"]
            topics_zh += ["美联航"]
        if "Blue and yellow" in en or "blue and yellow" in en:
            topics_en += ["blue and yellow aircraft"]
            topics_zh += ["蓝黄涂装飞机"]
        if "sailboat" in lower:
            topics_en += ["sailboats"]
            topics_zh += ["帆船"]
        if "w" in flags:
            topics_en += ["San Francisco Bay"]
            topics_zh += ["旧金山湾"]
        keywords_en = ordered([primary_en, *topics_en, "San Francisco Fleet Week", "San Francisco", "California", "United States"])
        keywords_zh = ordered([primary_zh, *topics_zh, "旧金山舰队周", "旧金山", "加利福尼亚", "美国"])
        people = "p" in flags
        recognized = "r" in flags
        logo = "l" in flags
        text = "t" in flags
        editorial_only = logo or recognized or text or index <= 16
        required_en, required_zh = [], []
        if index == 17:
            required_en, required_zh = ["FUCK TRUMP"], ["反特朗普"]
        elif mentions_golden:
            required_en, required_zh = ["Golden Gate Bridge"], ["金门大桥"]
        elif mentions_bay_bridge:
            required_en, required_zh = ["Bay Bridge"], ["海湾大桥"]
        if "United Airlines" in en:
            required_en.append("United Airlines")
            required_zh.append("美联航")
        facts = {
            "schema_version": 1,
            "primary_subjects_en": [primary_en],
            "primary_subjects_zh": [primary_zh],
            "required_terms_en": required_en,
            "required_terms_zh": required_zh,
            "forbidden_claims_en": [],
            "forbidden_claims_zh": [],
            "water_visible": "yes" if "w" in flags else ("unknown" if "coastal" in lower else "no"),
            "trail_visible": "unknown" if "trail" in lower else "no",
            "people_visible": "yes" if people else "no",
            "recognizable_people_visible": "yes" if recognized else ("unknown" if people else "no"),
            "structures_visible": "yes" if "s" in flags else "no",
            "vehicles_visible": "yes" if "v" in flags else "no",
            "animals_visible": "yes" if "a" in flags else "no",
            "reflection_visible": "yes" if index == 21 else "no",
            "text_visible": "yes" if text else "no",
            "logo_or_trademark_visible": "yes" if logo else "no",
            "copyrighted_content_visible": "yes" if "c" in flags else "no",
            "private_property_visible": "yes" if "q" in flags else ("unknown" if "s" in flags else "no"),
            "copy_space_visible": "yes" if "sky" in lower or "blue" in lower else "no",
            "scene_signature": burst_group or f"fleet-{index:03d}-{re.sub('[^a-z0-9]+', '-', primary_en)}",
            "burst_group_id": burst_group,
            "burst_rank": burst_rank,
            "technical_quality": "pass",
            "commercial_potential": "medium",
            "commercial_strengths_en": ["specific aviation, maritime, or urban subject", "documentary San Francisco event context"],
            "selection_status": "selected",
            "uncertain_details": ["Visible markings or releases require contributor review"] if editorial_only else [],
        }
        title_en = shorten(en, 69)
        if index == 115:
            title_en = "Military jet and small bird above Fleet Week spectators"
        title_zh = zh[:49].rstrip("，、")
        description_en = en.rstrip(".") + " during San Francisco Fleet Week in San Francisco, California."
        description_zh = zh[:48].rstrip("，、")
        if "airplane" in lower or "jet" in lower or "aircraft" in lower:
            cat1, cat2, adobe, tuchong, istock = "Transportation", "Sports/Recreation", "Transport", ["运动健康"], "Transport"
        elif "parade" in lower or index == 17 or index == 21:
            cat1, cat2, adobe, tuchong, istock = "People", "Holidays", "People", ["生活方式"], "People"
        elif "streetcar" in lower:
            cat1, cat2, adobe, tuchong, istock = "Transportation", "Vintage", "Transport", ["城市风光"], "Transport"
        elif "sailboat" in lower:
            cat1, cat2, adobe, tuchong, istock = "Transportation", "Sports/Recreation", "Hobbies and Leisure", ["运动健康"], "Transport"
        else:
            cat1, cat2, adobe, tuchong, istock = "Transportation", "Industrial", "Transport", ["城市风光"], "Transport"
        caption = "San Francisco, California - 11 October 2026: " + en.rstrip(".") + "." if editorial_only else ""
        release_risk = people or logo or text or "s" in flags or editorial_only
        eligibility = "editorial_only" if editorial_only else ("review" if release_risk else "clear")
        metadata = {
            "title_en": title_en,
            "title_zh": title_zh,
            "description_en": description_en,
            "description_zh": description_zh,
            "keywords_en": keywords_en,
            "keywords_zh": keywords_zh,
            "category1": cat1,
            "category2": cat2,
            "platform_categories": {"shutterstock": [cat1, cat2], "adobestock": adobe, "tuchong": tuchong, "istock": istock},
            "location_en": "San Francisco, California",
            "location_zh": "加利福尼亚州旧金山",
            "location_source": "context",
            "location_confidence": "medium",
            "core_keywords_zh": keywords_zh[:5],
            "commercial_uses_en": ["aviation event coverage", "San Francisco travel editorial"] if "v" in flags else ["San Francisco maritime coverage", "urban travel editorial"],
            "editorial_caption_en": caption,
            "editorial_date": "2026-10-11" if editorial_only else "",
            "editorial_date_source": "context" if editorial_only else "unknown",
            "editorial_location_en": "San Francisco, California" if editorial_only else "",
            "model_release_status": "unknown" if people else "not_required",
            "property_release_status": "unknown" if "q" in flags or "s" in flags else "not_required",
            "logo_trademark_status": "visible" if logo else "none",
            "copyrighted_content_status": "visible" if "c" in flags else "none",
            "commercial_eligibility": eligibility,
            "release_status": "unknown" if release_risk else "clear",
            "release_notes": "Military display, people, markings, or property require contributor review." if release_risk else "",
        }
        output.append({"image": image, "visual_facts": facts, "metadata": metadata})
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(output)} Fleet Week draft records: {OUTPUT}")


if __name__ == "__main__":
    main()
