#!/usr/bin/env python3
"""Run an isolated Luna Max text-only delivery draft and validate its output."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agent_delivery_lifecycle import (
    MODEL_ROSTER,
    route_delivery_draft,
    validate_artifact,
    validate_delivery_draft_structure,
)
from git_delivery_contract import validate_worker_patch


MODEL, REASONING_EFFORT = MODEL_ROSTER["Fast"]
MAX_INPUT_BYTES = 96 * 1024
DISABLED_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode_host",
    "computer_use",
    "goals",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "multi_agent_v2",
    "shell_tool",
    "skill_mcp_dependency_install",
    "standalone_web_search",
    "tool_call_mcp_elicitation",
    "tool_search_always_defer_mcp_tools",
    "tool_suggest",
    "workspace_dependencies",
)
TOOL_FEATURE_PREFIXES = (
    "apps",
    "artifact",
    "auth_elicitation",
    "browser_",
    "code_mode",
    "computer_use",
    "goals",
    "image_",
    "mcp_",
    "multi_agent",
    "request_permissions_tool",
    "search_tool",
    "shell_tool",
    "skill_mcp",
    "standalone_web_search",
    "tool_call",
    "workspace_dependencies",
)
CANONICAL_PR_SECTIONS = (
    "summary",
    "why",
    "trade_off",
    "out_of_scope",
    "impact",
    "tests",
    "residual_risks",
)


def output_schema(draft_input: Mapping[str, Any]) -> dict[str, Any]:
    if draft_input.get("draft_kind") == "commit":
        content_properties = {
            "type": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        }
    else:
        template_sections = tuple(
            item for item in draft_input.get("template_sections", []) if isinstance(item, str)
        )
        section_names = tuple(dict.fromkeys((*CANONICAL_PR_SECTIONS, *template_sections)))
        content_properties = {
            "title": {"type": "string"},
            "sections": {
                "type": "object",
                "additionalProperties": False,
                "required": list(section_names),
                "properties": {name: {"type": "string"} for name in section_names},
            },
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "draft_id",
            "draft_kind",
            "source_hash",
            "status",
            "claim_references",
            "content",
        ],
        "properties": {
            "draft_id": {"type": "string"},
            "draft_kind": {"enum": ["commit", "pull_request"]},
            "source_hash": {"type": "string"},
            "status": {"enum": ["DRAFT_READY", "DRAFT_BLOCKED"]},
            "claim_references": {"type": "array", "items": {"type": "string"}},
            "content": {
                "type": "object",
                "additionalProperties": False,
                "required": list(content_properties),
                "properties": content_properties,
            },
        },
    }


def build_command(schema_path: Path, output_path: Path, working_dir: Path) -> list[str]:
    command = [
        "codex",
        "exec",
        "--model",
        MODEL,
        "-c",
        f'model_reasoning_effort="{REASONING_EFFORT}"',
        "-c",
        'service_tier="priority"',
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--cd",
        str(working_dir),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
    ]
    for feature in DISABLED_FEATURES:
        command.extend(("--disable", feature))
    command.append("-")
    return command


def validate_feature_inventory(inventory: str) -> list[str]:
    if not inventory.strip():
        return ["Codex feature inventory is unavailable"]
    errors: list[str] = []
    for line in inventory.splitlines():
        columns = line.split()
        if len(columns) < 3 or columns[-1].lower() != "true":
            continue
        feature = columns[0]
        tool_capable = feature.startswith(TOOL_FEATURE_PREFIXES) or "tool" in feature
        if tool_capable and feature not in DISABLED_FEATURES:
            errors.append(f"enabled tool feature is not denied: {feature}")
    return errors


def draft_delivery_message(
    draft_input: Mapping[str, Any],
    *,
    expected_source_hash: str,
    feature_inventory: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[dict[str, Any] | None, list[str]]:
    input_errors = validate_artifact("delivery_draft_input", draft_input)
    if draft_input.get("source_hash") != expected_source_hash:
        input_errors.append("source_hash does not match trusted snapshot")
    patch_errors = validate_worker_patch(
        draft_input.get("worker_patch"),
        [path for path in draft_input.get("changed_paths", []) if isinstance(path, str)],
    )
    input_errors.extend(patch_errors)
    input_errors.extend(validate_feature_inventory(feature_inventory))
    routing = route_delivery_draft(requires_summary=True, available_models=[MODEL])
    if routing.allowed_tools or routing.model != MODEL or routing.reasoning_effort != REASONING_EFFORT:
        input_errors.append("Fast worker route is not output-only")
    if input_errors:
        return None, [f"input: {error}" for error in input_errors]
    encoded = json.dumps(draft_input, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_INPUT_BYTES:
        return None, ["input exceeds isolated worker limit"]

    with tempfile.TemporaryDirectory(prefix="codex-delivery-draft-") as directory:
        working_dir = Path(directory)
        schema_path = working_dir / "output-schema.json"
        output_path = working_dir / "output.json"
        schema_path.write_text(
            json.dumps(output_schema(draft_input), ensure_ascii=False), encoding="utf-8"
        )
        prompt = (
            "You are an output-only delivery drafter. Do not call tools, make decisions, "
            "or request side effects. Return only JSON matching the provided schema. "
            "Use only the supplied evidence identifiers and content. claim_references may contain "
            "only exact strings from changed_paths, acceptance_ids, test_ids, and "
            "residual_risk_ids; never use evidence_bundle_id. For commit, content must contain "
            "only type, subject, and body, and type must be one of feat, fix, docs, refactor, "
            "test, chore, perf, build, or ci. The commit subject must be concise Japanese. "
            "For pull_request, content must contain only "
            "title and sections; sections must include summary, why, trade_off, out_of_scope, "
            "impact, tests, residual_risks, and every supplied template section. Every ready "
            "draft must include one or more allowed claim_references.\n\n"
            f"DELIVERY_DRAFT_INPUT={encoded}"
        )
        result = runner(
            build_command(schema_path, output_path, working_dir),
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return None, [f"isolated Luna worker failed with exit {result.returncode}"]
        try:
            draft_output = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, ["isolated Luna worker returned invalid JSON"]
    if not isinstance(draft_output, dict):
        return None, ["isolated Luna worker output must be an object"]
    errors = validate_delivery_draft_structure(
        draft_input,
        draft_output,
        expected_source_hash=expected_source_hash,
    )
    return (None, errors) if errors else (draft_output, [])


def _load_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("input must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--expected-source-hash", required=True)
    args = parser.parse_args(argv)
    try:
        draft_input = _load_json(args.input)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "DRAFT_BLOCKED", "errors": [str(error)]}))
        return 3
    inventory_result = subprocess.run(
        ["codex", "features", "list"],
        check=False,
        capture_output=True,
        text=True,
    )
    feature_inventory = inventory_result.stdout if inventory_result.returncode == 0 else ""
    output, errors = draft_delivery_message(
        draft_input,
        expected_source_hash=args.expected_source_hash,
        feature_inventory=feature_inventory,
    )
    if errors:
        print(json.dumps({"status": "DRAFT_BLOCKED", "errors": errors}, ensure_ascii=False))
        return 3
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
