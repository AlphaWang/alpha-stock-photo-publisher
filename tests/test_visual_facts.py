import json
import unittest
from pathlib import Path

from metadata_core import enforce_limits, find_batch_quality_issues
from test_metadata_core import sample_metadata
from visual_facts import (
    VISUAL_FACT_FIELDS,
    validate_metadata_against_visual_facts,
    validate_visual_fact_batch,
    validate_visual_facts,
)


def complete_visual_facts():
    return {
        "schema_version": 1,
        "primary_subjects_en": ["desert road"],
        "primary_subjects_zh": ["沙漠公路"],
        "required_terms_en": [],
        "required_terms_zh": [],
        "forbidden_claims_en": [],
        "forbidden_claims_zh": [],
        "water_visible": "unknown",
        "trail_visible": "unknown",
        "people_visible": "no",
        "recognizable_people_visible": "no",
        "structures_visible": "no",
        "vehicles_visible": "no",
        "animals_visible": "no",
        "reflection_visible": "no",
        "text_visible": "no",
        "logo_or_trademark_visible": "no",
        "copyrighted_content_visible": "no",
        "private_property_visible": "no",
        "copy_space_visible": "unknown",
        "scene_signature": "desert-road-distant-mountains-sunset",
        "burst_group_id": "",
        "burst_rank": 0,
        "technical_quality": "pass",
        "commercial_potential": "medium",
        "commercial_strengths_en": ["clear road trip concept"],
        "selection_status": "selected",
        "uncertain_details": [],
    }


class VisualFactsTests(unittest.TestCase):
    def test_contract_requires_complete_checklist(self):
        issues = validate_visual_facts({"schema_version": 1})

        self.assertTrue(any("missing fields" in issue for issue in issues))
        self.assertEqual(len(VISUAL_FACT_FIELDS), 28)

    def test_json_contract_matches_runtime_fields(self):
        contract = json.loads(
            (Path(__file__).parents[1] / "visual_facts_contract.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(set(contract["required"]), set(VISUAL_FACT_FIELDS))
        self.assertEqual(set(contract["properties"]), set(VISUAL_FACT_FIELDS))

    def test_low_commercial_potential_is_not_selected_for_persistence(self):
        facts = complete_visual_facts()
        facts["commercial_potential"] = "low"

        issues = validate_visual_facts(facts)

        self.assertTrue(any("high or medium" in issue for issue in issues))

    def test_grand_teton_regression_cases_are_blocked(self):
        fixture = Path(__file__).parent / "fixtures" / (
            "grand_teton_visual_regressions.json"
        )
        cases = json.loads(fixture.read_text(encoding="utf-8"))

        for case in cases:
            with self.subTest(case=case["name"]):
                facts = {**complete_visual_facts(), **case["facts_patch"]}
                metadata = {**sample_metadata(), **case["metadata_patch"]}
                issues = validate_metadata_against_visual_facts(
                    enforce_limits(metadata), facts
                )
                self.assertTrue(
                    any(case["expected_issue"] in issue for issue in issues),
                    issues,
                )

    def test_location_context_does_not_count_as_visible_water_claim(self):
        facts = complete_visual_facts()
        facts["water_visible"] = "no"
        metadata = sample_metadata()
        metadata.update(
            {
                "location_en": "Jenny Lake, Grand Teton National Park",
                "location_zh": "大提顿国家公园珍妮湖区域",
                "location_source": "context",
                "location_confidence": "high",
            }
        )

        issues = validate_metadata_against_visual_facts(
            enforce_limits(metadata), facts
        )

        self.assertFalse(any("water_visible" in issue for issue in issues), issues)

    def test_visual_release_evidence_blocks_clear_status(self):
        facts = complete_visual_facts()
        facts.update(
            {
                "recognizable_people_visible": "yes",
                "logo_or_trademark_visible": "yes",
                "private_property_visible": "yes",
            }
        )

        issues = validate_metadata_against_visual_facts(
            enforce_limits(sample_metadata()), facts
        )

        self.assertIn("recognizable people require model release review", issues)
        self.assertIn(
            "visible private property requires property release review", issues
        )
        self.assertIn(
            "visible logo/trademark contradicts logo_trademark_status=none", issues
        )

    def test_unknown_release_evidence_cannot_be_marked_clear(self):
        facts = complete_visual_facts()
        facts.update(
            {
                "people_visible": "yes",
                "recognizable_people_visible": "unknown",
                "logo_or_trademark_visible": "unknown",
                "copyrighted_content_visible": "unknown",
                "private_property_visible": "unknown",
            }
        )

        issues = validate_metadata_against_visual_facts(
            enforce_limits(sample_metadata()), facts
        )

        self.assertEqual(
            sum("unknown" in issue for issue in issues),
            4,
            issues,
        )

    def test_more_than_three_selected_frames_in_burst_is_blocked(self):
        items = []
        for index in range(4):
            facts = complete_visual_facts()
            facts["burst_group_id"] = "fox-burst-1"
            facts["burst_rank"] = index + 1
            items.append(
                {
                    "image": f"fox-{index}.jpg",
                    "visual_facts": facts,
                    "metadata": sample_metadata(),
                }
            )

        issues = validate_visual_fact_batch(items)

        self.assertEqual(set(issues), {1, 2, 3, 4})

    def test_small_curated_burst_can_share_exact_factual_copy(self):
        facts_by_source = {}
        records = []
        for index in range(2):
            source = f"fox-{index}.jpg"
            facts = complete_visual_facts()
            facts["burst_group_id"] = "fox-burst-1"
            facts["burst_rank"] = index + 1
            facts_by_source[source] = facts
            records.append((source, enforce_limits(sample_metadata())))

        issues = find_batch_quality_issues(
            records, visual_facts_by_source=facts_by_source
        )

        self.assertEqual(issues, {})


if __name__ == "__main__":
    unittest.main()
