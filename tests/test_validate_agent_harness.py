from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-agent-harness.py"
SPEC = importlib.util.spec_from_file_location("validate_agent_harness", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ValidateAgentHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def make_valid_repo(self) -> None:
        references = "\n".join(MODULE.REQUIRED_REFERENCES)
        self.write("AGENTS.md", f"# Hub\n{references}\n")
        for reference in MODULE.REQUIRED_REFERENCES:
            self.write(reference, "# SSoT\n")
        for relative in (
            "templates/project/AGENTS.md",
            "claude-compat/templates/project/AGENTS.md",
        ):
            self.write(
                relative,
                "# Project\nMEMORY_DIR=.local/\nBASE_BRANCH=main\n## 品質チェック\n",
            )
        for relative in (
            "templates/project/CLAUDE.md",
            "claude-compat/templates/project/CLAUDE.md",
        ):
            self.write(relative, "@AGENTS.md\n")

    def test_valid_entrypoint_passes(self) -> None:
        self.make_valid_repo()
        self.assertEqual(MODULE.validate_entrypoint(self.root), [])

    def test_entrypoint_rejects_budget_and_missing_reference(self) -> None:
        self.make_valid_repo()
        self.write("AGENTS.md", "\n".join(["line"] * 121))
        errors = MODULE.validate_entrypoint(self.root)
        self.assertTrue(any("exceeds 120 lines" in error for error in errors))
        self.assertTrue(any("missing SSoT reference" in error for error in errors))

    def test_project_agents_template_requires_bootstrap_contract(self) -> None:
        self.make_valid_repo()
        self.write("templates/project/AGENTS.md", "# Project\n")
        errors = MODULE.validate_entrypoint(self.root)
        self.assertEqual(
            sum("project AGENTS template missing" in error for error in errors), 3
        )

    def test_phase_artifact_requires_frontmatter_contract(self) -> None:
        self.write(
            "artifacts/10-plan.md",
            "---\ntask: demo\nphase_or_step: phase-2\ncreated_at: 2026-08-07T17:00:00+09:00\n---\n",
        )
        self.assertEqual(MODULE.validate_artifact_dir(self.root / "artifacts"), [])

        self.write("artifacts/20_build.md", "# missing metadata\n")
        errors = MODULE.validate_artifact_dir(self.root / "artifacts")
        self.assertEqual(sum("missing frontmatter key" in error for error in errors), 3)

        self.write("artifacts/checkpoint.md", "# contract without metadata\n")
        errors = MODULE.validate_artifact_dir(self.root / "artifacts")
        self.assertEqual(sum("checkpoint.md" in error for error in errors), 3)

    def test_single_step_bypass_must_be_complete_and_unexpired(self) -> None:
        now = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)
        self.write(
            "artifacts/single-step/valid.json",
            json.dumps(
                {
                    "enabled": True,
                    "task": "demo",
                    "reason": "one-off formatting",
                    "expires_at": "2026-08-08T00:00:00Z",
                }
            ),
        )
        self.assertEqual(
            MODULE.validate_artifact_dir(self.root / "artifacts", now=now), []
        )

        self.write(
            "artifacts/single-step/expired.json",
            json.dumps(
                {
                    "enabled": True,
                    "task": "demo",
                    "reason": "old exception",
                    "expires_at": "2026-08-06T00:00:00Z",
                }
            ),
        )
        errors = MODULE.validate_artifact_dir(self.root / "artifacts", now=now)
        self.assertTrue(any("bypass expired" in error for error in errors))

    def test_invalid_timestamp_is_rejected(self) -> None:
        self.write(
            "artifacts/10-plan.md",
            "---\ntask: demo\nphase_or_step: phase-2\ncreated_at: someday\n---\n",
        )
        errors = MODULE.validate_artifact_dir(self.root / "artifacts")
        self.assertTrue(any("invalid created_at" in error for error in errors))

        self.write(
            "artifacts/10-plan.md",
            "---\ntask: demo\nphase_or_step: phase-2\ncreated_at: 2026-08-07T17:00:00\n---\n",
        )
        errors = MODULE.validate_artifact_dir(self.root / "artifacts")
        self.assertTrue(any("invalid created_at" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
