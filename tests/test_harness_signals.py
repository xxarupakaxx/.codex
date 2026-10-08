"""Black-box contracts for the intervention and tool-failure report."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "scripts/harness-signals.py"
REJECTED = "The user doesn't want to proceed with this tool use. The tool use was rejected."


# 実レコードの属性の有無に合わせる。本人の発話だけが origin.kind == "human" を持つ。
def user(content, **attributes):
    base = {"type": "user", "timestamp": "2026-10-01T01:02:03.000Z", "cwd": "/work/repo"}
    return dict(base, message={"content": content}, **attributes)


def human(text):
    return user(text, origin={"kind": "human"})


def machine(text, **attributes):
    return user(text, **attributes)


def interrupted(text="[Request interrupted by user]"):
    return user([{"type": "text", "text": text}])


def assistant(*tool_ids):
    blocks = [{"type": "tool_use", "id": tool_id, "name": "Bash", "input": {}} for tool_id in tool_ids]
    return {"type": "assistant", "message": {"content": blocks or [{"type": "text", "text": "done"}]}}


def failed(tool_id, body):
    return user([{"type": "tool_result", "tool_use_id": tool_id, "is_error": True, "content": body}])


class HarnessSignalsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / ".claude" / "projects" / "proj"

    def session(self, name, records, age_days=0):
        path = self.project / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
        return path

    def report(self, *args):
        done = subprocess.run(
            [sys.executable, str(CLI), "report", *args],
            capture_output=True,
            text=True,
            env=dict(os.environ, HOME=str(self.home)),
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_should_list_only_human_follow_ups_and_count_the_rest(self):
        self.session(
            "aaaaaaaa-1",
            [
                human("最初の依頼。見づらい資料を直す"),
                assistant(),
                machine("<task-notification>見づらい</task-notification>", origin={"kind": "task-notification"}),
                machine("要約: 見づらい", isCompactSummary=True),
                machine("展開されたスキル本文 見づらい", isMeta=True),
                machine("origin のない古い形式の発話"),
                human("表は見づらいので使わない"),
                human("次はテストを書いて"),
            ],
        )
        out = self.report()
        self.assertIn("最初の依頼 1 件、続きの発話 2 件", out)
        self.assertIn("判別できないレコード 1 件", out)
        self.assertIn("[出来への不満] 2026-10-01 repo/aaaaaaaa: 表は見づらいので使わない", out)
        self.assertEqual(out.count("見づらい"), 1)
        self.assertNotIn("次はテストを書いて", out)
        self.assertIn("次はテストを書いて", self.report("--all"))

    def test_should_not_read_subagent_transcripts(self):
        self.session("aaaaaaaa-1", [human("依頼"), assistant()])
        self.session("aaaaaaaa-1/subagents/agent-x", [human("親の指示"), assistant(), human("違う、やり直して")])
        self.assertNotIn("やり直して", self.report("--all"))

    def test_should_pick_up_interrupt_without_origin_and_the_next_utterance(self):
        self.session("bbbbbbbb-1", [human("依頼"), assistant(), interrupted(), human("先に計画を見せて")])
        out = self.report()
        self.assertIn("## 中断 1 件、拒否 0 件", out)
        self.assertIn("[中断の直後] 2026-10-01 repo/bbbbbbbb: 先に計画を見せて", out)
        self.assertIn("判別できないレコード 0 件", out)

    def test_should_count_rejection_once_and_keep_the_stated_reason(self):
        reason = REJECTED + " To tell you how to proceed, the user said:\nそのファイルは消さない"
        self.session(
            "cccccccc-1",
            [
                human("依頼"),
                assistant("t1"),
                failed("t1", reason),
                interrupted("[Request interrupted by user for tool use]"),
                human("別の方法で"),
            ],
        )
        out = self.report()
        self.assertIn("## 中断 0 件、拒否 1 件", out)
        self.assertIn("- 拒否 2026-10-01 repo/cccccccc Bash: そのファイルは消さない", out)
        self.assertIn("[拒否の直後]", out)
        self.assertNotIn("The user doesn't want", out)

    def test_should_match_english_labels_on_word_boundaries(self):
        self.session(
            "dddddddd-1",
            [human("依頼"), assistant(), human("it is undoubtedly fine"), human("please undo that")],
        )
        out = self.report("--all")
        self.assertIn("[ラベルなし] 2026-10-01 repo/dddddddd: it is undoubtedly fine", out)
        self.assertIn("[差し戻し] 2026-10-01 repo/dddddddd: please undo that", out)

    def test_should_not_label_long_pasted_text(self):
        self.session("eeeeeeee-1", [human("依頼"), assistant(), human("見づらい" + "資料" * 250)])
        self.assertIn("ラベルの付いた続きの発話 0 件（付かなかった発話 1 件）", self.report())

    def test_should_group_tool_failures_across_sessions(self):
        for name, number in (("ffffffff-1", 12), ("gggggggg-1", 345)):
            body = f"File does not exist: /work/repo/file{number}.md"
            self.session(name, [human("依頼"), assistant("t1"), failed("t1", body)])
        self.session("hhhhhhhh-1", [human("依頼"), assistant("t1"), failed("t1", "一度きりの失敗")])
        exit_code = [failed(tool_id, "Exit code 1\n\nzsh: command not found: rg") for tool_id in ("t1", "t2", "t3")]
        self.session("llllllll-1", [human("依頼"), assistant("t1", "t2", "t3"), *exit_code])
        out = self.report()
        self.assertIn("- 2 回 / 2 セッション Bash: File does not exist: <x>", out)
        self.assertIn("- 3 回 / 1 セッション Bash: Exit code <x> / zsh: command not found: rg", out)
        self.assertNotIn("一度きりの失敗", out)

    def test_should_mask_secret_like_strings(self):
        self.session("iiiiiiii-1", [human("依頼"), assistant(), human("やり直して。鍵は ghp_abcdefgh12345678 を使って")])
        out = self.report()
        self.assertIn("鍵は *** を使って", out)
        self.assertNotIn("ghp_", out)

    def test_should_skip_sessions_older_than_the_window(self):
        self.session("jjjjjjjj-1", [human("依頼"), assistant(), human("やり直して、古い発話")], age_days=40)
        self.assertNotIn("古い発話", self.report("--days", "30"))
        self.assertIn("古い発話", self.report("--days", "60"))

    def test_should_write_private_file_when_out_is_given(self):
        self.session("kkkkkkkk-1", [human("依頼"), assistant(), human("やり直して、秘密の発話")])
        target = self.home / ".claude" / ".local" / "harness-signals" / "report.md"
        target.parent.mkdir(parents=True)
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)
        stdout = self.report("--out", "report.md")
        self.assertNotIn("秘密の発話", stdout)
        self.assertIn("秘密の発話", target.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_should_refuse_out_path_outside_the_fixed_directory(self):
        self.session("mmmmmmmm-1", [human("依頼"), assistant(), human("やり直して")])
        for out in (str(self.home / "vault" / "report.md"), "sub/report.md", ".."):
            with self.subTest(out=out):
                done = subprocess.run(
                    [sys.executable, str(CLI), "report", "--out", out],
                    capture_output=True,
                    text=True,
                    env=dict(os.environ, HOME=str(self.home)),
                )
                self.assertNotEqual(done.returncode, 0)
        self.assertFalse((self.home / "vault").exists())

    def test_should_count_interrupt_during_tool_run_as_interrupt_not_failure(self):
        self.session(
            "nnnnnnnn-1",
            [
                human("依頼"),
                assistant("t1"),
                failed("t1", "[Request interrupted by user for tool use]"),
                interrupted("[Request interrupted by user for tool use]"),
                human("そこで止めて"),
            ],
        )
        out = self.report("--all")
        self.assertIn("## 中断 1 件、拒否 0 件", out)
        self.assertIn("[中断の直後] 2026-10-01 repo/nnnnnnnn: そこで止めて", out)
        self.assertNotIn("Bash: [Request interrupted", out)

    def test_should_drop_the_after_mark_once_the_assistant_has_answered(self):
        self.session(
            "oooooooo-1",
            [human("依頼"), assistant("t1"), failed("t1", REJECTED), assistant(), human("次の話題")],
        )
        out = self.report("--all")
        self.assertIn("## 中断 0 件、拒否 1 件", out)
        self.assertIn("[ラベルなし] 2026-10-01 repo/oooooooo: 次の話題", out)

    def test_should_mask_assignments_and_long_hex(self):
        text = "やり直して。password=hunter2 と 0123456789abcdef0123456789abcdef を使う"
        self.session("pppppppp-1", [human("依頼"), assistant(), human(text)])
        out = self.report()
        self.assertNotIn("hunter2", out)
        self.assertNotIn("0123456789abcdef0123456789abcdef", out)

    def test_should_warn_when_most_records_cannot_be_attributed(self):
        self.session("qqqqqqqq-1", [machine("origin のない発話 1"), machine("origin のない発話 2"), human("依頼")])
        self.assertIn("注意: 判別できないレコードが本人の発話より多い", self.report())


if __name__ == "__main__":
    unittest.main()
