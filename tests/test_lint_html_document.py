"""Black-box contracts for the mechanical minimum lint of HTML documents."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "scripts/lint-html-document.py"
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"


def page(body="", head="", css="", kind="html-document", h1="<h1>題名</h1>", csp=CSP):
    policy = f'<meta http-equiv="Content-Security-Policy" content="{csp}">' if csp else ""
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{policy}
<meta name="artifact-kind" content="{kind}">
{head}
<title>文書</title>
<style>{css}</style>
</head>
<body><main>{h1}{body}</main></body>
</html>
"""


TABLE = '<table><tr><th scope="col">項目</th></tr><tr><td>値</td></tr></table>'
SVG_TEXT = '<svg viewBox="0 0 10 10"><text x="1" y="5" {attrs}>語</text></svg>'


class LintHtmlDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def lint(self, *documents):
        paths = []
        for index, document in enumerate(documents):
            path = self.directory / f"doc{index}.html"
            path.write_text(document, encoding="utf-8")
            paths.append(str(path))
        done = subprocess.run([sys.executable, str(CLI), *paths], capture_output=True, text=True)
        self.assertEqual(done.stderr, "")
        return done.returncode, done.stdout

    def assert_error(self, document, code):
        status, out = self.lint(document)
        self.assertEqual(status, 1, out)
        self.assertIn(f"誤り {code}:", out)

    def assert_clean(self, document, checks=0):
        status, out = self.lint(document)
        self.assertEqual(status, 0, out)
        self.assertIn(f"誤り 0 件、要確認 {checks} 件", out)
        return out

    def test_should_pass_a_document_that_meets_the_minimum(self):
        out = self.assert_clean(page("<p>本文</p>", css=".a{color:red}"))
        self.assertIn("機械で数えられる項目だけ", out)

    def test_should_report_errors_of_the_existing_contract(self):
        self.assert_error(page(csp=""), "csp-missing")
        self.assert_error(page('<p id="a">1</p><p id="a">2</p>'), "duplicate-id")

    def test_should_reject_tables_without_a_stated_reason(self):
        self.assert_error(page(TABLE), "table")

    def test_should_downgrade_tables_with_a_reason_and_scoped_headers(self):
        out = self.assert_clean(page(TABLE, head='<meta name="table-exception" content="時系列の数値を並べるため">'), checks=1)
        self.assertIn("要確認 table:", out)
        self.assertIn("時系列の数値を並べるため", out)

    def test_should_require_scope_on_table_headers(self):
        unscoped = TABLE.replace(' scope="col"', "")
        self.assert_error(page(unscoped, head='<meta name="table-exception" content="理由">'), "th-scope")

    def test_should_require_exactly_one_h1(self):
        self.assert_error(page(h1=""), "h1-count")
        self.assert_error(page(h1="<h1>一</h1><h1>二</h1>"), "h1-count")

    def test_should_reject_scripts_without_a_stated_reason(self):
        script = "<script>document.title = 'x'</script>"
        self.assert_error(page(script), "script")
        out = self.assert_clean(page(script, head='<meta name="script-exception" content="絞り込みに要る">'), checks=1)
        self.assertIn("要確認 script:", out)

    def test_should_reject_text_labels_in_pseudo_elements(self):
        self.assert_error(page(css='.new::before{content:"追加"}'), "pseudo-content")
        self.assert_error(page(css="@media (min-width:600px){ .a, .b:after { color:red; content: 'New' } }"), "pseudo-content")
        self.assert_error(page(css='.d::after{content:"(" "注" ")"}'), "pseudo-content")
        status, out = self.lint(page(css='.c::before{content:"\\65B0"}'))
        self.assertEqual(status, 1, out)
        self.assertIn("文字「新」", out)

    def test_should_flag_counters_and_attributes_in_pseudo_elements_for_review(self):
        out = self.assert_clean(page(css=".step::before{content:counter(step)} .tip::after{content:attr(data-label)}"), checks=2)
        self.assertIn("counter()", out)
        self.assertIn("attr()", out)

    def test_should_allow_symbols_and_empty_content_in_pseudo_elements(self):
        css = '.a::before{content:""} .b::after{content:"▶"} .c::before{content:"\\21A9"} /* .d::before{content:"旧"} */ .e::after{content:"(" "→" ")"}'
        self.assert_clean(page(css=css))

    def test_should_reject_fill_attributes_overridden_by_css(self):
        status, out = self.lint(page(SVG_TEXT.format(attrs='fill="#f00"'), css="svg text{fill:#111}"))
        self.assertEqual(status, 1, out)
        self.assertIn("誤り svg-text-fill:", out)
        self.assertIn("svg text", out)

    def test_should_only_flag_fill_attributes_for_review_without_overriding_css(self):
        out = self.assert_clean(page(SVG_TEXT.format(attrs='fill="#f00"'), css="svg text.note{font-size:12px} .box{fill:#eee}"), checks=1)
        self.assertIn("要確認 svg-text-fill:", out)

    def test_should_not_call_scoped_fill_rules_an_error(self):
        # 範囲つきの規則は、どの text に当たるかを追わないので「要確認」にとどめる。
        out = self.assert_clean(page(SVG_TEXT.format(attrs='fill="#f00"'), css=".scene text{fill:#111}"), checks=1)
        self.assertIn(".scene text", out)
        self.assert_error(page(SVG_TEXT.format(attrs='fill="#f00"'), css="svg > g  text{fill:#111}"), "svg-text-fill")

    def test_should_pass_svg_text_coloured_by_class(self):
        self.assert_clean(page(SVG_TEXT.format(attrs='class="ink"'), css="svg text{fill:#111} .ink{fill:#222}"))

    def test_should_skip_artifacts_owned_by_other_skills(self):
        for kind, owner in (("session-dashboard", "session-dashboard"), ("html-plan", "viewing-plans"), ("html-prototype", "designing-ui-ux")):
            with self.subTest(kind):
                status, out = self.lint(page(TABLE, kind=kind))
                self.assertEqual(status, 0, out)
                self.assertIn(f"対象外（artifact-kind「{kind}」は {owner} の成果物）", out)

    def test_should_lint_every_document_type_of_this_skill(self):
        for kind in ("html-document", "technical-explainer", "research-report", "screen-diff"):
            with self.subTest(kind):
                self.assert_error(page(TABLE, kind=kind), "table")

    def test_should_fail_when_any_file_fails_and_report_every_file(self):
        status, out = self.lint(page("<p>本文</p>"), page(TABLE))
        self.assertEqual(status, 1)
        self.assertIn("doc0.html: 誤り 0 件", out)
        self.assertIn("doc1.html: 誤り 1 件", out)

    def test_should_fail_for_an_unreadable_file(self):
        done = subprocess.run([sys.executable, str(CLI), str(self.directory / "missing.html")], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("読めない", done.stdout)


if __name__ == "__main__":
    unittest.main()
