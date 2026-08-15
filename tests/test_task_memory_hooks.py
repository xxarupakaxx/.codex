from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "claude-compat" / "hooks" / "lib-task-memory.sh"


class TaskMemoryHookContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory = Path(self.temp_dir.name) / "memory"
        self.memory.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_task(self, name: str, **metadata: object) -> Path:
        task = self.memory / name
        task.mkdir()
        (task / "task-meta.json").write_text(json.dumps(metadata))
        return task

    def select(
        self, session_id: str, thread_id: str = ""
    ) -> subprocess.CompletedProcess[str]:
        script = (
            f'source "{HELPER}"\n'
            f'select_task_directory "{self.memory}" "{session_id}" "{thread_id}"'
        )
        return subprocess.run(["bash", "-c", script], text=True, capture_output=True)

    def test_exact_session_match_wins(self) -> None:
        expected = self.add_task("260816_one", session_id="session-1", task_state="active")
        self.add_task("260816_two", session_id="session-2", task_state="active")

        result = self.select("session-1")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), str(expected))

    def test_single_active_task_is_safe_fallback(self) -> None:
        expected = self.add_task("260816_one", task_state="waiting")
        self.add_task("260816_done", task_state="completed")

        result = self.select("unknown")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), str(expected))

    def test_exact_thread_match_wins_after_session_miss(self) -> None:
        expected = self.add_task(
            "260816_one", thread_id="thread-1", task_state="active"
        )
        self.add_task("260816_two", thread_id="thread-2", task_state="active")

        result = self.select("new-session", "thread-1")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), str(expected))

    def test_ambiguous_active_tasks_do_not_guess(self) -> None:
        self.add_task("260816_one", task_state="active")
        self.add_task("260816_two", task_state="waiting")

        result = self.select("missing-session")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_symlinked_memory_root_is_traversed(self) -> None:
        expected = self.add_task("260816_one", session_id="session-1", task_state="active")
        link = Path(self.temp_dir.name) / "linked-memory"
        try:
            link.symlink_to(self.memory, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks are unavailable: {error}")
        script = (
            f'source "{HELPER}"\n'
            f'select_task_directory "{link}" "session-1"'
        )

        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(Path(result.stdout.strip()).resolve(), expected.resolve())

    def test_handover_path_sanitizes_session_id(self) -> None:
        script = (
            f'source "{HELPER}"\n'
            'session_handover_path "/repo/.local" "session/../../bad"'
        )
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "/repo/.local/handovers/session_.._.._bad.md")


if __name__ == "__main__":
    unittest.main()
