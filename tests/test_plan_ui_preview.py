from __future__ import annotations

import base64
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN = load_module("roadmap_plan_contract_for_ui_preview", ROOT / "scripts" / "roadmap_plan_contract.py")
UI = load_module("plan_ui_preview", ROOT / "scripts" / "plan_ui_preview.py")


BASE_SHA = "0123456789abcdef0123456789abcdef01234567"
PNG_DATA = "data:image/png;base64,iVBORw0KGgo="


class GeneratorDouble:
    def __init__(self, *, status: str = "resolved", code: str = "Roadmap PLAN DOCUMENT 計画本文") -> None:
        self.status = status
        self.code = code
        self.calls: list[tuple[str, str, str]] = []
        self.last_kwargs: dict[str, object] = {}

    def normalize_source_prefixes(self, values):
        return tuple(values or ())

    def extract_git_source_preview(self, task_number, reference, **kwargs):
        self.last_kwargs = kwargs
        self.calls.append((str(task_number), str(reference), str(kwargs.get("evidence_revision"))))
        return {
            "status": self.status,
            "code": self.code if self.status == "resolved" else "",
            "message": "fixture source unavailable" if self.status != "resolved" else "",
        }


def html_source(preview_json: str, *, second_task: str = "") -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>UI preview plan</title>
<style>main {{ display: grid; gap: 1rem; scroll-behavior:auto; }} .mock {{ border: 1px solid #ccc; }}</style></head>
<body><main id="plan-document" data-plan-schema="2">
<h1 data-plan-title>UI preview plan</h1>
<section id="task-1" data-task-id="1" data-status="planned" data-ui-change="true">
<h2>Task 1: Source-backed mocks</h2>
<h3 data-field="purpose">目的</h3><p>既存画面の変更を確認する。</p>
<h3 data-field="targets">変更対象</h3><p>tools/roadmap_viewer.html</p>
<h3 data-field="implementation">実装</h3><ul><li data-step-index="1">mockを記録する。</li></ul>
<h3 data-field="outputs">成果物</h3><p>UI mock</p>
<h3 data-field="verification">検証</h3><p>sourceを照合する。</p>
<div id="mock-before-1" class="mock" data-ui-side="before"><nav aria-label="main navigation"><span>Roadmap</span></nav>
  <button type="button" disabled>更新</button><input type="search" disabled placeholder="検索">
  <select disabled><option selected>現在地</option></select><textarea disabled>計画本文</textarea>
  <img alt="architecture" src="{PNG_DATA}">
</div>
<div id="mock-after-1" class="mock" data-ui-side="after"><nav><span>Roadmap</span><span>レビュー</span></nav>
  <button type="button" disabled>更新</button><p>計画案・未実装</p></div>
<script type="application/json" data-plan-fragment="ui-preview">{preview_json}</script>
</section>
{second_task}
</main></body></html>"""


def valid_preview(*, task: str = "1", before: str | None = "mock-before-1", base_ref: str | None = BASE_SHA) -> str:
    before_payload = {"observedLabels": ["Roadmap", "計画本文"]}
    if before is not None:
        before_payload["source"] = "repo:tools/roadmap_viewer.html#L1-L20"
        before_payload["baseRef"] = base_ref
    return (
        '{"version":2,"taskNumber":"%s","previews":[{"id":"roadmap-shell",'
        '"title":"Roadmap shell",'
        '"provenance":{"before":%s,"after":{"source":"Task %s 実装"}},'
        '"before":{"anchor":%s},"after":{"anchor":"mock-after-1"},'
        '"uncertainty":[]}]}'
        % (
            task,
            json.dumps(before_payload, ensure_ascii=False, separators=(",", ":")),
            task,
            json.dumps(before),
        )
    )


class PlanUiPreviewTest(unittest.TestCase):
    def parse(self, payload: str, *, source: str | None = None, second_task: str = ""):
        return PLAN.parse_html_plan_contract(
            html_source(payload, second_task=second_task).encode("utf-8"),
            plan_source=source or "30_plan.html",
        )

    def test_collects_v2_metadata_and_preserves_nested_dom_controls(self) -> None:
        model = self.parse(valid_preview())
        document = model["planDocument"]
        rendered = str(document)
        self.assertIn("mock-before-1", rendered)
        self.assertIn("mock-after-1", rendered)
        self.assertIn('data-ui-side', rendered)
        self.assertIn('data-ui-control', rendered)
        generator = GeneratorDouble()

        result = UI.collect_html_ui_previews(
            model,
            generator=generator,
            source_root=ROOT,
            source_allow_prefixes=["tools"],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["version"], 2)
        self.assertEqual(result[0]["taskNumber"], "1")
        self.assertEqual(result[0]["before"], {"anchor": "mock-before-1"})
        self.assertEqual(result[0]["after"], {"anchor": "mock-after-1"})
        self.assertNotIn("items", result[0])
        self.assertNotIn("layout", result[0])
        self.assertEqual(generator.calls[0][2], BASE_SHA)
        self.assertEqual(generator.last_kwargs["max_lines"], 256)
        self.assertEqual(generator.last_kwargs["max_bytes"], 64 * 1024)

    def test_scroll_behavior_is_not_misclassified_as_legacy_behavior(self) -> None:
        # The real standalone plan uses this harmless CSS property in its
        # head stylesheet.  The unsafe legacy `behavior:` property must still
        # be rejected while the hyphenated property remains valid.
        model = self.parse(valid_preview())
        self.assertEqual(model["sourceKind"], "html")
        unsafe = html_source(valid_preview()).replace("scroll-behavior:auto", "behavior:auto")
        with self.assertRaisesRegex(PLAN.PlanContractError, "unsafe construct"):
            PLAN.parse_html_plan_contract(unsafe.encode("utf-8"))

    def test_existing_csp_is_optional_but_narrow_and_unique(self) -> None:
        policy = (
            "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; "
            "img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
        )
        meta = f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
        valid = html_source(valid_preview()).replace('<meta charset="utf-8">', '<meta charset="utf-8">' + meta)
        self.assertEqual(PLAN.parse_html_plan_contract(valid.encode("utf-8"))["sourceKind"], "html")

        inherited = html_source(valid_preview()).replace(
            '<meta charset="utf-8">',
            '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'none\'; img-src \'none\'">',
        )
        self.assertEqual(PLAN.parse_html_plan_contract(inherited.encode("utf-8"))["sourceKind"], "html")

        invalid_policies = (
            "default-src 'self'",
            "default-src 'none'; script-src 'unsafe-inline'",
            "default-src 'none'; style-src https:",
            "default-src 'none'; img-src https:",
            "default-src 'none'; connect-src 'self'",
            "default-src 'none'; report-uri https://example.test/csp",
            "default-src 'none'; custom-src 'none'",
        )
        for invalid_policy in invalid_policies:
            with self.subTest(policy=invalid_policy):
                invalid = html_source(valid_preview()).replace(
                    '<meta charset="utf-8">',
                    '<meta charset="utf-8">' + f'<meta http-equiv="Content-Security-Policy" content="{invalid_policy}">',
                )
                with self.assertRaisesRegex(PLAN.PlanContractError, "Content-Security-Policy"):
                    PLAN.parse_html_plan_contract(invalid.encode("utf-8"))

        duplicate = valid.replace(meta, meta + meta, 1)
        with self.assertRaisesRegex(PLAN.PlanContractError, "duplicate Content-Security-Policy"):
            PLAN.parse_html_plan_contract(duplicate.encode("utf-8"))

    def test_new_screen_is_after_only_and_does_not_read_before_source(self) -> None:
        new_task = """<section id="task-2" data-task-id="2" data-status="planned" data-ui-change="true">
<h2>Task 2: New screen</h2><h3 data-field="purpose">目的</h3><p>新画面を追加する。</p>
<h3 data-field="targets">変更対象</h3><p>app/page.tsx</p><h3 data-field="implementation">実装</h3><p>追加する。</p>
<h3 data-field="outputs">成果物</h3><p>画面</p><h3 data-field="verification">検証</h3><p>確認する。</p>
<div id="new-screen-after" data-ui-side="after"><h3>計画案・未実装</h3><p>監査ログ</p></div>
<script type="application/json" data-plan-fragment="ui-preview">{"version":2,"taskNumber":"2","previews":[{"id":"new-screen","title":"Audit log","provenance":{"before":{"observedLabels":[]},"after":{"source":"Task 2 実装"}},"before":{"anchor":null},"after":{"anchor":"new-screen-after"},"uncertainty":[]}]}</script>
</section>"""
        model = self.parse(valid_preview(), second_task=new_task)
        generator = GeneratorDouble()
        result = UI.collect_html_ui_previews(model, generator=generator, source_root=ROOT)

        self.assertEqual([item["taskNumber"] for item in result], ["1", "2"])
        self.assertEqual(result[1]["before"], {"anchor": None})
        self.assertEqual(result[1]["after"], {"anchor": "new-screen-after"})
        self.assertEqual(len(generator.calls), 1)

    def test_after_only_preview_cannot_claim_unbacked_before_labels(self) -> None:
        payload = valid_preview(task="1", before=None, base_ref=None).replace(
            '"observedLabels":[]', '"observedLabels":["Legacy"]'
        )
        model = self.parse(payload)
        with self.assertRaisesRegex(ValueError, "observedLabels.*source"):
            UI.collect_html_ui_previews(model, generator=GeneratorDouble(), source_root=ROOT)

    def test_fixed_sha_and_source_availability_are_required(self) -> None:
        invalid_sha = valid_preview(base_ref="not-a-sha")
        with self.assertRaisesRegex(ValueError, "baseRef.*40"):
            UI.collect_html_ui_previews(self.parse(invalid_sha), generator=GeneratorDouble(), source_root=ROOT)
        mismatch = self.parse(valid_preview())
        with self.assertRaisesRegex(ValueError, "does not match"):
            UI.collect_html_ui_previews(mismatch, generator=GeneratorDouble(), source_root=ROOT, base_ref="f" * 40)
        unavailable = self.parse(valid_preview())
        with self.assertRaisesRegex(ValueError, "unavailable"):
            UI.collect_html_ui_previews(
                unavailable,
                generator=GeneratorDouble(status="source-missing"),
                source_root=ROOT,
            )

    def test_cli_sha_can_supply_implicit_before_revision(self) -> None:
        payload = valid_preview().replace(f',"baseRef":"{BASE_SHA}"', "")
        model = self.parse(payload)
        generator = GeneratorDouble()
        result = UI.collect_html_ui_previews(
            model, generator=generator, source_root=ROOT, base_ref=BASE_SHA
        )
        self.assertEqual(result[0]["provenance"]["before"]["baseRef"], BASE_SHA)

    def test_missing_wrong_task_and_duplicate_anchors_fail(self) -> None:
        missing = self.parse(valid_preview(before="does-not-exist"))
        with self.assertRaisesRegex(ValueError, "anchor.*missing"):
            UI.collect_html_ui_previews(missing, generator=GeneratorDouble(), source_root=ROOT)
        wrong_side_payload = valid_preview(before="wrong-side")
        wrong_side_html = html_source(wrong_side_payload).replace(
            'id="mock-before-1" class="mock" data-ui-side="before"',
            'id="wrong-side" class="mock" data-ui-side="after"',
        )
        wrong_side = PLAN.parse_html_plan_contract(wrong_side_html.encode("utf-8"))
        with self.assertRaisesRegex(ValueError, "wrong data-ui-side"):
            UI.collect_html_ui_previews(wrong_side, generator=GeneratorDouble(), source_root=ROOT)
        wrong_task_payload = valid_preview().replace('"after":{"anchor":"mock-after-1"}', '"after":{"anchor":"task-1"}')
        wrong_task = self.parse(wrong_task_payload)
        with self.assertRaisesRegex(ValueError, "wrong data-ui-side|empty mock"):
            UI.collect_html_ui_previews(wrong_task, generator=GeneratorDouble(), source_root=ROOT)

    def test_active_controls_and_v1_items_remain_separate(self) -> None:
        active = html_source(valid_preview()).replace('<button type="button" disabled>更新</button>', '<button type="button">更新</button>')
        with self.assertRaisesRegex(PLAN.PlanContractError, "button.*disabled"):
            PLAN.parse_html_plan_contract(active.encode("utf-8"))
        legacy = self.parse(
            '{"version":1,"taskNumber":"1","previews":[{"id":"legacy","title":"Legacy","layout":"list","provenance":{"before":{"observedLabels":[]},"after":{"source":"Task 1"}},"before":{"items":[]},"after":{"items":[]}}]}'
        )
        self.assertEqual(UI.collect_html_ui_previews(legacy, generator=GeneratorDouble(), source_root=ROOT), [])

    def test_unsafe_embedded_svg_is_rejected(self) -> None:
        svg = "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxwYXRoIGQ9Ik0wIDAiLz48L3N2Zz4="
        unsafe = html_source(valid_preview()).replace(PNG_DATA, "data:image/svg+xml;base64," + svg)
        self.assertEqual(PLAN.parse_html_plan_contract(unsafe.encode("utf-8"))["tasks"][0]["number"], "1")
        active_svg = svg.replace("PjxwYXRo", "PjxzY3JpcHQ+YWxlcnQoMSk8L3NjcmlwdD48cGF0aA=")
        # Keep this assertion focused on the contract rather than relying on
        # browser behavior for an embedded image.
        bad = html_source(valid_preview()).replace(PNG_DATA, "data:image/svg+xml;base64," + active_svg)
        with self.assertRaises(PLAN.PlanContractError):
            PLAN.parse_html_plan_contract(bad.encode("utf-8"))

    def test_embedded_image_limit_is_decoded_bytes_not_generic_attr_length(self) -> None:
        svg_prefix = '<svg xmlns="http://www.w3.org/2000/svg"><text>'
        svg_suffix = "</text></svg>"
        large_svg = (svg_prefix + ("x" * 9000) + svg_suffix).encode("utf-8")
        large_data = "data:image/svg+xml;base64," + base64.b64encode(large_svg).decode("ascii")
        accepted = html_source(valid_preview()).replace(PNG_DATA, large_data)
        self.assertEqual(PLAN.parse_html_plan_contract(accepted.encode("utf-8"))["sourceKind"], "html")

        oversized_svg = (svg_prefix + ("x" * (PLAN.HTML_MAX_IMAGE_BYTES + 1)) + svg_suffix).encode("utf-8")
        oversized_data = "data:image/svg+xml;base64," + base64.b64encode(oversized_svg).decode("ascii")
        rejected = html_source(valid_preview()).replace(PNG_DATA, oversized_data)
        with self.assertRaisesRegex(PLAN.PlanContractError, "exceeds"):
            PLAN.parse_html_plan_contract(rejected.encode("utf-8"))

        long_class = html_source(valid_preview()).replace(
            'class="mock"', 'class="' + ("x" * 8193) + '"', 1
        )
        with self.assertRaisesRegex(PLAN.PlanContractError, "attribute value"):
            PLAN.parse_html_plan_contract(long_class.encode("utf-8"))

    def test_embedded_svg_allows_only_local_font_faces(self) -> None:
        safe_font = """<svg xmlns="http://www.w3.org/2000/svg"><style>
@font-face { font-family: 'JetBrains Mono'; font-weight: 400; src: local('JetBrains Mono'), local('JetBrainsMono-Regular'); }
svg { font-family: 'JetBrains Mono'; }
</style><text>Architecture</text></svg>""".encode("utf-8")
        safe_data = "data:image/svg+xml;base64," + base64.b64encode(safe_font).decode("ascii")
        safe_html = html_source(valid_preview()).replace(PNG_DATA, safe_data)
        self.assertEqual(PLAN.parse_html_plan_contract(safe_html.encode("utf-8"))["sourceKind"], "html")

        unsafe_font = safe_font.replace(
            b"local('JetBrains Mono'), local('JetBrainsMono-Regular')",
            b"url(https://example.test/font.woff2)",
        )
        unsafe_data = "data:image/svg+xml;base64," + base64.b64encode(unsafe_font).decode("ascii")
        with self.assertRaisesRegex(PLAN.PlanContractError, "external resources"):
            PLAN.parse_html_plan_contract(
                html_source(valid_preview()).replace(PNG_DATA, unsafe_data).encode("utf-8")
            )

    def test_embedded_svg_rejects_processing_instructions(self) -> None:
        svg = b'''<svg xmlns="http://www.w3.org/2000/svg"><text>Architecture</text></svg>'''
        xml_decl = b'''<?xml version="1.0" encoding="UTF-8"?>''' + svg
        accepted = html_source(valid_preview()).replace(
            PNG_DATA,
            "data:image/svg+xml;base64," + base64.b64encode(xml_decl).decode("ascii"),
        )
        self.assertEqual(PLAN.parse_html_plan_contract(accepted.encode("utf-8"))["sourceKind"], "html")

        stylesheet_pi = b'''<svg xmlns="http://www.w3.org/2000/svg"><?xml-stylesheet href="https://example.test/style.css"?><text>Architecture</text></svg>'''
        rejected = html_source(valid_preview()).replace(
            PNG_DATA,
            "data:image/svg+xml;base64," + base64.b64encode(stylesheet_pi).decode("ascii"),
        )
        with self.assertRaisesRegex(PLAN.PlanContractError, "processing instructions"):
            PLAN.parse_html_plan_contract(rejected.encode("utf-8"))

    def test_real_archify_svg_sample_is_accepted(self) -> None:
        sample = ROOT / ".local" / "memory" / "260906_standalone-visual-plan" / "30_plan.html"
        if not sample.is_file():
            self.skipTest("standalone plan sample is unavailable")
        model = PLAN.parse_html_plan_contract(sample.read_bytes(), plan_source=str(sample))
        self.assertEqual(model["sourceKind"], "html")


if __name__ == "__main__":
    unittest.main()
