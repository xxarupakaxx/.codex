#!/usr/bin/env python3
"""Read local usage counters, never print transcript text or execute log contents."""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("input_tokens", "uncached_input_tokens", "cached_input_tokens",
          "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
MAX_BYTES = 64 * 1024 * 1024
MAX_LINE = 8 * 1024 * 1024
MAX_FILES = 128
MAX_CANDIDATES = 10000
ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
LABEL = re.compile(r"[A-Za-z0-9_.:/-]{1,128}\Z")


class AnalysisError(Exception):
    pass


def number(value):
    return value if type(value) is int and value >= 0 else None


def total(values):
    values = list(values)
    return sum(values) if values and all(v is not None for v in values) else None


def subtract(a, b):
    return a - b if a is not None and b is not None and a >= b else None


def subtract_all(value, *parts):
    return value - sum(parts) if value is not None and all(
        part is not None for part in parts) and value >= sum(parts) else None


def label(value):
    return value if isinstance(value, str) and LABEL.fullmatch(value) else "unknown"


def tier(usage):
    """Return only an explicitly reported effective tier."""
    if not isinstance(usage, dict):
        return None
    speed = usage.get("speed")
    if speed in ("fast", "ultrafast"):
        return speed
    service = usage.get("service_tier")
    if service in ("standard", "fast", "ultrafast", "batch", "flex"):
        return service
    return None


def billing_tokens(usage, provider):
    """Keep per-request pricing counters without changing the legacy totals."""
    usage = usage if isinstance(usage, dict) else {}
    if provider == "claude":
        split = usage.get("cache_creation")
        split = split if isinstance(split, dict) else {}
        write = number(usage.get("cache_creation_input_tokens"))
        write_5m = number(split.get("ephemeral_5m_input_tokens")) if split else write
        write_1h = number(split.get("ephemeral_1h_input_tokens")) if split else 0
        if split and (write is None or write_5m is None or write_1h is None or write_5m + write_1h != write):
            write_5m = write_1h = None
        return {"input": number(usage.get("input_tokens")),
                "cache_read": number(usage.get("cache_read_input_tokens")),
                "cache_write_5m": write_5m, "cache_write_1h": write_1h,
                "output": number(usage.get("output_tokens"))}
    inp = number(usage.get("input_tokens"))
    cached = number(usage.get("cached_input_tokens"))
    write = number(usage.get("cache_write_input_tokens"))
    return {"input": subtract_all(inp, cached, write), "cache_read": cached,
            "cache_write": write,
            "output": number(usage.get("output_tokens"))}


def cache_write_split_known(usage, provider):
    """Whether provider-reported cache-write TTL buckets are complete and consistent."""
    if provider != "claude":
        return True
    usage = usage if isinstance(usage, dict) else {}
    write = number(usage.get("cache_creation_input_tokens"))
    split = usage.get("cache_creation")
    if write == 0 and not isinstance(split, dict):
        return True
    if not isinstance(split, dict):
        return False
    five = number(split.get("ephemeral_5m_input_tokens"))
    one = number(split.get("ephemeral_1h_input_tokens"))
    return write is not None and five is not None and one is not None and five + one == write


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def observed_time(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def normalize(usage, provider):
    usage = usage if isinstance(usage, dict) else {}
    inp = number(usage.get("input_tokens"))
    out = number(usage.get("output_tokens"))
    if provider == "claude":
        cache = number(usage.get("cache_read_input_tokens"))
        write = number(usage.get("cache_creation_input_tokens"))
        uncached, inp = inp, total([inp, cache, write])
        details = usage.get("output_tokens_details") or {}
        reasoning = number(details.get("thinking_tokens")) if isinstance(details, dict) else None
    else:
        cache = number(usage.get("cached_input_tokens"))
        write = number(usage.get("cache_write_input_tokens"))
        uncached = subtract_all(inp, cache, write)
        reasoning = number(usage.get("reasoning_output_tokens"))
    return dict(zip(FIELDS, [inp, uncached, cache, write, out, reasoning, total([inp, out])]))


def summed(rows):
    return {key: total(row["tokens"][key] for row in rows) for key in FIELDS}


def read_rows(path, warnings, parse_counts=None):
    """Read a fixed byte boundary so a live writer cannot extend this run forever."""
    try:
        limit = path.stat().st_size
        if limit > MAX_BYTES:
            raise AnalysisError("log_too_large: select a smaller explicit transcript")
        with path.open("rb") as stream:
            remaining = limit
            line_no = 0
            while remaining:
                raw = stream.readline(min(remaining, MAX_LINE + 1))
                if not raw:
                    warnings.add("file_changed_during_read")
                    break
                remaining -= len(raw)
                line_no += 1
                if len(raw) > MAX_LINE:
                    raise AnalysisError("log_line_too_large")
                try:
                    row = json.loads(raw)
                    if not isinstance(row, dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    warning = "incomplete_tail" if remaining == 0 else "malformed_record"
                    warnings.add(warning)
                    if parse_counts is not None:
                        parse_counts[warning] = parse_counts.get(warning, 0) + 1
                    continue
                yield line_no, row
    except OSError:
        raise AnalysisError("log_unreadable") from None


def header(path):
    try:
        with path.open("rb") as stream:
            raw = stream.readline(MAX_LINE + 1)
        row = json.loads(raw)
        payload = row.get("payload", {})
        return payload if row.get("type") == "session_meta" and isinstance(payload, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def candidates(root, pattern):
    found = []
    for path in root.rglob(pattern):
        if path.is_file():
            found.append(path)
        if len(found) > MAX_CANDIDATES:
            raise AnalysisError("discovery_limit: supply --log; narrow --root for child discovery")
    return sorted(found)


def resolve_log(provider, session_id, root, explicit):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise AnalysisError("log_not_found")
        return path
    matches = candidates(root, f"*{session_id}*.jsonl" if provider == "codex" else f"{session_id}.jsonl")
    if provider == "codex":
        matches = [p for p in matches if header(p).get("id") == session_id]
    if len(matches) != 1:
        raise AnalysisError("session_not_unique: supply --log for the intended session")
    return matches[0]


def discover_children(provider, root, path, session_id):
    if provider == "claude":
        return [(p, session_id) for p in candidates(path.with_suffix("") / "subagents", "*.jsonl")]
    related, known = [], {session_id}
    links = []
    for p in candidates(root, "*.jsonl"):
        if p.resolve() == path.resolve():
            continue
        meta = header(p)
        source = meta.get("source")
        if not isinstance(source, dict):
            continue
        subagent = source.get("subagent", {})
        spawn = subagent.get("thread_spawn", {}) if isinstance(subagent, dict) else {}
        parent = spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
        if parent and isinstance(meta.get("id"), str):
            links.append((p, meta["id"], parent))
    while True:
        additions = [(p, sid) for p, sid, parent in links if parent in known and sid not in known]
        if not additions:
            break
        if len({sid for _, sid in additions}) != len(additions):
            raise AnalysisError("child_session_not_unique: narrow --root")
        related.extend(additions)
        known.update(sid for _, sid in additions)
        if len(related) >= MAX_FILES:
            raise AnalysisError("child_limit: narrow the requested scope")
    return related


class Activity:
    """Content sizes are proxies; hashes only detect identical local output."""

    def __init__(self, provider, session_id, source_label):
        self.scope = [provider, session_id, source_label]
        self.tools = Counter()
        self.output_bytes = 0
        self.repeated_bytes = 0
        self.results = 0
        self.errors = 0
        self.seen = set()
        self.identities = set()
        self.call_ids = set()
        self.matched_results = 0
        self.compactions = 0

        self.records = {}
        self.identity_missing = 0
        self.missing_sequence = 0
        self.result_outcomes = {}
        self.call_signatures = {}
        self.relation_conflicts = 0

    def call(self, provider, identifier, record_type, row, tool_name=None):
        if identifier:
            key = (provider, identifier)
            scoped_id = identifier
        else:
            self.identity_missing += 1
            self.missing_sequence += 1
            scoped_id = f"missing-{self.missing_sequence}"
            key = (provider, scoped_id)
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        message_id = message.get("id") or row.get("turn_id")
        parent_id = row.get("parentUuid") or row.get("parent_id")
        model = label(message.get("model"))
        self.records.setdefault(key, {
            "event": "tool_call", "call_id": digest(self.scope + ["call", identifier]) if identifier else None,
            "result_id": None,
            "message_id": digest(self.scope + ["message", message_id]) if message_id else None,
            "parent_id": digest(self.scope + ["parent", parent_id]) if parent_id else None,
            "status": None, "rejection": None, "interruption": None,
            "source_record_id": digest(self.scope + [record_type, scoped_id]),
            "record_type": record_type, "observed_at": observed_time(row.get("timestamp")),
            "result_record_type": None, "call_observed_at": observed_time(row.get("timestamp")),
            "result_observed_at": None, "result_source_record_id": None,
            "model": None if model == "unknown" else model,
            "actual_tier": tier(message.get("usage")), "relation_reason": None,
            "call_id_reason": None if identifier else "tool_identity_missing",
            "result_id_reason": "tool_result_missing", "status_reason": "tool_result_missing",
        })
        if identifier:
            signature = (record_type, label(tool_name))
            previous = self.call_signatures.setdefault(key, signature)
            if previous != signature:
                self.relation_conflicts += 1

    @staticmethod
    def classify(error, metadata):
        data = metadata if isinstance(metadata, dict) else {}
        status = data.get("status")
        if data.get("is_interrupt") is True or status in ("interrupted", "cancelled", "canceled"):
            return "interruption"
        if data.get("rejection") is True or status in ("rejected", "denied", "permission_denied"):
            return "rejection"
        if error is True or status in ("error", "failed", "failure"):
            return "failure"
        if error is False or status in ("ok", "success", "succeeded", "completed"):
            return "success"
        return "unknown"

    def duplicate_result(self, provider, identifier, error=None, metadata=None):
        if not identifier:
            return
        key = (provider, identifier)
        outcome = self.classify(error, metadata)
        previous = self.result_outcomes.get(key)
        if previous is not None and previous != outcome:
            self.relation_conflicts += 1
            self.result_outcomes[key] = "unknown"
            if key in self.records:
                self.records[key].update(status=None, rejection=None, interruption=None,
                                         status_reason="conflicting_tool_result")

    def result(self, content, error=None, metadata=None, matched=False,
               provider=None, identifier=None, record_type="tool_result", observed_at=None):
        raw = json.dumps(content, ensure_ascii=False).encode()
        fingerprint = hashlib.sha256(raw).digest()
        self.results += 1
        self.output_bytes += len(raw)
        if fingerprint in self.seen:
            self.repeated_bytes += len(raw)
        self.seen.add(fingerprint)
        self.errors += int(error is True)
        outcome = self.classify(error, metadata)
        if not matched:
            if identifier:
                key = (provider, identifier)
                result_time = observed_time(observed_at)
                self.result_outcomes[key] = outcome
                self.records.setdefault(key, {
                    "event": "tool_result", "call_id": digest(self.scope + ["call", identifier]),
                    "result_id": digest(self.scope + [record_type, identifier]),
                    "message_id": None, "parent_id": None,
                    "status": None if outcome == "unknown" else outcome,
                    "rejection": None if outcome == "unknown" else outcome == "rejection",
                    "interruption": None if outcome == "unknown" else outcome == "interruption",
                    "source_record_id": digest(self.scope + [record_type, identifier]),
                    "record_type": record_type, "observed_at": result_time,
                    "result_record_type": record_type, "call_observed_at": result_time,
                    "result_observed_at": result_time,
                    "result_source_record_id": digest(self.scope + [record_type, identifier]),
                    "model": None, "actual_tier": None,
                    "relation_reason": "tool_call_missing", "call_id_reason": None,
                    "result_id_reason": None,
                    "status_reason": ("structured_tool_outcome_unavailable"
                                      if outcome == "unknown" else None),
                })
            return
        self.matched_results += 1
        key = (provider, identifier)
        if matched and identifier:
            self.result_outcomes[key] = outcome
        if key in self.records:
            result_time = observed_time(observed_at)
            self.records[key].update(
                result_id=digest(self.scope + [record_type, identifier]),
                status=None if outcome == "unknown" else outcome,
                rejection=None if outcome == "unknown" else outcome == "rejection",
                interruption=None if outcome == "unknown" else outcome == "interruption",
                observed_at=result_time or self.records[key]["observed_at"],
                result_record_type=record_type,
                result_observed_at=result_time,
                result_source_record_id=digest(self.scope + [record_type, identifier]),
                result_id_reason=None,
                status_reason="structured_tool_outcome_unavailable" if outcome == "unknown" else None,
            )

    def observe(self, row, provider):
        """Observe counts and explicit flags only; never retain arguments or bodies."""
        payload = row.get("payload", {}) if provider == "codex" else row
        if not isinstance(payload, dict):
            return
        kind = row.get("type")
        if kind == "compacted" or row.get("subtype") == "compact_boundary":
            self.compactions += 1
        if provider == "codex":
            if kind in ("item.started", "item.completed"):
                item = row.get("item") if isinstance(row.get("item"), dict) else payload.get("item")
                item = item if isinstance(item, dict) else {}
                if item.get("type") != "command_execution":
                    return
                item_id = item.get("id") or row.get("item_id")
                if kind == "item.started":
                    key = ("command_execution_call", item_id)
                    if item_id and key not in self.identities:
                        self.identities.add(key)
                        self.call_ids.add((provider, item_id))
                        self.tools["command_execution"] += 1
                        self.call(provider, item_id, "command_execution", row, "command_execution")
                    elif not item_id:
                        self.tools["command_execution"] += 1
                        self.call(provider, None, "command_execution", row, "command_execution")
                else:
                    key = ("command_execution_result", item_id)
                    if item_id and key in self.identities:
                        exit_code = item.get("exit_code")
                        status = "success" if exit_code == 0 else "failure" if type(exit_code) is int else None
                        self.duplicate_result(provider, item_id, metadata={"status": status})
                        return
                    if item_id:
                        self.identities.add(key)
                    call_key = (provider, item_id)
                    if item_id and call_key not in self.call_ids:
                        self.call_ids.add(call_key)
                        self.tools["command_execution"] += 1
                        self.call(provider, item_id, "command_execution", row, "command_execution")
                    elif not item_id:
                        if not any(record["call_id"] is None for record in self.records.values()):
                            self.tools["command_execution"] += 1
                            self.call(provider, None, "command_execution", row, "command_execution")
                    exit_code = item.get("exit_code")
                    status = "success" if exit_code == 0 else "failure" if type(exit_code) is int else None
                    self.result({"item_id": item_id}, metadata={"status": status},
                                matched=bool(item_id) and call_key in self.call_ids,
                                provider=provider, identifier=item_id,
                                record_type="command_execution_result", observed_at=row.get("timestamp"))
                return
            if kind != "response_item":
                return
            typ = payload.get("type")
            identity_type = ("tool_call" if typ in ("function_call", "custom_tool_call")
                             else "tool_result" if typ in ("function_call_output", "custom_tool_call_output")
                             else typ)
            key = (identity_type, payload.get("call_id"))
            if key[1] and key in self.identities:
                if identity_type == "tool_call":
                    self.call(provider, key[1], typ, row, payload.get("name"))
                elif identity_type == "tool_result":
                    self.duplicate_result(provider, key[1], metadata=payload)
                return
            if key[1]:
                self.identities.add(key)
            if typ in ("function_call", "custom_tool_call"):
                if key[1]:
                    self.call_ids.add((provider, key[1]))
                self.tools[label(payload.get("name"))] += 1
                self.call(provider, key[1], typ, row, payload.get("name"))
            elif typ in ("function_call_output", "custom_tool_call_output"):
                self.result(payload.get("output", ""), metadata=payload,
                            matched=bool(key[1]) and (provider, key[1]) in self.call_ids,
                            provider=provider, identifier=key[1], record_type=typ,
                            observed_at=row.get("timestamp"))
        else:
            message = row.get("message", {})
            blocks = message.get("content", []) if isinstance(message, dict) else []
            if not isinstance(blocks, list):
                return
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                typ = block.get("type")
                key = (typ, block.get("id") or block.get("tool_use_id"))
                if key[1] and key in self.identities:
                    if typ == "tool_use":
                        self.call(provider, key[1], typ, row, block.get("name"))
                    elif typ == "tool_result":
                        self.duplicate_result(provider, key[1], block.get("is_error"), block)
                    continue
                if key[1]:
                    self.identities.add(key)
                if typ == "tool_use":
                    if key[1]:
                        self.call_ids.add((provider, key[1]))
                    self.tools[label(block.get("name"))] += 1
                    self.call(provider, key[1], typ, row, block.get("name"))
                elif typ == "tool_result":
                    self.result(block.get("content", ""), block.get("is_error"), block,
                                matched=bool(key[1]) and (provider, key[1]) in self.call_ids,
                                provider=provider, identifier=key[1], record_type=typ,
                                observed_at=row.get("timestamp"))

    def report(self):
        expected = sum(self.tools.values())
        observed = min(self.matched_results, expected)
        canonical = Counter(record["status"] or "unknown" for record in self.records.values()
                            if record["event"] == "tool_call")
        outcomes = {key: canonical.get(key, 0)
                    for key in ("success", "failure", "rejection", "interruption", "unknown")}
        outcomes["unknown"] += max(expected - sum(outcomes.values()), 0)
        known = sum(outcomes[key] for key in ("success", "failure", "rejection", "interruption"))
        return {"tool_calls": dict(self.tools.most_common(12)), "tool_results": self.results,
                "tool_calls_expected": expected, "tool_results_matched": observed,
                "unmatched_results": max(self.results - self.matched_results, 0),
                "tool_identity_missing": self.identity_missing,
                "relation_conflicts": self.relation_conflicts,
                "tool_outcomes": outcomes, "tool_outcomes_known": known,
                "tool_result_bytes_proxy": self.output_bytes,
                "identical_result_bytes_proxy": self.repeated_bytes,
                "explicit_tool_errors": self.errors, "compactions_observed": self.compactions,
                "records": sorted(self.records.values(), key=lambda item: item["call_id"] or "")}


def collect(path, provider, session_id, source_label):
    warnings, records, legacy = set(), {}, []
    parse_counts = {"malformed_record": 0, "incomplete_tail": 0}
    stream_totals = {}
    activity = Activity(provider, session_id, source_label)
    identity_seen = False
    model, version = "unknown", "unknown"
    duplicates = 0
    last_thread_total = None
    modern_seen = False
    expected_usage = set()
    unidentified_usage = 0
    recorded_cost = None
    reported_estimated_cost = None
    for line_no, row in read_rows(path, warnings, parse_counts):
        kind = row.get("type")
        payload = row.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        if provider == "codex":
            if kind == "thread.started":
                thread_id = row.get("thread_id") or payload.get("thread_id")
                if thread_id != session_id:
                    raise AnalysisError("session_identity_mismatch")
                identity_seen = True
                activity.observe(row, provider)
                continue
            if kind == "session_meta":
                if payload.get("id") != session_id:
                    raise AnalysisError("session_identity_mismatch")
                identity_seen = True
                version = label(payload.get("cli_version"))
                if payload.get("forked_from_id") or payload.get("forked_from"):
                    warnings.add("fork_history_requires_attribution")
            if kind == "turn_context":
                model = label(payload.get("model"))
            if kind == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info")
                if isinstance(info, dict) and isinstance(info.get("total_token_usage"), dict):
                    legacy.append((line_no, observed_time(row.get("timestamp")), model,
                                   info["total_token_usage"]))
            if kind == "turn.completed":
                activity.observe(row, provider)
                usage = row.get("usage") if isinstance(row.get("usage"), dict) else payload.get("usage")
                run_id = row.get("run_id") or payload.get("run_id")
                completion_id = row.get("turn_id") or row.get("id") or payload.get("turn_id") or payload.get("id")
                key = [run_id, completion_id] if run_id and completion_id else None
                modern_seen = True
                last_thread_total = None
            else:
                if kind != "token_usage_record":
                    activity.observe(row, provider)
                    continue
                if payload.get("thread_id") != session_id:
                    warnings.add("foreign_thread_usage_excluded")
                    continue
                modern_seen = True
                key = payload.get("response_id")
                usage = payload.get("usage")
                last_thread_total = payload.get("thread_token_usage")
        else:
            sid = row.get("sessionId") or row.get("session_id")
            if sid is not None:
                if sid != session_id:
                    warnings.add("foreign_session_record_excluded")
                    continue
                identity_seen = True
            version = label(row.get("version")) if row.get("version") else version
            if kind == "system" and row.get("subtype") == "init":
                version = label(row.get("claude_code_version") or row.get("version"))
                model = label(row.get("model"))
            if kind == "result":
                value = row.get("total_cost_usd")
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                    reported_estimated_cost = {"usd": value, "basis": "claude_cli_estimate"}
                model_usage = row.get("modelUsage")
                if isinstance(model_usage, dict):
                    for stream_model, counters in model_usage.items():
                        if not isinstance(counters, dict):
                            continue
                        stream_totals[label(stream_model)] = (line_no, observed_time(row.get("timestamp")), {
                            "input_tokens": counters.get("inputTokens"),
                            "cache_read_input_tokens": counters.get("cacheReadInputTokens"),
                            "cache_creation_input_tokens": counters.get("cacheCreationInputTokens"),
                            "output_tokens": counters.get("outputTokens"),
                        })
                continue
            activity.observe(row, provider)
            if kind == "cost-state":
                value = row.get("totalCostUSD")
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                    recorded_cost = {"usd": value,
                                     "has_unknown_model_cost": bool(row.get("hasUnknownModelCost"))}
            message = row.get("message", {})
            if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                continue
            if sid is None:
                warnings.add("usage_without_session_id_excluded")
                unidentified_usage += 1
                continue
            usage = message["usage"]
            key = [message.get("id"), row.get("requestId")]
            if not key[0]:
                key = None
            elif not key[1]:
                warnings.add("request_id_missing_message_id_fallback")
            model = label(message.get("model"))
        if not key or not isinstance(usage, dict):
            warnings.add("unidentifiable_usage_excluded")
            unidentified_usage += int(isinstance(usage, dict))
            continue
        expected_usage.add(digest([provider, session_id, source_label, key]))
        if (provider == "claude" and number(usage.get("cache_creation_input_tokens"))
                and not isinstance(usage.get("cache_creation"), dict)):
            warnings.add("cache_write_tier_unknown_assumed_5m")
        split = usage.get("cache_creation")
        if provider == "claude" and isinstance(split, dict):
            write = number(usage.get("cache_creation_input_tokens"))
            write_5m = number(split.get("ephemeral_5m_input_tokens"))
            write_1h = number(split.get("ephemeral_1h_input_tokens"))
            if write is None or write_5m is None or write_1h is None or write_5m + write_1h != write:
                warnings.add("cache_write_split_mismatch")
        if provider == "claude" and usage.get("inference_geo") not in (None, "", "global", "not_available"):
            warnings.add("regional_inference_pricing_unknown")
        tokens = normalize(usage, provider)
        if tokens["input_tokens"] is None or tokens["output_tokens"] is None:
            warnings.add("required_usage_fields_missing")
        if any(value is None for value in tokens.values()):
            warnings.add("usage_breakdown_incomplete")
        if provider == "codex" and "total_tokens" in usage and number(usage.get("total_tokens")) != tokens["total_tokens"]:
            warnings.add("reported_total_mismatch")
        if (tokens["reasoning_output_tokens"] is not None and tokens["output_tokens"] is not None
                and tokens["reasoning_output_tokens"] > tokens["output_tokens"]):
            warnings.add("reasoning_exceeds_output")
        if provider == "codex" and tokens["cached_input_tokens"] is not None and tokens["uncached_input_tokens"] is None:
            warnings.add("invalid_cache_counters")
        fingerprint = digest([provider, session_id, source_label, key])
        if fingerprint in records:
            duplicates += 1
            if records[fingerprint]["tokens"] != tokens:
                warnings.add("usage_revision_latest_selected")
        source_id = digest([provider, session_id, source_label, kind, key])
        records[fingerprint] = {
            "key": fingerprint, "line": line_no, "timestamp": observed_time(row.get("timestamp")),
            "runtime": provider, "session_id": session_id, "event": "usage",
            "call_id": digest([provider, session_id, source_label, "call", key]),
            "message_id": (digest([provider, session_id, source_label, "message", key[0]])
                           if isinstance(key, list) and key[0] else None),
            "parent_id": (digest([provider, session_id, source_label, "parent",
                                  row.get("parentUuid") or row.get("parent_id")])
                          if row.get("parentUuid") is not None or row.get("parent_id") is not None else None),
            "model": model, "requested_tier": None, "actual_tier": tier(usage),
            "usage_scope": "call_delta", "includes_children": "unknown",
            "source_record_id": source_id, "tokens": tokens,
            "billing_tokens": billing_tokens(usage, provider),
            "cache_write_split_known": cache_write_split_known(usage, provider),
            "source": source_label}
    if provider == "claude" and stream_totals:
        if records:
            attributed = {}
            for row in records.values():
                attributed.setdefault(row["model"], []).append(row)
            mismatch = set(attributed) != set(stream_totals)
            for stream_model, (_, _, usage) in stream_totals.items():
                if stream_model not in attributed:
                    continue
                summary = normalize(usage, provider)
                observed = summed(attributed[stream_model])
                if any(summary[key] != observed[key] for key in (
                        "input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")):
                    mismatch = True
            if mismatch:
                warnings.add("cumulative_summary_differs_from_attributed_records")
                unidentified_usage += 1
            else:
                warnings.add("session_cumulative_summary_not_added")
        else:
            warnings.update(("claude_stream_result_session_cumulative", "includes_children_unknown"))
            for stream_model, (line_no, timestamp, usage) in stream_totals.items():
                tokens = normalize(usage, provider)
                key = digest([provider, session_id, source_label, "stream_result", stream_model])
                expected_usage.add(key)
                if number(usage.get("cache_creation_input_tokens")):
                    warnings.add("cache_write_tier_unknown_assumed_5m")
                if tokens["input_tokens"] is None or tokens["output_tokens"] is None:
                    warnings.add("required_usage_fields_missing")
                if any(value is None for value in tokens.values()):
                    warnings.add("usage_breakdown_incomplete")
                records[key] = {
                    "key": key, "line": line_no, "timestamp": timestamp,
                    "runtime": provider, "session_id": session_id, "event": "usage",
                    "call_id": None, "message_id": None, "model": stream_model,
                    "requested_tier": None, "actual_tier": None,
                    "usage_scope": "session_cumulative", "includes_children": "unknown",
                    "source_record_id": digest([provider, session_id, source_label, "result", stream_model]),
                    "tokens": tokens, "billing_tokens": billing_tokens(usage, provider),
                    "cache_write_split_known": cache_write_split_known(usage, provider),
                    "source": source_label,
                }
    if not identity_seen:
        raise AnalysisError("session_identity_unverified")
    if provider == "codex" and not modern_seen:
        warnings.add("legacy_cumulative_adapter")
        previous = {key: 0 for key in FIELDS}
        for line_no, timestamp, model, usage in legacy:
            current = normalize(usage, provider)
            if current == previous:
                duplicates += 1
                continue
            if any(current[k] is not None and previous[k] is not None and current[k] < previous[k]
                   for k in FIELDS):
                warnings.add("counter_reset_totals_are_partial")
                unidentified_usage += 1
                previous = current
                continue
            tokens = {k: subtract(current[k], previous[k]) for k in FIELDS}
            key = digest([provider, session_id, source_label, line_no, current])
            expected_usage.add(key)
            records[key] = {"key": key, "line": line_no, "timestamp": timestamp,
                            "runtime": provider, "session_id": session_id, "event": "usage",
                            "call_id": None, "message_id": None, "model": model,
                            "requested_tier": None, "actual_tier": None,
                            "usage_scope": "session_cumulative", "includes_children": "unknown",
                            "source_record_id": key, "tokens": tokens,
                            "billing_tokens": {
                                "input": tokens["uncached_input_tokens"],
                                "cache_read": tokens["cached_input_tokens"],
                                "cache_write": tokens["cache_write_input_tokens"],
                                "output": tokens["output_tokens"],
                            }, "cache_write_split_known": True, "source": source_label}
            previous = current
    rows = list(records.values())
    if not rows:
        warnings.add("usage_unavailable")
    activity_report = activity.report()
    for record in activity_report["records"]:
        record["session_id"] = session_id
    if activity_report["unmatched_results"]:
        warnings.add("unmatched_tool_result")
    if activity_report["tool_identity_missing"]:
        warnings.add("tool_identity_missing")
    if activity_report["relation_conflicts"]:
        warnings.add("conflicting_tool_record")
    if activity_report["tool_outcomes"]["unknown"]:
        warnings.add("tool_outcome_unknown")
    if isinstance(last_thread_total, dict):
        reported = normalize(last_thread_total, provider)
        observed = summed(rows)
        if any(reported[k] != observed[k] for k in ("input_tokens", "output_tokens")):
            warnings.add("thread_total_differs_from_attributed_records")
            unidentified_usage += 1
    usage_observed = sum(row["tokens"]["input_tokens"] is not None
                         and row["tokens"]["output_tokens"] is not None for row in rows)
    return {"source": source_label, "transcript_name": label(path.name),
            "version": version, "requests_observed": len(rows),
            "usage_expected": len(expected_usage) + unidentified_usage,
            "usage_complete": usage_observed,
            "recorded_cost": recorded_cost,
            "reported_estimated_cost": reported_estimated_cost,
            "duplicates_removed": duplicates, "tokens": summed(rows),
            "bad_lines": sum(parse_counts.values()),
            "malformed_records": parse_counts["malformed_record"],
            "incomplete_tail_records": parse_counts["incomplete_tail"],
            "warnings": sorted(warnings), "activity": activity_report}, rows


def findings(sources, rows):
    result = []
    for source in sources:
        evidence = source["activity"]
        sid = source["source"]
        if evidence["identical_result_bytes_proxy"]:
            result.append({"source": sid, "fact": "identical_tool_output_observed",
                           "evidence_bytes_proxy": evidence["identical_result_bytes_proxy"],
                           "hypothesis": "redundant_reads_or_repeated_checks", "confidence": "medium",
                           "action": "reuse_unchanged_evidence; retain_required_checks"})
        if evidence["tool_result_bytes_proxy"] >= 20000:
            result.append({"source": sid, "fact": "large_tool_output_observed",
                           "evidence_bytes_proxy": evidence["tool_result_bytes_proxy"],
                           "hypothesis": "tool_output_increases_later_input", "confidence": "medium",
                           "action": "filter_locally_and_return_relevant_excerpts"})
        if evidence["explicit_tool_errors"]:
            result.append({"source": sid, "fact": "tool_errors_observed",
                           "count": evidence["explicit_tool_errors"], "hypothesis": "retry_overhead",
                           "confidence": "low", "action": "inspect_failed_step_before_retry"})
    return result[:12]


def coverage_ratio(observed, expected):
    return {"expected": expected, "observed": observed,
            "rate": observed / expected if expected else None}


def build_report(provider, session_id, root, path, include_children=False):
    files = [(path, session_id, "main")]
    if include_children:
        children = discover_children(provider, root, path, session_id)
        if len(children) >= MAX_FILES:
            raise AnalysisError("child_limit")
        files.extend((p, sid, "child-" + digest(str(p.resolve()))[:12]) for p, sid in children)
    if sum(p.stat().st_size for p, _, _ in files) > MAX_BYTES:
        raise AnalysisError("scope_too_large: use main scope or selected transcripts")
    sources, rows = [], []
    for p, sid, source_label in files:
        source, entries = collect(p, provider, sid, source_label)
        sources.append(source)
        rows.extend(entries)
    groups = {}
    for entry in rows:
        groups.setdefault(entry["model"], []).append(entry)
    latest = next((r for r in reversed(rows) if r["source"] == "main"), None)
    usage_expected = sum(source["usage_expected"] for source in sources)
    usage_observed = sum(source["usage_complete"] for source in sources)
    tool_expected = sum(source["activity"]["tool_calls_expected"] for source in sources)
    tool_observed = sum(source["activity"]["tool_results_matched"] for source in sources)
    outcome_observed = sum(source["activity"]["tool_outcomes_known"] for source in sources)
    coverage = {"usage": coverage_ratio(usage_observed, usage_expected),
                "tool_calls": coverage_ratio(tool_observed, tool_expected),
                "outcome": coverage_ratio(outcome_observed, tool_expected)}
    report = {"schema_version": 1, "provider": provider, "session_id": session_id,
              "target": digest(str(path.resolve())),
              "snapshot_at": datetime.now(timezone.utc).isoformat(),
              "scope": "local_family" if include_children else "main_only",
              "coverage": coverage, "tokens": summed(rows),
              "measurement_status": "qualified" if any(s["warnings"] for s in sources) else "recorded",
              "sources": sources, "by_model": {m: summed(v) for m, v in groups.items()},
              "latest_main_request": latest,
              "largest_requests": sorted(rows, key=lambda r: r["tokens"]["total_tokens"] or -1,
                                         reverse=True)[:5],
              "findings": findings(sources, rows),
              "limits": ["not_billing_or_plan_limit", "bytes_are_not_tokens",
                         "no_exact_file_or_tool_token_attribution", "pending_requests_not_included",
                         "unlinked_or_remote_agents_not_included"]}
    return report, rows


def compare(baseline, report, rows):
    for key in ("schema_version", "provider", "session_id", "scope", "target"):
        if baseline.get(key) != report.get(key):
            raise AnalysisError("baseline_scope_mismatch")
    if baseline.get("measurement_status") != "recorded" or report.get("measurement_status") != "recorded":
        raise AnalysisError("baseline_or_current_measurement_qualified: inspect warnings before comparison")
    old = baseline.get("ledger")
    if not isinstance(old, dict):
        raise AnalysisError("baseline_ledger_missing")
    now = {row["key"]: row["tokens"] for row in rows}
    if any(key not in now or now[key] != tokens for key, tokens in old.items()):
        raise AnalysisError("baseline_history_changed: no reliable before_after_delta")
    added = [r for r in rows if r["key"] not in old]
    return {"requests_added": len(added),
            "tokens": summed(added) if added else {key: 0 for key in FIELDS},
            "interpretation": "observed_since_baseline_including_diagnostic_overhead; not_proven_savings"}


def save_snapshot(path, report, rows):
    data = {key: report[key] for key in ("schema_version", "provider", "session_id", "scope", "snapshot_at",
                                       "measurement_status", "target")}
    data["ledger"] = {r["key"]: r["tokens"] for r in rows}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(Path(path).expanduser(), flags, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.write("\n")
    except OSError:
        raise AnalysisError("snapshot_not_written: choose a new file in an existing private directory") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("codex", "claude"))
    parser.add_argument("--session-id")
    parser.add_argument("--log", help="explicit transcript; session identity is still verified")
    parser.add_argument("--root", help="sessions/ or projects/ directory")
    parser.add_argument("--include-children", action="store_true")
    parser.add_argument("--baseline", help="compare against a previous --save-snapshot")
    parser.add_argument("--save-snapshot", help="create a new private counters-only snapshot; no overwrite")
    args = parser.parse_args()
    try:
        env_key = "CODEX_THREAD_ID" if args.provider == "codex" else "CLAUDE_SESSION_ID"
        session_id = args.session_id or os.environ.get(env_key)
        if not session_id or not ID.fullmatch(session_id):
            raise AnalysisError("session_id_required: use the current runtime ID, never the latest log")
        home_key = "CODEX_HOME" if args.provider == "codex" else "CLAUDE_CONFIG_DIR"
        home = Path(os.environ.get(home_key, str(Path.home() / ("." + args.provider)))).expanduser()
        root = Path(args.root).expanduser() if args.root else home / ("sessions" if args.provider == "codex" else "projects")
        path = resolve_log(args.provider, session_id, root, args.log)
        report, rows = build_report(args.provider, session_id, root, path, args.include_children)
        if args.baseline:
            baseline_path = Path(args.baseline).expanduser()
            if baseline_path.stat().st_size > MAX_BYTES:
                raise AnalysisError("baseline_too_large")
            baseline = json.loads(baseline_path.read_text())
            if not isinstance(baseline, dict):
                raise AnalysisError("baseline_invalid")
            report["since_baseline"] = compare(baseline, report, rows)
        if args.save_snapshot:
            save_snapshot(args.save_snapshot, report, rows)
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (AnalysisError, OSError, ValueError, TypeError) as exc:
        message = str(exc) if isinstance(exc, AnalysisError) else "invalid_or_unreadable_input"
        print(json.dumps({"error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
