#!/usr/bin/env python3
"""セッションの transcript から、ダッシュボードに載せる利用量と費用を JSON で出す。

数え方の規則は context/session-dashboard.md の「費用・利用量の取得」に従う。
会話の本文や tool の引数は読み取るだけで、出力しない。
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

PRICING_FILE = Path(__file__).resolve().parents[1] / "config" / "model-pricing.json"
FX_URL = "https://open.er-api.com/v6/latest/USD"
FX_TIMEOUT_SECONDS = 10
TOKEN_KEYS = ("input", "cache_read", "cache_write_5m", "cache_write_1h", "output")
STANDARD_TIERS = {None, "", "standard", "not_available", "global"}
CODEX_RECORD_TYPES = {"session_meta", "turn_context", "response_item", "event_msg", "token_usage_record"}
SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")


def fx_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "agent-harness" / "fx.json"


def read_fx() -> Optional[dict]:
    """保存済みの為替を返す。ない、または読めないときは None。"""
    try:
        saved = json.loads(fx_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) and is_amount(saved.get("rate")) and saved["rate"] > 0 else None


def read_records(path: Path) -> tuple[list[dict], int]:
    records, bad = [], 0
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                bad += 1
    return records, bad


def as_count(value) -> Optional[int]:
    """usage の値を非負整数で返す。欠落は 0、負数や非有限数は None。"""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value)


def is_amount(value) -> bool:
    """金額やレートとして使える、有限で負でない数か。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def content_blocks(record: dict, kind: str) -> Iterator[dict]:
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), list) else []
    for block in content:
        if isinstance(block, dict) and block.get("type") == kind:
            yield block


def price_for(model: Optional[str], pricing: dict) -> Optional[dict]:
    models = pricing.get("models", {})
    if not model:
        return None
    return models.get(model) or models.get(re.sub(r"-\d{8}$", "", model))


def price_models(models: dict, pricing: dict) -> tuple[Optional[float], bool]:
    """モデルごとに推定額を付ける。合計（単価を1つも引けなければ None）と、全モデルに単価があったかを返す。"""
    priced = []
    for model, entry in models.items():
        price = price_for(model, pricing)
        if price is None:
            entry["usd"], entry["reason"] = None, "単価が model-pricing.json に未登録"
            continue
        entry["usd"] = sum(entry["tokens"][key] * price[key] for key in TOKEN_KEYS) / 1_000_000
        entry["pricing"] = {"source": price.get("source"), "checked": price.get("checked")}
        priced.append(entry["usd"])
    return (sum(priced) if priced else None), len(priced) == len(models)


def summarize_claude(records: list[dict], pricing: dict) -> dict:
    usages, calls, recorded = {}, {}, None
    for record in records:
        kind = record.get("type")
        if kind == "cost-state" and is_amount(record.get("totalCostUSD")):
            recorded = record  # 累計なので、最後の有効な1件を使う。
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        if kind == "assistant" and isinstance(message.get("usage"), dict):
            # streaming で同じ message ID が繰り返されるので、最後の usage を残す。
            usages[message.get("id") or record.get("uuid")] = (message["usage"], message.get("model"))
            for block in content_blocks(record, "tool_use"):
                calls.setdefault(block.get("id"), None)
        if kind == "user":
            for block in content_blocks(record, "tool_result"):
                if block.get("tool_use_id") in calls:
                    calls[block["tool_use_id"]] = bool(block.get("is_error"))

    models, invalid, split_unknown, tiers = {}, 0, 0, set()
    for usage, model in usages.values():
        split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else None
        row = {
            "input": as_count(usage.get("input_tokens")),
            "cache_read": as_count(usage.get("cache_read_input_tokens")),
            "cache_write_5m": as_count(
                split.get("ephemeral_5m_input_tokens") if split else usage.get("cache_creation_input_tokens")
            ),
            "cache_write_1h": as_count(split.get("ephemeral_1h_input_tokens")) if split else 0,
            "output": as_count(usage.get("output_tokens")),
        }
        if None in row.values():
            invalid += 1
            continue
        if not any(row.values()):
            continue  # API エラーなどの合成メッセージ。費用に影響しない。
        if split is None and row["cache_write_5m"]:
            split_unknown += 1
        tiers.update(
            f"{name}={usage[name]}"
            for name in ("speed", "service_tier", "inference_geo")
            if usage.get(name) not in STANDARD_TIERS
        )
        entry = models.setdefault(model or "unknown", {"messages": 0, "tokens": dict.fromkeys(TOKEN_KEYS, 0)})
        entry["messages"] += 1
        for key in TOKEN_KEYS:
            entry["tokens"][key] += row[key]

    total = {key: sum(entry["tokens"][key] for entry in models.values()) for key in TOKEN_KEYS}
    usd, priced_all = price_models(models, pricing)

    input_total = total["input"] + total["cache_read"] + total["cache_write_5m"] + total["cache_write_1h"]
    resolved = [value for value in calls.values() if value is not None]
    notes = []
    if invalid:
        notes.append(f"usage の値が不正な message {invalid} 件を除いた")
    if split_unknown:
        notes.append(f"キャッシュ書き込みの区分が不明な message {split_unknown} 件を5分書き込みとして数えた")
    if tiers:
        notes.append("標準以外の区分を含むので、標準料金で計算した参考額である: " + ", ".join(sorted(tiers)))
    if not priced_all:
        notes.append("単価が未登録のモデルを含むので、推定額は登録済みのモデルの小計である")
    return {
        "messages": len(usages),
        "tokens": dict(total, input_total=input_total),
        "cache_read_rate": ratio(total["cache_read"], input_total),
        "tool_calls": dict(
            ratio(sum(resolved), len(resolved), "errors", "resolved"),
            unresolved=len(calls) - len(resolved),
        ),
        "models": models,
        "estimated_usd": usd,
        "estimate_complete": priced_all and not invalid,
        "recorded_cost": None
        if recorded is None
        else {
            "usd": recorded.get("totalCostUSD"),
            "has_unknown_model_cost": bool(recorded.get("hasUnknownModelCost")),
        },
        "notes": notes,
    }


def summarize_codex(records: list[dict]) -> dict:
    usage, source, model = None, None, None
    for record in records:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if record.get("type") == "turn_context" and payload.get("model"):
            model = payload["model"]
        if record.get("type") == "token_usage_record" and isinstance(payload.get("thread_token_usage"), dict):
            usage, source = payload["thread_token_usage"], "token_usage_record"
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        is_count = record.get("type") == "event_msg" and payload.get("type") == "token_count"
        if is_count and source != "token_usage_record" and isinstance(info.get("total_token_usage"), dict):
            usage, source = info["total_token_usage"], "token_count"
    notes = ["Codex の tool の結果には失敗の flag がないので、ツールエラー率は未取得", "Codex の費用計算は未対応"]
    if usage is None:
        return {"tokens": None, "cache_read_rate": None, "models": {}, "notes": notes + ["token の累計が見つからない"]}
    tokens = {key: as_count(value) for key, value in usage.items()}
    if None in tokens.values():
        return {"tokens": None, "cache_read_rate": None, "models": {}, "notes": notes + ["token の累計に不正な値がある"]}
    return {
        "tokens": tokens,
        "token_source": source,
        # cached_input_tokens は input_tokens の内数。
        "cache_read_rate": ratio(tokens.get("cached_input_tokens", 0), tokens.get("input_tokens", 0)),
        "tool_calls": None,
        "models": {model or "unknown": {"usd": None, "reason": "Codex の費用計算は未対応"}},
        "estimated_usd": None,
        "estimate_complete": False,
        "recorded_cost": None,
        "notes": notes,
    }


def ratio(numerator: int, denominator: int, top: str = "numerator", bottom: str = "denominator") -> dict:
    return {top: numerator, bottom: denominator, "rate": numerator / denominator if denominator else None}


def find_transcript(session: str) -> Path:
    if not SESSION_ID.fullmatch(session):
        raise SystemExit("session-metrics: session ID に使えない文字がある")
    home = Path.home()
    found = list((home / ".claude" / "projects").glob(f"*/{session}.jsonl"))
    found += list((home / ".codex" / "sessions").glob(f"*/*/*/rollout-*{session}.jsonl"))
    if len(found) != 1:
        raise SystemExit(f"session-metrics: session {session} の transcript が {len(found)} 件見つかった（1件のときだけ進める）")
    return found[0]


def command_metrics(args) -> int:
    path = Path(args.transcript) if args.transcript else find_transcript(args.session)
    if not path.is_file():
        raise SystemExit(f"session-metrics: transcript がない: {path}")
    pricing = json.loads(PRICING_FILE.read_text(encoding="utf-8"))
    records, bad = read_records(path)
    is_codex = any(record.get("type") in CODEX_RECORD_TYPES for record in records[:50])
    result = {
        "runtime": "codex" if is_codex else "claude",
        "transcript": str(path),
        "collected_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "bad_lines": bad,
    }
    result.update(summarize_codex(records) if is_codex else summarize_claude(records, pricing))

    children = [] if is_codex else sorted((path.parent / path.stem / "subagents").glob("*.jsonl"))
    if children:
        parts = []
        for child in children:
            child_records, child_bad = read_records(child)
            part = summarize_claude(child_records, pricing)
            parts.append(part)
            result["bad_lines"] += child_bad
        child_usd = [part["estimated_usd"] for part in parts if part["estimated_usd"] is not None]
        result["subagents"] = {
            "files": len(children),
            "tokens": {key: sum(part["tokens"][key] for part in parts) for key in TOKEN_KEYS + ("input_total",)},
            "tool_calls": ratio(
                sum(part["tool_calls"]["errors"] for part in parts),
                sum(part["tool_calls"]["resolved"] for part in parts),
                "errors",
                "resolved",
            ),
            "estimated_usd": sum(child_usd) if child_usd else None,
            "estimate_complete": all(part["estimate_complete"] for part in parts),
        }
        for note in sorted({note for part in parts for note in part["notes"]}):
            result["notes"].append(f"子 agent: {note}")
    if not is_codex:
        result["estimate_scope"] = (
            "transcript に残る assistant message の usage だけを数える。"
            "compact の要約や補助モデルの呼び出し、web 検索などの追加料金は含まないので、実際より小さくなり得る"
        )
    if result["bad_lines"]:
        result["notes"].append(f"読めない行 {result['bad_lines']} 件を除いた部分集計である")

    usd_values = [result.get("estimated_usd"), (result.get("subagents") or {}).get("estimated_usd")]
    result["estimated_usd_with_subagents"] = sum(v for v in usd_values if v) if usd_values[0] is not None else None
    fx = read_fx()
    result["fx"] = fx
    total_usd = result["estimated_usd_with_subagents"]
    result["estimated_jpy_with_subagents"] = total_usd * fx["rate"] if fx and total_usd is not None else None
    if fx is None:
        result["notes"].append("為替の保存値がない、または読めないので円換算待ち（`session-metrics.py fx` で取得する）")
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
    saved = {
        "base": "USD",
        "quote": "JPY",
        "rate": rate,
        "as_of": payload.get("time_last_update_utc"),
        "source": FX_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    cache = fx_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"session-metrics: 為替の取得が完了 {cache}", file=sys.stderr)
    json.dump(saved, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    metrics = commands.add_parser("metrics", help="利用量と費用を JSON で出す")
    target = metrics.add_mutually_exclusive_group(required=True)
    target.add_argument("--session", help="session ID（Claude と Codex の保存先から探す）")
    target.add_argument("--transcript", help="transcript の JSONL のパス")
    metrics.set_defaults(run=command_metrics)
    fx = commands.add_parser("fx", help="USD/JPY を1回取得して保存する")
    fx.set_defaults(run=command_fx)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
