import unittest

from metadata_benchmark import evaluate_manifests, evaluate_record
from test_metadata_core import sample_metadata


class MetadataBenchmarkTests(unittest.TestCase):
    def test_evaluate_record_checks_terms_order_category_and_risk(self):
        issues = evaluate_record(
            sample_metadata(),
            {
                "required_terms_en": ["desert road", "sunset"],
                "forbidden_terms_en": ["ocean"],
                "required_terms_zh": ["沙漠公路"],
                "forbidden_terms_zh": ["海洋"],
                "first10_terms_en": ["desert road"],
                "category1": "Transportation",
                "commercial_eligibility": "clear",
            },
        )

        self.assertEqual(issues, [])

    def test_evaluate_manifests_reports_missing_and_invented_terms(self):
        report = evaluate_manifests(
            [
                {
                    "image": "one.jpg",
                    "expected": {
                        "required_terms_en": ["desert road"],
                        "forbidden_terms_en": ["ocean"],
                    },
                },
                {"image": "missing.jpg", "expected": {}},
            ],
            [
                {
                    "image": "one.jpg",
                    "metadata": {
                        **sample_metadata(),
                        "keywords_en": sample_metadata()["keywords_en"] + ["ocean"],
                    },
                }
            ],
        )

        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["failed"], 2)
        self.assertIn("forbidden en term", report["results"][0]["issues"][0])


if __name__ == "__main__":
    unittest.main()
