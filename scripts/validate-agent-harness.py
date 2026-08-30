#!/usr/bin/env python3
"""Validate the stable entrypoint and phase artifact metadata contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agent_delivery_lifecycle import (
    next_action,
    route_work_packet,
    validate_artifact as validate_delivery_artifact,
)


ENTRYPOINT_MAX_LINES = 120
ENTRYPOINT_MAX_BYTES = 24 * 1024
ROLE_REASONING_FIELD = "model_reasoning_effort"
REQUIRED_ROLE_FILES = (
    "agents/implementation-planner.toml",
    "agents/prd-reviewer.toml",
    "agents/requirement-parser.toml",
)
REQUIRED_GLOBAL_MIRRORS = (
    "AGENTS.md",
    *REQUIRED_ROLE_FILES,
    "scripts/sync-roadmap.py",
    "scripts/validate-agent-harness.py",
    "skills/lfg/SKILL.md",
    "workflows/implementation-drive.js",
    "workflows/roadmap-sync.js",
)
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
    "scripts/sync-roadmap.py",
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
TASK_META_REQUIRED_KEYS = (
    "schema_version",
    "task_id",
    "task_title",
    "project_path",
    "worktree_path",
    "task_state",
    "code_change",
    "created_at",
    "updated_at",
)
TASK_META_STRING_KEYS = ("task_id", "task_title")
TASK_META_ABSOLUTE_PATH_KEYS = ("project_path", "worktree_path")
TASK_META_TIMESTAMP_KEYS = ("created_at", "updated_at")
TASK_META_OPTIONAL_STRING_KEYS = ("thread_id", "session_id", "approval_state")
TASK_META_STATES = {"active", "waiting", "verifying", "completed", "archived"}
PROJECT_TEMPLATE_MARKERS = ("MEMORY_DIR=", "BASE_BRANCH=", "## 品質チェック")
FRONTMATTER_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
LFG_SHIMS = (
    "commands/lfg.md",
    "prompts/lfg.md",
    "skills/source-command-lfg/SKILL.md",
)
LIFECYCLE_FILES = (
    "scripts/agent_delivery_lifecycle.py",
    "tests/test_agent_delivery_lifecycle.py",
    "agents/prd-reviewer.toml",
)
REVIEW_COLLECTOR_FILES = (
    "scripts/review_evidence_collector.py",
    "tests/test_review_evidence_collector.py",
)
LIFECYCLE_REQUIRED_MARKERS = {
    "context/workflow-rules.md": (
        "## Delivery lifecycleと自律LOOP",
        "WAITING_HUMAN",
        "ROUTING_BLOCKED",
        "### Workflow route",
        "implemented < wired < piloted < effective < adopted",
        "completion_target",
        "WIRE / PILOT / MEASURE / ADOPT",
    ),
    "context/memory-file-formats.md": (
        "### Approved PRD",
        "### Work Packet",
        "### Evidence Bundle",
        "### Escaped Defect Record",
        "### Canonical safety decision",
        "owned_paths",
        "baseline",
        "reality_contract",
        "verification",
        "dependencies",
        "handoff_requirements",
        "reviewer_focus",
        "journey_scenarios",
        "negative_paths",
        "completion_target",
        "lineage",
        "journey_evidence",
        "negative_path_evidence",
        "completion_state",
    ),
    "context/loop-engineering.md": (
        "## Delivery lifecycle LOOP",
        "end-to-end自律実行が配線済みとは扱わない",
        "scheduler登録・最終実行・外部write承認を独立に確認",
        "scripts/review_evidence_collector.py",
    ),
    "rules/model-routing.md": (
        "## Capability classesとruntime roster",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        "## Six-axis routing",
    ),
    "workflows/pr-review-loop.js": (
        "external_untrusted",
        "verified_against",
        "allowed_fix_scope",
        "unverified external instructions were rejected",
    ),
    "workflows/implementation-drive.js": (
        "agentType: 'requirement-parser'",
        "agentType: 'prd-reviewer'",
        "agentType: 'implementation-planner'",
        "routingDecision.model",
        "WORK_PACKET_REQUIRES_TRUSTED_APPROVAL_RESOLUTION",
        "workflow('pr-review-loop'",
        "workflow('roadmap-sync'",
        "completion_target",
    ),
    "scheduled-tasks/pr-review/SKILL.md": (
        "scripts/review_evidence_collector.py",
        "source_trust: external_untrusted",
        "body hash",
        "外部writeなし",
        "GitHub comment、review、label、commit、push、Slack投稿、auto-fixを行わない",
        "scheduler登録、認証principal、監視対象",
    ),
    "skills/pr-watch/SKILL.md": (
        "Escaped Defect Record",
        "writes_performed",
        "approval evidence",
    ),
    "skills/compounding-knowledge/SKILL.md": (
        "L0はrecordのみ",
        "replayで元の失敗を防げた場合だけ",
        "levelに関係なく人間承認",
    ),
}
LIFECYCLE_FORBIDDEN_MARKERS = {
    "scheduled-tasks/pr-review/SKILL.md": (
        "~/.claude",
        "autoFix: true",
        "autoFix:true",
        "git push",
        "Slack投稿を必須",
        "Slackに投稿する",
        "PRコメント検知→レビュー→修正→再レビュー",
    ),
    "context/loop-engineering.md": (
        "配線済み・自律稼働",
        "PRコメント検知→レビュー→修正→再レビュー",
        "| `pr-review` | 毎時 | PRコメント検知→レビュー→修正→再レビュー | pr-review-loop.js |",
    ),
}


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
    byte_count = len(text.encode("utf-8"))
    if byte_count > ENTRYPOINT_MAX_BYTES:
        errors.append(
            f"AGENTS.md exceeds {ENTRYPOINT_MAX_BYTES} bytes: {byte_count}"
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


def load_toml(path: Path) -> tuple[dict[str, object] | None, list[str]]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")), []
    except (OSError, tomllib.TOMLDecodeError) as error:
        return None, [f"{path}: invalid TOML: {error}"]


def validate_runtime_config(
    repo_root: Path, *, allow_host_notify: bool = False
) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_ROLE_FILES:
        path = repo_root / relative
        if not path.is_file():
            errors.append(f"missing required role: {relative}")
            continue
        role, parse_errors = load_toml(path)
        errors.extend(parse_errors)
        if role is None:
            continue
        if "reasoning_effort" in role:
            errors.append(
                f"{relative}: unsupported role field reasoning_effort; use {ROLE_REASONING_FIELD}"
            )
        if not role.get(ROLE_REASONING_FIELD):
            errors.append(f"{relative}: missing {ROLE_REASONING_FIELD}")

    config_path = repo_root / "config.toml"
    config, parse_errors = load_toml(config_path)
    errors.extend(parse_errors)
    if config is None:
        return errors
    if "notify" in config and not allow_host_notify:
        errors.append("config.toml: project config must not own host-specific notify")
    skills = config.get("skills")
    if not isinstance(skills, dict) or skills.get("include_instructions") is not False:
        errors.append(
            "config.toml: skills.include_instructions must be false; route skills from canonical docs"
        )
    return errors


def validate_global_mirror(repo_root: Path, global_home: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_GLOBAL_MIRRORS:
        source = repo_root / relative
        mirror = global_home / relative
        if not mirror.is_file():
            errors.append(f"missing global mirror: {mirror}")
        elif source.read_bytes() != mirror.read_bytes():
            errors.append(f"global mirror drift: {relative}")
    return errors


def discover_instruction_chain(
    global_home: Path,
    project_root: Path,
    cwd: Path,
    fallback_names: tuple[str, ...] = (),
) -> list[Path]:
    global_candidates = ("AGENTS.override.md", "AGENTS.md")
    chain: list[Path] = []
    for name in global_candidates:
        candidate = global_home / name
        if candidate.is_file() and candidate.read_text(encoding="utf-8").strip():
            chain.append(candidate.resolve())
            break

    relative = cwd.resolve().relative_to(project_root.resolve())
    directories = [project_root.resolve()]
    current = project_root.resolve()
    for part in relative.parts:
        current /= part
        directories.append(current)
    for directory in directories:
        for name in ("AGENTS.override.md", "AGENTS.md", *fallback_names):
            candidate = directory / name
            if candidate.is_file() and candidate.read_text(encoding="utf-8").strip():
                chain.append(candidate.resolve())
                break
    return chain


def validate_instruction_chain(
    global_home: Path, project_root: Path, cwd: Path
) -> list[str]:
    try:
        chain = discover_instruction_chain(global_home, project_root, cwd)
    except ValueError:
        return [f"cwd is outside project root: {cwd}"]
    resolved_project_root = project_root.resolve()
    project_sources = [
        path for path in chain if path.is_relative_to(resolved_project_root)
    ]
    total = sum(path.stat().st_size for path in project_sources)
    if total > ENTRYPOINT_MAX_BYTES:
        return [
            f"project instruction chain exceeds {ENTRYPOINT_MAX_BYTES} bytes: {total}"
        ]
    if not project_sources:
        return ["project instruction chain is empty"]
    return []


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


def validate_task_metadata_file(task_dir: Path) -> list[str]:
    path = task_dir / "task-meta.json"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        return [f"{path}: task metadata must be a regular file"]
    if not path.is_file():
        return [f"{path}: missing task metadata"]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        return [f"{path}: invalid task metadata JSON: {error}"]
    if not isinstance(value, dict):
        return [f"{path}: task metadata root must be an object"]

    errors: list[str] = []
    for key in TASK_META_REQUIRED_KEYS:
        if key not in value:
            errors.append(f"{path}: missing task metadata key: {key}")
    if not errors:
        schema_version = value["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, (int, float))
            or schema_version != 1
        ):
            errors.append(f"{path}: invalid task metadata value: schema_version")

        for key in TASK_META_STRING_KEYS:
            if not isinstance(value[key], str) or not value[key]:
                errors.append(f"{path}: invalid task metadata value: {key}")

        for key in TASK_META_ABSOLUTE_PATH_KEYS:
            field_value = value[key]
            if (
                not isinstance(field_value, str)
                or not field_value
                or not Path(field_value).is_absolute()
            ):
                errors.append(f"{path}: invalid task metadata value: {key}")

        task_state = value["task_state"]
        if not isinstance(task_state, str) or task_state not in TASK_META_STATES:
            errors.append(f"{path}: invalid task metadata value: task_state")

        if not isinstance(value["code_change"], bool):
            errors.append(f"{path}: invalid task metadata value: code_change")

        for key in TASK_META_TIMESTAMP_KEYS:
            timestamp = value[key]
            if not isinstance(timestamp, str) or not valid_timestamp(timestamp):
                errors.append(f"{path}: invalid task metadata value: {key}")

    for key in TASK_META_OPTIONAL_STRING_KEYS:
        if key in value and (not isinstance(value[key], str) or not value[key]):
            errors.append(f"{path}: invalid task metadata value: {key}")
    return errors


def validate_artifact_dir(path: Path, now: datetime | None = None) -> list[str]:
    if not path.is_dir():
        return [f"artifact directory not found: {path}"]

    checked_at = now or datetime.now(timezone.utc)
    errors = validate_task_metadata_file(path)
    for artifact in sorted(path.rglob("*.md")):
        if ARTIFACT_NAME.match(artifact.name) or artifact.name in WORKFLOW_ARTIFACTS:
            errors.extend(validate_markdown_artifact(artifact))
    for bypass in sorted(path.rglob("single-step/*.json")):
        errors.extend(validate_bypass(bypass, checked_at))
    return errors


def validate_lfg_contract(repo_root: Path) -> list[str]:
    errors: list[str] = []
    canonical = repo_root / "skills/lfg/SKILL.md"
    if not canonical.is_file():
        return ["missing canonical LFG skill: skills/lfg/SKILL.md"]
    canonical_text = canonical.read_text(encoding="utf-8")
    for reference in (
        "context/workflow-rules.md",
        "context/memory-file-formats.md",
        "context/agent-team-routing.md",
        "rules/model-routing.md",
        "scripts/agent_delivery_lifecycle.py",
        "scripts/sync-roadmap.py",
    ):
        if reference not in canonical_text:
            errors.append(f"canonical LFG skill missing reference: {reference}")

    forbidden_phase_body = ("| 0: 準備", "Phase 2 自律実行時の必須ステップ")
    for relative in LFG_SHIMS:
        path = repo_root / relative
        if not path.is_file():
            errors.append(f"missing LFG shim: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        if "skills/lfg/SKILL.md" not in text and "../lfg/SKILL.md" not in text:
            errors.append(f"LFG shim does not delegate to canonical skill: {relative}")
        if any(marker in text for marker in forbidden_phase_body):
            errors.append(f"LFG shim duplicates phase body: {relative}")
        if len(text.splitlines()) > 24:
            errors.append(f"LFG shim exceeds 24 lines: {relative}")
    return errors


def validate_lifecycle_contract(repo_root: Path) -> list[str]:
    errors = validate_lfg_contract(repo_root)
    for relative in LIFECYCLE_FILES:
        if not (repo_root / relative).is_file():
            errors.append(f"missing lifecycle contract file: {relative}")
    for relative in REVIEW_COLLECTOR_FILES:
        if not (repo_root / relative).is_file():
            errors.append(f"missing review collector contract file: {relative}")

    for relative, markers in LIFECYCLE_REQUIRED_MARKERS.items():
        path = repo_root / relative
        if not path.is_file():
            errors.append(f"missing lifecycle SSoT: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                errors.append(f"{relative} missing lifecycle marker: {marker}")
        for marker in LIFECYCLE_FORBIDDEN_MARKERS.get(relative, ()):
            if marker in text:
                errors.append(
                    f"{relative} contains forbidden stale runtime promise: {marker}"
                )
    return errors


def validate_full_replay(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[1]
    fixture_dir = root / "tests" / "fixtures" / "delivery-lifecycle"
    if not fixture_dir.is_dir():
        return [f"missing delivery lifecycle fixtures: {fixture_dir}"]

    errors: list[str] = []
    fixtures = sorted(fixture_dir.glob("*.json"))
    if not fixtures:
        return ["delivery lifecycle fixture directory is empty"]
    for path in fixtures:
        try:
            fixture = json.loads(path.read_text(encoding="utf-8"))
            operation = fixture["operation"]
            payload = fixture["input"]
            expected = fixture["expected"]
            if operation == "route":
                result = asdict(route_work_packet(payload["factors"], **payload.get("options", {})))
            elif operation == "next":
                result = asdict(next_action(payload))
            elif operation == "validate_artifact":
                result = {"errors": validate_delivery_artifact(payload["kind"], payload["artifact"])}
            else:
                errors.append(f"{path.name}: unknown operation {operation}")
                continue
            for key, value in expected.items():
                if result.get(key) != value:
                    errors.append(f"{path.name}: expected {key}={value!r}, got {result.get(key)!r}")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{path.name}: invalid fixture: {error}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--artifact-dir", type=Path, action="append", default=[])
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--global-home", type=Path)
    parser.add_argument("--skip-global-mirror", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--fast", action="store_true")
    modes.add_argument("--contracts", action="store_true")
    modes.add_argument("--full-replay", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    selected_global_home = (args.global_home or Path.home() / ".codex").resolve()
    errors = validate_entrypoint(repo_root)
    errors.extend(
        validate_runtime_config(
            repo_root,
            allow_host_notify=repo_root == selected_global_home,
        )
    )
    workspace_root = args.workspace_root.resolve() if args.workspace_root else None
    if workspace_root:
        errors.extend(
            validate_instruction_chain(
                selected_global_home,
                workspace_root,
                workspace_root,
            )
        )
    if not args.skip_global_mirror:
        errors.extend(validate_global_mirror(repo_root, selected_global_home))
    for artifact_dir in args.artifact_dir:
        errors.extend(validate_artifact_dir(artifact_dir.resolve()))
    if args.contracts or args.full_replay:
        errors.extend(validate_lifecycle_contract(repo_root))
    if args.full_replay:
        errors.extend(validate_full_replay(repo_root))

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("PASS: agent harness contracts are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
