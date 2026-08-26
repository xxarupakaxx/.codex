from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "sync-roadmap.py"
SPEC = importlib.util.spec_from_file_location("sync_roadmap", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


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

    def write_task(self, route: str, plan: bool = True) -> Path:
        task = self.root / route
        task.mkdir()
        (task / "05_log.md").write_text(
            f"roadmap_route: {route}：fixture\n", encoding="utf-8"
        )
        if plan:
            (task / "30_plan.md").write_text("# Plan\n", encoding="utf-8")
        return task

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

    def test_missing_plan_fails_closed(self) -> None:
        task = self.write_task("roadmap", plan=False)
        code, result = MODULE.synchronize(
            task, self.generator, "2", self.workspace, "run-1"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(result["reason"], "plan_missing")

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

    def test_success_returns_artifact_fingerprints(self) -> None:
        task = self.write_task("roadmap")
        generator = self.root / "writing-generator.py"
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
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "synchronized")
        self.assertEqual(
            set(result["artifact_fingerprints"]),
            {"roadmap.html", "roadmap-snapshot.json"},
        )

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
