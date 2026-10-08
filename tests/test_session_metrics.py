"""Black-box contracts for the session usage and cost CLI."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "scripts/session-metrics.py"


def assistant(message_id, model="claude-opus-5-5", tool_ids=(), **usage):
    content = [{"type": "tool_use", "id": tool_id, "name": "Bash", "input": {}} for tool_id in tool_ids]
    return {"type": "assistant", "message": {"id": message_id, "model": model, "usage": usage, "content": content}}


def tool_result(tool_id, is_error):
    block = {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": "secret output"}
    return {"type": "user", "message": {"content": [block]}}


class SessionMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.transcript = self.directory / "session.jsonl"

    def write(self, records, path=None, raw_lines=()):
        path = path or self.transcript
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(record) for record in records] + list(raw_lines)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def metrics(self):
        env = dict(os.environ, XDG_CACHE_HOME=str(self.directory / "cache"))
        done = subprocess.run(
            [sys.executable, str(CLI), "metrics", "--transcript", str(self.transcript)],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("secret output", done.stdout)
        return json.loads(done.stdout)

    def test_should_keep_last_usage_per_message_id_and_price_cache_tiers(self):
        split = {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 1_000_000}
        self.write(
            [
                assistant("m1", input_tokens=1, output_tokens=1),
                assistant(
                    "m1",
                    input_tokens=1_000_000,
                    output_tokens=1_000_000,
                    cache_read_input_tokens=2_000_000,
                    cache_creation_input_tokens=2_000_000,
                    cache_creation=split,
                ),
            ]
        )
        result = self.metrics()
        self.assertEqual(result["messages"], 1)
        self.assertEqual(result["tokens"]["input_total"], 5_000_000)
        self.assertEqual(result["cache_read_rate"], {"numerator": 2_000_000, "denominator": 5_000_000, "rate": 0.4})
        # opus 5.5: 入力 4 + 読込 0.2×2 + 5分書込 5 + 1時間書込 8 + 出力 20
        self.assertAlmostEqual(result["estimated_usd"], 37.4)
        self.assertTrue(result["estimate_complete"])

    def test_should_count_tool_errors_among_resolved_calls(self):
        self.write(
            [
                assistant("m1", tool_ids=("t1", "t2", "t3"), input_tokens=1),
                tool_result("t1", True),
                tool_result("t2", False),
            ]
        )
        calls = self.metrics()["tool_calls"]
        self.assertEqual((calls["errors"], calls["resolved"], calls["unresolved"]), (1, 2, 1))
        self.assertEqual(calls["rate"], 0.5)

    def test_should_not_guess_price_for_unregistered_model(self):
        self.write([assistant("m1", model="claude-opus-5-5-preview", input_tokens=10)])
        result = self.metrics()
        self.assertIsNone(result["models"]["claude-opus-5-5-preview"]["usd"])
        self.assertFalse(result["estimate_complete"])
        # 単価を1つも引けないときは、0 ではなく「未取得」として返す。
        self.assertIsNone(result["estimated_usd"])
        self.assertIsNone(result["estimated_usd_with_subagents"])
        self.assertIsNone(result["estimated_jpy_with_subagents"])

    def test_should_keep_subtotal_when_only_some_models_are_priced(self):
        self.write(
            [
                assistant("m1", output_tokens=1_000_000),
                assistant("m2", model="unregistered-model", output_tokens=1_000_000),
            ]
        )
        result = self.metrics()
        self.assertAlmostEqual(result["estimated_usd"], 20.0)
        self.assertFalse(result["estimate_complete"])
        self.assertTrue(any("小計" in note for note in result["notes"]))

    def test_should_match_model_after_dropping_date_suffix(self):
        self.write([assistant("m1", model="claude-haiku-4-5-20251001", output_tokens=1_000_000)])
        self.assertAlmostEqual(self.metrics()["estimated_usd"], 5.0)

    def test_should_report_last_recorded_cost_and_unknown_model_flag(self):
        self.write(
            [
                {"type": "cost-state", "totalCostUSD": 1.5, "hasUnknownModelCost": False},
                assistant("m1", input_tokens=1),
                {"type": "cost-state", "totalCostUSD": 4.25, "hasUnknownModelCost": True},
            ]
        )
        self.assertEqual(self.metrics()["recorded_cost"], {"usd": 4.25, "has_unknown_model_cost": True})

    def test_should_use_last_valid_recorded_cost(self):
        self.write(
            [
                {"type": "cost-state", "totalCostUSD": 4.25},
                {"type": "cost-state", "totalCostUSD": "12"},
                {"type": "cost-state", "totalCostUSD": -1},
                {"type": "cost-state"},
                assistant("m1", input_tokens=1),
            ]
        )
        self.assertEqual(self.metrics()["recorded_cost"]["usd"], 4.25)

    def test_should_report_no_recorded_cost_instead_of_zero(self):
        self.write([assistant("m1", input_tokens=1)])
        self.assertIsNone(self.metrics()["recorded_cost"])

    def test_should_flag_bad_lines_and_invalid_values_as_partial(self):
        self.write(
            [assistant("m1", input_tokens=-5), assistant("m2", input_tokens=7)],
            raw_lines=['{"type": "assistant", "message": '],
        )
        result = self.metrics()
        self.assertEqual(result["bad_lines"], 1)
        self.assertEqual(result["tokens"]["input"], 7)
        self.assertFalse(result["estimate_complete"])
        self.assertTrue(any("不正" in note for note in result["notes"]))
        self.assertTrue(any("読めない行 1 件" in note for note in result["notes"]))

    def test_should_note_unknown_cache_write_tier(self):
        self.write([assistant("m1", cache_creation_input_tokens=1_000_000)])
        result = self.metrics()
        self.assertEqual(result["tokens"]["cache_write_5m"], 1_000_000)
        self.assertTrue(any("区分が不明" in note for note in result["notes"]))

    def test_should_mark_reference_amount_for_non_standard_speed(self):
        self.write([assistant("m1", input_tokens=1, speed="fast", service_tier="standard")])
        self.assertTrue(any("speed=fast" in note for note in self.metrics()["notes"]))

    def test_should_report_subagents_separately_from_parent(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        child = self.directory / "session" / "subagents" / "agent-a.jsonl"
        child_turn = assistant("c1", model="claude-sonnet-5-5", tool_ids=("t1",), output_tokens=1_000_000)
        self.write([child_turn, tool_result("t1", True)], path=child)
        result = self.metrics()
        self.assertAlmostEqual(result["estimated_usd"], 20.0)
        self.assertEqual(result["tool_calls"]["resolved"], 0)
        self.assertEqual(result["subagents"]["tool_calls"], {"errors": 1, "resolved": 1, "rate": 1.0})
        self.assertEqual(result["subagents"]["files"], 1)
        self.assertAlmostEqual(result["subagents"]["estimated_usd"], 10.0)
        self.assertAlmostEqual(result["estimated_usd_with_subagents"], 30.0)

    def test_should_convert_to_yen_only_with_saved_rate(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        self.assertIsNone(self.metrics()["estimated_jpy_with_subagents"])
        cache = self.directory / "cache" / "agent-harness" / "fx.json"
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({"rate": 150.0, "as_of": "x", "source": "y"}), encoding="utf-8")
        result = self.metrics()
        self.assertAlmostEqual(result["estimated_jpy_with_subagents"], 3000.0)
        self.assertEqual(result["fx"]["rate"], 150.0)

    def test_should_wait_for_yen_when_saved_rate_is_unreadable(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        cache = self.directory / "cache" / "agent-harness" / "fx.json"
        cache.parent.mkdir(parents=True)
        for broken in ("{not json", json.dumps({"rate": "158"}), json.dumps({"as_of": "x"}), json.dumps([1])):
            with self.subTest(broken=broken):
                cache.write_text(broken, encoding="utf-8")
                result = self.metrics()
                self.assertIsNone(result["estimated_jpy_with_subagents"])
                self.assertTrue(any("円換算待ち" in note for note in result["notes"]))

    def test_should_surface_notes_from_subagents(self):
        self.write([assistant("m1", output_tokens=1)])
        child = self.directory / "session" / "subagents" / "agent-a.jsonl"
        self.write([assistant("c1", output_tokens=1, speed="fast")], path=child)
        self.assertTrue(any(note.startswith("子 agent: ") and "speed=fast" in note for note in self.metrics()["notes"]))

    def test_should_find_transcript_by_session_id(self):
        home = self.directory / "home"
        self.write([assistant("m1", input_tokens=7)], path=home / ".claude" / "projects" / "proj" / "abc-123.jsonl")
        env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(self.directory / "cache"))

        def run(session):
            return subprocess.run(
                [sys.executable, str(CLI), "metrics", "--session", session], capture_output=True, text=True, env=env
            )

        found = run("abc-123")
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(json.loads(found.stdout)["tokens"]["input"], 7)
        self.assertNotEqual(run("no-such-session").returncode, 0)
        self.assertNotEqual(run("../abc-123").returncode, 0)

    def test_should_prefer_codex_thread_usage_over_token_count(self):
        thread = {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 5}
        older = {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}
        self.write(
            [
                {"type": "session_meta", "payload": {"id": "s"}},
                {"type": "turn_context", "payload": {"model": "gpt-x"}},
                {"type": "token_usage_record", "payload": {"thread_token_usage": thread}},
                {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": older}}},
            ]
        )
        result = self.metrics()
        self.assertEqual(result["runtime"], "codex")
        self.assertEqual(result["tokens"], thread)
        self.assertEqual(result["cache_read_rate"]["rate"], 0.4)
        self.assertIsNone(result["tool_calls"])
        self.assertIsNone(result["estimated_usd"])

    def test_should_fall_back_to_codex_token_count(self):
        total = {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 2}
        self.write(
            [
                {"type": "session_meta", "payload": {"id": "s"}},
                {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": total}}},
            ]
        )
        result = self.metrics()
        self.assertEqual(result["token_source"], "token_count")
        self.assertEqual(result["tokens"], total)


if __name__ == "__main__":
    unittest.main()
