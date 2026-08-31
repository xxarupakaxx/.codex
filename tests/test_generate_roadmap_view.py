from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate-roadmap-view.py"
SPEC = importlib.util.spec_from_file_location("generate_roadmap_view", SCRIPT)
assert SPEC and SPEC.loader
roadmap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(roadmap)


class RoadmapGeneratorContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.task_dir = self.root / "task"
        self.task_dir.mkdir()
        (self.task_dir / "00_spec.md").write_text("# Sample roadmap\n")

        self.template = self.root / "roadmap_viewer.html"
        self.template.write_text(
            "\n".join(
                [
                    "<!DOCTYPE html>",
                    '<html lang="ja">',
                    "<head>",
                    '  <meta charset="UTF-8">',
                    '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
                    "  <title>Roadmap Test</title>",
                    "</head>",
                    "<body>",
                    '  <main id="main-content">',
                    '    <script id="embedded-snapshot" type="application/json">'
                    f"{roadmap.PLACEHOLDER}"
                    "</script>",
                    "  </main>",
                    "</body>",
                    "</html>",
                    "",
                ]
            )
        )
        self.previous_template = roadmap.TEMPLATE
        roadmap.TEMPLATE = self.template

    def tearDown(self) -> None:
        roadmap.TEMPLATE = self.previous_template
        self.temp_dir.cleanup()

    def write_plan(
        self,
        reference: str,
        *,
        task_number: int = 1,
        task_dir: Path | None = None,
    ) -> None:
        target_dir = task_dir or self.task_dir
        (target_dir / "30_plan.md").write_text(
            "\n".join(
                [
                    "# Plan",
                    "",
                    f"### Task {task_number}: source preview",
                    "",
                    "#### 実装根拠",
                    "",
                    f"- `{reference}`",
                    "",
                    "#### 実装",
                    "",
                    "- 現在の実コードを根拠に変更する。",
                    "",
                ]
            )
        )

    def test_task_parser_matches_viewer_heading_contract(self) -> None:
        plan = "\n".join(
            [
                "## Task 1: valid",
                "- [ ] one",
                "### タスク 1.5： 有効",
                "- [ ] two",
            ]
        )

        sections = roadmap.iter_task_sections(plan)

        self.assertEqual([section[0] for section in sections], ["1", "1.5"])

    def test_structured_plan_and_timeline_are_generated_from_canonical_contract(self) -> None:
        plan = "\n".join(
            [
                "# Plan",
                "",
                "## Task 1: foundation",
                "",
                "#### 目的",
                "基礎を作る。",
                "",
                "#### 変更対象",
                "- `scripts/foundation.py`",
                "",
                "#### 実装",
                "- [x] 実装する",
                "",
                "#### 成果物",
                "- Foundation",
                "",
                "#### 検証",
                "- `pytest`",
                "",
                "## Task 2: integration",
                "",
                "**blockedBy:** Task 1",
                "",
                "#### 目的",
                "統合する。",
                "",
                "#### 変更対象",
                "- `scripts/integration.py`",
                "",
                "#### 実装",
                "- [ ] 統合する",
                "",
                "#### 成果物",
                "- Integration",
                "",
                "#### 検証",
                "- `pytest`",
            ]
        )
        (self.task_dir / "30_plan.md").write_text(plan, encoding="utf-8")
        (self.task_dir / "40_progress.md").write_text(
            "| Task | Status | Progress |\n|---|---|---|\n| Task 2 | in-progress | 1/2 |\n",
            encoding="utf-8",
        )
        (self.task_dir / "05_log.md").write_text(
            "\n".join(
                [
                    "# 作業ログ",
                    "",
                    "## 2026-08-30 23:20 - Plan started",
                    "- Phase 2へ遷移した。",
                    "",
                    "## 2026-08-31 - Follow-up",
                    "- 次の検証を記録した。",
                ]
            ),
            encoding="utf-8",
        )

        snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        self.assertEqual(snapshot["plan"]["schemaVersion"], 2)
        self.assertEqual(
            [task["number"] for task in snapshot["plan"]["tasks"]],
            ["1", "2"],
        )
        self.assertEqual(
            snapshot["plan"]["edges"],
            [{"from": "1", "to": "2", "kind": "blockedBy"}],
        )
        self.assertEqual(snapshot["plan"]["tasks"][1]["status"], "in-progress")
        self.assertEqual(snapshot["timeline"][0]["timestamp"], "2026-08-30T23:20")
        self.assertEqual(snapshot["timeline"][0]["time"], "2026-08-30T23:20")
        self.assertEqual(snapshot["timeline"][0]["phase"], "2")
        self.assertTrue(snapshot["timeline"][0]["id"].startswith("timeline-"))
        self.assertEqual(snapshot["timeline"][0]["source"]["file"], str(self.task_dir / "05_log.md"))
        self.assertIn("Phase 2", snapshot["timeline"][0]["body"])

    def test_plan_parser_is_called_once_and_generation_id_is_deterministic(self) -> None:
        with mock.patch.object(
            roadmap,
            "parse_plan_model",
            wraps=roadmap.parse_plan_model,
        ) as parse_plan:
            first = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        second = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        self.assertEqual(parse_plan.call_count, 1)
        self.assertEqual(first["generationId"], second["generationId"])
        self.assertEqual(first["plan"]["sourceHash"], second["plan"]["sourceHash"])
        self.assertEqual(first["timeline"], second["timeline"])

    def test_invalid_plan_does_not_overwrite_existing_generated_outputs(self) -> None:
        output = self.task_dir / "roadmap.html"
        json_output = self.task_dir / "roadmap-snapshot.json"
        output.write_text("previous valid html", encoding="utf-8")
        json_output.write_text('{"previous": true}', encoding="utf-8")
        (self.task_dir / "30_plan.md").write_text(
            "# Plan\n\n#### Task 1: too deep\nbody\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "H2 or H3"):
            roadmap.write_outputs(
                self.task_dir,
                output,
                write_json=True,
                source_root=self.root,
            )

        self.assertEqual(output.read_text(encoding="utf-8"), "previous valid html")
        self.assertEqual(json_output.read_text(encoding="utf-8"), '{"previous": true}')

    def test_pair_publish_rolls_back_when_json_publish_fails(self) -> None:
        output = self.task_dir / "roadmap.html"
        json_output = self.task_dir / "roadmap-snapshot.json"
        output.write_text("previous valid html", encoding="utf-8")
        json_output.write_text('{"previous": true}', encoding="utf-8")
        failed = False

        def fail_json_once(stage: Path, destination: Path) -> object:
            nonlocal failed
            if destination == json_output and not failed:
                failed = True
                raise OSError("injected JSON publish failure")
            return real_replace(stage, destination)

        real_replace = getattr(roadmap, "_replace_staged", None)
        with mock.patch.object(
            roadmap,
            "_replace_staged",
            side_effect=fail_json_once,
            create=True,
        ):
            with self.assertRaisesRegex(OSError, "injected JSON publish failure"):
                roadmap.write_outputs(
                    self.task_dir,
                    output,
                    write_json=True,
                    source_root=self.root,
                )

        self.assertTrue(failed)
        self.assertEqual(output.read_text(encoding="utf-8"), "previous valid html")
        self.assertEqual(json_output.read_text(encoding="utf-8"), '{"previous": true}')
        self.assertEqual(
            [path for path in self.task_dir.iterdir() if path.name.endswith(".tmp")],
            [],
        )

    def test_write_outputs_without_json_keeps_json_output_untouched(self) -> None:
        output = self.task_dir / "roadmap.html"
        json_output = self.task_dir / "roadmap-snapshot.json"
        json_output.write_text('{"previous": true}', encoding="utf-8")

        roadmap.write_outputs(
            self.task_dir,
            output,
            write_json=False,
            source_root=self.root,
        )

        self.assertTrue(output.is_file())
        self.assertEqual(json_output.read_text(encoding="utf-8"), '{"previous": true}')

    def build_source_snapshot(
        self,
        reference: str,
        *,
        source_root: Path | None = None,
        source_allow_prefixes: list[str] | None = None,
        task_number: int = 1,
    ) -> dict[str, object]:
        self.write_plan(reference, task_number=task_number)
        return roadmap.build_snapshot(
            self.task_dir,
            source_root=source_root or self.root,
            source_allow_prefixes=source_allow_prefixes,
        )

    def run_git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def init_git_source(self, text: str) -> str:
        self.run_git("init")
        self.run_git("config", "user.email", "codex@example.test")
        self.run_git("config", "user.name", "Codex Test")
        source = self.root / "src" / "Nav.tsx"
        source.parent.mkdir(exist_ok=True)
        source.write_text(text)
        self.run_git("add", "src/Nav.tsx")
        self.run_git("commit", "-m", "base")
        return self.run_git("rev-parse", "HEAD")

    def commit_git_source(self, text: str) -> str:
        source = self.root / "src" / "Nav.tsx"
        source.write_text(text)
        self.run_git("add", "src/Nav.tsx")
        self.run_git("commit", "-m", "update")
        return self.run_git("rev-parse", "HEAD")

    def valid_ui_payload(
        self,
        *,
        task_number: int = 1,
        source: str = "repo:src/Nav.tsx#function Nav",
        base_ref: str | None = None,
    ) -> dict[str, object]:
        before_provenance: dict[str, object] = {
            "source": source,
            "observedLabels": ["Home", "Settings"],
        }
        if base_ref:
            before_provenance["baseRef"] = base_ref
        return {
            "version": 1,
            "taskNumber": str(task_number),
            "previews": [
                {
                    "id": "main-nav",
                    "title": "Main navigation",
                    "layout": "topnav",
                    "provenance": {
                        "before": before_provenance,
                        "after": {"source": f"30_plan.md#Task {task_number}"},
                    },
                    "before": {
                        "items": [
                            {"id": "home", "label": "Home", "kind": "label", "state": "active", "change": "same"},
                            {"id": "settings", "label": "Settings", "kind": "label", "state": "", "change": "same"},
                        ]
                    },
                    "after": {
                        "items": [
                            {"id": "home", "label": "Home", "kind": "label", "state": "active", "change": "same"},
                            {"id": "reports", "label": "Reports", "kind": "action", "state": "", "change": "added"},
                            {"id": "settings", "label": "Settings", "kind": "label", "state": "", "change": "same"},
                        ]
                    },
                    "uncertainty": ["role visibility is unchanged"],
                }
            ],
        }

    def write_ui_plan(
        self,
        payload: dict[str, object] | str,
        *,
        task_number: int = 1,
    ) -> None:
        block = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        (self.task_dir / "30_plan.md").write_text(
            "\n".join(
                [
                    "# Plan",
                    "",
                    f"### Task {task_number}: UI preview",
                    "",
                    "#### 実装根拠",
                    "",
                    "- `repo:src/Nav.tsx#function Nav`",
                    "",
                    "#### UI差分",
                    "",
                    "```ui-preview-json",
                    block,
                    "```",
                    "",
                    "#### 実装",
                    "",
                    "- UI差分を確認する。",
                    "",
                ]
            )
        )

    def test_hub_mode_does_not_require_task_dir(self) -> None:
        args = roadmap.parse_args(["--hub", "--memory-root", "/tmp/memory"])

        self.assertTrue(args.hub)
        self.assertIsNone(args.task_dir)

    def test_single_task_serve_watch_cli_remains_supported(self) -> None:
        args = roadmap.parse_args([str(self.task_dir), "--serve", "--watch"])

        self.assertEqual(args.task_dir, str(self.task_dir))
        self.assertTrue(args.serve)
        self.assertTrue(args.watch)
        self.assertFalse(args.hub)

    def test_task_identity_flags_are_available_for_machine_owned_metadata(self) -> None:
        args = roadmap.parse_args([
            str(self.task_dir),
            "--thread-id", "thread-1",
            "--session-id", "session-1",
            "--task-state", "waiting",
        ])

        self.assertEqual(args.thread_id, "thread-1")
        self.assertEqual(args.session_id, "session-1")
        self.assertEqual(args.task_state, "waiting")

    def test_viewing_plans_requires_llm_authored_ui_preview_without_user_metadata(self) -> None:
        skill = (ROOT / "skills" / "viewing-plans" / "SKILL.md").read_text()
        runbook = (
            ROOT / "skills" / "viewing-plans" / "references" / "ui-change-preview.md"
        ).read_text()

        for phrase in ("LLM自身", "UI変更: yes", "metadata入力", "40桁commit SHA"):
            self.assertIn(phrase, skill)
        for phrase in ("LLM Authoring Flow", "ユーザーへJSON", "JSX / TSX", "通常生成"):
            self.assertIn(phrase, runbook)

    def test_hub_mode_rejects_task_dir(self) -> None:
        with self.assertRaises(SystemExit):
            roadmap.parse_args([str(self.task_dir), "--hub"])

    def test_hub_mode_delegates_memory_roots_and_server_options(self) -> None:
        with mock.patch.object(roadmap, "run_task_hub", return_value=17) as run_hub:
            result = roadmap.main([
                "--hub",
                "--memory-root", "/tmp/one",
                "--memory-root", "/tmp/two",
                "--host", "localhost",
                "--port", "4321",
                "--open",
            ])

        self.assertEqual(result, 17)
        run_hub.assert_called_once_with(
            [Path("/tmp/one").resolve(), Path("/tmp/two").resolve()],
            host="localhost",
            port=4321,
            open_browser=True,
        )

    def test_snapshot_v1_includes_optional_workflow_inputs(self) -> None:
        (self.task_dir / "team-journal.md").write_text("# Team Journal\n")
        (self.task_dir / "90_verification.md").write_text("# Verification\n")
        (self.task_dir / "graph-map.md").write_text("# Graph\n")

        snapshot = roadmap.build_snapshot(self.task_dir)

        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["files"]["team-journal.md"], "# Team Journal\n")
        self.assertEqual(snapshot["files"]["90_verification.md"], "# Verification\n")
        self.assertEqual(snapshot["files"]["graph-map.md"], "# Graph\n")

    def test_snapshot_embeds_fresh_codemap_as_workspace_view(self) -> None:
        codemap_snapshot = {
            "schemaVersion": 1,
            "version": 1,
            "kind": "codemap",
            "title": "Task code map",
            "generatedAt": "2026-08-16T00:00:00+00:00",
            "sourceFingerprint": "abc123",
            "scope": {"include": ["src/*.py"], "exclude": []},
            "lanes": [{"id": "runtime", "title": "Runtime", "order": 0}],
            "nodes": [{"id": "entry", "title": "Entry", "kind": "module", "lane": "runtime"}],
            "edges": [],
            "counts": {"lanes": 1, "nodes": 1, "edges": 0, "unknown": 0},
        }
        with mock.patch.object(
            roadmap,
            "load_codemap_state",
            return_value={"status": "fresh", "snapshot": codemap_snapshot},
        ):
            snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        self.assertEqual(snapshot["codemapStatus"], "fresh")
        self.assertEqual(snapshot["codemap"]["kind"], "codemap")
        self.assertEqual(snapshot["codemap"]["nodes"][0]["id"], "entry")

    def test_snapshot_keeps_codemap_failure_visible_without_topology(self) -> None:
        with mock.patch.object(
            roadmap,
            "load_codemap_state",
            return_value={"status": "stale", "message": "source fingerprint mismatch"},
        ):
            snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        self.assertEqual(snapshot["codemapStatus"], "stale")
        self.assertNotIn("codemap", snapshot)
        self.assertEqual(snapshot["codemapMessage"], "source fingerprint mismatch")

    def test_code_change_without_codemap_is_blocking_missing(self) -> None:
        (self.task_dir / "task-meta.json").write_text(
            json.dumps({"code_change": True})
        )

        state = roadmap.load_codemap_state(self.task_dir, self.root)

        self.assertEqual(state["status"], "missing")
        self.assertIn("required", state["message"])

    def test_codemap_mismatch_is_not_collapsed_into_stale(self) -> None:
        for name in ("codemap.source.json", "codemap.json", "codemap.lock"):
            (self.task_dir / name).write_text("{}")
        checker = mock.Mock()
        checker.check.side_effect = RuntimeError("map fingerprint mismatch")
        module_spec = mock.Mock(loader=mock.Mock())
        with mock.patch.object(roadmap.importlib.util, "spec_from_file_location", return_value=module_spec), mock.patch.object(
            roadmap.importlib.util, "module_from_spec", return_value=checker
        ):
            state = roadmap.load_codemap_state(self.task_dir, self.root)

        self.assertEqual(state["status"], "mismatch")

    def test_codemap_unknown_relationships_are_insufficient(self) -> None:
        for name in ("codemap.source.json", "codemap.json", "codemap.lock"):
            (self.task_dir / name).write_text("{}")
        (self.task_dir / "codemap.json").write_text(
            json.dumps({"counts": {"unknown": 1}})
        )
        checker = mock.Mock()
        checker.check.return_value = {"status": "fresh"}
        module_spec = mock.Mock(loader=mock.Mock())
        with mock.patch.object(roadmap.importlib.util, "spec_from_file_location", return_value=module_spec), mock.patch.object(
            roadmap.importlib.util, "module_from_spec", return_value=checker
        ):
            state = roadmap.load_codemap_state(self.task_dir, self.root)

        self.assertEqual(state["status"], "insufficient")

    def test_snapshot_title_uses_task_directory_name_without_date_prefix(self) -> None:
        task_dir = self.root / "260719_emilkowalski_skills_roadmap_ui"
        task_dir.mkdir()
        (task_dir / "00_spec.md").write_text("# Generic specification heading\n")

        snapshot = roadmap.build_snapshot(task_dir)

        self.assertEqual(snapshot["title"], "emilkowalski skills roadmap ui")

    def test_default_source_symlink_is_not_followed(self) -> None:
        target = self.root / "outside-plan.md"
        target.write_text("# Outside secret\n")
        (self.task_dir / "30_plan.md").symlink_to(target)

        snapshot = roadmap.build_snapshot(self.task_dir)

        self.assertNotIn("30_plan.md", snapshot["files"])
        self.assertNotIn("Outside secret", json.dumps(snapshot))

    def test_artifacts_are_recursive_sorted_metadata_without_outputs_or_symlinks(self) -> None:
        artifact_dir = self.task_dir / "artifacts"
        artifact_dir.mkdir()
        binary = artifact_dir / "result.bin"
        binary.write_bytes(b"\x00\x01secret payload")
        (artifact_dir / "alpha.txt").write_text("alpha")
        (self.task_dir / "roadmap.html").write_text("old output")
        (self.task_dir / "roadmap-snapshot.json").write_text("{}")
        (self.task_dir / ".roadmap.html.123.tmp").write_text("temporary")
        (self.task_dir / "scratch.tmp").write_text("temporary")

        custom_output = artifact_dir / "published.html"
        custom_output.write_text("custom output")

        symlink = artifact_dir / "linked-result.bin"
        symlink.symlink_to(binary)
        external_dir = self.root / "external"
        external_dir.mkdir()
        (external_dir / "outside.txt").write_text("outside")
        (self.task_dir / "linked-dir").symlink_to(external_dir, target_is_directory=True)

        snapshot = roadmap.build_snapshot(self.task_dir, output=custom_output)
        artifacts = snapshot["artifacts"]
        paths = [item["path"] for item in artifacts]

        self.assertEqual(paths, sorted(paths))
        self.assertIn("artifacts/alpha.txt", paths)
        self.assertIn("artifacts/result.bin", paths)
        self.assertNotIn("artifacts/published.html", paths)
        self.assertNotIn("artifacts/linked-result.bin", paths)
        self.assertNotIn("linked-dir/outside.txt", paths)
        self.assertNotIn("roadmap.html", paths)
        self.assertNotIn("roadmap-snapshot.json", paths)
        self.assertNotIn(".roadmap.html.123.tmp", paths)
        self.assertNotIn("scratch.tmp", paths)

        result = next(item for item in artifacts if item["path"] == "artifacts/result.bin")
        self.assertEqual(
            set(result),
            {"name", "path", "type", "size", "modifiedAt"},
        )
        self.assertEqual(result["name"], "result.bin")
        self.assertEqual(result["type"], "bin")
        self.assertEqual(result["size"], len(b"\x00\x01secret payload"))
        self.assertNotIn("secret payload", json.dumps(snapshot))

    def test_fingerprint_tracks_source_content_and_artifact_metadata(self) -> None:
        artifact = self.task_dir / "artifact.txt"
        artifact.write_text("unchanged content")

        first = roadmap.build_snapshot(self.task_dir)
        same = roadmap.build_snapshot(self.task_dir)
        self.assertEqual(first["fingerprint"], same["fingerprint"])

        before = artifact.stat()
        os.utime(
            artifact,
            ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
        )
        metadata_changed = roadmap.build_snapshot(self.task_dir)
        self.assertNotEqual(first["fingerprint"], metadata_changed["fingerprint"])

        spec = self.task_dir / "00_spec.md"
        spec_mtime = spec.stat().st_mtime_ns
        spec.write_text("# Changed roadmap\n")
        os.utime(spec, ns=(spec.stat().st_atime_ns, spec_mtime))
        source_changed = roadmap.build_snapshot(self.task_dir)
        self.assertNotEqual(metadata_changed["fingerprint"], source_changed["fingerprint"])

    def test_unchanged_fingerprint_does_not_rewrite_html_or_json(self) -> None:
        output = self.task_dir / "roadmap.html"
        first = roadmap.write_outputs(self.task_dir, output, write_json=True)
        json_output = self.task_dir / "roadmap-snapshot.json"
        before = {
            output: (output.stat().st_ino, output.stat().st_mtime_ns),
            json_output: (json_output.stat().st_ino, json_output.stat().st_mtime_ns),
        }

        time.sleep(0.02)
        second = roadmap.write_outputs(self.task_dir, output, write_json=True)

        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(
            before,
            {
                output: (output.stat().st_ino, output.stat().st_mtime_ns),
                json_output: (json_output.stat().st_ino, json_output.stat().st_mtime_ns),
            },
        )

    def test_rendered_roadmap_gets_static_contract_metadata(self) -> None:
        snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        html = roadmap.render_html(snapshot)

        self.assertIn('name="artifact-kind" content="html-plan"', html)
        self.assertIn('http-equiv="Content-Security-Policy"', html)
        roadmap.validate_roadmap_html(html, self.task_dir / "roadmap.html")

    def test_invalid_roadmap_html_does_not_overwrite_existing_outputs(self) -> None:
        output = self.task_dir / "roadmap.html"
        json_output = self.task_dir / "roadmap-snapshot.json"
        output.write_text("previous valid html")
        json_output.write_text('{"previous": true}')
        self.template.write_text(
            "\n".join(
                [
                    "<!DOCTYPE html>",
                    '<html lang="ja">',
                    "<head>",
                    '  <meta charset="UTF-8">',
                    '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
                    "  <title>Broken Roadmap</title>",
                    "</head>",
                    "<body>",
                    '  <main id="dup"></main>',
                    '  <section id="dup"></section>',
                    '  <script id="embedded-snapshot" type="application/json">'
                    f"{roadmap.PLACEHOLDER}"
                    "</script>",
                    "</body>",
                    "</html>",
                    "",
                ]
            )
        )

        with self.assertRaisesRegex(ValueError, "static HTML contract"):
            roadmap.write_outputs(self.task_dir, output, write_json=True, source_root=self.root)

        self.assertEqual(output.read_text(), "previous valid html")
        self.assertEqual(json_output.read_text(), '{"previous": true}')

    def test_write_outputs_creates_stable_task_metadata(self) -> None:
        output = self.task_dir / "roadmap.html"
        roadmap.write_outputs(
            self.task_dir,
            output,
            write_json=False,
            source_root=self.root,
            thread_id="thread-1",
            session_id="session-1",
            task_state="active",
        )
        meta_path = self.task_dir / "task-meta.json"
        first = json.loads(meta_path.read_text())
        before = meta_path.stat().st_mtime_ns

        roadmap.write_outputs(
            self.task_dir,
            output,
            write_json=False,
            source_root=self.root,
            thread_id="thread-1",
            session_id="session-1",
            task_state="active",
        )
        second = json.loads(meta_path.read_text())

        self.assertEqual(first, second)
        self.assertEqual(before, meta_path.stat().st_mtime_ns)
        self.assertEqual(second["task_id"], "task")
        self.assertEqual(second["thread_id"], "thread-1")
        self.assertEqual(second["session_id"], "session-1")
        self.assertTrue(second["project_path"].endswith(self.root.name))

    def test_write_outputs_preserves_invalid_task_metadata_for_diagnosis(self) -> None:
        meta_path = self.task_dir / "task-meta.json"
        meta_path.write_text("{broken")

        with self.assertRaisesRegex(ValueError, "invalid task-meta.json"):
            roadmap.write_outputs(
                self.task_dir,
                self.task_dir / "roadmap.html",
                write_json=False,
                source_root=self.root,
            )

        self.assertEqual(meta_path.read_text(), "{broken")

    def test_artifact_only_change_rewrites_outputs_and_snapshot_fingerprint(self) -> None:
        artifact = self.task_dir / "artifact.txt"
        artifact.write_text("unchanged content")
        output = self.task_dir / "roadmap.html"
        first = roadmap.write_outputs(self.task_dir, output, write_json=True)
        json_output = self.task_dir / "roadmap-snapshot.json"
        before = (output.stat().st_mtime_ns, json_output.stat().st_mtime_ns)

        stat = artifact.stat()
        os.utime(
            artifact,
            ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000),
        )
        time.sleep(0.02)
        second = roadmap.write_outputs(self.task_dir, output, write_json=True)

        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertNotEqual(before[0], output.stat().st_mtime_ns)
        self.assertNotEqual(before[1], json_output.stat().st_mtime_ns)

    def test_source_preview_resolves_anchor_and_line_range_from_repo_refs(self) -> None:
        source_dir = self.root / "src"
        source_dir.mkdir()
        anchor_source = source_dir / "anchor.py"
        anchor_source.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "def target():",
                    "    value = 1",
                    "    return value",
                    "",
                ]
            )
        )

        snapshot = self.build_source_snapshot(
            "repo:src/anchor.py#def target",
            task_number=2,
        )
        previews = snapshot["sourcePreviews"]

        self.assertEqual(len(previews), 1)
        preview = previews[0]
        self.assertEqual(
            set(preview),
            {
                "taskNumber",
                "path",
                "anchor",
                "language",
                "startLine",
                "endLine",
                "code",
                "status",
                "message",
                "truncated",
            },
        )
        self.assertEqual(preview["taskNumber"], "2")
        self.assertEqual(preview["path"], "src/anchor.py")
        self.assertEqual(preview["anchor"], "def target")
        self.assertEqual(preview["language"], "python")
        self.assertEqual(preview["status"], "resolved")
        self.assertEqual(preview["startLine"], 3)
        self.assertLessEqual(preview["endLine"], 6)
        self.assertEqual(preview["code"].splitlines()[0], "def target():")
        self.assertFalse(preview["truncated"])

        range_source = source_dir / "range.py"
        range_source.write_text(
            "\n".join(f"line_{number} = {number}" for number in range(1, 8)) + "\n"
        )
        range_snapshot = self.build_source_snapshot("repo:src/range.py#L2-L4")
        range_preview = range_snapshot["sourcePreviews"][0]

        self.assertEqual(range_preview["status"], "resolved")
        self.assertEqual(range_preview["anchor"], "L2-L4")
        self.assertEqual(range_preview["startLine"], 2)
        self.assertEqual(range_preview["endLine"], 4)
        self.assertEqual(
            range_preview["code"].splitlines(),
            ["line_2 = 2", "line_3 = 3", "line_4 = 4"],
        )

    def test_source_preview_infers_project_root_for_standard_task_layout(self) -> None:
        project = self.root / "project"
        nested_task = project / ".local" / "memory" / "260731_preview"
        nested_task.mkdir(parents=True)
        (nested_task / "00_spec.md").write_text("# Preview\n")
        source = project / "src" / "feature.py"
        source.parent.mkdir()
        source.write_text("def feature():\n    return True\n")
        self.write_plan(
            "repo:src/feature.py#def feature",
            task_dir=nested_task,
        )

        snapshot = roadmap.build_snapshot(nested_task)

        self.assertEqual(snapshot["sourcePreviews"][0]["status"], "resolved")
        self.assertEqual(snapshot["sourcePreviews"][0]["path"], "src/feature.py")

    def test_source_preview_does_not_cross_a_peer_heading_after_the_task(self) -> None:
        source = self.root / "src" / "appendix.py"
        source.parent.mkdir()
        source.write_text("def appendix_only():\n    return True\n")
        (self.task_dir / "30_plan.md").write_text(
            "\n".join(
                [
                    "# Plan",
                    "",
                    "### Task 1: source未記録",
                    "",
                    "#### 実装",
                    "",
                    "- source previewは作らない。",
                    "",
                    "### Appendix",
                    "",
                    "#### 実装根拠",
                    "",
                    "- `repo:src/appendix.py#def appendix_only`",
                    "",
                ]
            )
        )

        snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        self.assertEqual(snapshot["sourcePreviews"], [])
        self.assertNotIn("appendix_only", json.dumps(snapshot["sourcePreviews"]))

    def test_source_preview_budgets_lines_bytes_and_total_snapshot_content(self) -> None:
        source_dir = self.root / "src"
        source_dir.mkdir()
        long_source = source_dir / "long.py"
        long_source.write_text(
            "def target():\n"
            + "\n".join(f"    value_{number} = {number}" for number in range(1, 20))
            + "\n"
        )

        line_snapshot = self.build_source_snapshot("repo:src/long.py#def target")
        line_preview = line_snapshot["sourcePreviews"][0]

        self.assertEqual(line_preview["status"], "resolved")
        self.assertEqual(line_preview["startLine"], 1)
        self.assertEqual(line_preview["endLine"], 12)
        self.assertEqual(len(line_preview["code"].splitlines()), 12)
        self.assertTrue(line_preview["truncated"])

        byte_source = source_dir / "wide.py"
        byte_source.write_text("wide_value = '" + ("界" * 2_000) + "'\n")
        byte_snapshot = self.build_source_snapshot("repo:src/wide.py#L1-L1")
        byte_preview = byte_snapshot["sourcePreviews"][0]

        self.assertEqual(byte_preview["status"], "resolved")
        self.assertLessEqual(len(byte_preview["code"].encode("utf-8")), 4 * 1024)
        self.assertTrue(byte_preview["truncated"])

    def test_source_preview_collects_each_distinct_reference_in_task_evidence(self) -> None:
        source_dir = self.root / "src"
        source_dir.mkdir()
        (source_dir / "first.py").write_text("def first():\n    return 1\n")
        (source_dir / "second.py").write_text("def second():\n    return 2\n")
        (self.task_dir / "30_plan.md").write_text(
            "\n".join(
                [
                    "# Plan",
                    "",
                    "### Task 1: multiple source references",
                    "",
                    "#### 実装根拠",
                    "",
                    "- repo:src/first.py#def first",
                    "- repo:src/second.py#def second",
                    "- 同じ根拠を再掲: `repo:src/first.py#def first`。",
                    "",
                    "#### 実装",
                    "",
                    "- 2つのsourceを確認する。",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        self.assertEqual(
            [(preview["path"], preview["anchor"]) for preview in snapshot["sourcePreviews"]],
            [("src/first.py", "def first"), ("src/second.py", "def second")],
        )
        self.assertEqual(snapshot["sourcePreviews"][0]["code"].splitlines()[0], "def first():")
        self.assertEqual(snapshot["sourcePreviews"][1]["code"].splitlines()[0], "def second():")

        task_sections: list[str] = ["# Plan", ""]
        for number in range(1, 10):
            path = source_dir / f"budget_{number}.py"
            path.write_text(f"budget_{number} = '" + ("x" * 5_000) + "'\n")
            task_sections.extend(
                [
                    f"### Task {number}: budget {number}",
                    "",
                    "#### 実装根拠",
                    "",
                    f"- `repo:src/budget_{number}.py#L1-L1`",
                    "",
                    "#### 実装",
                    "",
                    "- bounded previewを表示する。",
                    "",
                ]
            )
        (self.task_dir / "30_plan.md").write_text("\n".join(task_sections))

        total_snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)
        total_bytes = sum(
            len(str(preview["code"]).encode("utf-8"))
            for preview in total_snapshot["sourcePreviews"]
        )

        self.assertLessEqual(total_bytes, 32 * 1024)

    def test_source_preview_changes_snapshot_fingerprint(self) -> None:
        source = self.root / "src" / "feature.py"
        source.parent.mkdir()
        source.write_text("value = 1\n")
        self.write_plan("repo:src/feature.py#L1-L1")

        first = roadmap.build_snapshot(self.task_dir, source_root=self.root)
        source.write_text("value = 2\n")
        second = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(second["sourcePreviews"][0]["code"].strip(), "value = 2")

    def test_valid_ui_preview_resolves_declared_base_ref_without_cli(self) -> None:
        base_sha = self.init_git_source(
            "export function Nav() {\n"
            "  return ['Home', 'Settings'].join(' ');\n"
            "}\n"
        )
        (self.root / "src" / "Nav.tsx").write_text(
            "export function Nav() {\n"
            "  return ['Danger', 'Working tree only'].join(' ');\n"
            "}\n"
        )
        self.write_ui_plan(self.valid_ui_payload(base_ref=base_sha))

        snapshot = roadmap.build_snapshot(
            self.task_dir,
            source_root=self.root,
            base_ref=base_sha,
        )
        preview = snapshot["uiPreviews"][0]

        self.assertEqual(preview["taskNumber"], "1")
        self.assertEqual(preview["id"], "main-nav")
        self.assertEqual(preview["layout"], "topnav")
        self.assertEqual(preview["status"], "resolved")
        self.assertEqual(preview["evidenceRevision"], base_sha)
        self.assertEqual(preview["source"]["evidenceRevision"], base_sha)
        self.assertIn("Home", preview["source"]["code"])
        self.assertNotIn("Danger", preview["source"]["code"])
        self.assertEqual(preview["before"]["items"][0]["label"], "Home")
        self.assertEqual(preview["after"]["items"][1]["change"], "added")

        source_preview = snapshot["sourcePreviews"][0]
        self.assertEqual(source_preview["evidenceRevision"], base_sha)
        self.assertIn("Home", source_preview["code"])

        automatic = roadmap.build_snapshot(self.task_dir, source_root=self.root)
        self.assertEqual(automatic["uiPreviews"][0]["status"], "resolved")
        self.assertEqual(automatic["uiPreviews"][0]["evidenceRevision"], base_sha)
        automatic_source = automatic["sourcePreviews"][0]
        self.assertEqual(automatic_source["status"], "resolved")
        self.assertNotIn("evidenceRevision", automatic_source)
        self.assertIn("Danger", automatic_source["code"])

    def test_ui_preview_rejects_invalid_blocks_without_building_model(self) -> None:
        valid = self.valid_ui_payload()
        cases: dict[str, str] = {
            "unknown_key": json.dumps({**valid, "secretInternalKey": "<button>Bad</button>"}),
            "empty_previews": json.dumps({**valid, "previews": []}),
            "unknown_layout": json.dumps(
                {
                    **valid,
                    "previews": [{**valid["previews"][0], "layout": "canvas"}],
                }
            ),
            "unknown_kind": json.dumps(
                {
                    **valid,
                    "previews": [
                        {
                            **valid["previews"][0],
                            "after": {
                                "items": [
                                    {**valid["previews"][0]["after"]["items"][0], "kind": "widget"}
                                ]
                            },
                        }
                    ],
                }
            ),
            "raw_html": json.dumps(
                {
                    **valid,
                    "previews": [{**valid["previews"][0], "title": "<button>Bad</button>"}],
                }
            ),
            "external_url": json.dumps(
                {
                    **valid,
                    "previews": [{**valid["previews"][0], "title": "https://example.com"}],
                }
            ),
            "too_many_previews": json.dumps(
                {
                    **valid,
                    "previews": [
                        {**valid["previews"][0], "id": f"preview-{index}"}
                        for index in range(4)
                    ],
                }
            ),
            "too_many_items": json.dumps(
                {
                    **valid,
                    "previews": [
                        {
                            **valid["previews"][0],
                            "after": {
                                "items": [
                                    {"id": f"item-{index}", "label": "Item", "kind": "item", "change": "same"}
                                    for index in range(25)
                                ]
                            },
                        }
                    ],
                }
            ),
            "long_string": json.dumps(
                {
                    **valid,
                    "previews": [{**valid["previews"][0], "title": "x" * 121}],
                }
            ),
            "before_without_source": json.dumps(
                {
                    **valid,
                    "previews": [
                        {
                            **valid["previews"][0],
                            "provenance": {"before": {}, "after": {"source": "30_plan.md#Task 1"}},
                        }
                    ],
                }
            ),
            "task_mismatch": json.dumps({**valid, "taskNumber": "2"}),
        }

        for label, block in cases.items():
            with self.subTest(case=label):
                self.write_ui_plan(block)
                snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)
                previews_json = json.dumps(snapshot["uiPreviews"], ensure_ascii=False)

                self.assertEqual(snapshot["uiPreviews"][0]["status"], "invalid")
                self.assertEqual(snapshot["uiPreviews"][0]["before"]["items"], [])
                self.assertNotIn("<button>Bad</button>", previews_json)
                self.assertNotIn("secretInternalKey", snapshot["uiPreviews"][0]["message"])
                self.assertNotIn("https://example.com", previews_json)

    def test_ui_preview_rejects_multiple_blocks_task_outside_block_and_oversized_block(self) -> None:
        block = json.dumps(self.valid_ui_payload())
        self.write_ui_plan(f"{block}\n```\n\n```ui-preview-json\n{block}")
        multiple = roadmap.build_snapshot(self.task_dir, source_root=self.root)
        self.assertEqual(multiple["uiPreviews"][0]["status"], "invalid")
        self.assertIn("1件だけ", multiple["uiPreviews"][0]["message"])

        (self.task_dir / "30_plan.md").write_text(
            "# Plan\n\n```ui-preview-json\n{}\n```\n"
        )
        outside = roadmap.build_snapshot(self.task_dir, source_root=self.root)
        self.assertEqual(outside["uiPreviews"][0]["status"], "invalid")
        self.assertEqual(outside["uiPreviews"][0]["taskNumber"], "")

        self.write_ui_plan('{"version":1,"taskNumber":"1","previews":[],"pad":"' + ("x" * 17000) + '"}')
        oversized = roadmap.build_snapshot(self.task_dir, source_root=self.root)
        self.assertEqual(oversized["uiPreviews"][0]["status"], "invalid")
        self.assertIn("16KiB", oversized["uiPreviews"][0]["message"])

    def test_declared_ui_task_fails_generation_when_preview_is_missing_or_invalid(self) -> None:
        (self.task_dir / "30_plan.md").write_text(
            "# Plan\n\n## Task 7: UI変更\n\nUI変更: yes\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Taskのui-preview-json"):
            roadmap.build_snapshot(self.task_dir, source_root=self.root)

        mutable = self.valid_ui_payload(task_number=7, base_ref="main")
        (self.task_dir / "30_plan.md").write_text(
            "# Plan\n\n## Task 7: UI変更\n\nUI変更: yes\n\n"
            "```ui-preview-json\n"
            + json.dumps(mutable)
            + "\n```\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "40桁commit SHA"):
            roadmap.build_snapshot(self.task_dir, source_root=self.root)

        (self.task_dir / "30_plan.md").write_text(
            "# Plan\n\n## Task 7: UI変更\n\nUI変更: yes\n\n"
            "```ui-preview-json\n{}\n```\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Taskのui-preview-json"):
            roadmap.build_snapshot(self.task_dir, source_root=self.root)

    def test_ui_preview_unverified_for_invalid_ref_and_anchor_drift(self) -> None:
        base_sha = self.init_git_source(
            "export function Nav() {\n"
            "  return ['Home', 'Settings'].join(' ');\n"
            "}\n"
        )
        self.write_ui_plan(self.valid_ui_payload())
        injected = "HEAD; touch injected-marker"
        invalid_ref = roadmap.build_snapshot(
            self.task_dir,
            source_root=self.root,
            base_ref=injected,
        )

        self.assertFalse((self.root / "injected-marker").exists())
        self.assertEqual(invalid_ref["sourcePreviews"][0]["status"], "base-ref-unavailable")
        self.assertEqual(invalid_ref["uiPreviews"][0]["status"], "unverified")
        self.assertEqual(invalid_ref["uiPreviews"][0]["before"]["items"], [])

        self.write_ui_plan(
            self.valid_ui_payload(source="repo:src/Nav.tsx#MissingAnchor")
        )
        drift = roadmap.build_snapshot(
            self.task_dir,
            source_root=self.root,
            base_ref=base_sha,
        )

        self.assertEqual(drift["uiPreviews"][0]["status"], "unverified")
        self.assertEqual(drift["uiPreviews"][0]["source"]["status"], "anchor-missing")
        self.assertEqual(drift["uiPreviews"][0]["before"]["items"], [])

    def test_ui_preview_uses_single_declared_commit_without_cli_base_ref(self) -> None:
        base_sha = self.init_git_source(
            "export function Nav() {\n"
            "  return ['Home', 'Settings'].join(' ');\n"
            "}\n"
        )
        self.write_ui_plan(self.valid_ui_payload(base_ref=base_sha))

        snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)
        preview = snapshot["uiPreviews"][0]

        self.assertEqual(preview["status"], "resolved")
        self.assertEqual(preview["evidenceRevision"], base_sha)
        self.assertEqual(preview["before"]["items"][0]["label"], "Home")

    def test_ui_preview_does_not_auto_use_mutable_or_multiple_declared_refs(self) -> None:
        mutable = self.valid_ui_payload(base_ref="main")
        self.write_ui_plan(mutable)
        mutable_snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)
        self.assertEqual(mutable_snapshot["uiPreviews"][0]["status"], "unverified")
        self.assertIn("40桁commit SHA", mutable_snapshot["uiPreviews"][0]["message"])

        first = self.valid_ui_payload(task_number=1, base_ref="1" * 40)
        second = self.valid_ui_payload(task_number=2, base_ref="2" * 40)
        plan = "\n".join([
            "# Plan",
            "## Task 1: first UI",
            "```ui-preview-json",
            json.dumps(first),
            "```",
            "## Task 2: second UI",
            "```ui-preview-json",
            json.dumps(second),
            "```",
        ])
        (self.task_dir / "30_plan.md").write_text(plan)
        multiple_snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root)

        self.assertTrue(multiple_snapshot["uiPreviews"])
        self.assertTrue(all(item["status"] == "unverified" for item in multiple_snapshot["uiPreviews"]))
        self.assertTrue(all("複数のbaseRef" in item["message"] for item in multiple_snapshot["uiPreviews"]))

        outside = self.valid_ui_payload(base_ref="3" * 40)
        inferred, message = roadmap.infer_ui_preview_base_ref(
            "# Plan\n\n```ui-preview-json\n"
            + json.dumps(outside)
            + "\n```\n"
        )
        self.assertIsNone(inferred)
        self.assertEqual(message, "")

    def test_ui_preview_fingerprint_tracks_base_ref_blob_content(self) -> None:
        base_sha = self.init_git_source(
            "export function Nav() {\n"
            "  return ['Home', 'Settings'].join(' ');\n"
            "}\n"
        )
        head_sha = self.commit_git_source(
            "export function Nav() {\n"
            "  return ['Home', 'Settings', 'Reports'].join(' ');\n"
            "}\n"
        )
        self.write_ui_plan(self.valid_ui_payload())

        base = roadmap.build_snapshot(
            self.task_dir,
            source_root=self.root,
            base_ref=base_sha,
        )
        head = roadmap.build_snapshot(
            self.task_dir,
            source_root=self.root,
            base_ref=head_sha,
        )

        self.assertNotEqual(base["fingerprint"], head["fingerprint"])
        self.assertEqual(base["uiPreviews"][0]["evidenceRevision"], base_sha)
        self.assertEqual(head["uiPreviews"][0]["evidenceRevision"], head_sha)
        self.assertNotIn("Reports", base["uiPreviews"][0]["source"]["code"])
        self.assertIn("Reports", head["uiPreviews"][0]["source"]["code"])

    def test_base_ref_cli_and_watch_paths_pass_through_to_writes(self) -> None:
        args = roadmap.parse_args([str(self.task_dir), "--base-ref", "HEAD"])
        self.assertEqual(args.base_ref, "HEAD")

        with mock.patch.object(roadmap, "write_outputs", return_value={}) as write_outputs:
            result = roadmap.main([str(self.task_dir), "--base-ref", "HEAD"])

        self.assertEqual(result, 0)
        self.assertEqual(write_outputs.call_args.kwargs["base_ref"], "HEAD")

        stop = roadmap.threading.Event()

        def stop_after_write(*_args: object, **_kwargs: object) -> dict[str, object]:
            stop.set()
            return {}

        with mock.patch.object(roadmap, "write_outputs", side_effect=stop_after_write) as watched:
            roadmap.watch_outputs(
                self.task_dir,
                self.task_dir / "roadmap.html",
                0.01,
                stop,
                source_root=self.root,
                base_ref="HEAD",
            )

        self.assertEqual(watched.call_args.kwargs["base_ref"], "HEAD")

    def test_git_ui_preview_respects_current_automation_read_false(self) -> None:
        self.run_git("init")
        self.run_git("config", "user.email", "codex@example.test")
        self.run_git("config", "user.name", "Codex Test")
        source = self.root / "docs" / "ui.md"
        source.parent.mkdir()
        source.write_text("---\ntitle: ui\n---\nVisible Home Settings LEAK_AUTOMATION\n")
        self.run_git("add", "docs/ui.md")
        self.run_git("commit", "-m", "base")
        base_sha = self.run_git("rev-parse", "HEAD")
        source.write_text("---\nautomation_read: false\n---\nVisible Home Settings LEAK_AUTOMATION\n")
        self.write_ui_plan(self.valid_ui_payload(source="repo:docs/ui.md#Visible"))

        snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root, base_ref=base_sha)
        preview = snapshot["uiPreviews"][0]

        self.assertEqual(preview["status"], "unverified")
        self.assertEqual(preview["source"]["status"], "source-denied")
        self.assertEqual(preview["before"]["items"], [])
        self.assertNotIn("LEAK_AUTOMATION", json.dumps(preview))

    def test_preview_caps_cache_and_git_timeout_bound_large_plans(self) -> None:
        base_sha = "1" * 40
        sections = ["# Plan"]
        for number in range(1, 10001):
            payload = self.valid_ui_payload(task_number=number)
            sections += [
                f"### Task {number}: UI",
                "",
                "#### 実装根拠",
                "",
                "- `repo:src/Nav.tsx#function Nav`",
                "",
                "```ui-preview-json",
                json.dumps(payload),
                "```",
                "",
            ]
        (self.task_dir / "30_plan.md").write_text("\n".join(sections))
        calls = []

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[object]:
            calls.append(command)
            self.assertEqual(kwargs.get("timeout"), roadmap.GIT_SUBPROCESS_TIMEOUT)
            if "rev-parse" in command:
                return subprocess.CompletedProcess(command, 0, stdout=base_sha + "\n")
            if "ls-tree" in command:
                return subprocess.CompletedProcess(command, 0, stdout=b"100644 blob abc\tsrc/Nav.tsx\0")
            if "-s" in command:
                return subprocess.CompletedProcess(command, 0, stdout="64\n")
            return subprocess.CompletedProcess(command, 0, stdout=b"export function Nav() { return 'Home Settings'; }\n")

        with mock.patch.object(roadmap.subprocess, "run", side_effect=fake_run):
            snapshot = roadmap.build_snapshot(self.task_dir, source_root=self.root, base_ref="HEAD")

        self.assertLessEqual(len(snapshot["sourcePreviews"]), roadmap.MAX_SOURCE_PREVIEW_COUNT)
        self.assertLessEqual(len(snapshot["uiPreviews"]), roadmap.MAX_UI_PREVIEW_COUNT)
        self.assertLessEqual(len(json.dumps(snapshot["uiPreviews"]).encode()), roadmap.MAX_TOTAL_UI_PREVIEW_BYTES)
        self.assertLessEqual(len(calls), 4)

    def test_source_preview_requires_repo_prefix_and_supports_explicit_allow_prefix(self) -> None:
        source = self.root / "custom" / "feature.py"
        source.parent.mkdir()
        source.write_text("def custom_feature():\n    return True\n")

        bare_snapshot = self.build_source_snapshot(
            "custom/feature.py#def custom_feature",
            source_allow_prefixes=["custom"],
        )
        self.assertEqual(bare_snapshot["sourcePreviews"], [])
        self.assertNotIn("return True", json.dumps(bare_snapshot))

        denied_snapshot = self.build_source_snapshot(
            "repo:custom/feature.py#def custom_feature"
        )
        denied_preview = denied_snapshot["sourcePreviews"][0]
        self.assertNotEqual(denied_preview["status"], "resolved")
        self.assertEqual(denied_preview["code"], "")
        self.assertTrue(denied_preview["message"])

        allowed_snapshot = self.build_source_snapshot(
            "repo:custom/feature.py#def custom_feature",
            source_allow_prefixes=["custom"],
        )
        allowed_preview = allowed_snapshot["sourcePreviews"][0]
        self.assertEqual(allowed_preview["status"], "resolved")
        self.assertIn("def custom_feature", allowed_preview["code"])

        args = roadmap.parse_args(
            [
                str(self.task_dir),
                "--source-root",
                str(self.root),
                "--source-allow-prefix",
                "custom",
                "--source-allow-prefix",
                "vendor/generated",
            ]
        )
        self.assertEqual(args.source_root, str(self.root))
        self.assertEqual(
            args.source_allow_prefix,
            ["custom", "vendor/generated"],
        )

    def test_source_preview_denies_unsafe_paths_and_files_without_leaking_content(self) -> None:
        fixtures: dict[str, tuple[str, str]] = {}

        text_cases = {
            "personal": ("Daily/private.py", "LEAK_PERSONAL = True\n"),
            "git": (".git/config", "LEAK_GIT = True\n"),
            "local": (".local/cache.py", "LEAK_LOCAL = True\n"),
            "secret_filename": ("src/.env", "LEAK_SECRET_FILENAME=1\n"),
            "automation_read_false": (
                "docs/private.md",
                "---\nautomation_read: false\n---\nLEAK_AUTOMATION\n",
            ),
            "traversal": ("outside.py", "LEAK_TRAVERSAL = True\n"),
            "absolute": ("src/absolute.py", "LEAK_ABSOLUTE = True\n"),
        }
        for label, (relative_path, content) in text_cases.items():
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            if label == "traversal":
                reference = "repo:src/../outside.py#L1-L1"
            elif label == "absolute":
                reference = f"repo:{path.resolve()}#L1-L1"
            else:
                reference = f"repo:{relative_path}#L1-L1"
            fixtures[label] = (reference, f"LEAK_{label.upper()}")

        symlink_target = self.root / "src" / "real.py"
        symlink_target.parent.mkdir(exist_ok=True)
        symlink_target.write_text("LEAK_SYMLINK = True\n")
        symlink = self.root / "src" / "linked.py"
        symlink.symlink_to(symlink_target)
        fixtures["symlink"] = ("repo:src/linked.py#L1-L1", "LEAK_SYMLINK")

        binary = self.root / "src" / "binary.py"
        binary.write_bytes(b"LEAK_BINARY\x00\x01")
        fixtures["binary"] = ("repo:src/binary.py#L1-L1", "LEAK_BINARY")

        non_utf8 = self.root / "src" / "non-utf8.py"
        non_utf8.write_bytes(b"LEAK_NON_UTF8 = \xff\n")
        fixtures["non_utf8"] = ("repo:src/non-utf8.py#L1-L1", "LEAK_NON_UTF8")

        oversized = self.root / "src" / "oversized.py"
        oversized.write_bytes(b"LEAK_OVERSIZED\n" + (b"x" * (1024 * 1024)))
        fixtures["oversized"] = ("repo:src/oversized.py#L1-L1", "LEAK_OVERSIZED")

        fixtures["tilde"] = ("repo:~/private.py#L1-L1", "LEAK_TILDE")

        for label, (reference, leak_marker) in fixtures.items():
            with self.subTest(case=label):
                snapshot = self.build_source_snapshot(reference)
                preview = snapshot["sourcePreviews"][0]
                serialized = json.dumps(snapshot)

                self.assertNotEqual(preview["status"], "resolved")
                self.assertEqual(preview["code"], "")
                self.assertTrue(preview["message"])
                self.assertNotIn(leak_marker, serialized)

    def test_source_preview_rejects_secret_content_and_missing_anchor_without_code(self) -> None:
        secret = self.root / "src" / "credentials.py"
        secret.parent.mkdir()
        secret.write_text(
            "PRIVATE_KEY = '''-----BEGIN PRIVATE KEY-----\n"
            "not-a-real-key\n"
            "-----END PRIVATE KEY-----'''\n"
        )

        secret_snapshot = self.build_source_snapshot(
            "repo:src/credentials.py#PRIVATE_KEY"
        )
        secret_preview = secret_snapshot["sourcePreviews"][0]

        self.assertEqual(secret_preview["status"], "secret-content")
        self.assertEqual(secret_preview["code"], "")
        self.assertTrue(secret_preview["message"])
        self.assertNotIn("not-a-real-key", json.dumps(secret_snapshot))

        ordinary = self.root / "src" / "ordinary.py"
        ordinary.write_text("def available():\n    return True\n")
        missing_snapshot = self.build_source_snapshot(
            "repo:src/ordinary.py#def unavailable"
        )
        missing_preview = missing_snapshot["sourcePreviews"][0]

        self.assertEqual(missing_preview["status"], "anchor-missing")
        self.assertEqual(missing_preview["code"], "")
        self.assertIsNone(missing_preview["startLine"])
        self.assertIsNone(missing_preview["endLine"])
        self.assertTrue(missing_preview["message"])


if __name__ == "__main__":
    unittest.main()
