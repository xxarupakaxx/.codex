"""Black-box contracts for the shared finite-command wrapper."""

import concurrent.futures
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "scripts/quiet-run.py"


class QuietRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.logs = self.directory / "logs"

    def command(self, code, *args):
        return [
            sys.executable,
            str(RUNNER),
            "--log-dir",
            str(self.logs),
            "--",
            sys.executable,
            "-c",
            code,
            *args,
        ]

    def run_code(self, code, *args, **kwargs):
        return subprocess.run(
            self.command(code, *args),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **kwargs,
        )

    def test_6500_success_lines_are_at_most_ten_with_complete_private_log(self):
        result = self.run_code("for i in range(6500): print('passed', i)")
        self.assertEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stdout.splitlines()), 10)
        self.assertIn("PASS exit=0", result.stdout)
        self.assertIn("passed 6499", result.stdout)
        (log,) = self.logs.glob("*.log")
        self.assertEqual(len(log.read_bytes().splitlines()), 6500)
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.logs.stat().st_mode & 0o777, 0o700)

    def test_failure_retains_exit_stderr_and_bounded_diagnostics(self):
        result = self.run_code(
            "import sys; print('first', flush=True); "
            "[print('detail', i) for i in range(500)]; "
            "sys.stdout.flush(); print('assertion failed', file=sys.stderr); "
            "sys.exit(23)"
        )
        self.assertEqual(result.returncode, 23)
        self.assertIn("FAIL exit=23", result.stdout)
        self.assertIn("assertion failed", result.stdout)
        self.assertLessEqual(len(result.stdout.splitlines()), 83)
        (log,) = self.logs.glob("*.log")
        self.assertTrue(log.read_text().startswith("first\n"))
        self.assertTrue(log.read_text().endswith("assertion failed\n"))

    def test_large_binary_line_is_preserved_but_not_echoed_in_full(self):
        result = self.run_code("import os; os.write(1, b'\\xff'*1000000)")
        self.assertEqual(result.returncode, 0)
        self.assertLess(len(result.stdout.encode()), 4500)
        (log,) = self.logs.glob("*.log")
        self.assertEqual(log.stat().st_size, 1000000)

    def test_argument_cwd_environment_and_single_execution_are_preserved(self):
        literal = "$(touch should-not-exist); `echo bad`"
        result = self.run_code(
            "import os,sys; from pathlib import Path; "
            "print(sys.argv[1]); print(os.getcwd()); "
            "print(os.environ['QUIET_FIXTURE']); "
            "Path('once').open('a').write('x')",
            literal,
            cwd=self.directory,
            env={**os.environ, "QUIET_FIXTURE": "fixture"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(literal, result.stdout)
        self.assertIn(str(self.directory), result.stdout)
        self.assertIn("fixture", result.stdout)
        self.assertEqual((self.directory / "once").read_text(), "x")
        self.assertFalse((self.directory / "should-not-exist").exists())

    def test_concurrent_runs_use_distinct_logs(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.run_code, [f"print({i})" for i in range(4)]))
        self.assertTrue(all(result.returncode == 0 for result in results))
        self.assertEqual(
            {p.read_text() for p in self.logs.glob("*.log")},
            {f"{i}\n" for i in range(4)},
        )

    def test_missing_executable_is_failure(self):
        command = [
            sys.executable,
            str(RUNNER),
            "--log-dir",
            str(self.logs),
            "--",
            str(self.directory / "missing"),
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=False
        )
        self.assertEqual(result.returncode, 127)
        self.assertIn("cannot start", result.stdout)

    def test_child_signal_is_nonzero(self):
        result = self.run_code("import os,signal; os.kill(os.getpid(),signal.SIGTERM)")
        self.assertEqual(result.returncode, 143)
        self.assertIn("FAIL", result.stdout)

    def test_cancel_cleans_up_grandchild_even_after_leader_exits(self):
        marker = self.directory / "ticks"
        code = (
            "import os,signal,time\n"
            "from pathlib import Path\n"
            "pid=os.fork()\n"
            "if pid == 0:\n"
            " signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            " signal.signal(signal.SIGINT,signal.SIG_IGN)\n"
            f" marker=Path({str(marker)!r})\n"
            " while True:\n"
            "  with marker.open('a') as f: f.write('x')\n"
            "  time.sleep(0.02)\n"
            "else:\n"
            f" Path({str(self.directory / 'pid')!r}).write_text(str(pid))\n"
            " time.sleep(60)\n"
        )
        proc = subprocess.Popen(
            self.command(code),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(proc.stdout.readline().strip(), "[quiet-run] START")
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "grandchild must reach ready state")
            proc.send_signal(signal.SIGTERM)
            output, _ = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 143)
            self.assertIn("FAIL exit=143", output)
            size = marker.stat().st_size
            time.sleep(0.15)
            self.assertEqual(marker.stat().st_size, size)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
            pidfile = self.directory / "pid"
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    unittest.main()
