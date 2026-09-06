from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("standalone_generator", ROOT / "scripts/generate-roadmap-view.py")
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def plan_html() -> str:
    return """<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="artifact-kind" content="html-plan">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>自己完結した計画書</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; color: #18211c; background: #f4f6f2; font: 16px/1.7 system-ui; }
main { max-width: 1080px; padding: 24px; margin: auto; }
.authored-layout { display: grid; grid-template-columns: 1fr 2fr; gap: 24px; }
.authored-layout > section { min-width: 0; background: #fff; padding: 24px; border: 1px solid #cdd7cf; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
a { color: #174936; }
a:focus-visible { outline: 3px solid #245fa6; outline-offset: 3px; }
@media(max-width: 760px) { .authored-layout { grid-template-columns: 1fr; } }
@media(forced-colors: active) { .authored-layout > section { border-color: CanvasText; } }
@media(prefers-reduced-motion: reduce) { * { animation: none; transition: none; } }
</style></head><body>
<main id="plan-document" data-plan-schema="2">
<h1 data-plan-title>自己完結した計画書</h1>
<p data-plan-intro>判断に必要な背景と実装の根拠を、一つの文書で確認する。</p>
<a href="#implementation">実装内容へ</a>
<section data-task-id="1" data-ui-change="false">
<h2>計画書を直接表示する</h2>
<div class="authored-layout">
<section data-field="purpose"><h3>WHY</h3><p>本文のレイアウトを保存したまま読めるようにする。</p></section>
<section id="implementation" data-field="implementation"><h3>実装</h3>
<ul><li>検査したHTMLをそのまま配布する。</li></ul>
<pre><code>document = read_plan()
validate(document)
publish(document)</code></pre></section>
</div>
<section data-field="targets"><h3>対象</h3><p>scripts/generate-roadmap-view.py</p></section>
<section data-field="outputs"><h3>成果物</h3><p>単体で開けるHTML。</p></section>
<section data-field="verification"><h3>検証</h3><p>元のHTMLと配布HTMLで本文とCSSが一致する。</p></section>
</section></main></body></html>
"""


class StandalonePlanTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = Path(self.temp.name) / "task"
        self.task.mkdir()
        self.source = self.task / "30_plan.html"
        self.source.write_text(plan_html(), encoding="utf-8")
        self.output = self.task / "roadmap.html"

    def test_publication_preserves_authored_document_without_viewer(self):
        with mock.patch.object(generator, "TEMPLATE", self.task / "missing-template.html"), mock.patch.object(
            generator, "load_codemap_state", side_effect=AssertionError("Code Map must not be loaded"), create=True
        ), mock.patch.object(generator, "build_archify_payload", side_effect=AssertionError("Task graph must not be rendered"), create=True):
            snapshot = generator.write_outputs(self.task, self.output, True, source_root=self.task)
        rendered = self.output.read_text()
        restored = generator.EMBEDDED_SNAPSHOT_RE.sub("", rendered).replace("\n</body>", "</body>")
        self.assertEqual(restored, plan_html())
        self.assertEqual(self.source.read_text(), plan_html())
        self.assertEqual(snapshot["renderMode"], "standalone")
        self.assertNotIn("task-appendix", rendered)
        self.assertNotIn("Code Map", rendered)
        self.assertNotIn("renderPlanDocument", rendered)
        self.assertEqual(generator.read_html_snapshot(self.output), generator.read_json_snapshot(self.task / "roadmap-snapshot.json"))

    def test_retired_codemap_does_not_affect_freshness(self):
        before = generator.build_snapshot(self.task, source_root=self.task)
        (self.task / "codemap.json").write_text("not valid JSON")
        (self.task / "codemap.lock").write_text("stale")
        after = generator.build_snapshot(self.task, source_root=self.task)
        self.assertEqual(before["fingerprint"], after["fingerprint"])
        self.assertEqual(after["codemapStatus"], "not-applicable")

    def test_missing_csp_gets_non_executable_policy(self):
        self.source.write_text(re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', '', plan_html()))
        generator.write_outputs(self.task, self.output, True, source_root=self.task)
        rendered = self.output.read_text()
        self.assertIn("script-src 'none'", rendered)
        self.assertIn("connect-src 'none'", rendered)
        self.assertNotIn("script-src 'unsafe-inline'", rendered)

    def test_generated_standalone_cannot_opt_into_legacy_script_policy(self):
        raw = plan_html().replace("script-src 'none'", "script-src 'unsafe-inline'")
        with self.assertRaisesRegex(ValueError, "static HTML contract"):
            generator.validate_roadmap_html(raw, self.output, standalone=True)
        raw = plan_html().replace('</body>', '<script>alert(1)</script></body>')
        with self.assertRaisesRegex(ValueError, "cannot execute scripts"):
            generator.validate_roadmap_html(raw, self.output, standalone=True)

    def test_snapshot_is_inert_even_with_script_end_in_text(self):
        snapshot = generator.build_snapshot(self.task, source_root=self.task)
        snapshot["title"] = '</script><script>alert("unexpected")</script>'
        rendered = generator.render_html(snapshot)
        self.assertNotIn('</script><script>alert', rendered)
        payload = generator.EMBEDDED_SNAPSHOT_RE.search(rendered).group(1)
        self.assertEqual(json.loads(payload)["title"], snapshot["title"])

    def test_hash_mismatch_is_rejected(self):
        snapshot = generator.build_snapshot(self.task, source_root=self.task)
        snapshot["files"]["30_plan.html"] = plan_html().replace("WHY", "Changed")
        with self.assertRaisesRegex(ValueError, "hash"):
            generator.render_html(snapshot)

    def test_declared_architecture_must_be_checked_before_publication(self):
        generator.write_outputs(self.task, self.output, True, source_root=self.task)
        old_output = self.output.read_bytes()
        fragment = '<script type="application/json" data-plan-fragment="diagram">{"version":1,"kind":"architecture","id":"implementation-architecture","title":"Actual components","nodes":[],"edges":[]}</script>'
        self.source.write_text(plan_html().replace('</section></main>', fragment + '</section></main>'))
        actual_loader = generator.load_plan_support
        checker = mock.Mock()
        checker.check_architecture.return_value = {"status": "invalid", "message": "図が未更新"}
        with mock.patch.object(generator, "load_plan_support", side_effect=lambda name: checker if name == "plan_architecture" else actual_loader(name)):
            with self.assertRaisesRegex(ValueError, "図が未更新"):
                generator.write_outputs(self.task, self.output, True, source_root=self.task)
        checker.check_architecture.assert_called_once_with(self.task)
        self.assertEqual(self.output.read_bytes(), old_output)
        checker.check_architecture.return_value = {"status": "verified", "sourceSha256": "0" * 64}
        with mock.patch.object(generator, "load_plan_support", side_effect=lambda name: checker if name == "plan_architecture" else actual_loader(name)):
            with self.assertRaisesRegex(ValueError, "検査中に計画HTMLが変更"):
                generator.write_outputs(self.task, self.output, True, source_root=self.task)
        self.assertEqual(self.output.read_bytes(), old_output)

    def test_invalid_source_keeps_published_pair(self):
        generator.write_outputs(self.task, self.output, True, source_root=self.task)
        old_html = self.output.read_bytes()
        old_json = (self.task / "roadmap-snapshot.json").read_bytes()
        self.source.write_text(plan_html().replace("<h1 data-plan-title>", '<h1 onclick="alert(1)" data-plan-title>'))
        with self.assertRaises(ValueError):
            generator.write_outputs(self.task, self.output, True, source_root=self.task)
        self.assertEqual(self.output.read_bytes(), old_html)
        self.assertEqual((self.task / "roadmap-snapshot.json").read_bytes(), old_json)

    def test_source_changed_after_snapshot_does_not_publish(self):
        generator.write_outputs(self.task, self.output, True, source_root=self.task)
        previous = self.output.read_bytes()
        build = generator.build_snapshot
        def replacing_source(*args, **kwargs):
            snapshot = build(*args, **kwargs)
            self.source.write_text(plan_html().replace("WHY", "Changed"))
            return snapshot
        with mock.patch.object(generator, "build_snapshot", side_effect=replacing_source):
            with self.assertRaisesRegex(ValueError, "source changed"):
                generator.write_outputs(self.task, self.output, True, source_root=self.task)
        self.assertEqual(self.output.read_bytes(), previous)

    def test_fragment_is_not_published_as_complete_document(self):
        raw = '<main><h1>Incomplete</h1><p>No complete document.</p></main>'
        snapshot = {"planSource": "30_plan.html", "files": {"30_plan.html": raw}, "planSourceRawSha256": hashlib.sha256(raw.encode()).hexdigest()}
        with self.assertRaisesRegex(ValueError, "完成したHTML"):
            generator.render_html(snapshot)


if __name__ == "__main__":
    unittest.main()
