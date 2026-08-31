from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "task-context.py"
SPEC = importlib.util.spec_from_file_location("task_context", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def plan(*tasks: str) -> str:
    blocks = []
    for task in tasks:
        number, title, checks = task.split("|", 2)
        blocks.append(
            f"## Task {number}: {title}\n\n"
            "#### 目的\n目的。\n\n"
            "#### 変更対象\n- `scripts/example.py`\n\n"
            "#### 実装\n"
            f"{checks}\n\n"
            "#### 成果物\n- 成果物\n\n"
            "#### 検証\n- `python3 -m unittest`"
        )
    return "\n\n".join(blocks)


class TaskContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "memory"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_task(self, name: str, *, plan_text: str | None, progress: str = "", route: str = "roadmap") -> Path:
        task = self.root / name
        task.mkdir()
        (task / "05_log.md").write_text(f"roadmap_route: {route}: fixture\n", encoding="utf-8")
        if plan_text is not None:
            (task / "30_plan.md").write_text(plan_text, encoding="utf-8")
        if progress:
            (task / "40_progress.md").write_text(progress, encoding="utf-8")
        (task / "roadmap.html").write_text("html", encoding="utf-8")
        return task

    def test_brief_uses_parser_and_reports_frontier_and_unresolved_dependency(self) -> None:
        text = plan(
            "1|base|- [ ] base step",
            "2|dependent|- [ ] dependent step\n**blockedBy:** Task 1",
        )
        task = self.write_task("260831_context", plan_text=text)

        result = MODULE.brief_context(task, memory_roots=[self.root])

        self.assertEqual(result["taskIds"], ["1", "2"])
        self.assertEqual(result["frontierTaskIds"], ["1"])
        self.assertEqual(result["unresolvedDependencies"]["2"], [{"taskId": "1", "status": "planned"}])
        self.assertEqual(result["selectedTask"]["id"], "1")
        self.assertEqual(result["htmlPath"], str(task.resolve() / "roadmap.html"))
        self.assertIn("30_plan.md", result["sourceRefs"])
        self.assertEqual(result["selectedTask"]["source"]["path"], str(task.resolve() / "30_plan.md"))

    def test_brief_uses_html_canonical_fields_and_ignores_md_sibling(self) -> None:
        task = self.write_task("html-context", plan_text=None, progress="進捗: 100%\n")
        (task / "30_plan.html").write_text(
            """<main id="plan-document" data-plan-schema="2"><h1>HTML context</h1>
<section data-task-id="1" data-status="complete"><h2>Task 1: Base</h2>
<h3 data-field="purpose">Purpose</h3><p>Base purpose。</p>
<h3 data-field="targets">Targets</h3><ul><li>src.py</li></ul>
<h3 data-field="implementation">Implementation</h3><ul><li data-complete="true">Base step</li></ul>
<h3 data-field="outputs">Outputs</h3><p>Base output。</p>
<h3 data-field="verification">Verification</h3><p>Base verification。</p>
<ul data-field="acceptance"><li data-acceptance-id="H1">HTML acceptance。</li></ul></section>
<section data-task-id="2" data-status="planned"><h2>Task 2: Child</h2>
<h3 data-field="purpose">Purpose</h3><p>HTML purpose。</p>
<h3 data-field="targets">Targets</h3><ul><li>src.py</li></ul>
<h3 data-field="implementation">Implementation</h3><ul><li data-complete="false">Child step</li></ul>
<h3 data-field="outputs">Outputs</h3><p>Child output。</p>
<h3 data-field="verification">Verification</h3><p>Child verification。</p>
<ul data-field="acceptance"><li data-acceptance-id="H2">Child acceptance。</li></ul>
<ul data-field="blocked-by"><li data-task-ref="1">Base</li></ul></section></main>""",
            encoding="utf-8",
        )
        (task / "30_plan.md").write_text("MD sibling must not be parsed", encoding="utf-8")

        result = MODULE.brief_context(task, memory_roots=[self.root])

        self.assertEqual(result["planSource"], "30_plan.html")
        self.assertEqual(result["selectedTask"]["id"], "2")
        self.assertEqual(result["selectedTask"]["purpose"], "HTML purpose。")
        self.assertEqual(result["selectedTask"]["source"]["path"], str(task.resolve() / "30_plan.html"))
        self.assertEqual(result["acceptanceIds"], ["H1", "H2"])
        self.assertEqual(result["unresolvedDependencies"], {})

    def test_acceptance_uses_explicit_task_fields_and_goal_heading(self) -> None:
        text = plan("1|context|- [ ] read")
        text = text.replace("#### 目的\n", "acceptance: REQ-1, AC01\n本文の引用 AC99 は対象外。\n\n#### 目的\n", 1)
        task = self.write_task("acceptance-context", plan_text=text)
        (task / "00_spec.md").write_text("# Spec\n\n## Goal\n短いgoal。\n", encoding="utf-8")

        result = MODULE.brief_context(task, memory_roots=[self.root])

        self.assertEqual(result["acceptanceIds"], ["REQ-1", "AC01"])
        self.assertEqual(result["goal"], "短いgoal。")

    def test_brief_bounds_plan_lists_but_keeps_selected_detail(self) -> None:
        task = self.write_task(
            "large-plan",
            plan_text=plan(*(f"{index}|task {index}|- [ ] step" for index in range(1, 20))),
        )

        result = MODULE.brief_context(task, memory_roots=[self.root])

        self.assertEqual(result["taskCount"], 19)
        self.assertEqual(len(result["taskIds"]), MODULE.MAX_ITEMS)
        self.assertTrue(result["taskIdsTruncated"])
        self.assertEqual(result["frontierCount"], 19)
        self.assertTrue(result["frontierTaskIdsTruncated"])
        self.assertIsNotNone(result["selectedTask"])
        self.assertEqual(result["selectedTask"]["id"], "1")
        self.assertNotIn("tasks", result)

    def test_global_100_percent_does_not_hide_raw_unchecked_steps(self) -> None:
        task = self.write_task(
            "100-false-complete",
            plan_text=plan("1|unfinished|- [ ] still unfinished"),
            progress="進捗: 100%\n",
        )

        result = MODULE.brief_context(task, memory_roots=[self.root])

        self.assertFalse(result["progress"]["rawComplete"])
        self.assertEqual(result["selectedTask"]["status"], "planned")
        self.assertEqual(result["selectedTask"]["incompleteSteps"], ["still unfinished"])

    def test_empty_frontier_does_not_promote_first_task_to_runnable(self) -> None:
        task = self.write_task("all-complete", plan_text=plan("1|done|- [x] done"))

        result = MODULE.brief_context(task, memory_roots=[self.root])

        self.assertEqual(result["frontierTaskIds"], [])
        self.assertIsNone(result["selectedTask"])
        self.assertEqual(result["selection"]["mode"], "no runnable frontier")

    def test_parser_diagnostics_block_frontier(self) -> None:
        task = self.write_task(
            "repair-plan",
            plan_text="## Task 1: incomplete contract\n\n#### 実装\n- [ ] repair\n",
        )

        result = MODULE.brief_context(task, memory_roots=[self.root])

        self.assertEqual(result["state"], "needs-plan-repair")
        self.assertEqual(result["frontierTaskIds"], [])
        self.assertIsNone(result["selection"]["selectedTaskId"])
        self.assertTrue(result["diagnostics"])

    def test_log_only_without_plan_is_explicit_and_readable(self) -> None:
        task = self.write_task("legacy-log-only", plan_text=None, route="log-only")

        result = MODULE.brief_context(task, memory_roots=[self.root])

        self.assertEqual(result["state"], "legacy-log-only")
        self.assertEqual(result["taskIds"], [])
        self.assertIsNone(result["selection"]["selectedTaskId"])

    def test_path_traversal_and_symlink_escape_are_rejected(self) -> None:
        task = self.write_task("safe-task", plan_text=plan("1|safe|- [ ] work"))
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "30_plan.md").write_text(plan("1|outside|- [ ] leak"), encoding="utf-8")
        escaped = self.root / "escaped"
        escaped.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(MODULE.ContextError):
            MODULE.brief_context(self.root / ".." / "memory" / task.name, memory_roots=[self.root])
        with self.assertRaisesRegex(MODULE.ContextError, "symlink"):
            MODULE.brief_context(escaped, memory_roots=[self.root])
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(MODULE.ContextError, "outside every explicit memory root"):
            MODULE.brief_context(alias / task.name, memory_roots=[self.root])

    def test_list_is_bounded_and_does_not_select_by_mtime(self) -> None:
        first = self.write_task("b-task", plan_text=plan("1|b|- [ ] b"))
        second = self.write_task("a-task", plan_text=plan("1|a|- [ ] a"))
        os.utime(first, (100, 100))
        os.utime(second, (200, 200))

        result = MODULE.list_context([self.root], limit=1)

        self.assertEqual(result["selection"]["returnedCount"], 1)
        self.assertTrue(result["selection"]["truncated"])
        self.assertTrue(result["selection"]["noLatestAutoSelection"])
        self.assertEqual(result["tasks"][0]["taskId"], "a-task")

    def test_resolved_list_path_can_be_briefed_through_symlinked_parent_root(self) -> None:
        task = self.write_task("round-trip", plan_text=plan("1|round trip|- [ ] work"))
        parent_alias = Path(self.temp.name) / "parent-alias"
        parent_alias.symlink_to(Path(self.temp.name), target_is_directory=True)
        lexical_root = parent_alias / self.root.name

        listed = MODULE.list_context([lexical_root])
        returned_path = listed["tasks"][0]["taskPath"]
        result = MODULE.brief_context(returned_path, memory_roots=[lexical_root])

        self.assertEqual(Path(returned_path), task.resolve())
        self.assertEqual(result["selectedTask"]["id"], "1")

    def test_list_is_metadata_only_and_keeps_plan_presence_when_plan_is_invalid(self) -> None:
        task = self.write_task("invalid-plan", plan_text="## Task 1: missing sections\n")

        result = MODULE.list_context([self.root])

        self.assertEqual(result["tasks"][0]["state"], "available")
        self.assertTrue(result["tasks"][0]["planExists"])
        self.assertNotIn("taskIds", result["tasks"][0])

    def test_cli_smoke_outputs_json_and_rejects_missing_explicit_path(self) -> None:
        task = self.write_task("cli-task", plan_text=plan("1|cli|- [ ] smoke"))
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "brief", str(task), "--memory-root", str(self.root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["command"], "brief")

        missing = subprocess.run(
            [sys.executable, str(SCRIPT), "brief", str(self.root / "missing"), "--memory-root", str(self.root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("unavailable", missing.stderr)


if __name__ == "__main__":
    unittest.main()
