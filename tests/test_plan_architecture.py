from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("plan_architecture_under_test", ROOT / "scripts" / "plan_architecture.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


ARCH = {
    "version": 1,
    "kind": "architecture",
    "id": "implementation-architecture",
    "title": "Implementation data flow",
    "lanes": [{"id": "runtime", "label": "Runtime"}],
    "nodes": [
        {"id": "plan", "label": "Plan document", "responsibility": "canonical source", "col": 0},
        {"id": "validator", "label": "Validator", "contract": "verified", "col": 1},
        {"id": "svg", "label": "Embedded SVG", "type": "frontend", "col": 2},
    ],
    "edges": [
        {"from": "plan", "to": "validator", "label": "parse"},
        {"from": "validator", "to": "svg", "label": "render"},
    ],
}
RAW_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect x="1" y="1" width="20" height="20"/></svg>'


class FakeAdapter:
    RENDER_DEADLINE = 2

    def __init__(self) -> None:
        self.calls = 0

    def _load_config(self):
        return "a" * 40, {"seccompSha256": "b" * 64}

    def _invoke_renderer(self, *_args, **_kwargs):
        self.calls += 1
        return {"status": "verified", "diagramType": "workflow"}, RAW_SVG

    def _validate_svg(self, raw):
        return raw.decode("utf-8"), "geometry"

    def _finalize_svg(self, text, _spec, geometry):
        return text.encode("utf-8"), geometry

    def _require_final_svg_metadata(self, _raw):
        return None

    def archify_for_spec(self, spec, digest, *, cache_only=False):
        if hasattr(self, "cached"):
            return self.cached
        self._invoke_renderer(None)
        self.cached = {"status": "verified", "revision": "a" * 40, "overview": {"diagramType": "workflow", "svg": RAW_SVG.decode(), "svgSha256": MODULE._sha256(RAW_SVG)}}
        return self.cached


class PlanArchitectureTests(unittest.TestCase):
    def test_actual_parser_delivers_the_explicit_diagram_fragment(self):
        fragment = json.dumps(ARCH, ensure_ascii=False, separators=(",", ":"))
        document = (
            '<!doctype html><html><head><meta charset="utf-8"><title>Plan</title></head><body>'
            '<main id="plan-document" data-plan-schema="2"><h1>Plan</h1>'
            '<section data-task-id="1"><h2>Task 1: Architecture</h2><p>body</p>'
            '<section data-field="purpose"><p>why</p></section>'
            '<section data-field="targets"><p>target</p></section>'
            '<section data-field="implementation"><p>implementation</p></section>'
            '<section data-field="outputs"><p>output</p></section>'
            '<section data-field="verification"><p>verification</p></section>'
            '<figure id="implementation-architecture"></figure>'
            '<script type="application/json" data-plan-fragment="diagram">'
            + fragment
            + '</script></section></main></body></html>'
        ).encode("utf-8")
        parsed = MODULE._parser().parse_html_plan_contract(document)
        self.assertNotIn("diagramBlocks", parsed["tasks"][0])
        block, spec, digest = MODULE.prepare_architecture(parsed)
        self.assertEqual(block, ARCH)
        self.assertEqual(len(spec["nodes"]), 3)
        self.assertEqual(len(spec["edges"]), 2)
        self.assertEqual(digest, MODULE.architecture_digest(ARCH))

    def test_only_explicit_task_diagram_blocks_are_projected(self):
        model = {"tasks": [{"number": "1", "title": "A", "diagramData": [ARCH]}], "edges": [{"from": "1", "to": "2"}]}
        block, spec, digest = MODULE.prepare_architecture(model)
        self.assertEqual(block, ARCH)
        self.assertEqual(digest, MODULE.architecture_digest(ARCH))
        self.assertEqual([node["id"] for node in spec["nodes"]], ["plan", "validator", "svg"])
        self.assertEqual([edge["label"] for edge in spec["edges"]], ["parse", "render"])

        no_architecture = {"tasks": [{"number": "1", "title": "A"}], "edges": [{"from": "1", "to": "2"}]}
        self.assertEqual(MODULE.prepare_architecture(no_architecture), (None, None, None))

    def test_duplicate_or_malformed_architecture_is_rejected_without_task_fallback(self):
        with self.assertRaises(MODULE.ArchitectureError):
            MODULE.extract_architecture_block({"tasks": [{"diagramData": [ARCH]}, {"diagramData": [ARCH]}]})
        wrong_id = {**ARCH, "id": "other"}
        with self.assertRaises(MODULE.ArchitectureError):
            MODULE.extract_architecture_block({"tasks": [{"diagramData": [wrong_id]}]})
        malformed = {**ARCH, "edges": [{"from": "missing", "to": "svg"}]}
        with self.assertRaises(MODULE.ArchitectureError):
            MODULE.build_architecture_spec(malformed)

    def test_cycle_is_preserved_and_return_route_is_explicit(self):
        block = {**ARCH, "nodes": [{"id": "a", "label": "A", "col": 0}, {"id": "b", "label": "B", "col": 1}], "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}
        spec = MODULE.build_architecture_spec(block)
        self.assertEqual(len(spec["edges"]), 2)
        self.assertEqual(spec["edges"][1]["route"], "return-left")

    def test_renderer_cache_is_keyed_by_fragment_digest_only(self):
        fake = FakeAdapter()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(MODULE, "_ADAPTER", fake):
            first, first_meta = MODULE._render_verified(MODULE.build_architecture_spec(ARCH), MODULE.architecture_digest(ARCH))
            second, second_meta = MODULE._render_verified(MODULE.build_architecture_spec(ARCH), MODULE.architecture_digest(ARCH))
            self.assertEqual(first, second)
            self.assertEqual(fake.calls, 1)
            self.assertTrue(first_meta["cache"])
            self.assertTrue(second_meta["cache"])

    def test_update_replaces_only_figure_content_and_check_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "30_plan.html"
            source = '<main><script type="application/json" data-plan-fragment="diagram">{"kept":true}</script><figure id="implementation-architecture"><p>placeholder</p></figure></main>'
            path.write_text(source, encoding="utf-8")
            model = {"tasks": [{"number": "1", "title": "A", "diagramData": [ARCH]}]}
            fake_meta = {"revision": "a" * 40, "digest": MODULE.architecture_digest(ARCH), "architectureSha256": MODULE.architecture_digest(ARCH), "svgSha256": MODULE._sha256(RAW_SVG), "svgBytes": len(RAW_SVG), "cache": False}
            with mock.patch.object(MODULE, "_read_plan", return_value=(path, source.encode(), model)), mock.patch.object(MODULE, "_render_verified", return_value=(RAW_SVG, fake_meta)):
                result = MODULE.update_plan_architecture(directory)
            updated = path.read_text(encoding="utf-8")
            self.assertEqual(result["status"], "verified")
            self.assertIn('data-plan-fragment="diagram">{"kept":true}', updated)
            self.assertIn("data:image/svg+xml;base64,", updated)

            before = path.read_bytes()
            updated_model = {"tasks": [{"number": "1", "title": "A", "diagramData": [ARCH]}]}
            with mock.patch.object(MODULE, "_read_plan", return_value=(path, before, updated_model)), mock.patch.object(MODULE, "_render_verified", return_value=(RAW_SVG, fake_meta)):
                checked = MODULE.check_architecture(directory)
            self.assertEqual(checked["status"], "verified")
            self.assertEqual(path.read_bytes(), before)

    def test_cli_reports_no_architecture_without_generating_a_task_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "30_plan.html"
            path.write_text("<main><h1>Plan</h1><figure id=\"implementation-architecture\"></figure></main>", encoding="utf-8")
            # The CLI reaches the canonical parser first; no fragment is a
            # successful no-op and does not invoke Docker or the renderer.
            result = subprocess.run(["python3", str(ROOT / "scripts" / "plan_architecture.py"), directory], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["status"], "none")


if __name__ == "__main__":
    unittest.main()
