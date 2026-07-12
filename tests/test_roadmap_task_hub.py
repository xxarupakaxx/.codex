import importlib.util
import io
import json
from pathlib import Path
import sys
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


if __name__ == "__main__":
    unittest.main()
