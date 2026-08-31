from __future__ import annotations

import importlib.util
import json
import hashlib
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

    def html_task(self, *, status: str = "in-progress", step_complete: str = "false") -> str:
        return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>HTML canonical plan</title></head>
<body><main id="plan-document" data-plan-schema="2">
<h1 data-plan-title>HTML canonical plan</h1><p data-plan-intro>Visible introduction.</p>
<section id="task-1" data-task-id="1" data-status="%s">
<h2>Task 1: Parse HTML</h2>
<h3 data-field="purpose">目的</h3><p>直接DOMを読む。</p>
<h3 data-field="targets">変更対象</h3><ul><li>scripts/roadmap_plan_contract.py</li></ul>
<h3 data-field="implementation">実装</h3><ul><li data-step-index="1" data-complete="%s">HTMLを解析する。</li></ul>
<h3 data-field="outputs">成果物</h3><p>typed Plan。</p>
<h3 data-field="verification">検証</h3><p>HTML-only fixture。</p>
<ul data-field="acceptance"><li data-acceptance-id="H1">H1を満たす。</li></ul>
<ul data-field="required-sources"><li data-source-ref="task:30_plan.html">正本</li></ul>
<p data-field="implementation-evidence"><code data-source-ref="repo:scripts/roadmap_plan_contract.py#def parse_plan_files, fallback">parser</code></p>
</section></main>
<script id="plan-envelope" type="application/json">{"schemaVersion":2,"machine":{"kind":"test"}}</script>
</body></html>""" % (status, step_complete)

    def test_html_source_parses_typed_fields_and_hashes_exact_bytes(self) -> None:
        raw = self.html_task(step_complete="true").encode("utf-8")
        model = MODULE.parse_html_plan_contract(raw, plan_source="/tmp/task/30_plan.html")

        raw_hash = hashlib.sha256(raw).hexdigest()
        self.assertEqual(model["sourceKind"], "html")
        self.assertEqual(model["sourceHashes"], {"30_plan.html": raw_hash})
        self.assertEqual(model["sourceHash"], hashlib.sha256(f"30_plan.html\0{raw_hash}".encode()).hexdigest())
        self.assertEqual(model["planDocument"]["format"], "html")
        self.assertEqual(model["planDocument"]["title"], "HTML canonical plan")
        self.assertEqual(model["tasks"][0]["purpose"], "直接DOMを読む。")
        self.assertEqual(model["tasks"][0]["steps"], [{"label": "HTMLを解析する。", "complete": True}])
        self.assertEqual(model["tasks"][0]["acceptanceIds"], ["H1"])
        self.assertEqual(model["tasks"][0]["requiredSources"], ["task:30_plan.html"])
        self.assertEqual(model["tasks"][0]["sourceRefs"], ["task:30_plan.html", "repo:scripts/roadmap_plan_contract.py#def parse_plan_files, fallback"])
        self.assertNotIn('"tag": "script"', json.dumps(model["planDocument"], ensure_ascii=False))

    def test_html_source_wins_over_markdown_and_invalid_html_does_not_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory)
            html = task / "30_plan.html"
            md = task / "30_plan.md"
            html.write_text(self.html_task(), encoding="utf-8")
            md.write_text("not a valid canonical task", encoding="utf-8")
            first = MODULE.resolve_plan_source(task)
            md.write_text("changed sibling", encoding="utf-8")
            second = MODULE.resolve_plan_source(task)
            self.assertEqual(first["sourceHash"], second["sourceHash"])
            self.assertEqual(first["tasks"], second["tasks"])

            html.write_text("<html><body><main data-plan-schema=\"2\"><script>alert(1)</script></main></body></html>", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.PlanContractError, "script"):
                MODULE.resolve_plan_source(task)

    def test_html_rejects_duplicate_or_nonfinite_json_and_hidden_visible_content(self) -> None:
        base = self.html_task(step_complete="true")
        duplicate = base.replace(
            '"machine":{"kind":"test"}',
            '"machine":{"kind":"test","kind":"duplicate"}',
        )
        nonfinite = base.replace(
            '"machine":{"kind":"test"}',
            '"machine":{"kind":NaN}',
        )
        hidden = base.replace(
            '<p data-plan-intro>Visible introduction.</p>',
            '<p aria-hidden="true">Hidden introduction.</p>',
        )
        for html in (duplicate, nonfinite, hidden):
            with self.subTest(html=html):
                with self.assertRaises(MODULE.PlanContractError):
                    MODULE.parse_html_plan_contract(html.encode("utf-8"))

    def test_html_external_navigation_links_are_safe_but_resource_urls_are_rejected(self) -> None:
        allowed = self.html_task(step_complete="true").replace(
            '<p data-plan-intro>Visible introduction.</p>',
            '<p data-plan-intro>Visible introduction. <a href="https://example.com/source" target="_blank" rel="noopener noreferrer">source</a></p>',
        )
        model = MODULE.parse_html_plan_contract(allowed.encode("utf-8"))
        tree_json = json.dumps(model["planDocument"], ensure_ascii=False)
        self.assertIn("https://example.com/source", tree_json)
        unsafe = (
            allowed.replace('target="_blank" rel="noopener noreferrer"', 'target="_self" rel="noopener noreferrer"'),
            allowed.replace('href="https://example.com/source"', 'href="javascript:alert(1)"'),
            allowed.replace('href="https://example.com/source"', 'href="//example.com/source"'),
            allowed.replace('href="https://example.com/source"', 'href="data:text/html,alert(1)"'),
            allowed.replace('<a href="https://example.com/source" target="_blank" rel="noopener noreferrer">source</a>', '<img src="https://example.com/source">'),
            allowed.replace('<p data-plan-intro>Visible introduction. <a href="https://example.com/source" target="_blank" rel="noopener noreferrer">source</a></p>', '<p data-plan-intro d="M0 0">Visible introduction.</p>'),
            allowed.replace('<p data-plan-intro>Visible introduction. <a href="https://example.com/source" target="_blank" rel="noopener noreferrer">source</a></p>', '<p data-plan-intro="Visible introduction."/><svg fill="url(https://evil.test/x)"></svg>'),
            allowed.replace('</main>', '<svg fill="u\\72l(file:///tmp/x)"></svg><svg fill="u\\72l(//evil.test/x)"></svg></main>'),
        )
        for html in unsafe:
            with self.subTest(html=html):
                with self.assertRaises(MODULE.PlanContractError):
                    MODULE.parse_html_plan_contract(html.encode("utf-8"))

    def test_html_requires_one_canonical_main_without_dropping_visible_content(self) -> None:
        base = self.html_task(step_complete="true")
        outside = base.replace("</main>", "</main><p>outside visible prose</p>")
        multiple = base.replace("</main>", "</main><main data-plan-schema=\"2\"><p>second root</p></main>")
        for html in (outside, multiple):
            with self.subTest(html=html):
                with self.assertRaisesRegex(MODULE.PlanContractError, "main|visible"):
                    MODULE.parse_html_plan_contract(html.encode("utf-8"))

    def test_html_rejects_nested_schema_marker_and_normalizes_boolean_checkbox_state(self) -> None:
        invalid = self.html_task(step_complete="true").replace(
            '<section id="task-1" data-task-id="1" data-status="in-progress">',
            '<section id="task-1" data-task-id="1" data-plan-schema="999" data-status="in-progress">',
        )
        with self.assertRaisesRegex(MODULE.PlanContractError, "schema"):
            MODULE.parse_html_plan_contract(invalid.encode("utf-8"))

        checked = self.html_task(step_complete="true").replace(
            'data-step-index="1" data-complete="true"',
            'data-step-index="1"',
        ).replace(
            '<li data-step-index="1">HTMLを解析する。</li>',
            '<li data-step-index="1"><input type="checkbox" checked="false">HTMLを解析する。</li>',
        )
        model = MODULE.parse_html_plan_contract(checked.encode("utf-8"))
        self.assertTrue(model["tasks"][0]["steps"][0]["complete"])
        self.assertIn('"checked": "true"', json.dumps(model["planDocument"], ensure_ascii=False))

    def test_plan_source_raw_sha_is_additive_across_legacy_and_html_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            md = root / "30_plan.md"
            lf = self.plan_task("1", "raw hash")
            md.write_bytes(lf.encode("utf-8"))
            first = MODULE.parse_plan_files(md, root / "40_progress.md")
            crlf_raw = lf.replace("\n", "\r\n").encode("utf-8")
            md.write_bytes(crlf_raw)
            second = MODULE.parse_plan_files(md, root / "40_progress.md")
            bom_raw = b"\xef\xbb\xbf" + lf.encode("utf-8")
            md.write_bytes(bom_raw)
            third = MODULE.parse_plan_files(md, root / "40_progress.md")

        self.assertEqual(first["sourceHash"], second["sourceHash"])
        self.assertEqual(first["sourceHashes"], second["sourceHashes"])
        self.assertNotEqual(second["planSourceRawSha256"], first["planSourceRawSha256"])
        self.assertEqual(third["planSourceRawSha256"], hashlib.sha256(bom_raw).hexdigest())
        self.assertEqual(first["planSourceRawSha256"], hashlib.sha256(lf.encode("utf-8")).hexdigest())
        self.assertEqual(second["planSourceRawSha256"], hashlib.sha256(crlf_raw).hexdigest())
        self.assertEqual(third["sourceHashes"]["30_plan.md"], MODULE._sha256(bom_raw.decode("utf-8")))

        html_raw = b"\xef\xbb\xbf" + self.html_task(step_complete="true").encode("utf-8")
        html_model = MODULE.parse_html_plan_contract(html_raw)
        self.assertEqual(html_model["planSourceRawSha256"], hashlib.sha256(html_raw).hexdigest())

    def test_head_metadata_and_css_resource_loads_fail_closed(self) -> None:
        valid = self.html_task(step_complete="true").replace(
            '<meta charset="utf-8">',
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
            '<style>body { font-family: sans-serif; color: #222; }</style>',
        )
        self.assertEqual(MODULE.parse_html_plan_contract(valid.encode())["planDocument"]["title"], "HTML canonical plan")
        invalid = (
            '<link rel="stylesheet" href="local.css">',
            '<base href="elsewhere">',
            '<meta http-equiv="refresh" content="0;url=https://evil.test">',
            '<style>@import url(https://evil.test/x);</style>',
            '<style>u\\72 l(https://evil.test/x)</style>',
            '<style>@\\69/*comment*/mport "evil.css";</style>',
            "<style>@im\\\nport \"evil.css\";</style>",
            "<style>u\\\nrl(//evil.test/x)</style>",
        )
        for head_node in invalid:
            with self.subTest(head_node=head_node):
                html = self.html_task(step_complete="true").replace(
                    '<title>HTML canonical plan</title>',
                    head_node + '<title>HTML canonical plan</title>',
                )
                with self.assertRaises(MODULE.PlanContractError):
                    MODULE.parse_html_plan_contract(html.encode("utf-8"))

    def test_html_rejects_non_whitespace_text_under_document_html_or_head(self) -> None:
        cases = (
            "IMPORTANT\n" + self.html_task(step_complete="true"),
            self.html_task(step_complete="true").replace("<html lang=\"ja\">", "<html lang=\"ja\">IMPORTANT"),
            self.html_task(step_complete="true").replace("<head>", "<head>IMPORTANT"),
            self.html_task(step_complete="true") + "IMPORTANT",
        )
        for html in cases:
            with self.subTest(html=html):
                with self.assertRaisesRegex(MODULE.PlanContractError, "text|head"):
                    MODULE.parse_html_plan_contract(html.encode("utf-8"))

    def test_preloaded_html_requires_current_regular_file_and_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory)
            html = task / "30_plan.html"
            raw = self.html_task(step_complete="true").encode("utf-8")
            html.write_bytes(raw)
            model = MODULE.resolve_plan_source(
                task,
                preloaded_plan_text=raw.decode("utf-8"),
                preloaded_plan_raw_sha256=hashlib.sha256(raw).hexdigest(),
            )
            self.assertEqual(model["planSourceRawSha256"], hashlib.sha256(raw).hexdigest())

            html.write_bytes(raw.replace(b"HTML canonical plan", b"Changed canonical plan", 1))
            with self.assertRaisesRegex(MODULE.PlanContractError, "preloaded HTML source"):
                MODULE.resolve_plan_source(
                    task,
                    preloaded_plan_text=raw.decode("utf-8"),
                    preloaded_plan_raw_sha256=hashlib.sha256(raw).hexdigest(),
                )

            html.unlink()
            html.symlink_to(task / "missing.html")
            with self.assertRaises(MODULE.PlanContractError):
                MODULE.resolve_plan_source(
                    task,
                    preloaded_plan_text=raw.decode("utf-8"),
                    preloaded_plan_raw_sha256=hashlib.sha256(raw).hexdigest(),
                )

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
