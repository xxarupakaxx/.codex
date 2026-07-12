import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "roadmap_task_hub.py"
SPEC = importlib.util.spec_from_file_location("roadmap_task_hub", SCRIPT)
hub = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = hub
SPEC.loader.exec_module(hub)


class FakeProcess:
    def __init__(self, responses):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            "".join(json.dumps(response) + "\n" for response in responses)
        )


class CodexAppServerProviderTest(unittest.TestCase):
    def test_provider_initializes_and_paginates(self):
        process = FakeProcess([
            {"id": 1, "result": {"codexHome": "/tmp/.codex", "platformFamily": "unix", "platformOs": "macos", "userAgent": "test"}},
            {"id": 2, "result": {"data": [{"id": "t1", "name": "設計", "preview": "", "cwd": "/repo", "status": {"type": "active"}, "createdAt": 10, "updatedAt": 20}], "nextCursor": "next"}},
            {"id": 3, "result": {"data": [{"id": "t2", "name": None, "preview": "実装", "cwd": "/repo", "status": {"type": "idle"}, "createdAt": 11, "updatedAt": 21}], "nextCursor": None}},
        ])
        result = hub.CodexAppServerProvider(
            process_factory=lambda: process
        ).list_threads()
        self.assertEqual([item.id for item in result.threads], ["t1", "t2"])
        self.assertEqual([item.title for item in result.threads], ["設計", "実装"])
        messages = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
        self.assertEqual(
            [message["method"] for message in messages],
            ["initialize", "initialized", "thread/list", "thread/list"],
        )
        self.assertEqual(messages[2]["params"]["limit"], 100)
        self.assertEqual(messages[2]["params"]["sortKey"], "updated_at")
        self.assertEqual(messages[3]["params"]["cursor"], "next")

    def test_safe_provider_snapshot_exposes_failure(self):
        provider = hub.CodexAppServerProvider(
            process_factory=lambda: (_ for _ in ()).throw(OSError("missing codex"))
        )
        result = hub.safe_provider_snapshot(provider)
        self.assertFalse(result.connected)
        self.assertIn("missing codex", result.error or "")

    def test_provider_skips_notifications_and_exposes_json_rpc_error(self):
        process = FakeProcess([
            {"method": "server/notification", "params": {}},
            {"id": 1, "result": {}},
            {"method": "thread/updated", "params": {}},
            {"id": 2, "error": {"code": -32603, "message": "failed"}},
        ])
        provider = hub.CodexAppServerProvider(process_factory=lambda: process)
        with self.assertRaisesRegex(hub.ProviderError, "failed"):
            provider.list_threads()


class MemoryDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_discovers_roots_and_exact_thread_id_wins(self):
        alpha = self.root / "one/memory/alpha"
        beta = self.root / "two/memory/beta"
        alpha.mkdir(parents=True)
        beta.mkdir(parents=True)
        (alpha / "00_spec.md").write_text("# Alpha\n")
        (alpha / "task-meta.json").write_text(
            '{"thread_id":"t1","project_path":"/repo"}'
        )
        (beta / "30_plan.md").write_text("# Beta\n")

        memories = hub.discover_memory_tasks([alpha.parent, beta.parent])
        thread = hub.CodexThread("t1", "Alpha", "/repo", "active", 0, 0)
        match = hub.match_thread_to_memory(thread, memories)

        self.assertEqual(match.confirmed.path, alpha)

    def test_heuristic_match_is_never_confirmed(self):
        task_dir = self.root / "memory/design"
        task_dir.mkdir(parents=True)
        (task_dir / "00_spec.md").write_text("# 設計\n")
        (task_dir / "task-meta.json").write_text(
            '{"project_path":"/repo","task_title":"設計"}'
        )
        memory = hub.discover_memory_tasks([task_dir.parent])[0]

        result = hub.match_thread_to_memory(
            hub.CodexThread("t2", "設計", "/repo", "active", 0, 0), [memory]
        )

        self.assertIsNone(result.confirmed)
        self.assertEqual(result.candidates[0].path, memory.path)

    def test_discovery_is_stable_skips_symlinks_and_keeps_invalid_metadata(self):
        first = self.root / "memory/a"
        second = self.root / "memory/b"
        first.mkdir(parents=True)
        second.mkdir()
        (first / "00_spec.md").write_text("# A\n")
        (second / "00_spec.md").write_text("# B\n")
        (second / "task-meta.json").write_text("{")
        (self.root / "memory/link").symlink_to(first, target_is_directory=True)

        memories = hub.discover_memory_tasks([first.parent])

        self.assertEqual([memory.path.name for memory in memories], ["a", "b"])
        self.assertIn("metadataError", memories[1].detail)

    def test_candidates_require_score_three_and_include_fifteen_minute_boundary(self):
        base = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)

        def memory(name, title, project_path, age):
            return hub.MemoryTask(
                Path("/memory") / name,
                title,
                None,
                project_path,
                None,
                None,
                datetime.fromtimestamp(base.timestamp() - age * 60, timezone.utc).isoformat(),
                {},
                {},
            )

        thread = hub.CodexThread(
            "t1", "Design", "/repo", "active", 0, int(base.timestamp())
        )
        memories = [
            memory("path", "Other", "/repo", 60),
            memory("title-time", "Design", "/other", 15),
            memory("title-only", "Design", "/other", 15.01),
        ]

        result = hub.match_thread_to_memory(thread, memories)

        self.assertEqual(
            [candidate.path.name for candidate in result.candidates],
            ["path", "title-time"],
        )


class TaskStateTest(unittest.TestCase):
    def test_explicit_state_precedes_freshness(self):
        cases = [
            ("active", "running", 15, "running"),
            ("active", "running", 16, "waiting"),
            ("idle", "waiting", 1, "waiting"),
            ("idle", "completed", 60, "recent_completed"),
            ("systemError", None, 1, "waiting"),
        ]

        for provider, explicit, age, expected in cases:
            with self.subTest(provider=provider, explicit=explicit, age=age):
                self.assertEqual(hub.classify_task(provider, explicit, age, 1), expected)

    def test_completed_is_recent_through_exactly_24_hours(self):
        self.assertEqual(
            hub.classify_task("idle", "completed", 24 * 60, 1),
            "recent_completed",
        )
        self.assertIsNone(
            hub.classify_task("idle", "completed", 24 * 60 + 0.01, 1)
        )


class UnifiedTaskIndexTest(unittest.TestCase):
    NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)

    def memory(self, name, title, age_minutes, state=None, thread_id=None):
        updated = datetime.fromtimestamp(
            self.NOW.timestamp() - age_minutes * 60, timezone.utc
        ).isoformat()
        return hub.MemoryTask(
            path=Path("/memory") / name,
            title=title,
            thread_id=thread_id,
            project_path="/repo",
            task_state=state,
            approval_state=None,
            updated_at=updated,
            summary={"artifactCount": 1},
            detail={"files": {"00_spec.md": "# Spec"}},
        )

    def test_builds_provider_only_memory_only_exact_and_candidate_tasks(self):
        exact = self.memory("exact", "Exact", 5, "running", "t1")
        candidate = self.memory("candidate", "Candidate", 5)
        memory_only = self.memory("memory-only", "Memory only", 20, "waiting")
        threads = (
            hub.CodexThread("t1", "Exact", "/repo", "active", 0, int(self.NOW.timestamp() - 5 * 60)),
            hub.CodexThread("t2", "Candidate", "/repo", "active", 0, int(self.NOW.timestamp() - 5 * 60)),
            hub.CodexThread("t3", "Provider only", "/elsewhere", "idle", 0, int(self.NOW.timestamp() - 20 * 60)),
        )
        snapshot = hub.ProviderSnapshot(threads, True, self.NOW.isoformat())

        index = hub.build_task_index(
            snapshot, [exact, candidate, memory_only], now=self.NOW
        )

        by_id = {task.id: task for task in index["tasks"]}
        self.assertEqual(by_id["t1"].match_state, "exact")
        self.assertEqual(by_id["t2"].match_state, "candidate")
        self.assertEqual(by_id["t3"].match_state, "unmatched")
        self.assertIn("memory:/memory/memory-only", by_id)

    def test_sorts_sections_and_counts_only_expired_completed_as_archived(self):
        memories = [
            self.memory("z", "Zulu", 5, "waiting"),
            self.memory("a", "Alpha", 5, "waiting"),
            self.memory("recent", "Recent", 24 * 60, "completed"),
            self.memory("old", "Old", 24 * 60 + 1, "completed"),
        ]

        index = hub.build_task_index(
            hub.ProviderSnapshot((), True, self.NOW.isoformat()),
            memories,
            now=self.NOW,
        )

        self.assertEqual(
            [(task.section, task.title) for task in index["tasks"]],
            [
                ("waiting", "Alpha"),
                ("waiting", "Zulu"),
                ("recent_completed", "Recent"),
            ],
        )
        self.assertEqual(index["archivedCount"], 1)


if __name__ == "__main__":
    unittest.main()
