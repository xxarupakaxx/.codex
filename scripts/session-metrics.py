#!/usr/bin/env python3
"""セッションの構造化記録から、比較可能性・利用量・API換算費用をJSONで返す。"""

from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRICING_FILE = ROOT / "config" / "model-pricing.json"
ANALYZER_FILE = ROOT / "skills" / "analyzing-session-tokens" / "scripts" / "analyze.py"
FX_URL = "https://open.er-api.com/v6/latest/USD"
FX_TIMEOUT_SECONDS = 10
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
OUTCOMES = ("success", "failure", "rejection", "interruption", "unknown")
SOURCE_INTEGRITY = {"malformed_record", "incomplete_tail", "file_changed_during_read",
                    "fork_history_requires_attribution"}
USAGE_INTEGRITY = {"usage_without_session_id_excluded", "unidentifiable_usage_excluded",
                   "required_usage_fields_missing", "reported_total_mismatch",
                   "reasoning_exceeds_output", "invalid_cache_counters",
                   "counter_reset_totals_are_partial", "usage_unavailable",
                   "thread_total_differs_from_attributed_records",
                   "cumulative_summary_differs_from_attributed_records"}
PRICING_ASSUMPTIONS = {"cache_write_tier_unknown_assumed_5m", "cache_write_split_mismatch",
                       "regional_inference_pricing_unknown"}
TOOL_INTEGRITY = {"unmatched_tool_result", "tool_identity_missing", "conflicting_tool_record"}


def load_analyzer():
    spec = importlib.util.spec_from_file_location("session_token_analyzer", ANALYZER_FILE)
    if spec is None or spec.loader is None:
        raise SystemExit("session-metrics: bundle内のanalyze.pyを読み込めない")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANALYZER = load_analyzer()


def fx_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "agent-harness" / "fx.json"


def is_amount(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def read_fx():
    try:
        saved = json.loads(fx_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    valid = (isinstance(saved, dict) and saved.get("base") == "USD" and saved.get("quote") == "JPY"
             and is_amount(saved.get("rate")) and saved["rate"] > 0
             and isinstance(saved.get("source"), str) and bool(saved["source"].strip())
             and isinstance(saved.get("as_of"), str) and bool(saved["as_of"].strip()))
    return saved if valid else None


def ratio(numerator: int, denominator: int, top="numerator", bottom="denominator") -> dict:
    return {top: numerator, bottom: denominator, "rate": numerator / denominator if denominator else None}


def qualify(coverage, reasons, scope):
    return dict(coverage, qualified=not reasons, reasons=sorted(reasons), scope=scope)


def find_transcript(session: str) -> Path:
    if not SESSION_ID.fullmatch(session):
        raise SystemExit("session-metrics: session ID に使えない文字がある")
    home = Path.home()
    found = list((home / ".claude" / "projects").glob(f"*/{session}.jsonl"))
    found += list((home / ".codex" / "sessions").glob(f"*/*/*/rollout-*{session}.jsonl"))
    if len(found) != 1:
        raise SystemExit(f"session-metrics: session {session} の transcript が {len(found)} 件見つかった（1件のときだけ進める）")
    return found[0].resolve()


def reject_sensitive_path(path: Path) -> None:
    lowered = {part.lower() for part in path.parts}
    forbidden = {"codex-note", "claude-note", "auth", "secrets", "secret"}
    if lowered & forbidden or path.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
        raise SystemExit("session-metrics: transcript以外の機密・DB pathは入力にできない")


def infer_identity(path: Path, expected=None):
    warnings = set()
    provider, sessions = None, set()
    for _, row in ANALYZER.read_rows(path, warnings):
        kind = row.get("type")
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if kind == "session_meta" and isinstance(payload.get("id"), str):
            provider, sessions = "codex", {payload["id"]}
            break
        if kind == "thread.started" and isinstance(row.get("thread_id") or payload.get("thread_id"), str):
            provider, sessions = "codex", {row.get("thread_id") or payload.get("thread_id")}
            break
        claude_session = row.get("sessionId") or row.get("session_id")
        if isinstance(claude_session, str):
            provider, sessions = "claude", sessions | {claude_session}
    if provider is None or (expected is None and len(sessions) != 1) or (expected is not None and expected not in sessions):
        raise SystemExit("session-metrics: transcriptのruntime/sessionを一意に照合できない（--session-idを指定する）")
    return provider, expected or next(iter(sessions))


def detect_provider(path: Path) -> str:
    warnings = set()
    for _, row in ANALYZER.read_rows(path, warnings):
        if row.get("type") in ("session_meta", "thread.started"):
            return "codex"
        if row.get("sessionId") is not None or row.get("session_id") is not None:
            return "claude"
    raise SystemExit("session-metrics: runtimeを判定できない")


def price_for(model, pricing):
    if not model or model == "unknown":
        return None
    models = pricing.get("models", {})
    return models.get(model) or models.get(re.sub(r"-\d{8}$", "", model))


def price_row(row, pricing, explicit_tier=None, assumed_tier=None):
    model = row.get("model")
    schedule = price_for(model, pricing)
    observed_tier = row.get("actual_tier")
    conflict = bool(explicit_tier and observed_tier and explicit_tier != observed_tier)
    actual_tier = None if conflict else (observed_tier or explicit_tier)
    used_tier = actual_tier or assumed_tier
    tokens = row.get("billing_tokens", {})
    if schedule is None:
        return None, None, "unknown_model"
    if used_tier not in schedule.get("tiers", {}):
        return None, None, "unknown_tier"
    if any(value is None for value in tokens.values()):
        return None, None, "usage_missing"
    rates = {key: schedule.get(key) for key in tokens}
    if any(not is_amount(value) for value in rates.values()):
        return None, None, "price_missing"
    tier_multiplier = schedule["tiers"][used_tier]
    long = schedule.get("long_context", {})
    long_request = row.get("tokens", {}).get("input_tokens")
    long_request = is_amount(long_request) and long_request > long.get("threshold_input_tokens", math.inf)
    cost = 0.0
    for key, amount in tokens.items():
        multiplier = long.get(key + "_multiplier", 1) if long_request else 1
        cost += amount * rates[key] * multiplier * tier_multiplier / 1_000_000
    state = "estimated" if actual_tier else "reference"
    return cost, state, None


def cost_rows(rows, pricing, explicit_tier=None, assumed_tier=None):
    costs, missing, states = [], [], []
    for row in rows:
        cost, state, reason = price_row(row, pricing, explicit_tier, assumed_tier)
        if cost is None:
            missing.append({"source_record_id": row.get("source_record_id"), "reason": reason})
        else:
            costs.append(cost)
            states.append(state)
    return {"value": sum(costs) if rows and not missing else None,
            "priced_subtotal": sum(costs) if costs else None,
            "expected": len(rows), "observed": len(costs),
            "state": "estimated" if states and set(states) == {"estimated"} else "reference",
            "missing": missing}


def model_rows(rows, pricing, explicit_tier=None, assumed_tier=None):
    result = {}
    for model in sorted({row["model"] for row in rows}):
        group = [row for row in rows if row["model"] == model]
        priced = cost_rows(group, pricing, explicit_tier, assumed_tier)
        keys = sorted({key for row in group for key in row["billing_tokens"]})
        tokens = {
            key: (sum(row["billing_tokens"][key] for row in group)
                  if all(row["billing_tokens"].get(key) is not None for row in group)
                  and not (key in ("cache_write_5m", "cache_write_1h")
                           and any(not row.get("cache_write_split_known") for row in group))
                  else None)
            for key in keys
        }
        result[model] = {"messages": len(group), "tokens": tokens,
                         "usd": priced["value"] if priced["state"] == "estimated" else None,
                         "reference_usd": priced["value"] if priced["state"] == "reference" else None,
                         "cost_state": priced["state"] if priced["value"] is not None else "unknown",
                         "reason": priced["missing"][0]["reason"] if priced["missing"] else None}
    return result


RECORD_FIELDS = ("runtime", "event", "call_id", "result_id", "session_id", "task_id", "model",
                 "requested_tier", "actual_tier", "input", "cache_read", "cache_write", "output",
                 "status", "rejection", "interruption", "message_id", "parent_id", "usage_scope",
                 "includes_children", "source_record_id", "cost_usd", "currency", "pricing_version",
                 "fx_rate", "fx_date")


def sanitized_records(provider, rows, sources, args, pricing, fx, observed_at, includes_children):
    """Expose numeric/schema evidence only; IDs are stable hashes and content is never retained."""
    result = []
    warnings_by_source = {source["source"]: set(source["warnings"]) for source in sources}

    manifest_seed = ["run_manifest", args.run_id, args.task_id, args.model,
                     args.requested_tier, args.actual_tier, args.includes_children]
    pricing_seed = ["pricing", pricing.get("version")]
    fx_seed = ["fx", fx.get("source"), fx.get("as_of")] if fx else ["fx", "unavailable"]

    def finish(values, record_type, missing=None, provenance=None):
        timestamp = ANALYZER.observed_time(values.pop("_observed_at", None)) or observed_at
        relation_reason = values.pop("_relation_reason", None)
        source_id = values.get("source_record_id")
        item = {name: values.get(name) for name in RECORD_FIELDS}
        item["field_meta"] = {}
        for name in RECORD_FIELDS:
            value = item[name]
            state = "estimated" if name == "cost_usd" and value is not None else (
                "observed" if value is not None else "unknown")
            source_type = ("pricing" if name in ("cost_usd", "currency", "pricing_version")
                           else "fx_cache" if name in ("fx_rate", "fx_date")
                           else "run_manifest" if name in ("task_id", "requested_tier", "includes_children")
                           else record_type)
            field_time, source_seed = timestamp, source_id
            if provenance and name in provenance:
                source_type, field_time, source_seed = provenance[name]
                field_time = ANALYZER.observed_time(field_time) or observed_at
            _, item["field_meta"][name] = meta(
                value, state, source_type, source_seed, field_time,
                (missing or {}).get(name, name + "_unavailable"),
            )
        if relation_reason:
            _, item["relation_meta"] = meta(
                None, "unknown", record_type, [source_id, "relation"], timestamp, relation_reason)
        result.append(item)

    for row in rows:
        cost, cost_state, cost_reason = price_row(row, pricing, args.actual_tier, args.assume_tier)
        cost = cost if cost_state == "estimated" else None
        invalid_cost = warnings_by_source.get(row["source"], set()).intersection(
            SOURCE_INTEGRITY | USAGE_INTEGRITY | PRICING_ASSUMPTIONS)
        if invalid_cost:
            cost, cost_reason = None, sorted(invalid_cost)[0]
        tokens = row["tokens"]
        usage_seed = row["source_record_id"]
        model_source = "run_manifest" if row.get("model_source") == "run_manifest" else "transcript_usage"
        tier_source = "transcript_usage" if row["actual_tier"] else "run_manifest"
        finish({
            "runtime": row["runtime"], "event": "usage",
            "call_id": row["call_id"],
            "result_id": None, "session_id": row["session_id"], "task_id": args.task_id,
            "model": row["model"] if row["model"] != "unknown" else None,
            "requested_tier": args.requested_tier, "actual_tier": row["actual_tier"] or args.actual_tier,
            "input": tokens["uncached_input_tokens"], "cache_read": tokens["cached_input_tokens"],
            "cache_write": tokens["cache_write_input_tokens"], "output": tokens["output_tokens"],
            "status": None, "rejection": None, "interruption": None,
            "message_id": row["message_id"], "parent_id": row.get("parent_id"),
            "usage_scope": row["usage_scope"],
            "includes_children": includes_children,
            "source_record_id": row["source_record_id"], "cost_usd": cost,
            "currency": "USD", "pricing_version": pricing.get("version"),
            "fx_rate": fx.get("rate") if fx else None, "fx_date": fx.get("as_of") if fx else None,
            "_observed_at": row.get("timestamp"),
        }, "transcript_usage", {"cost_usd": cost_reason or "cost_not_comparison_qualified"}, {
            "model": (model_source, observed_at if model_source == "run_manifest" else row.get("timestamp"),
                      manifest_seed if model_source == "run_manifest" else usage_seed),
            "actual_tier": (tier_source, observed_at if tier_source == "run_manifest" else row.get("timestamp"),
                            manifest_seed if tier_source == "run_manifest" else usage_seed),
            "task_id": ("run_manifest", observed_at, manifest_seed),
            "requested_tier": ("run_manifest", observed_at, manifest_seed),
            "includes_children": ("run_manifest", observed_at, manifest_seed),
            "cost_usd": ("pricing", observed_at, pricing_seed),
            "currency": ("pricing", observed_at, pricing_seed),
            "pricing_version": ("pricing", observed_at, pricing_seed),
            "fx_rate": ("fx_cache", observed_at, fx_seed),
            "fx_date": ("fx_cache", observed_at, fx_seed),
        })

    for source in sources:
        for record in source["activity"]["records"]:
            call_seed = record["source_record_id"]
            result_seed = record.get("result_source_record_id") or call_seed
            finish({
                "runtime": provider, "event": record["event"], "call_id": record["call_id"],
                "result_id": record["result_id"], "session_id": record["session_id"],
                "task_id": args.task_id, "model": record.get("model") or args.model,
                "requested_tier": args.requested_tier,
                "actual_tier": record.get("actual_tier") or args.actual_tier,
                "input": None, "cache_read": None,
                "cache_write": None, "output": None, "status": record["status"],
                "rejection": record["rejection"], "interruption": record["interruption"],
                "message_id": record["message_id"], "parent_id": record["parent_id"],
                "usage_scope": None, "includes_children": includes_children,
                "source_record_id": record["source_record_id"], "cost_usd": None,
                "currency": "USD", "pricing_version": pricing.get("version"),
                "fx_rate": fx.get("rate") if fx else None, "fx_date": fx.get("as_of") if fx else None,
                "_observed_at": record.get("call_observed_at"),
                "_relation_reason": record.get("relation_reason"),
            }, record["record_type"], {
                "call_id": record.get("call_id_reason") or "call_id_unavailable",
                "result_id": record.get("result_id_reason") or "result_id_unavailable",
                "status": record.get("status_reason") or "status_unavailable",
                "rejection": record.get("status_reason") or "rejection_unavailable",
                "interruption": record.get("status_reason") or "interruption_unavailable",
            }, {
                "result_id": (record.get("result_record_type") or record["record_type"],
                              record.get("result_observed_at"), result_seed),
                "status": (record.get("result_record_type") or record["record_type"],
                           record.get("result_observed_at"), result_seed),
                "rejection": (record.get("result_record_type") or record["record_type"],
                              record.get("result_observed_at"), result_seed),
                "interruption": (record.get("result_record_type") or record["record_type"],
                                 record.get("result_observed_at"), result_seed),
                "model": ((record["record_type"], record.get("call_observed_at"), call_seed)
                          if record.get("model") else ("run_manifest", observed_at, manifest_seed)),
                "actual_tier": ((record["record_type"], record.get("call_observed_at"), call_seed)
                                if record.get("actual_tier") else ("run_manifest", observed_at, manifest_seed)),
                "task_id": ("run_manifest", observed_at, manifest_seed),
                "requested_tier": ("run_manifest", observed_at, manifest_seed),
                "includes_children": ("run_manifest", observed_at, manifest_seed),
                "cost_usd": ("pricing", observed_at, pricing_seed),
                "currency": ("pricing", observed_at, pricing_seed),
                "pricing_version": ("pricing", observed_at, pricing_seed),
                "fx_rate": ("fx_cache", observed_at, fx_seed),
                "fx_date": ("fx_cache", observed_at, fx_seed),
            })
    return result


def meta(value, state, record_type, record_id, observed_at, reason=None):
    item = {"state": state,
            "source": {"record_type": record_type, "id": ANALYZER.digest(record_id)},
            "observed_at": observed_at,
            "missing_reason": reason if state == "unknown" else None}
    return value, item


def tool_summary(sources):
    counts = {key: 0 for key in OUTCOMES}
    expected = observed = known = 0
    unmatched = identity_missing = conflicts = 0
    for source in sources:
        activity = source["activity"]
        expected += activity["tool_calls_expected"]
        observed += activity["tool_results_matched"]
        known += activity["tool_outcomes_known"]
        unmatched += activity["unmatched_results"]
        identity_missing += activity["tool_identity_missing"]
        conflicts += activity["relation_conflicts"]
        for key in OUTCOMES:
            counts[key] += activity["tool_outcomes"][key]
    resolved = counts["success"] + counts["failure"]
    counts.update(total=expected, errors=counts["failure"], resolved=resolved,
                  unresolved=max(expected - observed, 0),
                  unmatched_results=unmatched, identity_missing=identity_missing,
                  relation_conflicts=conflicts,
                  rate=counts["failure"] / resolved if resolved else None)
    return counts, {"tool_calls": {"expected": expected, "observed": observed,
                                    "rate": observed / expected if expected else None},
                    "outcome": {"expected": expected, "observed": known,
                                "rate": known / expected if expected else None}}


def legacy_tokens(provider, tokens, rows):
    if provider == "claude":
        total_write = tokens["cache_write_input_tokens"]
        if total_write == 0 and all(row.get("cache_write_split_known") for row in rows):
            write_5m = write_1h = 0
        elif rows and all(row.get("cache_write_split_known") for row in rows):
            write_5m = sum(row["billing_tokens"]["cache_write_5m"] for row in rows)
            write_1h = sum(row["billing_tokens"]["cache_write_1h"] for row in rows)
        else:
            write_5m = write_1h = None
        result = {"input": tokens["uncached_input_tokens"],
                  "cache_read": tokens["cached_input_tokens"],
                  "cache_write": total_write, "cache_write_5m": write_5m,
                  "cache_write_1h": write_1h, "output": tokens["output_tokens"],
                  "input_total": tokens["input_tokens"]}
        return result
    return {"input_tokens": tokens["input_tokens"],
            "cached_input_tokens": tokens["cached_input_tokens"],
            "cache_write_input_tokens": tokens["cache_write_input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "reasoning_output_tokens": tokens["reasoning_output_tokens"],
            "total_tokens": tokens["total_tokens"]}


def command_metrics(args) -> int:
    path = (Path(args.transcript).expanduser().resolve() if args.transcript else find_transcript(args.session))
    reject_sensitive_path(path)
    if path.suffix != ".jsonl" or not path.is_file():
        raise SystemExit(f"session-metrics: transcript JSONL がない: {path}")
    provider = detect_provider(path)
    requested_session = args.session_id or args.session
    inferred_provider, inferred_session = infer_identity(path, requested_session)
    session_id = requested_session or inferred_session
    if not SESSION_ID.fullmatch(session_id or "") or provider != inferred_provider or session_id != inferred_session:
        raise SystemExit("session-metrics: session identity が transcript と一致しない")
    try:
        path = ANALYZER.resolve_log(provider, session_id, path.parent, path)
    except ANALYZER.AnalysisError as error:
        raise SystemExit(f"session-metrics: {error}") from None

    include_children = args.include_children or provider == "claude"
    try:
        report, rows = ANALYZER.build_report(provider, session_id, path.parent, path, include_children)
    except ANALYZER.AnalysisError as error:
        raise SystemExit(f"session-metrics: {error}") from None
    if args.model:
        for row in rows:
            if row["model"] == "unknown":
                row["model"] = args.model
                row["model_source"] = "run_manifest"
        report["by_model"] = {model: ANALYZER.summed([row for row in rows if row["model"] == model])
                              for model in sorted({row["model"] for row in rows})}
    if args.runtime_version:
        for source in report["sources"]:
            if source["version"] == "unknown":
                source["version"] = args.runtime_version
    pricing = json.loads(PRICING_FILE.read_text(encoding="utf-8"))
    main_rows = [row for row in rows if row["source"] == "main"]
    child_rows = [row for row in rows if row["source"] != "main"]
    has_child_sources = len(report["sources"]) > 1
    main_cost = cost_rows(main_rows, pricing, args.actual_tier, args.assume_tier)
    child_cost = cost_rows(child_rows, pricing, args.actual_tier, args.assume_tier)
    stream_scope_unknown = any("claude_stream_result_session_cumulative" in source["warnings"]
                               for source in report["sources"])
    main_warnings = set(report["sources"][0]["warnings"])
    child_warnings = {warning for source in report["sources"][1:] for warning in source["warnings"]}
    if main_warnings.intersection(PRICING_ASSUMPTIONS) and main_cost["value"] is not None:
        main_cost["state"] = "reference"
    if child_warnings.intersection(PRICING_ASSUMPTIONS) and child_cost["value"] is not None:
        child_cost["state"] = "reference"
    tools, tool_coverage = tool_summary(report["sources"][:1])
    child_tools, child_tool_coverage = tool_summary(report["sources"][1:])
    main_source = report["sources"][0]
    main_usage_coverage = ratio(main_source["usage_complete"], main_source["usage_expected"],
                                "observed", "expected")
    source_reasons = main_warnings.intersection(SOURCE_INTEGRITY)
    scope_reasons = ({"includes_children_unknown"}
                     if args.includes_children == "unknown" or stream_scope_unknown else set())
    usage_reasons = source_reasons | main_warnings.intersection(USAGE_INTEGRITY) | scope_reasons
    tool_reasons = source_reasons | main_warnings.intersection(TOOL_INTEGRITY)
    outcome_reasons = tool_reasons | main_warnings.intersection({"tool_outcome_unknown"})
    cost_reasons = usage_reasons | main_warnings.intersection(PRICING_ASSUMPTIONS)
    cost_reasons.update(item["reason"] for item in main_cost["missing"])
    if args.assume_tier:
        cost_reasons.add("assumed_tier_reference")
    main_numeric_integrity = source_reasons | main_warnings.intersection(USAGE_INTEGRITY)
    if main_numeric_integrity:
        main_cost["value"], main_cost["state"] = None, "unknown"
    coverage = {
        "tool_calls": qualify(tool_coverage["tool_calls"], tool_reasons, "main"),
        "outcome": qualify(tool_coverage["outcome"], outcome_reasons, "main"),
        "usage": qualify(main_usage_coverage, usage_reasons, "parent_claim"),
        "cost": qualify({
            "expected": main_cost["expected"], "observed": main_cost["observed"],
            "rate": main_cost["observed"] / main_cost["expected"] if main_cost["expected"] else None,
        }, cost_reasons, "parent_claim"),
    }
    child_usage_raw = ratio(sum(source["usage_complete"] for source in report["sources"][1:]),
                            sum(source["usage_expected"] for source in report["sources"][1:]),
                            "observed", "expected")
    child_source_reasons = child_warnings.intersection(SOURCE_INTEGRITY)
    child_usage_reasons = child_source_reasons | child_warnings.intersection(USAGE_INTEGRITY)
    child_tool_reasons = child_source_reasons | child_warnings.intersection(TOOL_INTEGRITY)
    child_outcome_reasons = child_tool_reasons | child_warnings.intersection({"tool_outcome_unknown"})
    child_cost_reasons = child_usage_reasons | child_warnings.intersection(PRICING_ASSUMPTIONS)
    child_cost_reasons.update(item["reason"] for item in child_cost["missing"])
    if args.assume_tier:
        child_cost_reasons.add("assumed_tier_reference")
    if child_source_reasons or child_warnings.intersection(USAGE_INTEGRITY):
        child_cost["value"], child_cost["state"] = None, "unknown"
    child_coverage = {
        "tool_calls": qualify(child_tool_coverage["tool_calls"], child_tool_reasons, "children"),
        "outcome": qualify(child_tool_coverage["outcome"], child_outcome_reasons, "children"),
        "usage": qualify(child_usage_raw, child_usage_reasons, "children"),
        "cost": qualify({
            "expected": child_cost["expected"], "observed": child_cost["observed"],
            "rate": child_cost["observed"] / child_cost["expected"] if child_cost["expected"] else None,
        }, child_cost_reasons, "children"),
    }
    usage_complete = coverage["usage"]["qualified"]
    outcome_complete = coverage["outcome"]["qualified"] and tools["unknown"] == 0
    run_outcome_known = args.status != "unknown"
    measurement_qualified = usage_complete and outcome_complete and run_outcome_known
    child_scope_complete = (not stream_scope_unknown and args.includes_children != "unknown"
                            and (not has_child_sources or args.includes_children == "yes"
                            or (args.includes_children == "no" and child_coverage["usage"]["qualified"]
                                and child_coverage["outcome"]["qualified"]
                                and child_coverage["cost"]["qualified"]))
                            )
    comparison_qualified = (measurement_qualified and coverage["cost"]["qualified"]
                            and not args.assume_tier and child_scope_complete
                            and main_cost["state"] == "estimated"
                            and (args.includes_children != "no" or not has_child_sources
                                 or child_cost["state"] == "estimated"))

    observed_at = report["snapshot_at"]
    models = sorted({row["model"] for row in main_rows})
    versions = [main_source["version"]]
    actual_tiers = sorted({row["actual_tier"] or args.actual_tier for row in main_rows
                           if row["actual_tier"] or args.actual_tier})
    field_meta = {}
    fields = {}
    known_fields = {
        "runtime": provider, "session": session_id, "task": args.task_id, "run": args.run_id,
        "model": models[0] if len(models) == 1 and models[0] != "unknown" else None,
        "version": versions[0] if len(versions) == 1 and versions[0] != "unknown" else None,
        "requested_tier": args.requested_tier,
        "actual_tier": actual_tiers[0] if len(actual_tiers) == 1 else None,
        "status": None if args.status == "unknown" else args.status,
        "usage_scope": ((lambda scopes: next(iter(scopes)) if len(scopes) == 1 else "mixed")(
            {row["usage_scope"] for row in main_rows}) if main_rows else None),
        "includes_children": None if stream_scope_unknown else args.includes_children,
        "source_record_id": report["target"], "pricing_version": pricing.get("version"),
        "currency": "USD",
    }
    for name, value in known_fields.items():
        state = "observed" if value is not None and value != "unknown" else "unknown"
        manifest_fields = {"task", "run", "requested_tier", "status", "includes_children"}
        record_type = ("run_manifest" if name in manifest_fields
                       or name == "model" and args.model
                       or name == "version" and args.runtime_version
                       or name == "actual_tier" and args.actual_tier
                       else "pricing_file" if name in ("pricing_version", "currency")
                       else "transcript")
        fields[name], field_meta[name] = meta(value, state, record_type, [name, report["target"]],
                                             observed_at, name + "_unavailable")
    fx = read_fx()
    for name, value in (("fx_rate", fx.get("rate") if fx else None),
                        ("fx_date", fx.get("as_of") if fx else None)):
        state = "observed" if value is not None else "unknown"
        fields[name], field_meta[name] = meta(value, state, "fx_cache", [name, report["target"]],
                                             observed_at, "fx_unavailable")

    notes = sorted({warning for source in report["sources"] for warning in source["warnings"]})
    if args.assume_tier:
        notes.append("assumed tierによる参考額であり、比較の採否には使えない")
    if main_cost["missing"] or child_cost["missing"]:
        notes.append("model・actual tier・usage・単価のいずれかが未確認のため費用は未取得")
    if main_cost["priced_subtotal"] is not None and main_cost["value"] is None:
        notes.append("一部のrecordだけ価格を確認できたため、priced subtotalだけを返した")
    if fx is None:
        notes.append("為替の保存値がない、または読めないので円換算待ち")
    tokens = legacy_tokens(provider, ANALYZER.summed(main_rows), main_rows)
    main_by_model = {model: ANALYZER.summed([row for row in main_rows if row["model"] == model])
                     for model in sorted({row["model"] for row in main_rows})}
    model_details = model_rows(main_rows, pricing, args.actual_tier, args.assume_tier)
    if main_numeric_integrity:
        for details in model_details.values():
            details["usd"] = details["reference_usd"] = None
            details["cost_state"] = "unknown"
            details["reason"] = sorted(main_numeric_integrity)[0]
    elif main_warnings.intersection(PRICING_ASSUMPTIONS):
        reason = sorted(main_warnings.intersection(PRICING_ASSUMPTIONS))[0]
        for details in model_details.values():
            if details["usd"] is not None:
                details["reference_usd"], details["usd"] = details["usd"], None
            details["cost_state"] = "reference"
            details["reason"] = details["reason"] or reason
    token_field_meta = {}
    for name, value in tokens.items():
        state = "observed" if value is not None else "unknown"
        _, token_field_meta[name] = meta(value, state, "transcript_usage",
                                         [name, report["target"]], observed_at,
                                         name + "_unavailable")
    record_scope = None if stream_scope_unknown else args.includes_children
    main_records = sanitized_records(provider, main_rows, report["sources"][:1], args, pricing, fx,
                                     observed_at, record_scope)
    child_records = sanitized_records(provider, child_rows, report["sources"][1:], args, pricing, fx,
                                      observed_at, None)
    result = dict(fields, schema_version=2, runtime=provider, session_id=session_id,
                  identity={"session_id": session_id, "transcript_path": str(path), "matched": True},
                  transcript=str(path), collected_at=observed_at, field_meta=field_meta,
                  token_field_meta=token_field_meta,
                  measurement_status="qualified" if measurement_qualified else "not_qualified",
                  collector_measurement_status=report["measurement_status"],
                  comparison_qualified=comparison_qualified, coverage=coverage,
                  tokens=tokens, tool_calls=tools, records=main_records,
                  sources=report["sources"], by_model=main_by_model,
                  models=model_details,
                  estimated_usd=main_cost["value"] if main_cost["state"] == "estimated" else None,
                  reference_usd=main_cost["value"] if main_cost["state"] == "reference" else None,
                  priced_subtotal_usd=main_cost["priced_subtotal"],
                  estimate_complete=main_cost["value"] is not None and main_cost["state"] == "estimated",
                  recorded_cost=report["sources"][0].get("recorded_cost"),
                  reported_estimated_cost=report["sources"][0].get("reported_estimated_cost"),
                  notes=notes, bad_lines=sum(source.get("bad_lines", 0) for source in report["sources"]))
    if provider == "claude":
        result["messages"] = len(main_rows)
        result["estimate_scope"] = (
            "transcriptにある構造化usageだけを集計する。親子scopeが未確認の累積値は比較へ使わない"
        )
    else:
        result["token_source"] = ("token_count" if any(row["usage_scope"] == "session_cumulative"
                                                         for row in main_rows) else "token_usage_record")
    input_total = tokens.get("input_total", tokens.get("input_tokens"))
    cache_read = tokens.get("cache_read", tokens.get("cached_input_tokens"))
    if cache_read is None or input_total is None:
        result["cache_read_rate"] = {"numerator": None, "denominator": None, "rate": None}
    else:
        result["cache_read_rate"] = ratio(cache_read, input_total)
    if has_child_sources:
        result["subagents"] = {"files": len(report["sources"]) - 1,
                               "tokens": legacy_tokens(provider, ANALYZER.summed(child_rows), child_rows),
                               "records": child_records,
                               "coverage": child_coverage,
                               "tool_calls": child_tools,
                               "estimated_usd": child_cost["value"] if child_cost["state"] == "estimated" else None,
                               "reference_usd": child_cost["value"] if child_cost["state"] == "reference" else None,
                               "estimate_complete": (child_cost["value"] is not None
                                                     and child_cost["state"] == "estimated")}
    if args.includes_children == "unknown" or stream_scope_unknown:
        combined = None
        combined_state = "unknown"
        result["notes"].append("includes_children がunknownのため親子費用を合算していない")
    elif args.includes_children == "yes" or not has_child_sources:
        combined = main_cost["value"]
        combined_state = main_cost["state"]
    elif args.includes_children == "no" and main_cost["value"] is not None and child_cost["value"] is not None:
        combined = main_cost["value"] + child_cost["value"]
        combined_state = ("estimated" if main_cost["state"] == child_cost["state"] == "estimated"
                          else "reference")
    else:
        combined = None
        combined_state = "unknown"
        result["notes"].append("子sourceの費用coverageが不足しているため親子費用を合算していない")
    result["estimated_usd_with_subagents"] = combined if combined_state == "estimated" else None
    result["reference_usd_with_subagents"] = combined if combined_state == "reference" else None
    result["fx"] = fx
    result["estimated_jpy_with_subagents"] = combined * fx["rate"] if (
        fx and combined is not None and combined_state == "estimated") else None
    if result["bad_lines"]:
        result["notes"].append(f"読めない行 {result['bad_lines']} 件を除いた部分集計である")
    success_runs = 1 if args.status == "success" else 0
    result["cost_per_success_usd"] = (combined / success_runs if success_runs
                                      and comparison_qualified and combined is not None else None)
    cost_value = result["estimated_usd"]
    cost_state = "estimated" if cost_value is not None else "unknown"
    _, result["field_meta"]["cost_usd"] = meta(
        cost_value, cost_state, "pricing", [pricing.get("version"), report["target"]], observed_at,
        "cost_unavailable" if cost_value is None else None)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


def command_fx(_args) -> int:
    print(f"session-metrics: 為替の取得を開始 {FX_URL}", file=sys.stderr)
    try:
        with urllib.request.urlopen(FX_URL, timeout=FX_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
        rate = payload["rates"]["JPY"]
        if not is_amount(rate) or rate <= 0:
            raise ValueError(f"JPY のレートが不正: {rate!r}")
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as error:
        print(f"session-metrics: 為替の取得に失敗（保存値は変えていない）: {error}", file=sys.stderr)
        return 1
    saved = {"base": "USD", "quote": "JPY", "rate": rate,
             "as_of": payload.get("time_last_update_utc"), "source": FX_URL,
             "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    cache = fx_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"session-metrics: 為替の取得が完了 {cache}", file=sys.stderr)
    json.dump(saved, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    metrics = commands.add_parser("metrics")
    target = metrics.add_mutually_exclusive_group(required=True)
    target.add_argument("--session")
    target.add_argument("--transcript")
    metrics.add_argument("--session-id")
    metrics.add_argument("--task-id")
    metrics.add_argument("--run-id")
    metrics.add_argument("--requested-tier")
    metrics.add_argument("--actual-tier")
    metrics.add_argument("--assume-tier")
    metrics.add_argument("--model", help="manifestで明示された実効model")
    metrics.add_argument("--runtime-version", help="manifestで明示されたruntime version")
    metrics.add_argument("--status", choices=OUTCOMES, default="unknown")
    metrics.add_argument("--includes-children", choices=("yes", "no", "unknown"), default="unknown")
    metrics.add_argument("--include-children", action="store_true")
    metrics.set_defaults(run=command_metrics)
    fx = commands.add_parser("fx")
    fx.set_defaults(run=command_fx)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
