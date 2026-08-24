from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "run-agents-md-canary.py"
SPEC = importlib.util.spec_from_file_location("agents_md_canary", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AgentsMdCanaryTest(unittest.TestCase):
    def test_evaluate_repeats_each_scenario_and_records_missing_markers(self) -> None:
        scenarios = [
            {"id": "safe", "safety": True, "required": ["stop", "approve"]},
            {"id": "route", "safety": False, "required": ["roadmap"]},
        ]
        trials = MODULE.evaluate(
            "candidate", {"AGENTS.md": "stop approve"}, scenarios, 2
        )
        self.assertEqual(len(trials), 4)
        self.assertEqual([trial["status"] for trial in trials], ["pass", "pass", "fail", "fail"])
        self.assertEqual(trials[-1]["missing"], ["roadmap"])

    def test_reachable_sources_follow_references_instead_of_repo_presence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".codex" / "context").mkdir(parents=True)
            (root / ".codex" / "AGENTS.md").write_text(
                "`context/routing.md`\n", encoding="utf-8"
            )
            (root / "AGENTS.md").write_text("project entry\n", encoding="utf-8")
            (root / ".codex" / "context" / "routing.md").write_text(
                "reachable marker\n", encoding="utf-8"
            )

            reachable = MODULE.reachable_sources(root, None, None)
            self.assertIn(".codex/context/routing.md", reachable)

            (root / ".codex" / "AGENTS.md").write_text(
                "no reference\n", encoding="utf-8"
            )
            unreachable = MODULE.reachable_sources(root, None, None)
            self.assertNotIn(".codex/context/routing.md", unreachable)

    def test_execution_canary_covers_instruction_and_roadmap_gates(self) -> None:
        self.assertEqual(
            set(MODULE.EXECUTION_CHECKS),
            {"instruction_contract", "roadmap_adapter", "roadmap_phase_gate"},
        )


if __name__ == "__main__":
    unittest.main()
