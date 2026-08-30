from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "roadmap_plan_contract.py"
SPEC = importlib.util.spec_from_file_location("roadmap_plan_contract", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RoadmapPlanContractTest(unittest.TestCase):
    def plan_task(
        self,
        number: str,
        title: str,
        *,
        heading: str = "Task",
        level: str = "##",
        colon: str = ":",
        blocked_by: str = "",
        checks: tuple[str, ...] = ("- [ ] 実装する",),
        include_sections: tuple[str, ...] = (
            "purpose",
            "targets",
            "implementation",
            "outputs",
            "verification",
        ),
    ) -> str:
        sections = [f"{level} {heading} {number}{colon} {title}", ""]
        if blocked_by:
            sections.extend([f"**blockedBy:** {blocked_by}", ""])
        if "purpose" in include_sections:
            sections.extend(["#### 目的", "成立させる目的。", ""])
        if "targets" in include_sections:
            sections.extend(["#### 変更対象", "- `scripts/example.py`", ""])
        if "implementation" in include_sections:
            sections.extend(["#### 実装", *checks, ""])
        if "outputs" in include_sections:
            sections.extend(["#### 成果物", "- 成果物A", ""])
        if "verification" in include_sections:
            sections.extend(["#### 検証", "- `pytest`", ""])
        return "\n".join(sections)

    def test_parses_canonical_task_contract(self) -> None:
        model = MODULE.parse_plan_contract(
            "\n".join(
                [
                    "# 実装計画",
                    "",
                    "## Task 1: Parser contract",
                    "",
                    "#### 目的",
                    "Planを構造化する。",
                    "",
                    "#### 変更対象",
                    "- `scripts/roadmap_plan_contract.py`",
                    "",
                    "#### 実装",
                    "- [x] 見出しを読む",
                    "- [ ] 進捗を重ねる",
                    "",
                    "#### 成果物",
                    "- Plan model",
                    "",
                    "#### 検証",
                    "- `python3 -m unittest`",
                ]
            ),
            "",
        )

        self.assertEqual(model["schemaVersion"], 2)
        self.assertEqual(model["tasks"][0]["number"], "1")
        self.assertEqual(model["tasks"][0]["title"], "Parser contract")
        self.assertEqual(model["tasks"][0]["purpose"], "Planを構造化する。")
        self.assertEqual(model["tasks"][0]["done"], 1)
        self.assertEqual(model["tasks"][0]["total"], 2)
        self.assertEqual(model["tasks"][0]["status"], "in-progress")
        self.assertIsInstance(model["sourceHash"], str)
        self.assertEqual(len(model["sourceHash"]), 64)
        self.assertEqual(model["diagnostics"], [])

    def test_accepts_legacy_h3_japanese_task_and_fullwidth_colon(self) -> None:
        model = MODULE.parse_plan_contract(
            self.plan_task(
                "1.5",
                "レガシー記法",
                heading="タスク",
                level="###",
                colon="：",
                checks=("- [x] 完了済み",),
            )
        )

        task = model["tasks"][0]
        self.assertEqual(task["number"], "1.5")
        self.assertEqual(task["title"], "レガシー記法")
        self.assertEqual(task["status"], "complete")
        self.assertEqual(task["source"]["lineStart"], 1)

    def test_returns_model_with_diagnostic_for_zero_tasks(self) -> None:
        model = MODULE.parse_plan_contract("# 実装計画\n\n## 概要\nTaskなし\n")

        self.assertEqual(model["tasks"], [])
        self.assertEqual(model["edges"], [])
        self.assertEqual(model["progress"], {"done": 0, "total": 0, "globalComplete": False, "signals": {}})
        self.assertEqual(model["diagnostics"][0]["code"], "no_tasks")
        json.dumps(model)

    def test_missing_required_sections_are_diagnostics_not_hard_errors(self) -> None:
        model = MODULE.parse_plan_contract(
            self.plan_task("1", "section diagnostics", include_sections=("purpose", "implementation"))
        )

        missing = {
            (diagnostic["task"], diagnostic["field"])
            for diagnostic in model["diagnostics"]
            if diagnostic["code"] == "missing_required_section"
        }
        self.assertEqual(missing, {("1", "targets"), ("1", "outputs"), ("1", "verification")})

    def test_rejects_empty_task_body(self) -> None:
        with self.assertRaisesRegex(MODULE.PlanContractError, "empty task body"):
            MODULE.parse_plan_contract("## Task 1: empty\n\n## 概要\nstop")

    def test_rejects_empty_title_h4_nested_and_duplicate_ids(self) -> None:
        invalid_cases = [
            ("## Task 1: \nbody", "empty task title"),
            ("#### Task 1: too deep\nbody", "H2 or H3"),
            ("## Task 1.1.1: nested\nbody", "invalid task id"),
            (
                self.plan_task("1", "first") + "\n" + self.plan_task("1", "second"),
                "duplicate task id",
            ),
        ]
        for plan, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(MODULE.PlanContractError, message):
                    MODULE.parse_plan_contract(plan)

    def test_rejects_unknown_and_self_dependencies(self) -> None:
        unknown = self.plan_task("2", "blocked", blocked_by="Task 1")
        self_dependent = self.plan_task("2", "blocked", blocked_by="Task 2")

        with self.assertRaisesRegex(MODULE.PlanContractError, "unknown dependency"):
            MODULE.parse_plan_contract(unknown)
        with self.assertRaisesRegex(MODULE.PlanContractError, "self dependency"):
            MODULE.parse_plan_contract(self_dependent)

    def test_dependency_edges_are_returned_for_known_blockers(self) -> None:
        model = MODULE.parse_plan_contract(
            self.plan_task("1", "base", checks=("- [x] done",))
            + "\n"
            + self.plan_task("2", "blocked", blocked_by="Task 1")
        )

        self.assertEqual(model["edges"], [{"from": "1", "to": "2", "kind": "blockedBy"}])
        self.assertEqual(model["tasks"][1]["blockedBy"], "Task 1")

    def test_dependency_edges_accept_blocked_by_section(self) -> None:
        plan = self.plan_task("1", "base") + "\n" + "\n".join(
            [
                "## Task 2: section blocker",
                "",
                "#### blockedBy",
                "- Task 1",
                "",
                "#### 目的",
                "依存を読む。",
                "",
                "#### 変更対象",
                "- `scripts/example.py`",
                "",
                "#### 実装",
                "- [ ] 実装する",
                "",
                "#### 成果物",
                "- 成果物A",
                "",
                "#### 検証",
                "- `pytest`",
                "",
            ]
        )

        model = MODULE.parse_plan_contract(plan)

        self.assertEqual(model["tasks"][1]["blockedBy"], "Task 1")
        self.assertEqual(model["edges"], [{"from": "1", "to": "2", "kind": "blockedBy"}])

    def test_progress_checklist_overrides_plan_status(self) -> None:
        model = MODULE.parse_plan_contract(
            self.plan_task("1", "override", checks=("- [ ] plan unchecked",)),
            "- [x] Task 1 finished externally\n",
        )

        self.assertEqual(model["tasks"][0]["status"], "complete")
        self.assertEqual(model["tasks"][0]["done"], 1)
        self.assertEqual(model["tasks"][0]["total"], 1)

    def test_progress_table_overrides_done_total_and_status(self) -> None:
        progress = "\n".join(
            [
                "| タスク | 状態 | 進捗 |",
                "|---|---|---|",
                "| Task 1 | blocked | 1/3 |",
            ]
        )

        model = MODULE.parse_plan_contract(
            self.plan_task("1", "table override", checks=("- [x] local", "- [x] local2")),
            progress,
        )

        self.assertEqual(model["tasks"][0]["status"], "blocked")
        self.assertEqual(model["tasks"][0]["done"], 1)
        self.assertEqual(model["tasks"][0]["total"], 3)

    def test_global_complete_progress_marks_unoverridden_tasks_complete(self) -> None:
        model = MODULE.parse_plan_contract(
            self.plan_task("1", "global", checks=("- [ ] local",)),
            "進捗: 100%\n",
        )

        self.assertEqual(model["tasks"][0]["status"], "complete")
        self.assertEqual(model["tasks"][0]["done"], 1)
        self.assertEqual(model["progress"]["done"], 1)

    def test_parse_plan_files_reads_plan_and_progress_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "30_plan.md"
            progress = root / "40_progress.md"
            plan.write_text(self.plan_task("1", "file api"), encoding="utf-8")
            progress.write_text("- [x] Task 1\n", encoding="utf-8")

            model = MODULE.parse_plan_files(plan, progress)

        self.assertEqual(model["tasks"][0]["status"], "complete")
        self.assertEqual(model["sources"], {"plan": str(plan), "progress": str(progress)})

    def test_large_plan_task_section_boundaries_are_near_linear(self) -> None:
        task_count = 2500
        plan = "\n".join(
            self.plan_task(str(index), f"Task {index}")
            for index in range(1, task_count + 1)
        )
        real_heading_re = MODULE.MARKDOWN_HEADING_RE
        start_calls = 0

        class CountingHeading:
            def __init__(self, match: object) -> None:
                self._match = match

            def start(self) -> int:
                nonlocal start_calls
                start_calls += 1
                return self._match.start()

            def group(self, index: int) -> str:
                return self._match.group(index)

        class CountingHeadingRe:
            def finditer(self, text: str) -> list[CountingHeading]:
                return [CountingHeading(match) for match in real_heading_re.finditer(text)]

        MODULE.MARKDOWN_HEADING_RE = CountingHeadingRe()
        try:
            sections = MODULE._iter_task_sections(plan, "30_plan.md")
        finally:
            MODULE.MARKDOWN_HEADING_RE = real_heading_re

        self.assertEqual(len(sections), task_count)
        self.assertEqual(sections[-1]["number"], str(task_count))
        self.assertLess(start_calls, task_count * 8)

    def test_line_for_offset_uses_indexed_lookup_not_linear_scan(self) -> None:
        class CountingStarts:
            def __init__(self, values: list[int]) -> None:
                self.values = values
                self.iter_count = 0
                self.getitem_count = 0

            def __iter__(self) -> object:
                for value in self.values:
                    self.iter_count += 1
                    yield value

            def __len__(self) -> int:
                return len(self.values)

            def __getitem__(self, index: int) -> int:
                self.getitem_count += 1
                return self.values[index]

        starts = CountingStarts(list(range(0, 100_000, 10)))

        line = MODULE._line_for_offset(starts, 98_765)

        self.assertEqual(line, 9877)
        self.assertEqual(starts.iter_count, 0)
        self.assertLess(starts.getitem_count, 32)


if __name__ == "__main__":
    unittest.main()
