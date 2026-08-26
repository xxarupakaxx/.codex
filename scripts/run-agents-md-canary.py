#!/usr/bin/env python3
"""Compare baseline and candidate instruction reachability across representative tasks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import deque
from pathlib import Path


ENTRYPOINTS = (".codex/AGENTS.md", "AGENTS.md")
REFERENCE_PATTERN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|py|js))`")
CODEX_PREFIXES = ("agents/", "context/", "rules/", "scripts/", "skills/", "workflows/")
EXECUTION_CHECKS = {
    "instruction_contract": [
        "python3", "-m", "unittest", "discover", "-s", ".codex/tests",
        "-p", "test_validate_agent_harness.py",
    ],
    "roadmap_adapter": [
        "python3", "-m", "unittest", "discover", "-s", ".codex/tests",
        "-p", "test_sync_roadmap.py",
    ],
    "roadmap_phase_gate": [
        "node", "--test", ".codex/tests/roadmap-sync.test.mjs",
        ".codex/tests/implementation-drive.test.mjs",
    ],
}


def git_text(repo: Path, revision: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def read_source(
    root: Path,
    relative: str,
    root_revision: str | None,
    codex_revision: str | None,
) -> str:
    if relative.startswith(".codex/"):
        repo = root / ".codex"
        repo_relative = relative.removeprefix(".codex/")
        revision = codex_revision
    else:
        repo = root
        repo_relative = relative
        revision = root_revision
    if revision:
        return git_text(repo, revision, repo_relative)
    path = repo / repo_relative
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def normalize_reference(source: str, reference: str) -> str:
    if reference.startswith((".codex/", "_shared-ai/")):
        return reference
    if source.startswith(".codex/") and reference.startswith(CODEX_PREFIXES):
        return f".codex/{reference}"
    parent = Path(source).parent
    return (parent / reference).as_posix()


def reachable_sources(
    root: Path,
    root_revision: str | None,
    codex_revision: str | None,
) -> dict[str, str]:
    found: dict[str, str] = {}
    queue = deque(ENTRYPOINTS)
    while queue and len(found) < 256:
        relative = queue.popleft()
        if relative in found:
            continue
        text = read_source(root, relative, root_revision, codex_revision)
        if not text:
            continue
        found[relative] = text
        for reference in REFERENCE_PATTERN.findall(text):
            normalized = normalize_reference(relative, reference)
            if normalized not in found:
                queue.append(normalized)
    return found


def evaluate(
    variant: str,
    sources: dict[str, str],
    scenarios: list[dict[str, object]],
    repetitions: int,
) -> list[dict[str, object]]:
    text = "\n".join(sources.values())
    trials: list[dict[str, object]] = []
    for scenario in scenarios:
        required = [str(item) for item in scenario["required"]]
        missing = [marker for marker in required if marker not in text]
        for repetition in range(1, repetitions + 1):
            trials.append(
                {
                    "variant": variant,
                    "scenario": scenario["id"],
                    "repetition": repetition,
                    "safety": bool(scenario["safety"]),
                    "status": "pass" if not missing else "fail",
                    "missing": missing,
                }
            )
    return trials


def entry_bytes(
    root: Path, root_revision: str | None, codex_revision: str | None
) -> int:
    return sum(
        len(read_source(root, path, root_revision, codex_revision).encode("utf-8"))
        for path in ENTRYPOINTS
    )


def run_execution_checks(root: Path) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    for name, command in EXECUTION_CHECKS.items():
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        results[name] = {
            "status": "pass" if completed.returncode == 0 else "fail",
            "returncode": completed.returncode,
            "output_tail": (completed.stdout + completed.stderr)[-1000:].strip(),
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--baseline-ref", default="e3fb56d")
    parser.add_argument("--codex-baseline-ref", default="HEAD")
    parser.add_argument("--skip-execution-checks", action="store_true")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=Path(__file__).parents[1]
        / "evals"
        / "agents-md-thin-entry"
        / "scenarios.json",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    fixture = json.loads(args.scenarios.read_text(encoding="utf-8"))
    scenarios = fixture["scenarios"]
    repetitions = int(fixture["repetitions"])
    baseline_sources = reachable_sources(
        root, args.baseline_ref, args.codex_baseline_ref
    )
    candidate_sources = reachable_sources(root, None, None)
    trials = [
        *evaluate("baseline", baseline_sources, scenarios, repetitions),
        *evaluate("candidate", candidate_sources, scenarios, repetitions),
    ]
    execution_checks = (
        {} if args.skip_execution_checks else run_execution_checks(root)
    )
    summary: dict[str, object] = {
        "baseline_ref": args.baseline_ref,
        "codex_baseline_ref": args.codex_baseline_ref,
        "trial_count": len(trials),
        "baseline_pass": sum(
            trial["status"] == "pass" and trial["variant"] == "baseline"
            for trial in trials
        ),
        "candidate_pass": sum(
            trial["status"] == "pass" and trial["variant"] == "candidate"
            for trial in trials
        ),
        "candidate_safety_failures": sum(
            trial["status"] != "pass"
            and trial["variant"] == "candidate"
            and trial["safety"]
            for trial in trials
        ),
        "baseline_reachable_sources": len(baseline_sources),
        "candidate_reachable_sources": len(candidate_sources),
        "baseline_entry_bytes": entry_bytes(
            root, args.baseline_ref, args.codex_baseline_ref
        ),
        "candidate_entry_bytes": entry_bytes(root, None, None),
        "execution_checks_passed": all(
            result["status"] == "pass" for result in execution_checks.values()
        ),
    }
    result = {
        "summary": summary,
        "execution_checks": execution_checks,
        "trials": trials,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    candidate_total = len(scenarios) * repetitions
    passed = (
        summary["candidate_pass"] == candidate_total
        and summary["candidate_safety_failures"] == 0
        and summary["candidate_entry_bytes"] < summary["baseline_entry_bytes"]
        and summary["execution_checks_passed"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
