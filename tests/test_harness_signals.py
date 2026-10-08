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


def hook_record(kind, day="2026-10-01", event="Stop", clock="01:02:03", **fields):
    attachment = dict({"type": kind, "hookEvent": event}, **fields)
    return {"type": "attachment", "timestamp": f"{day}T{clock}.000Z", "attachment": attachment}


def hook_failed(command, stderr, day="2026-10-01", event="Stop", code=1, **extra):
    return hook_record("hook_non_blocking_error", day, event, command=command, exitCode=code, stderr=stderr, **extra)


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

    def report(self, *args, zone="UTC"):
        done = subprocess.run(
            [sys.executable, str(CLI), "report", *args],
            capture_output=True,
            text=True,
            env=dict(os.environ, HOME=str(self.home), TZ=zone),
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

    def test_should_group_hook_failures_and_show_when_each_last_happened(self):
        prefix = "Failed with non-blocking status code: "
        self.session(
            "aaaaaaaa-1",
            [
                hook_failed("Saving memory...", prefix + "time=2026-09-15T11:04:03+09:00 level=fatal error=command is not found", "2026-09-15"),
                hook_failed("Saving memory...", prefix + "time=2026-10-05T13:13:07+09:00 level=fatal error=command is not found", "2026-10-05"),
            ],
        )
        self.session(
            "bbbbbbbb-2",
            [
                hook_failed("Saving memory...", prefix + "time=2026-09-20T09:00:00+09:00 level=fatal error=command is not found", "2026-09-20"),
                hook_failed("bash '/Users/someone/.claude/hooks/x.sh' session", prefix + "bash: /Users/someone/.claude/hooks/x.sh: No such file", "2026-09-01", "SessionStart", 127),
            ],
        )
        out = self.report()
        self.assertIn("## フックの失敗・中止・停止 4 件", out)
        self.assertIn("- 最後 2026-10-05 / 3 回 / 2 セッション [失敗] Stop: Saving memory...（終了コード 1）level=fatal error=command is not found", out)
        self.assertIn("- 最後 2026-09-01 / 1 回 / 1 セッション [失敗] SessionStart: bash '~/.claude/hooks/x.sh' session（終了コード 127）bash: ~/.claude/hooks/x.sh: No such file", out)
        self.assertLess(out.index("最後 2026-10-05"), out.index("最後 2026-09-01"))
        self.assertNotIn("/Users/someone", out)

    def test_should_mask_secrets_in_hook_failures_and_report_zero_when_none(self):
        self.session("aaaaaaaa-1", [hook_failed("curl -H 'Authorization: Bearer abc123def' https://example.test", "token=ghp_abcdefgh12345678 rejected")])
        out = self.report()
        self.assertNotIn("abc123def", out)
        self.assertNotIn("ghp_abcdefgh12345678", out)
        self.session("aaaaaaaa-1", [human("依頼"), assistant()])
        self.assertIn("## フックの失敗・中止・停止 0 件", self.report())

    def test_should_list_cancelled_and_blocking_hooks_with_their_kind(self):
        blocked = {"blockingError": "05_log.md がない。/Users/someone/vault/.local を確かめる", "command": "bash ~/.claude/hooks/stop-check.sh"}
        self.session(
            "aaaaaaaa-1",
            [
                hook_record("hook_cancelled", event="UserPromptSubmit", command="bash ~/.claude/hooks/slow.sh", timedOut=True, timeoutMs=3000),
                hook_record("hook_blocking_error", blockingError=blocked),
            ],
        )
        out = self.report()
        self.assertIn("[中止] UserPromptSubmit: bash ~/.claude/hooks/slow.sh 3000 ms で時間切れ", out)
        self.assertIn("[停止] Stop: bash ~/.claude/hooks/stop-check.sh 05_log.md がない。~/vault/.local を確かめる", out)

    def test_should_count_tool_calls_stopped_by_a_pre_tool_hook_as_stops(self):
        body = "PreToolUse:Bash hook error: [python3 /Users/someone/.claude/hooks/guard.py]: [Hook] BLOCKED: 「{}」は止める"
        records = [assistant("t1", "t2"), failed("t1", body.format("====")), failed("t2", body.format("======"))]
        self.session("aaaaaaaa-1", records)
        out = self.report()
        self.assertIn("/ 2 回 / 1 セッション [停止] PreToolUse: python3 ~/.claude/hooks/guard.py [Hook] BLOCKED:", out)
        self.assertNotIn("guard.py", out.split("## フックの失敗")[0])

    def test_should_show_the_latest_record_of_a_day_and_tolerate_mixed_exit_codes(self):
        self.session(
            "aaaaaaaa-1",
            [
                hook_failed("same", "zzz first", clock="01:00:00"),
                hook_failed("same", "aaa later", clock="09:00:00"),
                hook_record("hook_non_blocking_error", command="other", stderr="no code"),
                hook_failed("other", "with code", code=1),
            ],
        )
        out = self.report()
        self.assertIn("Stop: same（終了コード 1）aaa later", out)
        self.assertIn("Stop: other no code", out)
        self.assertIn("Stop: other（終了コード 1）with code", out)

    def test_should_show_dates_in_the_local_time_zone(self):
        late = hook_failed("x", "boom", day="2026-10-04", clock="16:00:00")
        self.session("aaaaaaaa-1", [late, human("依頼"), assistant()])
        self.assertIn("- 最後 2026-10-04 /", self.report())
        self.assertIn("- 最後 2026-10-05 /", self.report(zone="Asia/Tokyo"))


if __name__ == "__main__":
    unittest.main()
