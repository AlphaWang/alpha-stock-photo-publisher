"""Format agent-authored Bean Hollow observations into a reviewable draft.

The observations are visual judgments, not automated image classifications.  This
script only adds fixed platform fields and wording for the independent review.
"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OBSERVATIONS = ROOT / ".tmp/bean_hollow_native_observations.tsv"
PREVIEWS = Path(
    "/private/var/folders/3p/00bh2_k15s952y77m7y84ft80000gn/T/"
    "stock-photo-previews-ybsie5wb/preview_manifest.json"
)
OUTPUT = ROOT / ".tmp/bean_hollow_metadata_draft.json"


def ordered(values):
    return list(dict.fromkeys(value for value in values if value))


def short_words(value, limit):
    text = value if len(value) <= limit else value[:limit].rsplit(" ", 1)[0]
    if len(value) > limit:
        if "," in text and len(text.split(",", 1)[0]) >= 25:
            text = text.split(",", 1)[0]
        else:
            for joiner in [" with ", " above ", " below ", " beside ", " against ", " as ", " and ", " beyond ", " beneath "]:
                point = text.rfind(joiner)
                if point >= 22 and point > len(text) - 35:
                    text = text[:point]
                    break
    weak_endings = {"a", "an", "the", "with", "by", "in", "of", "beside", "below", "beyond", "above", "and", "as", "on", "near", "enclosed", "beneath", "toward", "under", "deep", "dark", "pale", "golden", "blue", "white", "orange", "small", "narrow", "thin", "broad", "distant", "low", "clear", "surrounded", "leading", "sunlit", "framed", "visible", "showing", "extending", "flowing", "rising", "touching", "rolling", "breaking", "coastal"}
    words = text.rstrip(" ,;:").split()
    while words and words[-1].lower() in weak_endings:
        words.pop()
    return " ".join(words).rstrip(" ,;:")


def mentions(text, words):
    return any(re.search(r"\b" + re.escape(word) + r"\b", text) for word in words)


def main():
    rows = {}
    for line in OBSERVATIONS.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name, en, zh = line.split("|", 2)
        rows[name] = (en.strip(), zh.strip())
    preview_items = json.loads(PREVIEWS.read_text())["items"]
    if set(rows) != {Path(item["source"]).name for item in preview_items}:
        raise ValueError("observation inventory does not match preview inventory")

    groups = [
        "DSC04047 DSC04050 DSC04051",
        "DSC04060 DSC04061 DSC04066",
        "DSC04067 DSC04068",
        "DSC04073 DSC04074 DSC04075",
        "DSC04083 DSC04086 DSC04087",
        "DSC04090 DSC04091",
        "DSC04092 DSC04095 DSC04096 DSC04097",
        "DSC04104 DSC04105",
        "DSC04108 DSC04110 DSC04111",
        "DSC04124 DSC04125 DSC04128 DSC04129 DSC04131 DSC04132",
        "DSC04134 DSC04135 DSC04136",
        "DSC04138 DSC04139 DSC04140",
        "DSC04143 DSC04144",
        "DSC04148 DSC04149 DSC04150",
        "DSC04151 DSC04152 DSC04159",
        "DSC04153 DSC04154 DSC04156 DSC04157",
        "DSC04177 DSC04178",
        "DSC04179 DSC04180 DSC04181 DSC04183 DSC04185",
        "DSC04188 DSC04189",
        "DSC04190 DSC04191 DSC04193 DSC04194 DSC04196 DSC04199",
        "DSC04200 DSC04201",
        "DSC04204 DSC04205 DSC04206",
        "DSC04207 DSC04208 DSC04209",
        "DSC04210 DSC04211 DSC04212",
    ]
    grouped = {}
    for group in groups:
        names = group.split()
        group_id = "bean-" + names[0].lower()
        for rank, name in enumerate(names, 1):
            grouped[name + ".jpg"] = (group_id, rank)

    output = []
    for item in preview_items:
        image = item["source"]
        name = Path(image).name
        en, zh = rows[name]
        en_lower = en.lower()
        if "marine mammal carcass" in en_lower:
            primary_en, primary_zh = "marine mammal carcass", "海洋哺乳动物遗体"
            topic_en = ["marine mammal carcass", "wildlife", "rocky shore"]
            topic_zh = ["海洋哺乳动物遗体", "野生动物", "岩岸"]
            cat1, cat2, adobe, istock = "Animals/Wildlife", "Nature", "Animals", "Animals/Wildlife"
        elif "pinniped" in en_lower:
            primary_en, primary_zh = "pinniped", "鳍足类动物"
            topic_en = ["pinniped", "marine mammal", "sandy beach" if mentions(en_lower, ["beach", "sand"]) else "rocky shore"]
            topic_zh = ["鳍足类动物", "海洋哺乳动物", "沙滩" if mentions(en_lower, ["beach", "sand"]) else "礁石"]
            cat1, cat2, adobe, istock = "Animals/Wildlife", "Nature", "Animals", "Animals/Wildlife"
        elif "sandstone" in en_lower:
            primary_en, primary_zh = "sandstone", "砂岩"
            topic_en = ["sandstone", "rock formation", "erosion"]
            topic_zh = ["砂岩", "岩石地貌", "侵蚀"]
            cat1, cat2, adobe, istock = "Nature", "Backgrounds/Textures", "Landscapes", "Nature"
        elif "boulder" in en_lower:
            primary_en, primary_zh = "boulder", "巨石"
            topic_en = ["boulder", "rocky coast", "ocean surf"]
            topic_zh = ["巨石", "岩石海岸", "海浪"]
            cat1, cat2, adobe, istock = "Nature", "Parks/Outdoor", "Landscapes", "Nature"
        elif "bluff" in en_lower:
            primary_en, primary_zh = "bluff", "崖壁"
            topic_en = ["coastal bluff", "rocky coast", "shoreline"]
            topic_zh = ["海岸崖壁", "岩石海岸", "海岸线"]
            cat1, cat2, adobe, istock = "Nature", "Parks/Outdoor", "Landscapes", "Nature"
        elif "sun" in en_lower or "dusk" in en_lower or "twilight" in en_lower:
            primary_en, primary_zh = "rocky coast", "岩岸"
            topic_en = ["rocky coast", "ocean", "sunset"]
            topic_zh = ["岩岸", "海洋", "日落"]
            cat1, cat2, adobe, istock = "Nature", "Parks/Outdoor", "Landscapes", "Nature"
        else:
            primary_en, primary_zh = "rock", "岩石"
            topic_en = ["rocky coast", "ocean surf", "shoreline"]
            topic_zh = ["岩石", "海浪", "海岸线"]
            cat1, cat2, adobe, istock = "Nature", "Parks/Outdoor", "Landscapes", "Nature"

        water = mentions(en_lower, ["ocean", "sea", "seascape", "seawater", "water", "wave", "waves", "surf", "tide pool", "cove", "bay", "spray", "splash", "splashes", "shoreline"])
        # A place may be on the coast even when the frame itself shows no water.
        # Keep that contextual place in location fields, not scene keywords.
        display_en = en if water else en.replace("coastal ", "").replace("shoreline ", "")
        display_zh = zh if water else zh.replace("海岸", "").replace("海洋", "")
        display_en_lower = display_en.lower()
        if not re.search(r"\b" + re.escape(primary_en) + r"\b", display_en_lower):
            primary_en = next((w for w in ["rocky shelves", "rocky shore", "pinnipeds", "rocks", "rock", "waves", "surf", "ocean", "sandstone", "shore"] if re.search(r"\b" + re.escape(w) + r"\b", display_en_lower)), display_en_lower.split()[0])
        if primary_zh not in display_zh:
            primary_zh = next((w for w in ["砂岩", "鳍足类动物", "海洋哺乳动物遗体", "海浪", "浪花", "岩石", "岩板", "裂岩", "礁石", "巨石", "海面", "海水", "崖壁", "沙滩", "潮池", "岩岸"] if w in display_zh), display_zh[:2])
        animal = "marine mammal" in en_lower or "pinniped" in en_lower or "bird" in en_lower
        wide = any(word in en_lower for word in ["beach", "bluff", "headland", "cove", "bay", "hillside"]) or name in {"DSC04058.jpg", "DSC04070.jpg", "DSC04074.jpg", "DSC04075.jpg"}
        people = "unknown" if wide else "no"
        structures = "unknown" if wide else "no"
        private = "unknown" if wide else "no"
        group_id, rank = grouped.get(name, ("", 0))
        facts = {
            "schema_version": 1,
            "primary_subjects_en": [primary_en],
            "primary_subjects_zh": [primary_zh],
            "required_terms_en": ["US flag"] if name in {"DSC04134.jpg", "DSC04135.jpg", "DSC04136.jpg"} else [],
            "required_terms_zh": ["美国国旗"] if name in {"DSC04134.jpg", "DSC04135.jpg", "DSC04136.jpg"} else [],
            "forbidden_claims_en": ["seal", "sea lion", "alive"] if "carcass" in en_lower else [],
            "forbidden_claims_zh": ["海豹", "海狮", "活着"] if "carcass" in en_lower else [],
            "water_visible": "yes" if water else "no",
            "trail_visible": "no",
            "people_visible": people,
            "recognizable_people_visible": "no" if people == "no" else "unknown",
            "structures_visible": structures,
            "vehicles_visible": "no",
            "animals_visible": "yes" if animal else ("unknown" if wide else "no"),
            "reflection_visible": "yes" if "reflected" in en_lower else "no",
            "text_visible": "no",
            "logo_or_trademark_visible": "no",
            "copyrighted_content_visible": "no",
            "private_property_visible": private,
            "copy_space_visible": "yes" if "sky" in en_lower or "horizon" in en_lower else "no",
            "scene_signature": group_id or (name.lower().removesuffix(".jpg") + "-" + re.sub(r"[^a-z0-9]+", "-", en_lower)[:60]),
            "burst_group_id": group_id,
            "burst_rank": rank,
            "technical_quality": "pass",
            "commercial_potential": "medium",
            "commercial_strengths_en": ["distinctive coastal subject", "usable travel and nature imagery"],
            "selection_status": "selected",
            "uncertain_details": (["distant people or structures cannot be ruled out"] if wide else [])
                + (["species and cause of death cannot be determined"] if "carcass" in en_lower else []),
        }

        extra_en = []
        extra_zh = []
        for en_token, zh_token, triggers in [
            ("ocean", "海洋", ["ocean", "sea", "seascape", "seawater"]),
            ("waves", "海浪", ["wave", "waves", "surf", "breaker", "breakers"]),
            ("honeycomb erosion", "蜂窝状侵蚀", ["honeycomb", "honeycombed", "pitted"]),
            ("sandstone", "砂岩", ["sandstone"]),
            ("rock texture", "岩石纹理", ["texture", "seam", "fold", "folds", "cavities", "hollow", "hollows"]),
            ("tide pool", "潮池", ["tide pool"]),
            ("sea spray", "浪花", ["spray", "splash", "splashes"]),
            ("sunset", "日落", ["sunset", "setting sun", "dusk", "twilight", "evening"]),
            ("pebbles", "卵石", ["pebble", "pebbles"]),
            ("sandy beach", "沙滩", ["beach", "sand"]),
            ("coastal bluff", "海岸崖壁", ["bluff"]),
            ("rock formation", "岩石地貌", ["sculpted", "eroded", "weathered"]),
        ]:
            if mentions(en_lower, triggers):
                extra_en.append(en_token)
                extra_zh.append(zh_token)
        if not water:
            topic_en = [token for token in topic_en if not any(word in token for word in ["ocean", "coast", "shore", "surf", "wave"])]
            topic_zh = [token for token in topic_zh if not any(word in token for word in ["海洋", "海岸", "海浪"])]
            extra_en = [token for token in extra_en if not any(word in token for word in ["ocean", "coast", "shore", "surf", "wave"])]
            extra_zh = [token for token in extra_zh if not any(word in token for word in ["海洋", "海岸", "海浪"])]
        if animal:
            base_en = ["Bean Hollow State Beach", "California", "wildlife", "nature", "conservation"]
            base_zh = ["豆空州立海滩", "加利福尼亚", "野生动物", "自然", "保育"]
        elif water:
            base_en = ["Bean Hollow State Beach", "California", "Pacific Coast", "coastal landscape", "nature", "travel"]
            base_zh = ["豆空州立海滩", "加利福尼亚", "太平洋海岸", "自然风光"]
        else:
            base_en = ["Bean Hollow State Beach", "California", "natural texture", "geology", "nature", "travel"]
            base_zh = ["豆空州立海滩", "加利福尼亚", "自然纹理", "地质", "自然风光"]
        keywords_en = ordered([primary_en, *topic_en, *extra_en, *base_en])
        keywords_zh = ordered([primary_zh, *topic_zh, *extra_zh, *base_zh])
        if "bird" in en_lower:
            keywords_en = ordered([*keywords_en[:3], "bird", *keywords_en[3:]])
            keywords_zh = ordered([*keywords_zh[:3], "鸟", *keywords_zh[3:]])
        if name in {"DSC04134.jpg", "DSC04135.jpg", "DSC04136.jpg"}:
            keywords_en = ordered([*keywords_en[:4], "US flag", *keywords_en[4:]])
            keywords_zh = ordered([*keywords_zh[:4], "美国国旗", *keywords_zh[4:]])
        title_en = short_words(display_en, 67)
        if name == "DSC04138.jpg":
            title_en = "Rounded pebbles lodged in honeycomb sandstone cavities"
        elif name == "DSC04151.jpg":
            title_en = "Orange coastal bluff, beach and shoreline vegetation"
        elif name == "DSC04212.jpg":
            title_en = "Sculpted sandstone ridge beneath a pink-orange dusk sky"
        title_zh = display_zh[:45].rstrip("，、")
        description_en = display_en.rstrip(".") + " at Bean Hollow State Beach, California."
        description_zh = display_zh[:50].rstrip("，、")
        clear = people == "no" and private == "no"
        release_notes = "" if clear else "Distant people or property may require contributor review."
        metadata = {
            "title_en": title_en,
            "title_zh": title_zh,
            "description_en": description_en,
            "description_zh": description_zh,
            "keywords_en": keywords_en,
            "keywords_zh": keywords_zh,
            "category1": cat1,
            "category2": cat2,
            "platform_categories": {
                "shutterstock": [cat1, cat2],
                "adobestock": adobe,
                "tuchong": ["野生动物"] if animal else ["自然风光"],
                "istock": istock,
            },
            "location_en": "Bean Hollow State Beach, California",
            "location_zh": "加利福尼亚州 Bean Hollow 州立海滩",
            "location_source": "context",
            "location_confidence": "medium",
            "core_keywords_zh": keywords_zh[:5],
            "commercial_uses_en": ["wildlife conservation coverage", "California coastal travel"] if animal else ["California coastal travel", "geology and nature education"],
            "editorial_caption_en": "",
            "editorial_date": "",
            "editorial_date_source": "unknown",
            "editorial_location_en": "",
            "model_release_status": "not_required" if people == "no" else "unknown",
            "property_release_status": "not_required" if private == "no" else "unknown",
            "logo_trademark_status": "none",
            "copyrighted_content_status": "none",
            "commercial_eligibility": "clear" if clear else "review",
            "release_status": "clear" if clear else "unknown",
            "release_notes": release_notes,
        }
        output.append({"image": image, "visual_facts": facts, "metadata": metadata})

    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(output)} draft records: {OUTPUT}")


if __name__ == "__main__":
    main()
