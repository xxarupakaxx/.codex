"""Black-box contracts for the element-level change list of two HTML files."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "scripts/html-change-list.py"

BASE = """<!doctype html><html lang="ja"><head><title>請求書</title>
<style>.card{color:#111} .muted{color:#777}</style></head><body>
<h1>請求書の作成</h1>
<section id="pay"><h2>支払方法</h2>
<label class="opt">銀行振込</label>
<label class="opt">カード決済</label>
<p class="muted">期日は月末です。</p></section>
<section id="list"><h2>一覧</h2><ul><li>送付済み</li><li>入金済み</li></ul></section>
</body></html>"""


class HtmlChangeListTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def changes(self, after, before=BASE, *options):
        old, new = self.directory / "before.html", self.directory / "after.html"
        old.write_text(before, encoding="utf-8")
        new.write_text(after, encoding="utf-8")
        done = subprocess.run([sys.executable, str(CLI), *options, str(old), str(new)], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        return done.stdout

    def test_should_report_no_change_for_identical_documents(self):
        self.assertEqual(self.changes(BASE).strip(), "[html-change] 変更なし")
        self.assertEqual(self.changes(BASE.replace("\n", "\n\n  ")).strip(), "[html-change] 変更なし")

    def test_should_list_an_added_element_under_its_section(self):
        out = self.changes(BASE.replace('<p class="muted">', '<label class="opt">かけ払い</label>\n<p class="muted">'))
        self.assertIn("要素: 追加 1、削除 0、文言の変更 0、属性だけの変更 0、文言と属性の変更 0", out)
        self.assertIn("## #pay 「支払方法」\n- 追加 <label.opt> かけ払い", out)
        self.assertNotIn("#list", out)

    def test_should_list_a_removed_element(self):
        out = self.changes(BASE.replace("<li>入金済み</li>", ""))
        self.assertIn("削除 1", out)
        self.assertIn("## #list 「一覧」\n- 削除 <li> 入金済み", out)

    def test_should_separate_wording_changes_from_attribute_changes(self):
        after = BASE.replace("期日は月末です。", "期日は翌月末です。").replace('<label class="opt">銀行振込', '<label class="opt on" data-default="1">銀行振込')
        out = self.changes(after)
        self.assertIn("文言の変更 1、属性だけの変更 1", out)
        self.assertIn("- 文言の変更 <p.muted> 「期日は月末です。 → 期日は翌月末です。」", out)
        self.assertIn("- 属性だけの変更 <label.opt> class: opt → opt on; data-default: （なし） → 1", out)

    def test_should_name_long_attributes_without_their_values(self):
        before = BASE.replace("</body>", '<svg><path d="M0 0L9 9"/></svg></body>')
        out = self.changes(before.replace("M0 0L9 9", "M0 0L1 1L2 2"), before=before)
        self.assertIn("- 属性だけの変更 <path> d", out)
        self.assertNotIn("L1 1", out)

    def test_should_count_css_rules_by_selector(self):
        after = BASE.replace(".card{color:#111}", ".card{color:#222} .badge{color:red}").replace(" .muted{color:#777}", "")
        out = self.changes(after)
        self.assertIn("CSS の規則: 追加 1、削除 1、変更 1", out)
        self.assertIn("## CSS の規則\n- 追加 .badge\n- 削除 .muted\n- 変更 .card { color:#111 → color:#222 }", out)
        self.assertIn("要素: 追加 0、削除 0", out)

    def test_should_show_the_first_difference_even_when_it_is_far_from_the_start(self):
        long = "これは支払方法の説明で、同じ文がしばらく続きます。" * 4
        before = BASE.replace("期日は月末です。", long + "期日は月末です。")
        out = self.changes(before.replace("期日は月末です。", "期日は翌月末です。"), before=before)
        self.assertIn("月末です。", out)
        self.assertIn("翌月末です。", out)
        self.assertRegex(out, r"文言の変更 <p\.muted> 「….+ → ….+」")

    def test_should_show_what_changed_in_a_style_attribute_and_a_script(self):
        before = BASE.replace('<p class="muted">', '<p class="muted" style="margin:0;color:#777">').replace("</body>", "<script>const limit = 30;</script></body>")
        out = self.changes(before.replace("color:#777", "color:#d00").replace("limit = 30", "limit = 45"), before=before)
        self.assertIn("style: margin:0;color:#777 → margin:0;color:#d00", out)
        self.assertIn("- 文言の変更 <script> 「const limit = 30; → const limit = 45;」", out)

    def test_should_end_with_the_instruction_to_map_each_line_to_the_request(self):
        self.assertIn("依頼のどの文に対応するか", self.changes(BASE.replace("送付済み", "送付待ち")))

    def test_should_keep_a_rare_change_visible_among_many_similar_ones(self):
        items = "".join(f"<li>項目{index}</li>" for index in range(300))
        after = BASE.replace("<li>入金済み</li>", "<li>入金済み</li>" + items).replace("送付済み", "送付待ち")
        out = self.changes(after)
        self.assertIn("追加 300", out)
        self.assertIn("- 追加 … ほか 292 件", out)
        self.assertIn("- 文言の変更 <li> 「送付済み → 送付待ち」", out)
        self.assertLess(len(out.splitlines()), 30)
        everything = self.changes(after, BASE, "--all")
        self.assertIn("- 追加 <li> 項目299", everything)
        self.assertNotIn("ほか", everything)

    def test_should_cap_the_whole_list_when_many_sections_change(self):
        sections = "".join(f'<section id="s{index}"><p>段落{index}</p></section>' for index in range(150))
        out = self.changes(BASE.replace("</body>", sections + "</body>").replace(".card{color:#111}", ".card{color:#222}"))
        self.assertRegex(out, r"… ほか \d+ 行。--all を付けると全件を出す。")
        self.assertIn("## CSS の規則\n- 変更 .card", out)
        self.assertLess(len(out.splitlines()), 215)

    def test_should_fail_for_an_unreadable_file(self):
        done = subprocess.run([sys.executable, str(CLI), str(self.directory / "a.html"), str(self.directory / "b.html")], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("読めない", done.stderr)


if __name__ == "__main__":
    unittest.main()
