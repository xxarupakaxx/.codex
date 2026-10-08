"""Black-box contracts for the hook wiring lint."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "scripts/lint-hook-wiring.py"
PREFIX = "[hook-wiring]"


class LintHookWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # 実際のホームに依存しないよう、HOME を一時ディレクトリへ向ける。
        self.home = Path(self.temp.name) / "home dir"
        (self.home / "hooks").mkdir(parents=True)
        (self.home / "hooks" / "ok.sh").write_text("exit 0\n", encoding="utf-8")
        self.config = Path(self.temp.name) / "settings.json"

    def lint(self, *commands, extra=(), raw=None):
        hooks = [{"type": "command", "command": command} for command in commands]
        body = raw if raw is not None else json.dumps({"hooks": {"SessionStart": [{"hooks": hooks}]}})
        self.config.write_text(body, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(CLI), "--config", str(self.config), *extra],
            capture_output=True,
            text=True,
            env=dict(os.environ, HOME=str(self.home)),
        )
        lines = done.stdout.splitlines()
        self.assertTrue(all(line.startswith(PREFIX) for line in lines), done.stdout)
        return done.returncode, lines

    def test_should_pass_silently_when_every_script_exists(self):
        code, lines = self.lint("bash ~/hooks/ok.sh", 'bash "$HOME/hooks/ok.sh" session', "afplay /System/x.aiff || true")
        self.assertEqual((code, lines), (0, []))

    def test_should_report_script_that_does_not_exist(self):
        code, lines = self.lint("bash ~/hooks/missing.sh")
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)
        self.assertIn("~/hooks/missing.sh が存在しない", lines[0])

    def test_should_report_home_absolute_path_on_any_machine(self):
        for command in ("bash '/Users/alice/.claude/hooks/x.sh' session", "sh /home/bob/hook.sh"):
            with self.subTest(command=command):
                code, lines = self.lint(command)
                self.assertEqual(code, 1)
                self.assertIn("他の端末で壊れる", lines[0])

    def test_should_allow_shared_and_home_relative_paths(self):
        code, lines = self.lint("bash /Users/Shared/tool.sh", "bash $HOME/hooks/ok.sh")
        self.assertEqual((code, lines), (0, []))

    def test_should_report_home_path_without_trailing_slash_but_not_variables(self):
        code, lines = self.lint("cd /Users/alice && ./run.sh")
        self.assertEqual((code, len(lines)), (1, 1))
        self.assertEqual(self.lint("bash /Users/$USER/hooks/x.sh"), (0, []))

    def test_should_check_existence_only_for_scripts(self):
        code, lines = self.lint("bash ~/hooks/ok.sh >> ~/hooks/run.log", "[ -f ~/hooks/flag ] && bash ~/hooks/ok.sh;")
        self.assertEqual((code, lines), (0, []))

    def test_should_report_one_finding_per_registration(self):
        code, lines = self.lint("bash /Users/alice/a.sh ~/hooks/missing.sh")
        self.assertEqual((code, len(lines)), (1, 1))

    def test_should_ignore_hooks_without_command(self):
        raw = json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "prompt", "prompt": "/Users/alice/x"}]}]}, "env": {}})
        self.assertEqual(self.lint(raw=raw), (0, []))

    def test_should_exit_zero_in_hook_mode_and_print_findings(self):
        code, lines = self.lint("bash ~/hooks/missing.sh", extra=("--hook",))
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 2)  # 指摘1件と、件数の1行
        self.assertIn("1 件", lines[1])

    def test_should_exit_zero_in_hook_mode_under_non_utf8_locale(self):
        self.config.write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "bash ~/hooks/missing.sh"}]}]}}),
            encoding="utf-8",
        )
        env = dict(os.environ, HOME=str(self.home), PYTHONIOENCODING="ascii", LC_ALL="C")
        done = subprocess.run(
            [sys.executable, str(CLI), "--hook", "--config", str(self.config)], capture_output=True, env=env
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(PREFIX.encode(), done.stdout)

    def test_should_report_unreadable_config(self):
        code, lines = self.lint(raw="{not json")
        self.assertEqual(code, 1)
        self.assertIn("設定を読めない", lines[0])

    def test_should_exit_zero_in_hook_mode_for_unreadable_config_and_bad_arguments(self):
        code, lines = self.lint(raw="{not json", extra=("--hook",))
        self.assertEqual(code, 0)
        self.assertIn("設定を読めない", lines[0])
        code, lines = self.lint("bash ~/hooks/ok.sh", extra=("--hook", "--no-such-option"))
        self.assertEqual(code, 0)
        self.assertIn("検査を完了できなかった", lines[0])


if __name__ == "__main__":
    unittest.main()
