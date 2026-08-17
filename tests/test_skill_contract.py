import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_SKILL = ROOT / ".agents/skills/publish-photos/SKILL.md"
CLAUDE_SKILL = ROOT / ".claude/skills/publish-photos/SKILL.md"


class SkillContractTests(unittest.TestCase):
    def test_host_skill_copies_are_identical(self):
        self.assertEqual(
            AGENT_SKILL.read_text(encoding="utf-8"),
            CLAUDE_SKILL.read_text(encoding="utf-8"),
        )

    def test_native_workflow_cannot_silently_switch_providers(self):
        skill = AGENT_SKILL.read_text(encoding="utf-8")
        required_guardrails = (
            "Keep AI inference on the active host",
            "Never invoke an external or cross-provider AI SDK",
            "never as user consent or a routing signal",
            "--allow-anthropic-api",
        )
        for guardrail in required_guardrails:
            with self.subTest(guardrail=guardrail):
                self.assertIn(guardrail, skill)


if __name__ == "__main__":
    unittest.main()
