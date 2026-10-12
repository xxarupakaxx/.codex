"""Black-box contracts for the session usage and cost CLI."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "scripts/session-metrics.py"


def assistant(message_id, model="claude-opus-5-5", tool_ids=(), session="session", **usage):
    usage.setdefault("input_tokens", 0)
    usage.setdefault("output_tokens", 0)
    usage.setdefault("cache_read_input_tokens", 0)
    usage.setdefault("cache_creation_input_tokens", 0)
    content = [{"type": "tool_use", "id": tool_id, "name": "Bash", "input": {}} for tool_id in tool_ids]
    return {"type": "assistant", "sessionId": session, "requestId": "req-" + message_id,
            "message": {"id": message_id, "model": model, "usage": usage, "content": content}}


def tool_result(tool_id, is_error, session="session", **flags):
    block = {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": "secret output"}
    block.update(flags)
    return {"type": "user", "sessionId": session, "message": {"content": [block]}}


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

    def metrics(self, *extra):
        env = dict(os.environ, XDG_CACHE_HOME=str(self.directory / "cache"))
        defaults = ["--status", "success", "--includes-children", "no"]
        if "--actual-tier" not in extra and "--assume-tier" not in extra:
            defaults += ["--actual-tier", "standard"]
        done = subprocess.run(
            [sys.executable, str(CLI), "metrics", "--transcript", str(self.transcript), *defaults, *extra],
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
        self.assertEqual(result["tokens"]["cache_write"], 2_000_000)
        self.assertEqual(result["tokens"]["cache_write_5m"], 1_000_000)
        self.assertEqual(result["tokens"]["cache_write_1h"], 1_000_000)
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

    def test_unmatched_result_does_not_hide_unknown_call_outcome(self):
        self.write([
            assistant("m1", tool_ids=("t1",), input_tokens=1),
            tool_result("foreign", False),
        ])
        result = self.metrics()
        calls = result["tool_calls"]
        classified = sum(calls[key] for key in ("success", "failure", "rejection", "interruption", "unknown"))
        self.assertEqual(calls["total"], classified)
        self.assertEqual((calls["unknown"], calls["unresolved"]), (1, 1))
        self.assertEqual(result["measurement_status"], "not_qualified")
        self.assertEqual(calls["unmatched_results"], 1)
        self.assertFalse(result["coverage"]["tool_calls"]["qualified"])
        self.assertFalse(result["coverage"]["outcome"]["qualified"])
        self.assertIn("unmatched_tool_result", result["coverage"]["tool_calls"]["reasons"])

    def test_unmatched_result_without_call_disqualifies_zero_call_coverage(self):
        unmatched = tool_result("missing-call", True)
        self.write([assistant("m1", input_tokens=1), unmatched, unmatched])
        result = self.metrics()
        self.assertEqual((result["tool_calls"]["total"], result["tool_calls"]["unmatched_results"]), (0, 1))
        self.assertFalse(result["coverage"]["tool_calls"]["qualified"])
        self.assertFalse(result["coverage"]["outcome"]["qualified"])
        self.assertFalse(result["comparison_qualified"])
        records = [record for record in result["records"] if record["event"] == "tool_result"]
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["result_id"] and records[0]["result_id"] != "missing-call")
        self.assertEqual(records[0]["relation_meta"]["missing_reason"], "tool_call_missing")

    def test_missing_tool_identity_is_unknown_and_has_ledger_reason(self):
        call = assistant("m1", input_tokens=1)
        call["message"]["content"] = [{"type": "tool_use", "name": "Bash", "input": {}}]
        result_row = {"type": "user", "sessionId": "session", "message": {"content": [
            {"type": "tool_result", "is_error": False, "content": "secret output"}
        ]}}
        self.write([call, result_row])
        result = self.metrics()
        calls = result["tool_calls"]
        self.assertEqual((calls["total"], calls["unknown"], calls["identity_missing"]), (1, 1, 1))
        self.assertFalse(result["coverage"]["tool_calls"]["qualified"])
        self.assertFalse(result["coverage"]["outcome"]["qualified"])
        tool_record = next(record for record in result["records"] if record["event"] == "tool_call")
        self.assertIsNone(tool_record["call_id"])
        self.assertEqual(tool_record["field_meta"]["call_id"]["state"], "unknown")
        self.assertEqual(tool_record["field_meta"]["call_id"]["missing_reason"], "tool_identity_missing")

    def test_missing_tool_ids_have_distinct_source_record_ids(self):
        call = assistant("m1", input_tokens=1)
        call["message"]["content"] = [
            {"type": "tool_use", "name": "Bash", "input": {}},
            {"type": "tool_use", "name": "Bash", "input": {}},
        ]
        self.write([call])
        records = [record for record in self.metrics()["records"] if record["event"] == "tool_call"]
        self.assertEqual(len(records), 2)
        self.assertEqual(len({record["source_record_id"] for record in records}), 2)
        self.assertTrue(all(record["call_id"] is None for record in records))

    def test_exact_duplicate_tool_call_and_result_are_counted_once(self):
        call = assistant("m1", tool_ids=("t1",), input_tokens=1)
        result_row = tool_result("t1", False)
        self.write([call, call, result_row, result_row])
        result = self.metrics()
        calls = result["tool_calls"]
        self.assertEqual((calls["total"], calls["success"], calls["relation_conflicts"]), (1, 1, 0))
        self.assertTrue(result["coverage"]["tool_calls"]["qualified"])
        self.assertTrue(result["coverage"]["outcome"]["qualified"])
        tool_record = next(record for record in result["records"] if record["event"] == "tool_call")
        self.assertEqual(tool_record["model"], "claude-opus-5-5")
        self.assertEqual(tool_record["field_meta"]["model"]["source"]["record_type"], "tool_use")

    def test_usage_parent_id_is_scoped_hash_without_raw_id(self):
        row = assistant("m1", input_tokens=1)
        row["parentUuid"] = "parent-1"
        self.write([row])
        result = self.metrics()
        record = next(record for record in result["records"] if record["event"] == "usage")
        self.assertTrue(record["parent_id"] and record["parent_id"] != "parent-1")
        self.assertNotIn("parent-1", json.dumps(result))
        self.assertEqual(record["field_meta"]["parent_id"]["state"], "observed")

    def test_untrusted_timestamps_are_not_copied_to_ledger_metadata(self):
        first = assistant("m1", input_tokens=1)
        second = assistant("m2", input_tokens=1)
        first["timestamp"] = "TOP_SECRET_TIMESTAMP"
        second["timestamp"] = {"secret": "DICT_TIMESTAMP_SECRET"}
        self.write([first, second])
        result = self.metrics()
        serialized = json.dumps(result)
        self.assertNotIn("TOP_SECRET_TIMESTAMP", serialized)
        self.assertNotIn("DICT_TIMESTAMP_SECRET", serialized)
        for record in result["records"]:
            for metadata in record["field_meta"].values():
                self.assertEqual(metadata["observed_at"], result["collected_at"])

    def test_foreign_tool_result_is_excluded_from_current_ledger(self):
        self.write([
            assistant("m1", tool_ids=("t1",), input_tokens=1),
            tool_result("t1", False, session="foreign-session"),
        ])
        result = self.metrics("--session-id", "session")
        self.assertEqual((result["tool_calls"]["total"], result["tool_calls"]["unknown"],
                          result["tool_calls"]["unmatched_results"]), (1, 1, 0))
        record = next(record for record in result["records"] if record["event"] == "tool_call")
        self.assertIsNone(record["result_id"])
        self.assertEqual(record["field_meta"]["result_id"]["missing_reason"], "tool_result_missing")

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
        self.assertIsNone(result["estimated_usd"])
        self.assertAlmostEqual(result["priced_subtotal_usd"], 20.0)
        self.assertFalse(result["estimate_complete"])
        self.assertLess(result["coverage"]["cost"]["rate"], 1.0)

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

    def test_usage_without_session_id_reduces_usage_coverage(self):
        missing = assistant("m2", input_tokens=99)
        missing.pop("sessionId")
        self.write([assistant("m1", input_tokens=1), missing])
        result = self.metrics()
        self.assertEqual((result["coverage"]["usage"]["expected"],
                          result["coverage"]["usage"]["observed"]), (2, 1))
        self.assertFalse(result["coverage"]["usage"]["qualified"])
        self.assertFalse(result["comparison_qualified"])

    def test_should_flag_bad_lines_and_invalid_values_as_partial(self):
        self.write(
            [assistant("m1", input_tokens=-5), assistant("m2", input_tokens=7)],
            raw_lines=['{"type": "assistant", "message": '],
        )
        result = self.metrics()
        self.assertEqual(result["bad_lines"], 1)
        self.assertIsNone(result["tokens"]["input"])
        self.assertEqual(result["measurement_status"], "not_qualified")
        self.assertFalse(result["estimate_complete"])
        self.assertIn("required_usage_fields_missing", result["notes"])
        self.assertIn("incomplete_tail", result["notes"])
        self.assertEqual(result["cache_read_rate"], {
            "numerator": None, "denominator": None, "rate": None,
        })
        self.assertEqual(result["token_field_meta"]["input"]["state"], "unknown")
        self.assertEqual(result["token_field_meta"]["input"]["missing_reason"], "input_unavailable")

    def test_should_count_each_malformed_line_for_legacy_compatibility(self):
        self.write(
            [assistant("m1", input_tokens=7)],
            raw_lines=["{malformed-one}", "{malformed-two}", "{incomplete-tail"],
        )
        result = self.metrics()
        self.assertEqual(result["bad_lines"], 3)
        self.assertIn("malformed_record", result["notes"])
        self.assertIn("incomplete_tail", result["notes"])
        self.assertTrue(any("読めない行 3 件" in note for note in result["notes"]))

    def test_should_note_unknown_cache_write_tier(self):
        self.write([assistant("m1", cache_creation_input_tokens=1_000_000)])
        result = self.metrics()
        self.assertEqual(result["tokens"]["cache_write"], 1_000_000)
        self.assertIsNone(result["tokens"]["cache_write_5m"])
        self.assertIsNone(result["tokens"]["cache_write_1h"])
        self.assertIn("cache_write_tier_unknown_assumed_5m", result["notes"])
        self.assertIsNone(result["estimated_usd"])
        self.assertAlmostEqual(result["reference_usd"], 5.0)
        self.assertFalse(result["comparison_qualified"])
        self.assertIsNone(result["models"]["claude-opus-5-5"]["usd"])
        self.assertAlmostEqual(result["models"]["claude-opus-5-5"]["reference_usd"], 5.0)

    def test_zero_cache_write_has_observed_zero_ttl_buckets(self):
        self.write([assistant("m1", input_tokens=1, cache_creation_input_tokens=0)])
        tokens = self.metrics()["tokens"]
        self.assertEqual((tokens["cache_write"], tokens["cache_write_5m"],
                          tokens["cache_write_1h"]), (0, 0, 0))

    def test_cache_write_split_mismatch_has_no_cost(self):
        self.write([assistant(
            "m1", cache_creation_input_tokens=1_000_000,
            cache_creation={"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0},
        )])
        result = self.metrics()
        self.assertEqual(result["tokens"]["cache_write"], 1_000_000)
        self.assertIsNone(result["tokens"]["cache_write_5m"])
        self.assertIsNone(result["tokens"]["cache_write_1h"])
        self.assertIsNone(result["estimated_usd"])
        self.assertIsNone(result["reference_usd"])
        self.assertEqual(result["coverage"]["cost"]["rate"], 0.0)
        self.assertFalse(result["comparison_qualified"])
        self.assertIn("cache_write_split_mismatch", result["notes"])
        usage_record = next(record for record in result["records"] if record["event"] == "usage")
        self.assertIsNone(usage_record["cost_usd"])
        self.assertEqual(usage_record["field_meta"]["cost_usd"]["missing_reason"],
                         "cache_write_split_mismatch")

    def test_complete_usage_with_incomplete_tail_is_not_qualified(self):
        self.write([assistant("m1", input_tokens=1, output_tokens=1)], raw_lines=['{"type":'])
        result = self.metrics()
        self.assertEqual(result["coverage"]["usage"]["rate"], 1.0)
        self.assertEqual(result["measurement_status"], "not_qualified")
        self.assertIsNone(result["estimated_usd"])
        self.assertFalse(result["estimate_complete"])
        self.assertIsNotNone(result["priced_subtotal_usd"])
        for field in ("usage", "tool_calls", "outcome", "cost"):
            self.assertFalse(result["coverage"][field]["qualified"])

    def test_should_mark_reference_amount_for_non_standard_speed(self):
        self.write([assistant("m1", input_tokens=1, speed="fast", service_tier="standard")])
        result = self.metrics()
        self.assertIsNone(result["estimated_usd"])
        self.assertFalse(result["comparison_qualified"])

    def test_regional_inference_is_reference_until_multiplier_is_confirmed(self):
        self.write([assistant("m1", input_tokens=1_000_000, inference_geo="us")])
        result = self.metrics()
        self.assertIsNone(result["estimated_usd"])
        self.assertAlmostEqual(result["reference_usd"], 4.0)
        self.assertFalse(result["comparison_qualified"])
        self.assertIn("regional_inference_pricing_unknown", result["notes"])
        usage_record = next(record for record in result["records"] if record["event"] == "usage")
        self.assertIsNone(usage_record["cost_usd"])
        self.assertEqual(usage_record["field_meta"]["cost_usd"]["missing_reason"],
                         "regional_inference_pricing_unknown")

    def test_should_report_subagents_separately_from_parent(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        child = self.directory / "session" / "subagents" / "agent-a.jsonl"
        child_turn = assistant("c1", model="claude-sonnet-5-5", tool_ids=("t1",), output_tokens=1_000_000)
        self.write([child_turn, tool_result("t1", True)], path=child)
        result = self.metrics()
        self.assertAlmostEqual(result["estimated_usd"], 20.0)
        self.assertEqual(result["tokens"]["output"], 1_000_000)
        self.assertEqual(result["subagents"]["tokens"]["output"], 1_000_000)
        self.assertEqual(result["tool_calls"]["resolved"], 0)
        self.assertEqual(result["subagents"]["tool_calls"]["failure"], 1)
        self.assertEqual(result["subagents"]["tool_calls"]["resolved"], 1)
        self.assertEqual(result["subagents"]["tool_calls"]["rate"], 1.0)
        self.assertEqual(result["subagents"]["files"], 1)
        self.assertAlmostEqual(result["subagents"]["estimated_usd"], 10.0)
        self.assertAlmostEqual(result["estimated_usd_with_subagents"], 30.0)

    def test_child_cache_write_ttl_split_is_preserved(self):
        self.write([assistant("m1", input_tokens=1)])
        child = self.directory / "session" / "subagents" / "cache.jsonl"
        split = {"ephemeral_5m_input_tokens": 2, "ephemeral_1h_input_tokens": 3}
        self.write([assistant("c1", cache_creation_input_tokens=5,
                              cache_creation=split)], path=child)
        result = self.metrics()
        tokens = result["subagents"]["tokens"]
        self.assertEqual((tokens["cache_write"], tokens["cache_write_5m"],
                          tokens["cache_write_1h"]), (5, 2, 3))

    def test_main_and_child_reused_ids_have_distinct_scoped_ledger_ids(self):
        self.write([assistant("same", tool_ids=("same-tool",), input_tokens=1)])
        child = self.directory / "session" / "subagents" / "agent-a.jsonl"
        self.write([assistant("same", tool_ids=("same-tool",), input_tokens=1)], path=child)
        result = self.metrics()
        main_usage = next(record for record in result["records"] if record["event"] == "usage")
        child_usage = next(record for record in result["subagents"]["records"] if record["event"] == "usage")
        main_tool = next(record for record in result["records"] if record["event"] == "tool_call")
        child_tool = next(record for record in result["subagents"]["records"] if record["event"] == "tool_call")
        self.assertNotEqual(main_usage["call_id"], child_usage["call_id"])
        self.assertNotEqual(main_usage["source_record_id"], child_usage["source_record_id"])
        self.assertNotEqual(main_tool["call_id"], child_tool["call_id"])
        self.assertNotEqual(main_tool["source_record_id"], child_tool["source_record_id"])

    def test_tool_only_child_source_is_preserved_and_disqualifies_exclusive_sum(self):
        self.write([assistant("m1", input_tokens=1)])
        child = self.directory / "session" / "subagents" / "tool-only.jsonl"
        self.write([{
            "type": "assistant", "sessionId": "session", "message": {
                "id": "child", "model": "claude-opus-5-5",
                "content": [{"type": "tool_use", "id": "child-tool", "name": "Bash", "input": {}}],
            },
        }], path=child)
        result = self.metrics("--includes-children", "no")
        self.assertEqual(result["subagents"]["files"], 1)
        self.assertFalse(result["subagents"]["coverage"]["usage"]["qualified"])
        self.assertTrue(any(record["event"] == "tool_call"
                            for record in result["subagents"]["records"]))
        self.assertIsNone(result["estimated_usd_with_subagents"])
        self.assertFalse(result["comparison_qualified"])

    def test_identity_only_child_source_is_not_treated_as_no_child(self):
        self.write([assistant("m1", input_tokens=1)])
        child = self.directory / "session" / "subagents" / "identity-only.jsonl"
        self.write([{"type": "system", "subtype": "init", "sessionId": "session",
                     "model": "claude-opus-5-5"}], path=child)
        result = self.metrics("--includes-children", "no")
        self.assertEqual(result["subagents"]["files"], 1)
        self.assertEqual(result["subagents"]["records"], [])
        self.assertFalse(result["subagents"]["coverage"]["usage"]["qualified"])
        self.assertIsNone(result["estimated_usd_with_subagents"])
        self.assertFalse(result["comparison_qualified"])

    def test_child_model_version_tier_and_scope_do_not_change_parent_fields(self):
        main = assistant("m1", model="claude-opus-5-5", service_tier="standard")
        main["version"] = "main-v"
        self.write([main])
        child_dir = self.directory / "session" / "subagents"
        child = assistant("c1", model="claude-sonnet-5-5", speed="fast")
        child["version"] = "child-v"
        self.write([child], path=child_dir / "call.jsonl")
        self.write([
            {"type": "system", "subtype": "init", "session_id": "session",
             "model": "claude-haiku-4-5", "claude_code_version": "child-stream-v"},
            {"type": "result", "session_id": "session", "modelUsage": {"claude-haiku-4-5": {
                "inputTokens": 1, "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0, "outputTokens": 1,
            }}},
        ], path=child_dir / "stream.jsonl")
        result = self.metrics("--includes-children", "yes")
        self.assertEqual(result["model"], "claude-opus-5-5")
        self.assertEqual(result["version"], "main-v")
        self.assertEqual(result["actual_tier"], "standard")
        self.assertEqual(result["usage_scope"], "call_delta")
        self.assertEqual(set(result["by_model"]), {"claude-opus-5-5"})

    def test_should_convert_to_yen_only_with_saved_rate(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        self.assertIsNone(self.metrics()["estimated_jpy_with_subagents"])
        cache = self.directory / "cache" / "agent-harness" / "fx.json"
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({"base": "USD", "quote": "JPY", "rate": 150.0,
                                     "as_of": "x", "source": "y"}), encoding="utf-8")
        result = self.metrics()
        self.assertAlmostEqual(result["estimated_jpy_with_subagents"], 3000.0)
        self.assertEqual(result["fx"]["rate"], 150.0)

    def test_should_wait_for_yen_when_saved_rate_is_unreadable(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        cache = self.directory / "cache" / "agent-harness" / "fx.json"
        cache.parent.mkdir(parents=True)
        for broken in ("{not json", json.dumps({"rate": "158"}), json.dumps({"as_of": "x"}),
                       json.dumps({"base": "USD", "quote": "JPY", "rate": 158, "as_of": "x"}),
                       json.dumps([1])):
            with self.subTest(broken=broken):
                cache.write_text(broken, encoding="utf-8")
                result = self.metrics()
                self.assertIsNone(result["estimated_jpy_with_subagents"])
                self.assertTrue(any("円換算待ち" in note for note in result["notes"]))

    def test_should_surface_notes_from_subagents(self):
        self.write([assistant("m1", output_tokens=1)])
        child = self.directory / "session" / "subagents" / "agent-a.jsonl"
        self.write([assistant("c1", output_tokens=1, speed="fast")], path=child)
        result = self.metrics()
        self.assertIsNone(result["subagents"]["estimated_usd"])
        self.assertFalse(result["comparison_qualified"])

    def test_child_reference_cost_is_not_exposed_as_estimated_yen(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        child = self.directory / "session" / "subagents" / "agent-a.jsonl"
        self.write([assistant("c1", cache_creation_input_tokens=1_000_000)], path=child)
        cache = self.directory / "cache" / "agent-harness" / "fx.json"
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({"base": "USD", "quote": "JPY", "rate": 150.0,
                                     "as_of": "x", "source": "y"}), encoding="utf-8")
        result = self.metrics()
        self.assertIsNone(result["estimated_usd_with_subagents"])
        self.assertAlmostEqual(result["reference_usd_with_subagents"], 25.0)
        self.assertFalse(result["subagents"]["estimate_complete"])
        self.assertIsNone(result["subagents"]["tokens"]["cache_write_5m"])
        self.assertIsNone(result["subagents"]["tokens"]["cache_write_1h"])
        self.assertIsNone(result["estimated_jpy_with_subagents"])

    def test_should_find_transcript_by_session_id(self):
        home = self.directory / "home"
        self.write([assistant("m1", session="abc-123", input_tokens=7)],
                   path=home / ".claude" / "projects" / "proj" / "abc-123.jsonl")
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

    def test_rejects_sensitive_and_database_transcript_paths(self):
        env = dict(os.environ, XDG_CACHE_HOME=str(self.directory / "cache"))
        for component in ("auth", "Codex-note", "Claude-note"):
            target = self.directory / component / "session.jsonl"
            self.write([assistant("m1", input_tokens=1)], path=target)
            link = self.directory / f"{component}.jsonl"
            link.symlink_to(target)
            done = subprocess.run(
                [sys.executable, str(CLI), "metrics", "--transcript", str(link)],
                capture_output=True, text=True, env=env,
            )
            self.assertNotEqual(done.returncode, 0, component)
            self.assertIn("機密・DB path", done.stderr)
        database = self.directory / "session.db"
        self.write([assistant("m1", input_tokens=1)], path=database)
        done = subprocess.run(
            [sys.executable, str(CLI), "metrics", "--transcript", str(database)],
            capture_output=True, text=True, env=env,
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("機密・DB path", done.stderr)

    def test_should_prefer_codex_thread_usage_over_token_count(self):
        thread = {"input_tokens": 100, "cached_input_tokens": 40, "cache_write_input_tokens": 0,
                  "output_tokens": 5, "reasoning_output_tokens": 0, "total_tokens": 105}
        older = {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}
        self.write(
            [
                {"type": "session_meta", "payload": {"id": "s"}},
                {"type": "turn_context", "payload": {"model": "gpt-x"}},
                {"type": "token_usage_record", "payload": {"thread_id": "s", "response_id": "r1",
                  "usage": thread, "thread_token_usage": thread}},
                {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": older}}},
            ]
        )
        result = self.metrics()
        self.assertEqual(result["runtime"], "codex")
        self.assertEqual(result["tokens"], thread)
        self.assertEqual(result["cache_read_rate"]["rate"], 0.4)
        self.assertEqual(result["tool_calls"]["total"], 0)
        self.assertIsNone(result["estimated_usd"])

    def test_codex_thread_total_mismatch_reduces_usage_coverage(self):
        usage = {"input_tokens": 10, "cached_input_tokens": 0,
                 "cache_write_input_tokens": 0, "output_tokens": 1,
                 "reasoning_output_tokens": 0, "total_tokens": 11}
        thread = dict(usage, input_tokens=20, output_tokens=2, total_tokens=22)
        self.write([
            {"type": "session_meta", "payload": {"id": "s"}},
            {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
            {"type": "token_usage_record", "payload": {"thread_id": "s", "response_id": "r1",
                                                        "usage": usage, "thread_token_usage": thread}},
        ])
        result = self.metrics()
        usage_coverage = result["coverage"]["usage"]
        self.assertEqual((usage_coverage["observed"], usage_coverage["expected"], usage_coverage["rate"]),
                         (1, 2, 0.5))
        self.assertFalse(usage_coverage["qualified"])
        self.assertEqual(result["measurement_status"], "not_qualified")
        self.assertFalse(result["comparison_qualified"])
        self.assertIn("thread_total_differs_from_attributed_records", result["notes"])

    def test_codex_result_types_share_one_call_identity(self):
        usage = {"input_tokens": 1, "cached_input_tokens": 0,
                 "cache_write_input_tokens": 0, "output_tokens": 1,
                 "reasoning_output_tokens": 0, "total_tokens": 2}
        self.write([
            {"type": "session_meta", "payload": {"id": "s"}},
            {"type": "token_usage_record", "payload": {"thread_id": "s", "response_id": "r",
                                                        "usage": usage}},
            {"type": "response_item", "payload": {"type": "function_call",
                                                     "call_id": "call-1", "name": "x"}},
            {"type": "response_item", "payload": {"type": "function_call_output",
                                                     "call_id": "call-1", "output": "one"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output",
                                                     "call_id": "call-1", "output": "two"}},
        ])
        result = self.metrics()
        calls = result["tool_calls"]
        classified = sum(calls[key] for key in ("success", "failure", "rejection", "interruption", "unknown"))
        self.assertEqual((calls["total"], classified, calls["unknown"]), (1, 1, 1))

    def test_codex_missing_item_id_is_counted_but_unqualified(self):
        usage = {"input_tokens": 1, "cached_input_tokens": 0,
                 "cache_write_input_tokens": 0, "output_tokens": 1,
                 "reasoning_output_tokens": 0, "total_tokens": 2}
        self.write([
            {"type": "thread.started", "thread_id": "missing-id"},
            {"type": "item.started", "item": {"type": "command_execution"}},
            {"type": "turn.completed", "run_id": "run-1", "turn_id": "turn-1", "usage": usage},
        ])
        result = self.metrics("--session-id", "missing-id", "--model", "gpt-6.1-sol",
                              "--actual-tier", "standard")
        self.assertEqual((result["tool_calls"]["total"], result["tool_calls"]["unknown"],
                          result["tool_calls"]["identity_missing"]), (1, 1, 1))
        self.assertFalse(result["coverage"]["tool_calls"]["qualified"])
        record = next(record for record in result["records"] if record["event"] == "tool_call")
        self.assertIsNone(record["call_id"])

    def test_conflicting_call_type_is_relation_integrity_failure(self):
        usage = {"input_tokens": 1, "cached_input_tokens": 0,
                 "cache_write_input_tokens": 0, "output_tokens": 1,
                 "reasoning_output_tokens": 0, "total_tokens": 2}
        self.write([
            {"type": "session_meta", "payload": {"id": "call-conflict"}},
            {"type": "token_usage_record", "payload": {"thread_id": "call-conflict",
                "response_id": "r", "usage": usage}},
            {"type": "response_item", "payload": {"type": "function_call",
                "call_id": "same", "name": "one"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call",
                "call_id": "same", "name": "two"}},
        ])
        result = self.metrics("--session-id", "call-conflict", "--model", "gpt-6.1-sol",
                              "--actual-tier", "standard")
        self.assertEqual((result["tool_calls"]["total"], result["tool_calls"]["relation_conflicts"]),
                         (1, 1))
        self.assertFalse(result["coverage"]["tool_calls"]["qualified"])
        self.assertIn("conflicting_tool_record", result["coverage"]["tool_calls"]["reasons"])

    def test_conflicting_duplicate_result_becomes_unknown_and_unqualified(self):
        usage = {"input_tokens": 1, "cached_input_tokens": 0,
                 "cache_write_input_tokens": 0, "output_tokens": 1,
                 "reasoning_output_tokens": 0, "total_tokens": 2}
        self.write([
            {"type": "thread.started", "thread_id": "conflict-1"},
            {"type": "item.started", "item": {"id": "cmd-1", "type": "command_execution"}},
            {"type": "item.completed", "item": {"id": "cmd-1", "type": "command_execution",
                                                   "exit_code": 0}},
            {"type": "item.completed", "item": {"id": "cmd-1", "type": "command_execution",
                                                   "exit_code": 2}},
            {"type": "item.completed", "item": {"id": "cmd-1", "type": "command_execution",
                                                   "exit_code": 2}},
            {"type": "turn.completed", "run_id": "run-1", "turn_id": "turn-1", "usage": usage},
        ])
        result = self.metrics("--session-id", "conflict-1", "--model", "gpt-6.1-sol",
                              "--actual-tier", "standard")
        calls = result["tool_calls"]
        classified = sum(calls[key] for key in ("success", "failure", "rejection", "interruption", "unknown"))
        self.assertEqual((calls["total"], classified, calls["unknown"], calls["relation_conflicts"]),
                         (1, 1, 1, 2))
        self.assertTrue(all(calls[key] >= 0 for key in (
            "success", "failure", "rejection", "interruption", "unknown")))
        self.assertFalse(result["coverage"]["tool_calls"]["qualified"])
        self.assertFalse(result["coverage"]["outcome"]["qualified"])
        record = next(record for record in result["records"] if record["event"] == "tool_call")
        self.assertIsNone(record["status"])
        self.assertEqual(record["field_meta"]["status"]["missing_reason"], "conflicting_tool_result")

    def test_result_conflict_permutations_never_make_negative_categories(self):
        usage = {"input_tokens": 1, "cached_input_tokens": 0,
                 "cache_write_input_tokens": 0, "output_tokens": 1,
                 "reasoning_output_tokens": 0, "total_tokens": 2}
        for third_status in ("failure", "interrupted"):
            with self.subTest(third_status=third_status):
                self.write([
                    {"type": "thread.started", "thread_id": "permutation"},
                    {"type": "response_item", "payload": {"type": "function_call",
                        "call_id": "call-1", "name": "tool"}},
                    {"type": "response_item", "payload": {"type": "function_call_output",
                        "call_id": "call-1", "status": "success"}},
                    {"type": "response_item", "payload": {"type": "custom_tool_call_output",
                        "call_id": "call-1", "status": "failure"}},
                    {"type": "response_item", "payload": {"type": "function_call_output",
                        "call_id": "call-1", "status": third_status}},
                    {"type": "turn.completed", "run_id": "run", "turn_id": "turn",
                     "usage": usage},
                ])
                calls = self.metrics("--session-id", "permutation", "--model", "gpt-6.1-sol",
                                     "--actual-tier", "standard")["tool_calls"]
                categories = [calls[key] for key in (
                    "success", "failure", "rejection", "interruption", "unknown")]
                self.assertTrue(all(value >= 0 for value in categories))
                self.assertEqual((sum(categories), calls["total"], calls["unknown"]), (1, 1, 1))

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
        for key, value in total.items():
            self.assertEqual(result["tokens"][key], value)

    def test_assumed_tier_is_reference_only_and_unknown_metadata_has_reason(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        result = self.metrics("--assume-tier", "standard", "--status", "unknown")
        self.assertIsNone(result["estimated_usd"])
        self.assertAlmostEqual(result["reference_usd"], 20.0)
        self.assertFalse(result["comparison_qualified"])
        self.assertEqual(result["field_meta"]["actual_tier"]["state"], "unknown")
        self.assertEqual(result["field_meta"]["status"]["missing_reason"], "status_unavailable")

    def test_codex_exec_json_long_context_fast_price_and_outcome(self):
        usage = {"input_tokens": 300_000, "cached_input_tokens": 100_000,
                 "cache_write_input_tokens": 50_000, "output_tokens": 10_000,
                 "reasoning_output_tokens": 0, "total_tokens": 310_000}
        self.write([
            {"type": "thread.started", "thread_id": "exec-1"},
            {"type": "item.started", "timestamp": "2026-10-13T00:00:00+00:00",
             "item": {"id": "cmd-1", "type": "command_execution"}},
            {"type": "item.completed", "item": {"id": "cmd-1", "type": "command_execution",
                                                   "exit_code": 3, "command": "RAW_COMMAND_SECRET"},
             "timestamp": "2026-10-13T00:00:01+00:00"},
            {"type": "turn.completed", "run_id": "run-1", "turn_id": "turn-1", "usage": usage,
             "timestamp": "2026-10-13T00:00:02+00:00"},
        ])
        result = self.metrics("--session-id", "exec-1", "--model", "gpt-6.1-sol",
                              "--runtime-version", "0.153.4", "--actual-tier", "fast")
        self.assertEqual(result["identity"]["session_id"], "exec-1")
        self.assertEqual(result["tool_calls"]["failure"], 1)
        self.assertEqual(result["coverage"]["outcome"]["rate"], 1.0)
        self.assertAlmostEqual(result["estimated_usd"], 2.04)
        self.assertTrue(result["comparison_qualified"])
        self.assertNotIn("RAW_COMMAND_SECRET", json.dumps(result))
        self.assertEqual(len(result["records"]), 2)
        tool_record = next(record for record in result["records"] if record["event"] == "tool_call")
        usage_record = next(record for record in result["records"] if record["event"] == "usage")
        self.assertEqual(tool_record["status"], "failure")
        self.assertTrue(tool_record["call_id"] and tool_record["call_id"] != "cmd-1")
        self.assertTrue(tool_record["result_id"] and tool_record["result_id"] != "cmd-1")
        self.assertAlmostEqual(usage_record["cost_usd"], 2.04)
        self.assertEqual(tool_record["field_meta"]["call_id"]["observed_at"],
                         "2026-10-13T00:00:00+00:00")
        self.assertEqual(tool_record["field_meta"]["status"]["observed_at"],
                         "2026-10-13T00:00:01+00:00")
        self.assertEqual(tool_record["field_meta"]["call_id"]["source"]["record_type"],
                         "command_execution")
        self.assertEqual(tool_record["field_meta"]["status"]["source"]["record_type"],
                         "command_execution_result")
        self.assertEqual(tool_record["field_meta"]["model"]["source"]["record_type"], "run_manifest")
        self.assertEqual(usage_record["field_meta"]["actual_tier"]["source"]["record_type"],
                         "run_manifest")
        self.assertNotEqual(tool_record["field_meta"]["call_id"]["source"]["id"],
                            tool_record["field_meta"]["status"]["source"]["id"])
        self.assertEqual(tool_record["field_meta"]["model"]["source"]["id"],
                         usage_record["field_meta"]["actual_tier"]["source"]["id"])
        self.assertEqual(tool_record["field_meta"]["pricing_version"]["source"]["id"],
                         usage_record["field_meta"]["cost_usd"]["source"]["id"])
        expected_fields = {"runtime", "event", "call_id", "result_id", "session_id", "task_id",
                           "model", "requested_tier", "actual_tier", "input", "cache_read",
                           "cache_write", "output", "status", "rejection", "interruption",
                           "message_id", "parent_id", "usage_scope", "includes_children",
                           "source_record_id", "cost_usd", "currency", "pricing_version",
                           "fx_rate", "fx_date"}
        self.assertEqual(set(tool_record) - {"field_meta"}, expected_fields)
        self.assertEqual(set(tool_record["field_meta"]), expected_fields)
        for metadata in tool_record["field_meta"].values():
            self.assertEqual(set(metadata["source"]), {"record_type", "id"})
            self.assertIsNotNone(metadata["observed_at"])
            if metadata["state"] == "unknown":
                self.assertTrue(metadata["missing_reason"])

    def test_codex_cache_and_write_exceeding_total_fail_closed(self):
        usage = {"input_tokens": 10, "cached_input_tokens": 8,
                 "cache_write_input_tokens": 4, "output_tokens": 1,
                 "reasoning_output_tokens": 0, "total_tokens": 11}
        self.write([
            {"type": "thread.started", "thread_id": "bad-cache"},
            {"type": "turn.completed", "run_id": "run", "turn_id": "turn",
             "usage": usage},
        ])
        result = self.metrics("--session-id", "bad-cache", "--model", "gpt-6.1-sol",
                              "--actual-tier", "standard")
        usage_record = next(record for record in result["records"] if record["event"] == "usage")
        self.assertIsNone(usage_record["input"])
        self.assertIsNone(result["estimated_usd"])
        self.assertFalse(result["coverage"]["usage"]["qualified"])
        self.assertFalse(result["coverage"]["cost"]["qualified"])
        self.assertIn("invalid_cache_counters", result["coverage"]["usage"]["reasons"])

    def test_codex_standard_context_does_not_double_charge_cache_write(self):
        usage = {"input_tokens": 100_000, "cached_input_tokens": 20_000,
                 "cache_write_input_tokens": 10_000, "output_tokens": 5_000,
                 "reasoning_output_tokens": 0, "total_tokens": 105_000}
        self.write([
            {"type": "thread.started", "thread_id": "standard-cache"},
            {"type": "turn.completed", "run_id": "run", "turn_id": "turn",
             "usage": usage},
        ])
        result = self.metrics("--session-id", "standard-cache", "--model", "gpt-6.1-sol",
                              "--actual-tier", "standard")
        # ordinary input 70k×$2/M + cached 20k×$0.1/M + write 10k×$2.5/M + output 5k×$10/M
        self.assertAlmostEqual(result["estimated_usd"], 0.217)
        usage_record = next(record for record in result["records"] if record["event"] == "usage")
        self.assertEqual(usage_record["input"], 70_000)

    def test_codex_unknown_child_scope_never_qualifies_comparison(self):
        usage = {"input_tokens": 10, "cached_input_tokens": 0,
                 "cache_write_input_tokens": 0, "output_tokens": 1,
                 "reasoning_output_tokens": 0, "total_tokens": 11}
        self.write([
            {"type": "thread.started", "thread_id": "exec-scope"},
            {"type": "turn.completed", "run_id": "run-1", "turn_id": "turn-1", "usage": usage},
        ])
        result = self.metrics("--session-id", "exec-scope", "--model", "gpt-6.1-sol",
                              "--actual-tier", "standard", "--includes-children", "unknown")
        self.assertEqual(result["coverage"]["cost"]["rate"], 1.0)
        self.assertFalse(result["coverage"]["usage"]["qualified"])
        self.assertFalse(result["coverage"]["cost"]["qualified"])
        self.assertTrue(result["coverage"]["tool_calls"]["qualified"])
        self.assertFalse(result["comparison_qualified"])

    def test_children_unknown_scope_are_separate_and_not_combined(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        child = self.directory / "session" / "subagents" / "agent-a.jsonl"
        self.write([assistant("c1", output_tokens=1_000_000)], path=child)
        result = self.metrics("--includes-children", "unknown")
        self.assertAlmostEqual(result["estimated_usd"], 20.0)
        self.assertAlmostEqual(result["subagents"]["estimated_usd"], 20.0)
        self.assertIsNone(result["estimated_usd_with_subagents"])
        self.assertFalse(result["comparison_qualified"])

    def test_unknown_scope_without_discovered_child_does_not_claim_combined_cost(self):
        self.write([assistant("m1", output_tokens=1_000_000)])
        result = self.metrics("--includes-children", "unknown")
        self.assertAlmostEqual(result["estimated_usd"], 20.0)
        self.assertIsNone(result["estimated_usd_with_subagents"])
        self.assertIsNone(result["estimated_jpy_with_subagents"])
        self.assertFalse(result["comparison_qualified"])

    def test_identity_mismatch_fails_closed(self):
        self.write([assistant("m1", session="exact-session")])
        done = subprocess.run(
            [sys.executable, str(CLI), "metrics", "--transcript", str(self.transcript),
             "--session-id", "other-session"], capture_output=True, text=True,
            env=dict(os.environ, XDG_CACHE_HOME=str(self.directory / "cache")),
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("session", done.stderr)

    def test_claude_stream_result_cost_is_estimate_with_unknown_child_scope(self):
        self.write([
            {"type": "system", "subtype": "init", "session_id": "stream-1",
             "model": "claude-opus-5-5", "claude_code_version": "2.1"},
            {"type": "result", "session_id": "stream-1", "total_cost_usd": 1.25,
             "result": "RAW_RESULT_SECRET", "modelUsage": {"claude-opus-5-5": {
                 "inputTokens": 0, "cacheReadInputTokens": 0,
                 "cacheCreationInputTokens": 1_000_000, "outputTokens": 1_000_000,
             }}},
        ])
        result = self.metrics()
        self.assertIsNone(result["estimated_usd"])
        self.assertAlmostEqual(result["reference_usd"], 25.0)
        self.assertEqual(result["usage_scope"], "session_cumulative")
        self.assertEqual(result["reported_estimated_cost"]["basis"], "claude_cli_estimate")
        self.assertEqual(result["field_meta"]["includes_children"]["state"], "unknown")
        self.assertFalse(result["comparison_qualified"])
        self.assertNotIn("RAW_RESULT_SECRET", json.dumps(result))

    def test_claude_cumulative_summary_mismatch_reduces_usage_coverage(self):
        self.write([
            assistant("m1", input_tokens=10, output_tokens=1),
            {"type": "result", "session_id": "session", "modelUsage": {"claude-opus-5-5": {
                "inputTokens": 100, "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0, "outputTokens": 10,
            }}},
        ])
        result = self.metrics()
        usage = result["coverage"]["usage"]
        self.assertEqual((usage["expected"], usage["observed"]), (2, 1))
        self.assertFalse(usage["qualified"])
        self.assertFalse(result["comparison_qualified"])
        self.assertIn("cumulative_summary_differs_from_attributed_records", usage["reasons"])


if __name__ == "__main__":
    unittest.main()
