#!/usr/bin/env python3
"""フックの登録が壊れていないか、他の端末で壊れる書き方でないかを調べる。

対象は settings.json / hooks.json の hooks にある command。1つの登録につき指摘は1件まで。
--hook を付けると SessionStart 用になり、指摘を stdout に出して必ず 0 で終わる。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Iterator, Optional

# SessionStart は「{」で始まる stdout を JSON として解釈するので、必ずこの接頭辞で始める。
PREFIX = "[hook-wiring]"
# git で共有する設定に個人のホームの絶対パスを書くと、別の端末で必ず壊れる。
# 名前が $USER のような変数なら可搬なので対象にしない。/Users/Shared は個人のホームではない。
HOME_ABSOLUTE = re.compile(r"(?<![\w.~$}])/(?:Users|home)/(?!Shared(?:/|\b))[^/\s'\"$]+(?=[/\s'\";&|)]|$)")
HOME_RELATIVE = ("~/", "$HOME/", "${HOME}/")
# 実在を確かめるのはスクリプトだけにする。出力先や存在確認の引数まで調べると誤検出になる。
SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb")
COMMAND_PREVIEW = 100


def default_configs() -> list[Path]:
    return [Path.home() / ".claude" / "settings.json", Path.home() / ".codex" / "hooks.json"]


def hook_commands(config: object) -> Iterator[tuple[str, str]]:
    hooks = config.get("hooks") if isinstance(config, dict) else None
    for event, groups in hooks.items() if isinstance(hooks, dict) else ():
        for group in groups if isinstance(groups, list) else ():
            for hook in group.get("hooks") or () if isinstance(group, dict) else ():
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    yield event, hook["command"]


def check_command(command: str) -> Optional[str]:
    absolute = HOME_ABSOLUTE.search(command)
    if absolute:
        return f"ホームの絶対パス {absolute.group(0)} は他の端末で壊れる。~ か $HOME で書く"
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for token in tokens:
        token = token.rstrip(";")
        if token.startswith(HOME_RELATIVE) and token.endswith(SCRIPT_SUFFIXES):
            target = Path(os.path.expandvars(os.path.expanduser(token)))
            if not target.exists():
                return f"{token} が存在しない"
    return None


def lint(paths: list[Path], explicit: bool) -> list[str]:
    findings = []
    for path in paths:
        if not path.is_file():
            if explicit:
                findings.append(f"{PREFIX} {path}: 設定ファイルがない")
            continue
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            findings.append(f"{PREFIX} {path}: 設定を読めない: {error}")
            continue
        for event, command in hook_commands(config):
            problem = check_command(command)
            if problem:
                preview = command if len(command) <= COMMAND_PREVIEW else command[:COMMAND_PREVIEW] + "…"
                findings.append(f"{PREFIX} {path} の {event}: {problem} — {preview}")
    return findings


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    hook_mode = "--hook" in argv
    # 非 UTF-8 のロケールでも、日本語の出力で落ちないようにする。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
        parser.add_argument("--config", action="append", help="調べる JSON。省略時は両ホームの設定")
        parser.add_argument("--hook", action="store_true", help="SessionStart 用。必ず 0 で終わる")
        args = parser.parse_args(argv)
        configs = [Path(os.path.expanduser(item)) for item in args.config or ()]
        findings = lint(configs or default_configs(), explicit=bool(configs))
    except (Exception, SystemExit) as error:
        # セッション開始のフックでは、検査の失敗でセッションを止めない。
        if not hook_mode or (isinstance(error, SystemExit) and error.code in (0, None)):
            raise
        print(f"{PREFIX} 検査を完了できなかった: {error!r}")
        return 0
    for finding in findings:
        print(finding)
    if hook_mode:
        if findings:
            print(f"{PREFIX} フックの登録に問題が {len(findings)} 件ある。上の内容を本人に伝える")
        return 0
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
