#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tools" / "roadmap_viewer.html"
PLACEHOLDER = '{"__ROADMAP_SNAPSHOT_JSON__": true}'
DEFAULT_FILES = [
    "00_spec.md",
    "10_task.md",
    "20_survey.md",
    "30_plan.md",
    "40_progress.md",
    "80_review.md",
    "05_log.md",
    "99_history.md",
    "checkpoint.md",
]


def read_files(task_dir: Path) -> tuple[dict[str, str], list[dict[str, object]]]:
    files: dict[str, str] = {}
    sources: list[dict[str, object]] = []
    for name in DEFAULT_FILES:
        path = task_dir / name
        if not path.is_file():
            continue
        text = path.read_text()
        files[name] = text
        stat = path.stat()
        sources.append(
            {
                "name": name,
                "path": str(path),
                "size": stat.st_size,
                "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    return files, sources


def infer_title(files: dict[str, str], task_dir: Path) -> str:
    for name in ("30_plan.md", "00_spec.md", "05_log.md"):
        text = files.get(name, "")
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                if title:
                    return title
    return task_dir.name.replace("_", " ")


def build_snapshot(task_dir: Path) -> dict[str, object]:
    files, sources = read_files(task_dir)
    if not files:
        raise ValueError(f"no roadmap source files found in {task_dir}")
    return {
        "version": 1,
        "title": infer_title(files, task_dir),
        "taskDir": str(task_dir),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "sources": sources,
    }


def render_html(snapshot: dict[str, object]) -> str:
    template = TEMPLATE.read_text()
    if PLACEHOLDER not in template:
        raise ValueError(f"placeholder not found in {TEMPLATE}")
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    return template.replace(PLACEHOLDER, payload, 1)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a browser-readable roadmap.html from a Codex task memory directory."
    )
    parser.add_argument("task_dir", help="Path to .local/memory/<task>")
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Defaults to <task_dir>/roadmap.html.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write roadmap-snapshot.json next to the HTML as well.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    task_dir = Path(args.task_dir).expanduser().resolve()
    if not task_dir.is_dir():
        print(f"task_dir is not a directory: {task_dir}", file=sys.stderr)
        return 2

    output = Path(args.output).expanduser().resolve() if args.output else task_dir / "roadmap.html"
    snapshot = build_snapshot(task_dir)
    html = render_html(snapshot)
    output.write_text(html)

    if args.json:
        json_path = output.with_name("roadmap-snapshot.json")
        json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
