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
        self.worktree = (Path(self.temp_dir.name) / "worktree").resolve()
        self.memory = self.worktree / ".local" / "memory"
        self.memory.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_task(self, name: str, **updates: object) -> Path:
        task = self.memory / name
        task.mkdir()
        metadata: dict[str, object] = {
            "schema_version": 1,
            "task_id": name,
            "task_title": f"Synthetic {name}",
            "project_path": str(self.worktree),
            "worktree_path": str(self.worktree),
            "task_state": "active",
            "code_change": True,
            "created_at": "2026-10-13T00:00:00+09:00",
            "updated_at": "2026-10-13T00:00:00+09:00",
        }
        metadata.update(updates)
        (task / "task-meta.json").write_text(json.dumps(metadata), encoding="utf-8")
        return task

    def select(self, session_id: str = "", thread_id: str = "") -> subprocess.CompletedProcess[str]:
        script = (
            f'source "{HELPER}"\n'
            f'select_task_directory "{self.memory}" "{session_id}" "{thread_id}"'
        )
        return subprocess.run(
            ["bash", "-c", script],
            cwd=self.worktree,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_three_argument_helper_supports_global_runtime_memory(self) -> None:
        global_memory = (Path(self.temp_dir.name) / "runtime-home" / ".local" / "memory").resolve()
        global_memory.mkdir(parents=True)
        local_memory = self.memory
        self.memory = global_memory
        try:
            expected = self.add_task("task-global", session_id="session-global")
            result = self.select("session-global")
        finally:
            self.memory = local_memory
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(), expected.resolve())

    def test_exact_session_match(self) -> None:
        expected = self.add_task("task-one", session_id="session-1", thread_id="thread-1")
        self.add_task("task-two", session_id="session-2", thread_id="thread-2")
        result = self.select("session-1", "thread-1")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(Path(result.stdout.strip()).resolve(), expected.resolve())

    def test_session_miss_does_not_fall_back_to_thread(self) -> None:
        self.add_task("task-one", session_id="session-1", thread_id="thread-1")
        result = self.select("session-missing", "thread-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_thread_match_is_allowed_when_session_absent(self) -> None:
        expected = self.add_task("task-one", thread_id="thread-1")
        result = self.select("", "thread-1")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(Path(result.stdout.strip()).resolve(), expected.resolve())

    def test_single_active_task_is_not_a_fallback(self) -> None:
        self.add_task("task-one", task_state="waiting")
        result = self.select()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_duplicate_and_invalid_metadata_are_rejected(self) -> None:
        self.add_task("task-one", session_id="session-1")
        self.add_task("task-two", session_id="session-1")
        result = self.select("session-1")
        self.assertNotEqual(result.returncode, 0)

        (self.memory / "task-two" / "task-meta.json").write_text(
            json.dumps({"session_id": "session-1"})
        )
        result = self.select("session-1")
        self.assertNotEqual(result.returncode, 0)

    def test_unsafe_id_is_rejected_not_sanitized(self) -> None:
        self.add_task("task-one", session_id="session-1")
        script = (
            f'source "{HELPER}"\n'
            f'session_handover_path "{self.worktree / ".local"}" "session/../../bad" ""'
        )
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_symlinked_memory_root_escape_is_rejected(self) -> None:
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        for child in list(self.memory.iterdir()):
            child.rmdir()
        self.memory.rmdir()
        try:
            self.memory.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        result = self.select("session-1")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
