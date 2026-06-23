#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

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
    "config.example.toml",
}
CLAUDE_MODEL_ALIASES = ["hai" + "ku", "son" + "net", "op" + "us"]
CLAUDE_MODEL_ALIAS_PATTERN = "|".join(re.escape(alias) for alias in CLAUDE_MODEL_ALIASES)
CLAUDE_MODEL_TOKEN = (
    rf"(?:{CLAUDE_MODEL_ALIAS_PATTERN}|"
    rf"claude-[A-Za-z0-9_.-]*(?:{CLAUDE_MODEL_ALIAS_PATTERN})[A-Za-z0-9_.-]*)"
)
MODEL_BOUNDARY = r"[A-Za-z0-9_.-]"

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

BANNED_MODEL_RE = re.compile(
    rf"(?<!{MODEL_BOUNDARY}){CLAUDE_MODEL_TOKEN}(?!{MODEL_BOUNDARY})",
    re.IGNORECASE,
)
EXPLICIT_CODEX_MODEL_RE = re.compile(r"\bmodel\s*[:=]\s*[\"'`]gpt-5\.[45][\"'`]")
SERVICE_TIER_RE = re.compile(r"\bservice_tier\s*[:=]\s*[\"'`]priority[\"'`]")


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


def check_text(root: Path) -> list[str]:
    violations: list[str] = []
    for path in iter_active_files(root):
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            lineno = index + 1
            if BANNED_MODEL_RE.search(line):
                violations.append(f"{path.relative_to(root)}:{lineno}: {line.strip()}")
            if EXPLICIT_CODEX_MODEL_RE.search(line):
                window_start = max(0, index - 1)
                window_end = min(len(lines), index + 4)
                nearby = "\n".join(lines[window_start:window_end])
                if not SERVICE_TIER_RE.search(nearby):
                    violations.append(
                        f"{path.relative_to(root)}:{lineno}: explicit model without nearby service_tier priority: {line.strip()}"
                    )
    return violations


def check_agents(root: Path) -> list[str]:
    violations: list[str] = []
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return violations
    for path in sorted(agents_dir.glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text())
        except Exception as exc:
            violations.append(f"{path.relative_to(root)}: TOML parse failed: {exc}")
            continue
        model = data.get("model")
        if isinstance(model, str) and BANNED_MODEL_RE.search(model):
            violations.append(f"{path.relative_to(root)}: banned model field {model!r}")
        if model and not data.get("service_tier"):
            violations.append(f"{path.relative_to(root)}: model is set but service_tier is missing")
    return violations


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: verify-codex-model-compat.py <codex-root> [<codex-root>...]", file=sys.stderr)
        return 2

    all_violations: list[str] = []
    for arg in sys.argv[1:]:
        root = Path(arg).expanduser().resolve()
        violations = check_text(root) + check_agents(root)
        all_violations.extend(f"{root}: {violation}" for violation in violations)

    if all_violations:
        print("Codex model compatibility violations found:", file=sys.stderr)
        for violation in all_violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    print("Codex model compatibility check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
