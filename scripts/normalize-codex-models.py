#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

CODEX_MODEL = "gpt-5.5"
CODEX_SERVICE_TIER = "priority"
CLAUDE_MODEL_ALIASES = ["hai" + "ku", "son" + "net", "op" + "us"]
CLAUDE_MODEL_ALIAS_PATTERN = "|".join(re.escape(alias) for alias in CLAUDE_MODEL_ALIASES)
CLAUDE_MODEL_TOKEN = (
    rf"(?:{CLAUDE_MODEL_ALIAS_PATTERN}|"
    rf"claude-[A-Za-z0-9_.-]*(?:{CLAUDE_MODEL_ALIAS_PATTERN})[A-Za-z0-9_.-]*)"
)
MODEL_BOUNDARY = r"[A-Za-z0-9_.-]"

ACTIVE_ENTRIES = {
    "AGENTS.md",
    "agents",
    "commands",
    "prompts",
    "skills",
    "context",
    "rules",
    "scripts",
    "templates",
    "workflows",
    "scheduled-tasks",
}

TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yml",
    ".yaml",
}

CLAUDE_MODEL_RE = re.compile(
    rf"(?<!{MODEL_BOUNDARY}){CLAUDE_MODEL_TOKEN}(?!{MODEL_BOUNDARY})",
    re.IGNORECASE,
)

MODEL_ASSIGNMENT_RE = re.compile(
    rf"(?P<prefix>(?<!{MODEL_BOUNDARY})model\s*[:=]\s*)"
    rf"(?P<quote>[\"']?)(?P<model>{CLAUDE_MODEL_TOKEN})(?P=quote)(?!{MODEL_BOUNDARY})",
    re.IGNORECASE,
)


def iter_active_files(root: Path):
    for entry in ACTIVE_ENTRIES:
        path = root / entry
        if path.is_file():
            yield path
            continue
        if not path.is_dir():
            continue
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            if any(part in {".git", ".system", "node_modules", "dist"} for part in child.parts):
                continue
            if child.suffix and child.suffix.lower() not in TEXT_SUFFIXES:
                continue
            yield child


def add_service_tier_to_model_literals(text: str) -> str:
    text = re.sub(
        rf'(model\s*:\s*"{re.escape(CODEX_MODEL)}"\s*,)(?!\s*service_tier)',
        rf'\1 service_tier: "{CODEX_SERVICE_TIER}",',
        text,
    )
    text = re.sub(
        rf"(model\s*:\s*'{re.escape(CODEX_MODEL)}'\s*,)(?!\s*service_tier)",
        rf"\1 service_tier: '{CODEX_SERVICE_TIER}',",
        text,
    )
    return text


def normalize_text(text: str) -> str:
    text = MODEL_ASSIGNMENT_RE.sub(
        lambda match: f'{match.group("prefix")}"{CODEX_MODEL}"',
        text,
    )
    text = CLAUDE_MODEL_RE.sub(CODEX_MODEL, text)
    return add_service_tier_to_model_literals(text)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: normalize-codex-models.py <codex-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).expanduser().resolve()
    changed: list[Path] = []
    for path in iter_active_files(root):
        try:
            before = path.read_text()
        except UnicodeDecodeError:
            continue
        after = normalize_text(before)
        if after != before:
            path.write_text(after)
            changed.append(path.relative_to(root))

    if changed:
        print("normalized Codex model aliases:")
        for path in changed:
            print(f"  {path}")
    else:
        print("normalized Codex model aliases: no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
