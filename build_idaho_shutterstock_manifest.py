#!/usr/bin/env python3
"""Build visually reviewed Shutterstock metadata for the 2026-07-04 Idaho set."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/Volumes/Photo/10_US-RoadTrip/2026-07-04_Idaho")
OUTPUT = Path("/private/tmp/idaho-shutterstock-manifest.json")


def facts(subject_en, subject_zh, signature, *, people="no", water="no", structures="no",
          text="no", logo="no", copy="yes", group="", rank=0, potential="medium",
          uncertainty=None):
    return {
        "schema_version": 1,
        "primary_subjects_en": [subject_en], "primary_subjects_zh": [subject_zh],
        "required_terms_en": [subject_en], "required_terms_zh": [subject_zh],
        "forbidden_claims_en": [], "forbidden_claims_zh": [],
        "water_visible": water, "trail_visible": "no", "people_visible": people,
        "recognizable_people_visible": "no" if people == "no" else "unknown",
        "structures_visible": structures, "vehicles_visible": "no", "animals_visible": "no",
        "reflection_visible": "no", "text_visible": text,
        "logo_or_trademark_visible": logo, "copyrighted_content_visible": "no",
        "private_property_visible": "no", "copy_space_visible": copy,
        "scene_signature": signature, "burst_group_id": group, "burst_rank": rank,
        "technical_quality": "pass", "commercial_potential": potential,
        "commercial_strengths_en": ["authentic Idaho travel and nature subject"],
        "selection_status": "selected", "uncertain_details": uncertainty or [],
    }


def metadata(title, title_zh, desc, desc_zh, keywords, keywords_zh, *, category1="Nature",
             category2="Parks/Outdoor", editorial=False, release_note=""):
    location = "Idaho, USA"
    base = {
        "title_en": title, "title_zh": title_zh,
        "description_en": desc, "description_zh": desc_zh,
        "keywords_en": keywords, "keywords_zh": keywords_zh,
        "category1": category1, "category2": category2,
        "platform_categories": {"shutterstock": [category1, category2] if category2 else [category1],
            "adobestock": "Landscapes", "tuchong": ["自然风光"], "istock": "Nature"},
        "location_en": location, "location_zh": "美国爱达荷州",
        "location_source": "context", "location_confidence": "medium",
        "core_keywords_zh": keywords_zh[:5],
        "commercial_uses_en": ["travel promotion", "outdoor editorial", "nature education"],
        "editorial_caption_en": "", "editorial_date": "", "editorial_date_source": "unknown",
        "editorial_location_en": "", "model_release_status": "not_required",
        "property_release_status": "not_required", "logo_trademark_status": "none",
        "copyrighted_content_status": "none", "commercial_eligibility": "clear",
        "release_status": "clear", "release_notes": "",
    }
    if editorial:
        base.update({
            "editorial_caption_en": f"IDAHO, USA - 4 July 2026: {desc}",
            "editorial_date": "2026-07-04", "editorial_date_source": "context",
            "editorial_location_en": location,
            "model_release_status": "required" if "visitor" in desc.lower() or "hiker" in desc.lower() else "not_required",
            "commercial_eligibility": "editorial_only", "release_status": "required",
            "release_notes": release_note,
        })
    return base


NATURE_KW = ["volcanic landscape", "lava rock", "Idaho", "geology", "basalt", "volcanic terrain", "outdoor", "nature", "travel", "rugged landscape", "United States"]
NATURE_ZH = ["火山地貌", "熔岩", "爱达荷州", "地质", "玄武岩", "自然风光", "户外", "美国"]

def scene_for(path, rank):
    n = path.stem
    parent = path.parent.parent.name
    if parent == "1_Fireworks":
        return (facts("fireworks", "烟花", "night-fireworks-display", group="fireworks", rank=rank, potential="high"),
                metadata("Colorful Fireworks Burst in Night Sky", "夜空中绽放的彩色烟花",
                    "Colorful fireworks burst across the dark night sky in Idaho, USA.", "美国爱达荷州夜空中绽放的彩色烟花。",
                    ["fireworks", "night sky", "pyrotechnics", "celebration", "colorful", "light trails", "festival", "holiday", "Idaho", "United States", "dark sky", "event"],
                    ["烟花", "夜空", "焰火", "庆典", "彩色", "节日", "爱达荷州", "美国"]))
    if parent == "3_TwinFalls":
        if n in {"DSC03325", "DSC03326"}:
            return (facts("river", "河流", "river-canyon-green-water", water="yes", group="twinfalls-canyon", rank=rank),
                metadata("Green River Through Rocky Canyon", "岩石峡谷中的绿色河流", "A green river winds through a rocky canyon in Twin Falls, Idaho, USA.", "美国爱达荷州双瀑城岩石峡谷中的绿色河流。", ["river canyon", "green river", "Twin Falls", "Idaho", "canyon", "rocky landscape", "water", "travel", "nature", "United States", "outdoor", "scenic"], ["河流峡谷", "绿色河流", "双瀑城", "爱达荷州", "峡谷", "水景", "自然风光", "美国"]))
        if n in {"DSC03330", "DSC03331", "DSC03332", "DSC03334", "DSC03341", "DSC03343", "DSC03347"}:
            return (facts("United States flag", "美国国旗", "flag-over-river-canyon", water="yes", group="twinfalls-flag", rank=rank, potential="high"),
                metadata("United States Flag Above River Canyon", "河流峡谷上方飘扬的美国国旗", "A United States flag flies above a river canyon in Twin Falls, Idaho, USA.", "美国爱达荷州双瀑城河流峡谷上方飘扬的美国国旗。", ["United States flag", "American flag", "river canyon", "Twin Falls", "Idaho", "patriotism", "flag", "canyon", "water", "travel", "United States", "scenic landscape"], ["美国国旗", "河流峡谷", "双瀑城", "爱达荷州", "爱国主义", "旗帜", "峡谷", "自然风光", "美国"]))
        if n == "DSC03335":
            return (facts("bridge", "大桥", "bridge-over-river-canyon", water="yes", structures="yes"),
                metadata("Bridge Spanning a River Canyon", "横跨河流峡谷的大桥", "A bridge spans a river canyon in Twin Falls, Idaho, USA.", "美国爱达荷州双瀑城横跨河流峡谷的大桥。", ["bridge", "river canyon", "Twin Falls", "Idaho", "canyon", "river", "infrastructure", "travel", "water", "United States", "scenic landscape", "outdoor"], ["大桥", "河流峡谷", "双瀑城", "爱达荷州", "峡谷", "河流", "基础设施", "美国"]))
        return (facts("waterfall", "瀑布", "waterfall-in-rocky-canyon", water="yes", group="twinfalls-waterfalls", rank=rank, potential="high"),
                metadata("Waterfall in Rocky Canyon", "岩石峡谷中的瀑布", "A waterfall flows through a rocky canyon in Twin Falls, Idaho, USA.", "美国爱达荷州双瀑城岩石峡谷中的瀑布。", ["waterfall", "rocky canyon", "Twin Falls", "Idaho", "water", "canyon", "landscape", "travel", "nature", "United States", "outdoor", "scenic"], ["瀑布", "岩石峡谷", "双瀑城", "爱达荷州", "水景", "峡谷", "自然风光", "美国"]))
    if n == "DSC03185":
        return (facts("cinder cone", "火山渣锥", "cinder-cone-grassland"), metadata("Volcanic Cinder Cone Above Grassland", "草原上方的火山渣锥", "A volcanic cinder cone rises above grassland in Idaho, USA.", "美国爱达荷州草原上方的火山渣锥。", ["cinder cone"] + NATURE_KW, ["火山渣锥"] + NATURE_ZH))
    if n in {"DSC03191", "DSC03193"}:
        return (facts("wind-shaped tree", "风塑树木", "tree-on-volcanic-terrain", group="craters-trees", rank=rank), metadata("Wind-Shaped Tree on Volcanic Terrain", "火山地貌上的风塑树木", "A wind-shaped tree stands on volcanic terrain in Idaho, USA.", "美国爱达荷州火山地貌上的风塑树木。", ["wind-shaped tree", "volcanic terrain", "Idaho", "lava rock", "tree", "geology", "nature", "outdoor", "travel", "United States", "rugged landscape"], ["风塑树木", "火山地貌", "爱达荷州", "熔岩", "树木", "地质", "自然风光", "美国"]))
    if n in {"DSC03194", "DSC03195"}:
        return (facts("wildflower", "野花", "wildflower-on-lava", group="craters-wildflowers", rank=rank), metadata("Wildflower Growing Among Lava Rocks", "熔岩岩石间生长的野花", "A small wildflower grows among dark lava rocks in Idaho, USA.", "美国爱达荷州深色熔岩岩石间生长的小野花。", ["wildflower", "lava rocks", "Idaho", "volcanic terrain", "plant", "geology", "nature", "resilience", "outdoor", "United States", "basalt"], ["野花", "熔岩岩石", "爱达荷州", "火山地貌", "植物", "地质", "自然风光", "美国"]))
    if n in {"DSC03215", "DSC03216"}:
        return (facts("visitors", "游客", "visitors-on-cinder-cone", people="yes", group="craters-visitors-cone", rank=rank, uncertainty=["people require editorial handling"]), metadata("Visitors Climbing a Volcanic Cinder Cone", "攀登火山渣锥的游客", "Visitors climb a dark volcanic cinder cone under a cloudy sky in Idaho, USA.", "美国爱达荷州游客在多云天空下攀登深色火山渣锥。", ["visitors", "cinder cone", "volcanic landscape", "Idaho", "hiking", "people", "geology", "outdoor", "travel", "United States"], ["游客", "火山渣锥", "火山地貌", "爱达荷州", "徒步", "人物", "地质", "美国"], editorial=True, release_note="Visible visitors; submit as editorial only."))
    if n in {"DSC03222", "DSC03230"}:
        return (facts("visitors", "游客", "visitors-beside-tree-volcanic-plain", people="yes", group="craters-visitors-tree", rank=rank, uncertainty=["people require editorial handling"]), metadata("Visitors Beside a Wind-Shaped Tree", "风塑树旁的游客", "Visitors stand beside a wind-shaped tree above volcanic terrain in Idaho, USA.", "美国爱达荷州游客站在火山地貌上方的风塑树旁。", ["visitors", "wind-shaped tree", "volcanic terrain", "Idaho", "people", "travel", "geology", "outdoor", "United States", "landscape"], ["游客", "风塑树", "火山地貌", "爱达荷州", "人物", "旅游", "地质", "美国"], editorial=True, release_note="Visible visitors; submit as editorial only."))
    if n in {"DSC03231", "DSC03232"}:
        return (facts("road", "道路", "road-through-lava-field", structures="yes", group="craters-road", rank=rank), metadata("Road Through Dark Lava Field", "穿过深色熔岩原的道路", "A paved road crosses a dark lava field in Idaho, USA.", "美国爱达荷州一条铺装道路穿过深色熔岩原。", ["road", "lava field", "Idaho", "volcanic landscape", "basalt", "geology", "infrastructure", "travel", "outdoor", "United States", "rugged landscape"], ["道路", "熔岩原", "爱达荷州", "火山地貌", "玄武岩", "地质", "基础设施", "美国"]))
    if n in {"DSC03288", "DSC03292"}:
        return (facts("visitors", "游客", "visitors-in-lava-cave", people="yes", group="craters-cave-visitors", rank=rank, uncertainty=["people require editorial handling"]), metadata("Visitors Inside a Lava Cave", "熔岩洞内的游客", "Visitors explore a lava cave with rough volcanic walls in Idaho, USA.", "美国爱达荷州游客探索粗糙火山岩壁的熔岩洞。", ["visitors", "lava cave", "Idaho", "volcanic rock", "people", "geology", "cave", "outdoor", "travel", "United States"], ["游客", "熔岩洞", "爱达荷州", "火山岩", "人物", "地质", "洞穴", "美国"], editorial=True, release_note="Visible visitors; submit as editorial only."))
    if n == "DSC03314":
        return (facts("caution sign", "警示标志", "caution-sign-on-lava-field", text="yes", group="craters-caution-sign", rank=rank, uncertainty=["visible sign text requires editorial handling"]), metadata("Caution Sign Beside Volcanic Pit", "火山坑旁的警示标志", "A caution sign stands beside a volcanic pit opening in an Idaho lava field.", "美国爱达荷州熔岩原火山坑开口旁的警示标志。", ["caution sign", "volcanic pit", "lava field", "Idaho", "warning", "geology", "basalt", "safety", "volcanic landscape", "United States"], ["警示标志", "火山坑", "熔岩原", "爱达荷州", "警告", "地质", "安全", "火山地貌", "美国"], category1="Signs/Symbols", category2="Nature", editorial=True, release_note="Visible sign text; submit as editorial only."))
    if n in {"DSC03247", "DSC03248", "DSC03249", "DSC03270"}:
        return (facts("lava cave", "熔岩洞", "lava-cave-rock-texture", group="craters-caves", rank=rank), metadata("Rugged Interior of Lava Cave", "粗犷的熔岩洞内部", "Rugged volcanic rock forms the interior of a lava cave in Idaho, USA.", "美国爱达荷州熔岩洞内部的粗犷火山岩。", ["lava cave", "volcanic rock", "Idaho", "cave interior", "geology", "basalt", "rock texture", "nature", "outdoor", "United States", "rugged"], ["熔岩洞", "火山岩", "爱达荷州", "洞穴内部", "地质", "玄武岩", "岩石纹理", "美国"]))
    if n in {"DSC03251", "DSC03253"}:
        return (facts("lava rock", "熔岩岩层", "lava-rock-formation", group="craters-lava-formations", rank=rank), metadata("Rugged Lava Rock Formation", "粗犷的熔岩岩层", "A rugged lava rock formation stands in volcanic terrain in Idaho, USA.", "美国爱达荷州火山地貌中的粗犷熔岩岩层。", NATURE_KW + ["rock formation"], NATURE_ZH + ["熔岩岩层"]))
    return (facts("lava rock", "熔岩", "lava-landscape-idaho", group="craters-lava-landscape", rank=rank), metadata("Volcanic Lava Landscape in Idaho", "爱达荷州火山熔岩地貌", "Dark lava rock and sparse vegetation form a volcanic landscape in Idaho, USA.", "美国爱达荷州深色熔岩岩石与稀疏植被构成的火山地貌。", NATURE_KW, NATURE_ZH))


def main():
    records = []
    ranks = {}
    for image in sorted(ROOT.glob("*/4/*.jpg")):
        group_key = image.parent.parent.name
        ranks[group_key] = ranks.get(group_key, 0) + 1
        visual, meta = scene_for(image, ranks[group_key])
        records.append({"image": str(image), "visual_facts": visual, "metadata": meta})
    OUTPUT.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} records to {OUTPUT}")

if __name__ == "__main__":
    main()
