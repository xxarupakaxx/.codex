from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "sync-roadmap.py"
SPEC = importlib.util.spec_from_file_location("sync_roadmap", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VALID_DELEGATION_DECISION = """
## 2026-08-27 - Delegation Decision
- decision: worker
- role: implementer
- gate: PASS
- decision_unit: roadmap-sync
- passed_conditions: isolated implementation unit
- failed_conditions: none
- local_first_evidence: target files are local
- reason: enforce recorded delegation decision
- write_scope: scripts/sync-roadmap.py; tests/test_sync_roadmap.py
- acceptance: validation gates phase 2 eligible routes
- supersedes: none
- lead_retains: review and codemap refresh
"""


class SyncRoadmapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / ".local" / "memory"
        self.root.mkdir(parents=True)
        self.generator = self.root / "generator.py"
        self.generator.write_text("# fixture\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_task(
        self,
        route: str,
        plan: bool = True,
        delegation: str | None = VALID_DELEGATION_DECISION,
    ) -> Path:
        task = self.root / route
        task.mkdir()
        log_text = f"roadmap_route: {route}：fixture\n"
        if delegation is not None:
            log_text += delegation
        (task / "05_log.md").write_text(log_text, encoding="utf-8")
        if plan:
            (task / "30_plan.md").write_text(
                "# Plan\n\n"
                "## Task 1: fixture\n\n"
                "#### 目的\nfixture purpose\n\n"
                "#### 変更対象\n- `fixture.py`\n\n"
                "#### 実装\n- [ ] verify fixture\n\n"
                "#### 成果物\n- fixture output\n\n"
                "#### 検証\n- fixture test\n",
                encoding="utf-8",
            )
        return task

    def snapshot_v2(
        self,
        task: Path,
        *,
        generation_id: str = "fixture-generation",
    ) -> dict[str, object]:
        resolved_task = task.resolve()
        model = MODULE.parse_plan_files(
            resolved_task / "30_plan.md",
            resolved_task / "40_progress.md",
        )
        return {
            "version": 1,
            "taskDir": str(resolved_task),
            "generationId": generation_id,
            "files": {
                "30_plan.md": (resolved_task / "30_plan.md").read_text(encoding="utf-8")
            },
            "plan": model,
        }

    def write_snapshot_generator(
        self,
        task: Path,
        snapshot: dict[str, object],
        name: str = "writing-generator.py",
        *,
        html_snapshot: dict[str, object] | None = None,
    ) -> Path:
        generator = self.root / name
        encoded = json.dumps(snapshot, ensure_ascii=False)
        html_encoded = json.dumps(
            html_snapshot if html_snapshot is not None else snapshot,
            ensure_ascii=False,
        ).replace("</", "<\\/")
        generator.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "import sys\n"
            "task = Path(sys.argv[1]).resolve()\n"
            f"(task / 'roadmap.html').write_text({('<script id="embedded-snapshot" type="application/json">' + html_encoded + '</script>')!r})\n"
            f"snapshot = json.loads({encoded!r})\n"
            "(task / 'roadmap-snapshot.json').write_text("
            "json.dumps(snapshot, ensure_ascii=False))\n",
            encoding="utf-8",
        )
        return generator

    def test_explicit_route_builds_open_request(self) -> None:
        task = self.write_task("explicit-roadmap")
        code, result = MODULE.synchronize(
            task,
            self.generator,
            "2",
            self.workspace,
            "run-1",
            open_requested=True,
            dry_run=True,
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["task_dir"], str(task.resolve()))
        self.assertEqual(result["open_status"], "requested")
        self.assertIn("--open", result["command"])

    def test_headless_suppresses_open_but_keeps_generation(self) -> None:
        task = self.write_task("roadmap")
        code, result = MODULE.synchronize(
            task,
            self.generator,
            "4",
            self.workspace,
            "run-1",
            open_requested=True,
            headless=True,
            dry_run=True,
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["open_status"], "suppressed_headless")
        self.assertNotIn("--open", result["command"])
        self.assertIn("verifying", result["command"])

    def test_log_only_never_generates(self) -> None:
        task = self.write_task("log-only", plan=False)
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["phase"], "2")
        self.assertFalse((task / "roadmap.html").exists())

        (task / "05_log.md").write_text("roadmap_route: log-only：fixture\n", encoding="utf-8")
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "delegation_decision_missing")

    def test_missing_plan_fails_closed(self) -> None:
        task = self.write_task("roadmap", plan=False)
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "plan_missing")

    def test_eligible_route_without_task_heading_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        (task / "30_plan.md").write_text("# Plan\n", encoding="utf-8")

        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1", dry_run=True
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "plan_tasks_missing")

    def test_invalid_plan_contract_fails_before_dry_run(self) -> None:
        task = self.write_task("roadmap")
        (task / "30_plan.md").write_text(
            "# Plan\n\n## Task 1: blocked\n\n**blockedBy:** Task 9\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1", dry_run=True
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "plan_contract_invalid")
        self.assertIn("unknown dependency", result["error"])

    def test_phase_2_rejects_nonempty_plan_diagnostics(self) -> None:
        task = self.write_task("roadmap")
        (task / "30_plan.md").write_text(
            "# Plan\n\n"
            "## Task 1: incomplete contract\n\n"
            "#### 目的\n目的だけ\n\n"
            "#### 実装\n- [ ] 実装\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1", dry_run=True
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "plan_diagnostics_present")
        self.assertTrue(result["diagnostics"])

    def test_non_viewer_task_heading_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        (task / "30_plan.md").write_text(
            "# Plan\n\n#### Task 1.1.1: viewerでは読めない\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1", dry_run=True
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "plan_contract_invalid")

    def test_phase_2_requires_preview_for_llm_declared_ui_task(self) -> None:
        task = self.write_task("roadmap")
        (task / "30_plan.md").write_text(
            "# Plan\n\n## Task 2: UIを変更する\n\nUI変更: yes\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1", dry_run=True
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "ui_preview_authoring_incomplete")
        self.assertEqual(result["missing_task_numbers"], ["2"])

    def test_phase_2_accepts_valid_preview_and_behavior_only_plan(self) -> None:
        task = self.write_task("roadmap")
        payload = (
            '{"version":1,"taskNumber":"2","previews":['
            '{"id":"nav","title":"Nav","layout":"topnav"}]}'
        )
        (task / "30_plan.md").write_text(
            "# Plan\n\n"
            "## Task 1: API変更\n\n"
            "#### 目的\nAPIを更新する。\n\n"
            "#### 変更対象\n- `api.py`\n\n"
            "#### 実装\nUI変更: no\n- [ ] APIを更新する\n\n"
            "#### 成果物\n- API\n\n"
            "#### 検証\n- API test\n\n"
            "## Task 2: UIを変更する\n\n"
            "#### 目的\nUIを更新する。\n\n"
            "#### 変更対象\n- `ui.py`\n\n"
            "#### 実装\nUI変更: yes\n- [ ] UIを更新する\n\n"
            "#### 成果物\n- UI\n\n"
            "#### 検証\n- UI test\n\n"
            f"```ui-preview-json\n{payload}\n```\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1", dry_run=True
        )

        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "dry_run")

    def test_ui_preview_gate_rejects_invalid_block_only_in_phase_2(self) -> None:
        task = self.write_task("roadmap")
        (task / "30_plan.md").write_text(
            "# Plan\n\n## Task 3: UIを変更する\n\nUI変更: yes\n\n"
            "```ui-preview-json\n{}\n```\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1", dry_run=True
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["invalid_task_numbers"], ["3"])

        code, result = MODULE.synchronize(
            task, self.generator, "3", self.workspace, "run-1", dry_run=True
        )
        self.assertEqual(code, 0)

    def test_delegation_decision_required_only_for_phase_2(self) -> None:
        task = self.write_task("roadmap", delegation=None)
        code, result = MODULE.synchronize(task, self.generator, "2", self.workspace, "run-1")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "delegation_decision_missing")
        code, result = MODULE.synchronize(
            task, self.generator, "3", self.workspace, "run-1", dry_run=True
        )
        self.assertEqual(code, 0)

    def test_phase_2_invalid_delegation_decision_reports_fields(self) -> None:
        task = self.write_task(
            "roadmap",
            delegation=(
                "## 2026-08-27 - Delegation Decision\n"
                "- decision: worker\n"
                "- role: \n"
            ),
        )
        code, result = MODULE.synchronize(task, self.generator, "2", self.workspace, "run-1")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "delegation_decision_invalid")
        self.assertLessEqual({"role", "lead_retains"}, set(result["missing_fields"]))

    def test_phase_2_checks_latest_delegation_decision_with_suffix(self) -> None:
        latest = (
            VALID_DELEGATION_DECISION.replace(
                "## 2026-08-27 - Delegation Decision", "## 2026-08-28 - Delegation Decision (updated)",
            )
            .replace("- decision: worker", "- decision: delegate")
            .replace("- role: implementer", "- role: lead")
            .replace("- gate: PASS", "- gate: HOLD")
        )
        task = self.write_task("roadmap", delegation=VALID_DELEGATION_DECISION + latest)
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1", dry_run=True
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "delegation_decision_invalid")
        self.assertEqual(set(result["invalid_fields"]), {"decision", "role", "gate"})

    def test_task_dir_outside_memory_is_rejected(self) -> None:
        task = Path(self.temp.name) / "other"
        task.mkdir()
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "task_dir_outside_memory")

    def test_missing_route_fails_closed(self) -> None:
        task = self.root / "missing-route"
        task.mkdir()
        (task / "05_log.md").write_text("# Log\n", encoding="utf-8")
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "route_missing")

    def test_missing_generator_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        code, result = MODULE.synchronize(
            task, self.root / "missing-generator.py", "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "generator_missing")

    def test_generator_failure_is_not_hidden(self) -> None:
        task = self.write_task("roadmap")
        failing = self.root / "failing-generator.py"
        failing.write_text("raise SystemExit(7)\n", encoding="utf-8")
        code, result = MODULE.synchronize(
            task, failing, "2", self.workspace, "run-1"
        )
        self.assertEqual(code, 7)
        self.assertEqual(result["reason"], "generator_failed")

    def test_success_without_roadmap_artifacts_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_artifact_missing")

    def test_generator_output_without_plan_tasks_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        generator = self.root / "empty-snapshot-generator.py"
        generator.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "task = Path(sys.argv[1])\n"
            "(task / 'roadmap.html').write_text('html')\n"
            "(task / 'roadmap-snapshot.json').write_text('{}')\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, generator, "2", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_invalid")

    def test_success_returns_artifact_fingerprints(self) -> None:
        task = self.write_task("roadmap")
        generator = self.write_snapshot_generator(task, self.snapshot_v2(task))
        code, result = MODULE.synchronize(
            task, generator, "2", self.workspace, "run-1"
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "synchronized")
        self.assertEqual(
            set(result["artifact_fingerprints"]),
            {"roadmap.html", "roadmap-snapshot.json"},
        )

    def test_dry_run_reports_same_plan_contract_used_by_sync(self) -> None:
        task = self.write_task("roadmap")
        expected = MODULE.parse_plan_files(task / "30_plan.md", task / "40_progress.md")

        code, result = MODULE.synchronize(
            task, self.generator, "3", self.workspace, "run-1", dry_run=True
        )

        self.assertEqual(code, 0)
        self.assertEqual(result["plan_source_hash"], expected["sourceHash"])
        self.assertEqual(result["plan_task_ids"], ["1"])
        self.assertEqual(result["plan_edges"], [])

    def test_v2_snapshot_source_hash_mismatch_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        snapshot = self.snapshot_v2(task)
        snapshot["plan"]["sourceHash"] = "0" * 64  # type: ignore[index]
        generator = self.write_snapshot_generator(task, snapshot, "stale-generator.py")

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_source_mismatch")

    def test_v2_snapshot_rejects_stale_progress_source(self) -> None:
        task = self.write_task("roadmap")
        (task / "40_progress.md").write_text("進捗: 10%\n", encoding="utf-8")
        snapshot = self.snapshot_v2(task)
        snapshot["files"]["40_progress.md"] = "進捗: 90%\n"  # type: ignore[index]
        generator = self.write_snapshot_generator(task, snapshot, "stale-progress-generator.py")

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_source_mismatch")

    def test_v2_snapshot_task_and_edge_mismatch_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        (task / "30_plan.md").write_text(
            "# Plan\n\n"
            "## Task 1: base\n\n"
            "#### purpose\nbase\n\n"
            "#### targets\n- `a.py`\n\n"
            "#### implementation\n- [ ] base\n\n"
            "#### outputs\n- output\n\n"
            "#### verification\n- test\n\n"
            "## Task 2: dependent\n\n"
            "**blockedBy:** Task 1\n\n"
            "#### purpose\ndependent\n\n"
            "#### targets\n- `b.py`\n\n"
            "#### implementation\n- [ ] dependent\n\n"
            "#### outputs\n- output\n\n"
            "#### verification\n- test\n",
            encoding="utf-8",
        )
        snapshot = self.snapshot_v2(task)
        snapshot["plan"]["tasks"] = snapshot["plan"]["tasks"][:1]  # type: ignore[index]
        snapshot["plan"]["edges"] = []  # type: ignore[index]
        generator = self.write_snapshot_generator(task, snapshot, "mismatch-generator.py")

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_task_mismatch")

    def test_v2_snapshot_progress_must_match_canonical_model(self) -> None:
        task = self.write_task("roadmap")
        snapshot = self.snapshot_v2(task)
        snapshot["plan"]["progress"]["total"] = 0  # type: ignore[index]
        generator = self.write_snapshot_generator(task, snapshot, "zero-progress-generator.py")

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_progress_mismatch")

    def test_v2_snapshot_requires_generation_identity(self) -> None:
        task = self.write_task("roadmap")
        snapshot = self.snapshot_v2(task)
        del snapshot["generationId"]
        generator = self.write_snapshot_generator(task, snapshot, "identityless-generator.py")

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_identity_invalid")

    def test_v2_snapshot_rejects_malformed_edges_even_when_plan_has_no_edges(self) -> None:
        task = self.write_task("roadmap")
        snapshot = self.snapshot_v2(task)
        snapshot["plan"]["edges"] = [{"from": "1"}]  # type: ignore[index]
        generator = self.write_snapshot_generator(task, snapshot, "malformed-edges-generator.py")

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_edge_mismatch")

    def test_legacy_snapshot_without_plan_remains_supported(self) -> None:
        task = self.write_task("roadmap")
        generator = self.root / "legacy-generator.py"
        legacy_snapshot = {
            "version": 1,
            "taskDir": str(task.resolve()),
            "files": {"30_plan.md": (task / "30_plan.md").read_text()},
        }
        encoded = json.dumps(legacy_snapshot, ensure_ascii=False).replace("</", "<\\/")
        generator.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "import sys\n"
            "task = Path(sys.argv[1]).resolve()\n"
            f"(task / 'roadmap.html').write_text({('<script id="embedded-snapshot" type="application/json">' + encoded + '</script>')!r})\n"
            f"snapshot = json.loads({json.dumps(legacy_snapshot, ensure_ascii=False)!r})\n"
            "(task / 'roadmap-snapshot.json').write_text(json.dumps(snapshot))\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "synchronized")

    def test_html_updated_while_json_is_old_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        old_snapshot = self.snapshot_v2(task, generation_id="old-generation")
        new_snapshot = self.snapshot_v2(task, generation_id="new-generation")
        generator = self.write_snapshot_generator(
            task,
            old_snapshot,
            "partial-publish-generator.py",
            html_snapshot=new_snapshot,
        )

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_pair_mismatch")

    def test_missing_embedded_html_snapshot_fails_closed(self) -> None:
        task = self.write_task("roadmap")
        snapshot = self.snapshot_v2(task)
        encoded = json.dumps(snapshot, ensure_ascii=False)
        generator = self.root / "missing-html-snapshot-generator.py"
        generator.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "import sys\n"
            "task = Path(sys.argv[1]).resolve()\n"
            "(task / 'roadmap.html').write_text('<html></html>')\n"
            f"snapshot = json.loads({encoded!r})\n"
            "(task / 'roadmap-snapshot.json').write_text(json.dumps(snapshot))\n",
            encoding="utf-8",
        )

        code, result = MODULE.synchronize(
            task, generator, "3", self.workspace, "run-1"
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "roadmap_snapshot_pair_invalid")

    def test_other_workspace_memory_is_rejected(self) -> None:
        other = self.workspace / "other"
        task = other / ".local" / "memory" / "roadmap"
        task.mkdir(parents=True)
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "task_dir_outside_memory")

    def test_task_metadata_must_match_workspace(self) -> None:
        task = self.write_task("roadmap")
        (task / "task-meta.json").write_text(
            '{"project_path":"/tmp/other"}', encoding="utf-8"
        )
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "task_metadata_project_path_mismatch")


if __name__ == "__main__":
    unittest.main()
