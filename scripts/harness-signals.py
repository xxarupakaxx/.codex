#!/usr/bin/env python3
"""Claude Code の transcript から、本人の介入、ツールの失敗、フックの失敗を拾って Markdown で出す。

再発防止の材料を集める道具で、判定はしない。本当の訂正かどうか、原因が何かは、
出力を読むエージェントと本人が判断する。抜粋はこの端末の外へ出さない。
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

INTERRUPT = "[Request interrupted by user"
# ツール実行の拒否でも中断のレコードが残る。拒否として数えるので、中断には入れない。
INTERRUPT_FOR_TOOL = "[Request interrupted by user for tool use]"
REJECTIONS = ("The user doesn't want to proceed with this tool use", "The user doesn't want to take this action")
REPORT_DIR = Path(".claude") / ".local" / "harness-signals"  # ホームからの相対。git の対象外。
EXCERPT_CHARS = 160
LABEL_MAX_CHARS = 400  # これより長い発話は貼り付けた資料が多いので、語彙を当てない。
FAILURE_MIN_COUNT, FAILURE_MIN_SESSIONS = 3, 2

# 絞り込みではなくラベルに使う。英語は単語の境界で照合する。
# 「違う」「じゃなくて」「なんで」は内容の相談でも普通に出るので入れない（2026-10-08 の実測で適合率 12%）。
LABELS = {
    "出来への不満": r"好きじゃない|見づら|見にく|見えづら|読みづら|読みにく|[わ分]かりづら|[わ分]かりにく|微妙|いまいち|イマイチ|冗長|長すぎ|多すぎ",
    "差し戻し": r"元に戻|戻して|のままで|やり直|直して|\b(?:revert|undo)\b",
    "不要と制止": r"不要|[い要]らない|しなくていい|しないで|やめて|勝手に|だめ|ダメ|壊さず|\b(?:stop|don't)\b",
    "指示の再掲": r"って言った|と言った|言ったよね|言ったはず|伝えた(?:よね|はず)",
    "抜け": r"ないのかな|抜けて|漏れて|忘れて|入ってない|反映されてない|なってない",
}
LABEL_PATTERNS = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in LABELS.items()}
# 最善の努力であり、すべての鍵を伏せる保証ではない。
SECRET = re.compile(
    r"(?:sk-|sk_live_|sk_test_|ghp_|gho_|ghs_|github_pat_|xox[abprs]-|AKIA|AIza)[A-Za-z0-9_-]{8,}"
    r"|op://\S+|\bBearer\s+\S+|\b(?:password|passwd|token|secret|api[_-]?key)\s*[=:]\s*\S+"
    r"|\b[0-9a-fA-F]{32,}\b|\b[A-Za-z0-9+/_-]{40,}={0,2}",
    re.IGNORECASE,
)
VOLATILE = re.compile(r"(?:~|\.{0,2})/[\w@.+~/-]+|\b[0-9a-f]{7,}\b|\d+")
# transcript の attachment に残るフックの記録。停止は、フックが操作を止めたもので、意図した停止も含む。
HOOK_KINDS = {"hook_non_blocking_error": "失敗", "hook_cancelled": "中止", "hook_blocking_error": "停止"}
# PreToolUse のフックが操作を止めた記録は attachment ではなく、ツールの結果に残る。
PRE_TOOL_BLOCK = re.compile(r"^PreToolUse:\S+ hook error: \[(.*?)\]: (.*)", re.S)
HOOK_NOISE = re.compile(r"^Failed with non-blocking status code:\s*|\btime=\S+\s*")
HOME_PATH = re.compile(r"/(?:Users|home)/[^/\s'\"]+")


def mask(text: str) -> str:
    return SECRET.sub("***", text)


def excerpt(text: str) -> str:
    flat = mask(" ".join(text.split()))
    return flat if len(flat) <= EXCERPT_CHARS else flat[:EXCERPT_CHARS] + "…"


def failure_line(body: str) -> str:
    """失敗の型を表す1行。Bash は1行目が終了コードだけなので、原因に近い末尾の行も添える。"""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return ""
    head = f"{lines[0]} / {lines[-1]}" if lines[0].startswith("Exit code") and len(lines) > 1 else lines[0]
    return VOLATILE.sub("<x>", mask(head)[:120])


def hook_text(text) -> str:
    """フックのコマンドか標準エラーの1行目。ホームのパスと鍵らしい文字列を伏せる。"""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return mask(HOME_PATH.sub("~", HOOK_NOISE.sub("", lines[0])))[:EXCERPT_CHARS] if lines else ""


def local_day(timestamp) -> str:
    """ISO 8601 の時刻を、この端末の時間帯の日付にする。読めなければ先頭の10字を返す。"""
    text = str(timestamp or "")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except ValueError:
        return text[:10]


def hook_signal(attachment: dict, kind: str):
    """束ねる鍵（種類、イベント、コマンド、終了コード）と、1件ごとの説明を返す。"""
    blocking = attachment.get("blockingError") if isinstance(attachment.get("blockingError"), dict) else {}
    key = (kind, str(attachment.get("hookEvent")), hook_text(attachment.get("command") or blocking.get("command")), attachment.get("exitCode"))
    if kind == "中止":
        return key, f"{attachment.get('timeoutMs')} ms で時間切れ" if attachment.get("timedOut") else ""
    return key, hook_text(blocking.get("blockingError") if kind == "停止" else attachment.get("stderr"))


def block_text(body) -> str:
    if isinstance(body, list):
        return " ".join(part.get("text", "") for part in body if isinstance(part, dict))
    return body if isinstance(body, str) else ""


def scan(path: Path, signals: dict) -> None:
    session = path.stem[:8]
    project, tool_names = None, {}
    seen_assistant, pending = False, None
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            attachment = record.get("attachment") if isinstance(record.get("attachment"), dict) else {}
            hook_kind = HOOK_KINDS.get(attachment.get("type"))
            if hook_kind:
                key, detail = hook_signal(attachment, hook_kind)
                signals["hook_failures"][key].append((str(record.get("timestamp") or ""), session, detail))
                continue
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            content = message.get("content")
            blocks = [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []
            if record.get("type") == "assistant":
                seen_assistant, pending = True, None
                tool_names.update((b.get("id"), b.get("name")) for b in blocks if b.get("type") == "tool_use")
                continue
            if record.get("type") != "user":
                continue
            project = project or Path(record.get("cwd") or "").name or path.parent.name[-30:]
            where = f"{local_day(record.get('timestamp'))} {project}/{session}"
            text = content if isinstance(content, str) else block_text([b for b in blocks if b.get("type") == "text"])
            text = text.strip()

            # 1. 構造の信号を先に拾う。中断のレコードは origin を持たない。
            for block in blocks:
                if block.get("type") != "tool_result" or not block.get("is_error"):
                    continue
                body = block_text(block.get("content")).strip()
                tool = tool_names.get(block.get("tool_use_id")) or "unknown"
                if body.startswith(INTERRUPT):
                    continue  # 実行中の中断。下の中断のレコードで数える。
                blocked = PRE_TOOL_BLOCK.match(body)
                if blocked:
                    key = ("停止", "PreToolUse", hook_text(blocked.group(1)), None)
                    signals["hook_failures"][key].append((str(record.get("timestamp") or ""), session, hook_text(blocked.group(2))))
                    continue
                if body.startswith(REJECTIONS):
                    # 拒否と同時に本人が理由を書くと、tool_result の本文に入る。
                    said = body.partition("the user said:")[2].strip()
                    signals["rejections"].append(f"{where} {tool}" + (f": {excerpt(said)}" if said else ""))
                    pending = "拒否"
                else:
                    signals["failures"][(tool, failure_line(body))].append(session)
            if text.startswith(INTERRUPT):
                # 拒否と対になった「for tool use」は拒否として数え済みなので、二重に数えない。
                if not (text.startswith(INTERRUPT_FOR_TOOL) and pending == "拒否"):
                    signals["interrupts"].append(where)
                    pending = "中断"
                continue

            # 2. 本人の発話を見分ける。
            origin = record.get("origin") if isinstance(record.get("origin"), dict) else {}
            if origin.get("kind") != "human":
                is_known_machine = record.get("isMeta") or record.get("isCompactSummary") or origin or not text
                if not is_known_machine and not any(b.get("type") == "tool_result" for b in blocks):
                    signals["undetermined"] += 1
                continue
            if not seen_assistant:
                signals["first_prompts"] += 1
                continue
            labels = [n for n, p in LABEL_PATTERNS.items() if len(text) <= LABEL_MAX_CHARS and p.search(text)]
            if pending:
                labels.insert(0, f"{pending}の直後")
            target = signals["labelled"] if labels else signals["unlabelled"]
            target.append(f"[{'、'.join(labels) or 'ラベルなし'}] {where}: {excerpt(text)}")
            pending = None


def render(signals: dict, days: int, files: int, seconds: float, show_all: bool) -> str:
    labelled, unlabelled = signals["labelled"], signals["unlabelled"]
    failures = sorted(
        (
            (len(sessions), len(set(sessions)), tool, line)
            for (tool, line), sessions in signals["failures"].items()
            if len(sessions) >= FAILURE_MIN_COUNT or len(set(sessions)) >= FAILURE_MIN_SESSIONS
        ),
        reverse=True,
    )
    # 束ごとに、最後に起きた日、件数、セッション数、最後の1件の説明を出す。hits は (時刻, セッション, 説明)。
    latest = {key: max(hits, key=lambda hit: hit[0]) for key, hits in signals["hook_failures"].items()}
    hook_failures = sorted(
        ((local_day(latest[key][0]), len(hits), len({hit[1] for hit in hits}), key, latest[key][2]) for key, hits in signals["hook_failures"].items()),
        key=lambda item: item[:3],  # 鍵の終了コードは数と None が混ざるので、比較に入れない
        reverse=True,
    )
    out = [
        f"# ハーネスの信号（過去 {days} 日）",
        "",
        f"- 集計 {time.strftime('%Y-%m-%d %H:%M')}。transcript {files} 本、所要 {seconds:.1f} 秒。",
        "- 対象は ~/.claude/projects のセッションで、subagents は読まない。Codex のセッションは含まない。",
        "- 期間はファイルの更新日時で絞る。再開したセッションでは、期間より前の発話も入る。日付はこの端末の時間帯である。",
        f"- 本人の発話: 最初の依頼 {signals['first_prompts']} 件、続きの発話 {len(labelled) + len(unlabelled)} 件。"
        f"本人かどうか判別できないレコード {signals['undetermined']} 件。",
        "- ラベルは語彙の一致で付けた目印で、訂正と決まったわけではない。抜粋をこの端末の外へ転記しない。",
        *(
            ["- 注意: 判別できないレコードが本人の発話より多い。origin を書かない版の記録が多く、取りこぼしている。"]
            if signals["undetermined"] > signals["first_prompts"] + len(labelled) + len(unlabelled)
            else []
        ),
        "",
        f"## 中断 {len(signals['interrupts'])} 件、拒否 {len(signals['rejections'])} 件",
        "",
        *[f"- 中断 {item}" for item in signals["interrupts"]],
        *[f"- 拒否 {item}" for item in signals["rejections"]],
        "",
        f"## ラベルの付いた続きの発話 {len(labelled)} 件（付かなかった発話 {len(unlabelled)} 件）",
        "",
        *[f"- {item}" for item in labelled],
    ]
    if show_all:
        out += ["", "## ラベルの付かなかった続きの発話", "", *[f"- {item}" for item in unlabelled]]
    out += [
        "",
        f"## ツールの失敗（{FAILURE_MIN_COUNT} 回以上、または {FAILURE_MIN_SESSIONS} セッション以上）",
        "",
        *[f"- {count} 回 / {sessions} セッション {tool}: {line}" for count, sessions, tool, line in failures],
        "",
        f"## フックの失敗・中止・停止 {sum(item[1] for item in hook_failures)} 件（最後に起きた日の新しい順）",
        "",
        "失敗は、失敗しても処理が続いたもの。中止は、時間切れなどで打ち切られたもの。停止は、フックが操作を止めたもので、意図した停止も含む。",
        "最後に起きた日が古ければ、すでに直っている。",
        "",
        *[
            f"- 最後 {last} / {count} 回 / {sessions} セッション [{kind}] {event}: {command}"
            + (f"（終了コード {code}）" if code is not None else " ")
            + detail
            for last, count, sessions, (kind, event, command, code), detail in hook_failures
        ],
    ]
    return "\n".join(out) + "\n"


def command_report(args) -> int:
    started = time.time()
    cutoff = started - args.days * 86400
    root = Path.home() / ".claude" / "projects"
    # subagents/ は親エージェントの指示が user として入るので、直下の JSONL だけを読む。
    paths = sorted(path for path in root.glob("*/*.jsonl") if path.stat().st_mtime >= cutoff)
    signals = {
        "interrupts": [],
        "rejections": [],
        "labelled": [],
        "unlabelled": [],
        "failures": collections.defaultdict(list),
        "hook_failures": collections.defaultdict(list),
        "first_prompts": 0,
        "undetermined": 0,
    }
    for path in paths:
        scan(path, signals)
    report = render(signals, args.days, len(paths), time.time() - started, args.all)
    if not args.out:
        sys.stdout.write(report)
        return 0
    if Path(args.out).name != args.out or args.out in (".", ".."):
        # 抜粋を含むので、git で同期される場所へ書けないよう、置き場を固定する。
        raise SystemExit(f"harness-signals: --out はファイル名だけを受ける。置き場は ~/{REPORT_DIR} に固定している")
    target = Path.home() / REPORT_DIR / args.out
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT, 0o600)
    os.fchmod(descriptor, 0o600)  # 既存のファイルの権限が広くても、書く前に絞る。
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.truncate()
        handle.write(report)
    print(f"harness-signals: {target} に書いた（{len(report)} 字）")
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="期間内のセッションを走査して Markdown で出す")
    report.add_argument("--days", type=int, default=30, help="ファイルの更新日時で絞る日数（既定 30）")
    report.add_argument("--all", action="store_true", help="ラベルの付かなかった発話も一覧にする")
    report.add_argument("--out", help="stdout の代わりに、~/.claude/.local/harness-signals/ のこのファイル名へ 0600 で書く")
    report.set_defaults(run=command_report)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
