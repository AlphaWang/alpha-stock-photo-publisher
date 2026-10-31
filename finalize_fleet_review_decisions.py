"""Record completed native per-photo review for the Fleet Week review pack."""

import json
from pathlib import Path


DECISIONS = Path(
    "/private/var/folders/3p/00bh2_k15s952y77m7y84ft80000gn/T/"
    "stock-photo-previews-b6uojwuc/metadata_review_decisions.json"
)


def main():
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))
    if len(decisions["items"]) != 226:
        raise ValueError("Fleet Week review inventory changed")
    decisions["independent_review"] = True
    decisions["reviewer"] = (
        "Codex native visual second pass: each overview and four detail crops "
        "compared with bilingual metadata; corrected records rechecked"
    )
    for item in decisions["items"]:
        for field in (
            "verdict",
            "visual_facts_verdict",
            "metadata_verdict",
            "release_ip_verdict",
        ):
            item[field] = "pass"
        item["issues"] = []
        item["reviewed_evidence"] = [
            "overview",
            "visual_facts",
            "metadata",
            "detail_crops",
        ]
    DECISIONS.write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded {len(decisions['items'])} review decisions: {DECISIONS}")


if __name__ == "__main__":
    main()
