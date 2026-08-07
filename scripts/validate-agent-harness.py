#!/usr/bin/env python3
"""Validate the stable entrypoint and phase artifact metadata contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


ENTRYPOINT_MAX_LINES = 120
REQUIRED_REFERENCES = (
    "context/workflow-rules.md",
    "context/agent-team-routing.md",
    "context/team-run.md",
    "context/memory-file-formats.md",
    "rules/model-routing.md",
    "rules/complexity-budget.md",
    "rules/adr-criteria.md",
    "rules/security.md",
    "rules/common-git-workflow.md",
    "rules/code-review-philosophy.md",
    "skills/team-run/SKILL.md",
)
ARTIFACT_NAME = re.compile(r"^\d{2}[-_].+\.md$")
WORKFLOW_ARTIFACTS = {
    "00_spec.md",
    "05_log.md",
    "20_survey.md",
    "30_plan.md",
    "40_progress.md",
    "80_review.md",
    "90_verification.md",
    "checkpoint.md",
    "team-journal.md",
}
PROJECT_TEMPLATE_MARKERS = ("MEMORY_DIR=", "BASE_BRANCH=", "## 品質チェック")
FRONTMATTER_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")


def parse_frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}

    values: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return values
        match = FRONTMATTER_LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"\'')
    return {}


def valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_entrypoint(repo_root: Path) -> list[str]:
    errors: list[str] = []
    agents = repo_root / "AGENTS.md"
    if not agents.is_file():
        return ["missing entrypoint: AGENTS.md"]

    text = agents.read_text(encoding="utf-8")
    line_count = len(text.splitlines())
    if line_count > ENTRYPOINT_MAX_LINES:
        errors.append(
            f"AGENTS.md exceeds {ENTRYPOINT_MAX_LINES} lines: {line_count}"
        )

    for reference in REQUIRED_REFERENCES:
        if reference not in text:
            errors.append(f"AGENTS.md missing SSoT reference: {reference}")
        if not (repo_root / reference).is_file():
            errors.append(f"missing SSoT target: {reference}")

    for relative in (
        "templates/project/AGENTS.md",
        "templates/project/CLAUDE.md",
        "claude-compat/templates/project/AGENTS.md",
        "claude-compat/templates/project/CLAUDE.md",
    ):
        if not (repo_root / relative).is_file():
            errors.append(f"missing project entrypoint template: {relative}")

    for relative in (
        "templates/project/CLAUDE.md",
        "claude-compat/templates/project/CLAUDE.md",
    ):
        path = repo_root / relative
        if path.is_file() and path.read_text(encoding="utf-8").strip() != "@AGENTS.md":
            errors.append(f"Claude template must only import AGENTS.md: {relative}")

    for relative in (
        "templates/project/AGENTS.md",
        "claude-compat/templates/project/AGENTS.md",
    ):
        path = repo_root / relative
        if not path.is_file():
            continue
        template = path.read_text(encoding="utf-8")
        for marker in PROJECT_TEMPLATE_MARKERS:
            if marker not in template:
                errors.append(f"project AGENTS template missing {marker}: {relative}")

    return errors


def validate_markdown_artifact(path: Path) -> list[str]:
    errors: list[str] = []
    values = parse_frontmatter(path)
    for key in ("task", "phase_or_step", "created_at"):
        if not values.get(key):
            errors.append(f"{path}: missing frontmatter key: {key}")
    created_at = values.get("created_at")
    if created_at and not valid_timestamp(created_at):
        errors.append(f"{path}: invalid created_at: {created_at}")
    return errors


def validate_bypass(path: Path, now: datetime) -> list[str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        return [f"{path}: invalid JSON: {error}"]

    errors: list[str] = []
    if value.get("enabled") is not True:
        errors.append(f"{path}: enabled must be true")
    for key in ("task", "reason", "expires_at"):
        if not value.get(key):
            errors.append(f"{path}: missing key: {key}")

    expires_at = value.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= now:
                errors.append(f"{path}: bypass expired: {expires_at}")
        except ValueError:
            errors.append(f"{path}: invalid expires_at: {expires_at}")
    return errors


def validate_artifact_dir(path: Path, now: datetime | None = None) -> list[str]:
    if not path.is_dir():
        return [f"artifact directory not found: {path}"]

    checked_at = now or datetime.now(timezone.utc)
    errors: list[str] = []
    for artifact in sorted(path.rglob("*.md")):
        if ARTIFACT_NAME.match(artifact.name) or artifact.name in WORKFLOW_ARTIFACTS:
            errors.extend(validate_markdown_artifact(artifact))
    for bypass in sorted(path.rglob("single-step/*.json")):
        errors.extend(validate_bypass(bypass, checked_at))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--artifact-dir", type=Path, action="append", default=[])
    args = parser.parse_args()

    errors = validate_entrypoint(args.repo_root.resolve())
    for artifact_dir in args.artifact_dir:
        errors.extend(validate_artifact_dir(artifact_dir.resolve()))

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("PASS: agent harness contracts are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
