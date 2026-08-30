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

    def write_valid_task_meta(self, relative: str = "artifacts/task-meta.json") -> Path:
        return self.write(
            relative,
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": "task",
                    "task_title": "Task",
                    "project_path": str(self.root),
                    "worktree_path": str(self.root),
                    "task_state": "active",
                    "code_change": False,
                    "created_at": "2026-08-07T17:00:00+00:00",
                    "updated_at": "2026-08-07T17:00:00+00:00",
                }
            ),
        )

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
        for relative in MODULE.REQUIRED_ROLE_FILES:
            self.write(
                relative,
                'name = "role"\ndescription = "test"\nmodel_reasoning_effort = "high"\n',
            )
        self.write(
            "config.toml",
            "[skills]\ninclude_instructions = false\n",
        )

    def make_valid_lifecycle_repo(self) -> None:
        self.write(
            "skills/lfg/SKILL.md",
            "\n".join(
                (
                    "context/workflow-rules.md",
                    "context/memory-file-formats.md",
                    "context/agent-team-routing.md",
                    "rules/model-routing.md",
                    "scripts/agent_delivery_lifecycle.py",
                    "scripts/sync-roadmap.py",
                )
            ),
        )
        for relative in MODULE.LFG_SHIMS:
            target = "../lfg/SKILL.md" if relative.startswith("skills/") else "skills/lfg/SKILL.md"
            self.write(relative, f"Compatibility shim: {target}\n")
        for relative in MODULE.LIFECYCLE_FILES:
            self.write(relative, "# lifecycle file\n")
        for relative in MODULE.REVIEW_COLLECTOR_FILES:
            self.write(relative, "# review collector file\n")
        for relative, markers in MODULE.LIFECYCLE_REQUIRED_MARKERS.items():
            self.write(relative, "\n".join(markers))

    def test_valid_entrypoint_passes(self) -> None:
        self.make_valid_repo()
        self.assertEqual(MODULE.validate_entrypoint(self.root), [])

    def test_entrypoint_rejects_budget_and_missing_reference(self) -> None:
        self.make_valid_repo()
        self.write("AGENTS.md", "\n".join(["line"] * 121))
        errors = MODULE.validate_entrypoint(self.root)
        self.assertTrue(any("exceeds 120 lines" in error for error in errors))
        self.assertTrue(any("missing SSoT reference" in error for error in errors))

    def test_runtime_config_rejects_legacy_role_effort_and_skill_catalog(self) -> None:
        self.make_valid_repo()
        self.write(
            "agents/prd-reviewer.toml",
            'name = "reviewer"\ndescription = "test"\nreasoning_effort = "max"\n',
        )
        self.write("config.toml", 'notify = ["host-only"]\n')
        errors = MODULE.validate_runtime_config(self.root)
        self.assertTrue(any("unsupported role field" in error for error in errors))
        self.assertTrue(any("host-specific notify" in error for error in errors))
        self.assertTrue(any("skills.include_instructions" in error for error in errors))

    def test_user_scope_runtime_allows_host_notify(self) -> None:
        self.make_valid_repo()
        self.write(
            "config.toml",
            'notify = ["host-command"]\n[skills]\ninclude_instructions = false\n',
        )
        self.assertEqual(
            MODULE.validate_runtime_config(self.root, allow_host_notify=True), []
        )

    def test_instruction_chain_uses_override_and_nested_order(self) -> None:
        global_home = self.root / "home"
        project = self.root / "project"
        nested = project / "src" / "feature"
        self.write("home/AGENTS.md", "global fallback")
        global_override = self.write("home/AGENTS.override.md", "global override")
        project_agents = self.write("project/AGENTS.md", "project root")
        nested_agents = self.write("project/src/AGENTS.md", "nested")
        nested.mkdir(parents=True, exist_ok=True)

        chain = MODULE.discover_instruction_chain(global_home, project, nested)
        self.assertEqual(
            chain,
            [global_override.resolve(), project_agents.resolve(), nested_agents.resolve()],
        )
        self.assertEqual(
            MODULE.validate_instruction_chain(global_home, project, nested), []
        )

    def test_instruction_chain_rejects_cumulative_budget(self) -> None:
        global_home = self.root / "home"
        project = self.root / "project"
        nested = project / "nested"
        global_home.mkdir(parents=True)
        nested.mkdir(parents=True)
        self.write("project/AGENTS.md", "a" * 16000)
        self.write("project/nested/AGENTS.md", "b" * 9000)
        errors = MODULE.validate_instruction_chain(global_home, project, nested)
        self.assertTrue(any("instruction chain exceeds" in error for error in errors))

    def test_global_mirror_detects_role_drift(self) -> None:
        repo = self.root / "repo"
        home = self.root / "home"
        for relative in MODULE.REQUIRED_GLOBAL_MIRRORS:
            self.write(f"repo/{relative}", "same\n")
            self.write(f"home/{relative}", "same\n")
        self.assertEqual(MODULE.validate_global_mirror(repo, home), [])
        self.write("home/agents/prd-reviewer.toml", "drift\n")
        errors = MODULE.validate_global_mirror(repo, home)
        self.assertEqual(errors, ["global mirror drift: agents/prd-reviewer.toml"])

    def test_project_agents_template_requires_bootstrap_contract(self) -> None:
        self.make_valid_repo()
        self.write("templates/project/AGENTS.md", "# Project\n")
        errors = MODULE.validate_entrypoint(self.root)
        self.assertEqual(
            sum("project AGENTS template missing" in error for error in errors), 3
        )

    def test_phase_artifact_requires_frontmatter_contract(self) -> None:
        self.write_valid_task_meta()
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

    def test_artifact_dir_requires_task_metadata_at_task_root(self) -> None:
        self.write(
            "artifacts/10-plan.md",
            "---\ntask: demo\nphase_or_step: phase-2\ncreated_at: 2026-08-07T17:00:00+09:00\n---\n",
        )
        self.write_valid_task_meta("artifacts/nested/task-meta.json")

        errors = MODULE.validate_artifact_dir(self.root / "artifacts")

        self.assertIn(
            f"{self.root / 'artifacts' / 'task-meta.json'}: missing task metadata",
            errors,
        )

    def test_artifact_dir_rejects_invalid_task_metadata_file(self) -> None:
        artifacts = self.root / "artifacts"
        artifacts.mkdir()
        target = self.write("task-meta-target.json", "{}")
        (artifacts / "task-meta.json").symlink_to(target)

        errors = MODULE.validate_artifact_dir(artifacts)

        self.assertIn(
            f"{artifacts / 'task-meta.json'}: task metadata must be a regular file",
            errors,
        )

        (artifacts / "task-meta.json").unlink()
        self.write("artifacts/task-meta.json", "[]")
        errors = MODULE.validate_artifact_dir(artifacts)

        self.assertIn(
            f"{artifacts / 'task-meta.json'}: task metadata root must be an object",
            errors,
        )

    def test_artifact_dir_requires_current_task_metadata_keys(self) -> None:
        self.write_valid_task_meta()
        metadata_path = self.root / "artifacts" / "task-meta.json"
        metadata = json.loads(metadata_path.read_text())
        del metadata["worktree_path"]
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        errors = MODULE.validate_artifact_dir(self.root / "artifacts")

        self.assertIn(
            f"{metadata_path}: missing task metadata key: worktree_path",
            errors,
        )

    def test_artifact_dir_rejects_malformed_task_metadata_values(self) -> None:
        malformed_values = {
            "schema_version": "1",
            "task_id": "",
            "task_title": 123,
            "project_path": "relative/project",
            "worktree_path": "",
            "task_state": "done",
            "code_change": "false",
            "created_at": "2026-08-07T17:00:00",
            "updated_at": "not-a-time",
            "thread_id": 7,
            "session_id": False,
            "approval_state": [],
        }
        for key, value in malformed_values.items():
            with self.subTest(key=key):
                metadata_path = self.write_valid_task_meta()
                metadata = json.loads(metadata_path.read_text())
                metadata[key] = value
                metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

                errors = MODULE.validate_artifact_dir(self.root / "artifacts")

                self.assertTrue(
                    any(f"invalid task metadata value: {key}" in error for error in errors),
                    errors,
                )

    def test_single_step_bypass_must_be_complete_and_unexpired(self) -> None:
        now = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)
        self.write_valid_task_meta()
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
        self.write_valid_task_meta()
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

    def test_lfg_shims_delegate_without_phase_body(self) -> None:
        self.write(
            "skills/lfg/SKILL.md",
            "\n".join(
                (
                    "context/workflow-rules.md",
                    "context/memory-file-formats.md",
                    "context/agent-team-routing.md",
                    "rules/model-routing.md",
                    "scripts/agent_delivery_lifecycle.py",
                    "scripts/sync-roadmap.py",
                )
            ),
        )
        for relative in MODULE.LFG_SHIMS:
            target = "../lfg/SKILL.md" if relative.startswith("skills/") else "skills/lfg/SKILL.md"
            self.write(relative, f"Compatibility shim: {target}\n")
        self.assertEqual(MODULE.validate_lfg_contract(self.root), [])

        self.write("commands/lfg.md", "skills/lfg/SKILL.md\n| 0: 準備\n")
        errors = MODULE.validate_lfg_contract(self.root)
        self.assertTrue(any("duplicates phase body" in error for error in errors))

    def test_full_replay_contract_passes(self) -> None:
        self.assertEqual(MODULE.validate_full_replay(), [])

    def test_lifecycle_contract_requires_runtime_truth_and_review_collector(self) -> None:
        self.make_valid_lifecycle_repo()

        self.assertEqual(MODULE.validate_lifecycle_contract(self.root), [])

        (self.root / "scripts/review_evidence_collector.py").unlink()
        errors = MODULE.validate_lifecycle_contract(self.root)

        self.assertIn(
            "missing review collector contract file: scripts/review_evidence_collector.py",
            errors,
        )

    def test_lifecycle_contract_rejects_stale_runtime_promises(self) -> None:
        self.make_valid_lifecycle_repo()
        self.write(
            "scheduled-tasks/pr-review/SKILL.md",
            (
                "scripts/review_evidence_collector.py\n"
                "external_writeなし\n"
                "autoFix: true\n"
                "git push\n"
                "Slack投稿を必須にする\n"
                "~/.claude/config/user.json\n"
            ),
        )
        self.write(
            "context/loop-engineering.md",
            (
                "## Delivery lifecycle LOOP\n"
                "scripts/review_evidence_collector.py\n"
                "配線済み・自律稼働\n"
            ),
        )

        errors = MODULE.validate_lifecycle_contract(self.root)

        self.assertTrue(any("forbidden stale runtime promise" in error for error in errors))
        self.assertTrue(any("autoFix: true" in error for error in errors))
        self.assertTrue(any("配線済み・自律稼働" in error for error in errors))

    def test_lifecycle_marker_in_wrong_file_does_not_satisfy_contract(self) -> None:
        self.make_valid_lifecycle_repo()
        workflow_markers = [
            marker
            for marker in MODULE.LIFECYCLE_REQUIRED_MARKERS["context/workflow-rules.md"]
            if marker != "completion_target"
        ]
        self.write("context/workflow-rules.md", "\n".join(workflow_markers))
        self.write(
            "rules/model-routing.md",
            "\n".join(
                (
                    *MODULE.LIFECYCLE_REQUIRED_MARKERS["rules/model-routing.md"],
                    "completion_target",
                )
            ),
        )

        errors = MODULE.validate_lifecycle_contract(self.root)

        self.assertIn(
            "context/workflow-rules.md missing lifecycle marker: completion_target",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
