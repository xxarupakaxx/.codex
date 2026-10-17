#!/usr/bin/env python3
"""Vendor poteto's pstack (cursor/plugins/pstack) into this Codex home.

The vendored tree lives at skills/pstack/ and mirrors upstream pstack/ so every
relative link keeps working. Codex discovers the nested skills/pstack/skills/*/SKILL.md.

Local changes applied on every sync, nothing else is edited:
- frontmatter `name` becomes the folder slug; names that collide with existing
  Codex skills get a `pstack-` prefix (see COLLISIONS).
- SKILL.md files that use Cursor names get one line after the H1 pointing at
  docs/harness/codex.md (same approach as upstream's Claude Code tree).
- skills with `disable-model-invocation: true` get agents/openai.yaml with
  `allow_implicit_invocation: false`, the Codex equivalent.
- relative links to files left out of the tree (images, automations, assets)
  point at GitHub at the pinned commit.
- agents/*.md are ported to ~/.codex/agents/<name>.toml.

Usage:
  python3 scripts/sync-pstack.py                 # fetch upstream main, re-vendor
  python3 scripts/sync-pstack.py --ref <sha>     # pin a specific commit
  python3 scripts/sync-pstack.py --source DIR    # use an existing cursor/plugins checkout
  python3 scripts/sync-pstack.py --check         # verify the tree matches upstream.json's commit
Network access is only `git clone`/`git fetch` of https://github.com/cursor/plugins.
No upstream code is executed.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = "https://github.com/cursor/plugins"
CODEX_HOME = Path(__file__).resolve().parent.parent
DEST = CODEX_HOME / "skills" / "pstack"
AGENTS_DIR = CODEX_HOME / "agents"
LOCAL_FILES = {"docs/harness/codex.md"}
INCLUDE_TOP = ["skills", "agents", "docs", "LICENSE", "README.md", "plugin.json"]
EXCLUDE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".DS_Store"}
COLLISIONS = {"tdd", "teach", "why"}  # names already owned by user skills in ~/.codex/skills
ADAPTER = "docs/harness/codex.md"
ADAPTER_LINE = (
    f"In Codex, read [the Codex adapter](../../{ADAPTER}) once per session before you follow this skill. "
    "It maps the Cursor names in pstack skills to Codex."
)
LINK = re.compile(r"\]\(([^)\s]+)\)")
TERMS = [
    r"`Task`|\bTask (tool|subagent|call)", r"AskQuestion", r"\btodo ?list\b", r"generalPurpose",
    r"poteto-agent", r"comment-sicko", r"readonly: (true|false)|readonly/Ask", r'environment: "(cloud|local)"',
    r"cloud_base_branch", r"run_in_background", r"`resume`", r"file_attachments", r"\bclaude-[a-z]+-\d",
    r"\bgrok-\d", r"\bgpt-\d", r"inherit-parent", r"pstack-models\.mdc", r"\.cursor/skills",
    r"\.cursor/plugins|\.cursor-plugin", r"\.cursor/rules|always-applied rule", r"agent-transcripts|\.cursor/projects",
    r"Bugbot|Cursor [Aa]utomation|cursor\.(sh|com)/automations|[Cc]loud [Aa]gent",
]
AGENT_NOTE = """\
Codex note (added by ~/.codex/scripts/sync-pstack.py): pstack is vendored at ~/.codex/skills/pstack.
The poteto-mode skill is ~/.codex/skills/pstack/skills/poteto-mode/SKILL.md. Wherever the text below says to
search ~/.cursor/plugins/ for it, use that path. Read ~/.codex/skills/pstack/docs/harness/codex.md first; it maps
the Cursor tool, subagent, model, and path names to Codex. The user's AGENTS.md outranks pstack.
"""


def run(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch(ref: str, workdir: Path) -> Path:
    checkout = workdir / "plugins"
    print(f"fetch: {REPO} {ref}", file=sys.stderr)
    run(["git", "init", "-q", str(checkout)])
    run(["git", "remote", "add", "origin", REPO], cwd=checkout)
    run(["git", "fetch", "-q", "--depth", "1", "origin", ref], cwd=checkout)
    run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=checkout)
    print("fetch: done", file=sys.stderr)
    return checkout


def split_frontmatter(text: str) -> tuple[list[str], str]:
    if not text.startswith("---\n"):
        return [], text
    end = text.index("\n---\n", 4)
    return text[4:end].split("\n"), text[end + 5:]


def codex_name(slug: str) -> str:
    return f"pstack-{slug}" if slug in COLLISIONS else slug


def render(src: Path, sha: str) -> dict[str, tuple[bytes, bool]]:
    pstack = src / "pstack"
    files: dict[str, tuple[bytes, bool]] = {}
    for top in INCLUDE_TOP:
        base = pstack / top
        paths = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for path in paths:
            rel = path.relative_to(pstack).as_posix()
            if path.suffix in EXCLUDE_SUFFIXES or path.name in EXCLUDE_SUFFIXES or rel in LOCAL_FILES:
                continue
            files[rel] = (path.read_bytes(), os.access(path, os.X_OK))

    skills = sorted(p.parent.name for p in (pstack / "skills").glob("*/SKILL.md"))
    for slug in skills:
        others = "|".join(re.escape(s) for s in skills if s != slug)
        route = re.compile(rf"the \*\*({others})\*\* skill|`/({others})`")
        uses = False
        for rel, (data, _) in files.items():
            if rel.startswith(f"skills/{slug}/") and rel.endswith(".md"):
                text = data.decode()
                if any(re.search(t, text, re.I if "todo" in t else 0) for t in TERMS) or route.search(text):
                    uses = True
                    break
        key = f"skills/{slug}/SKILL.md"
        data, exe = files[key]
        fm, body = split_frontmatter(data.decode())
        disabled = any(line.strip() == "disable-model-invocation: true" for line in fm)
        fm = [f"name: {codex_name(slug)}" if line.startswith("name:") else line for line in fm]
        if uses and re.search(r"^# ", body, re.M):
            body = re.sub(r"^(# .*)\n+", lambda m: f"{m.group(1)}\n\n{ADAPTER_LINE}\n\n", body, count=1, flags=re.M)
        files[key] = (("---\n" + "\n".join(fm) + "\n---\n" + body).encode(), exe)
        if disabled:
            yaml = "# Generated by scripts/sync-pstack.py from `disable-model-invocation: true`.\npolicy:\n  allow_implicit_invocation: false\n"
            files[f"skills/{slug}/agents/openai.yaml"] = (yaml.encode(), False)

    present = set(files) | LOCAL_FILES
    for rel, (data, exe) in list(files.items()):
        if not rel.endswith(".md"):
            continue

        def fix(match: re.Match[str]) -> str:
            href = match.group(1)
            target = re.sub(r"[#?].*", "", href)
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                return match.group(0)
            path = posixpath.normpath(posixpath.join(posixpath.dirname(rel), target))
            if path.startswith("..") or path in present or any(p.startswith(path + "/") for p in present):
                return match.group(0)
            full = pstack / path
            if not full.exists():
                return match.group(0)
            kind = "tree" if full.is_dir() else "blob"
            return f"]({REPO}/{kind}/{sha}/pstack/{path}{href[len(target):]})"

        files[rel] = (LINK.sub(fix, data.decode()).encode(), exe)

    manifest = json.loads((pstack / "plugin.json").read_text())
    names = {s: codex_name(s) for s in skills}
    upstream = {
        "repository": REPO,
        "path": "pstack",
        "commit": sha,
        "version": manifest.get("version"),
        "license": manifest.get("license"),
        "author": manifest.get("author", {}).get("name"),
        "skills": len(skills),
        "renamed": {s: n for s, n in names.items() if s != n},
        "excluded": ["assets/", "automations/", "docs/**/images (linked to GitHub)"],
    }
    files["upstream.json"] = ((json.dumps(upstream, indent=2, ensure_ascii=False) + "\n").encode(), False)
    files["UPSTREAM.md"] = (upstream_md(upstream, skills).encode(), False)
    return files


def upstream_md(u: dict, skills: list[str]) -> str:
    rows = "\n".join(f"| `{s}` | `${codex_name(s)}` |" for s in skills)
    return f"""# pstack (vendored)

poteto's pstack, vendored from {u['repository']}/tree/{u['commit']}/pstack for Codex.
Generated by `scripts/sync-pstack.py`; edit upstream or the script, not these files.
Only `docs/harness/codex.md` is hand-written here.

- Commit: `{u['commit']}`
- Version: `{u['version']}`
- License: {u['license']} (`LICENSE`, Copyright (c) 2026 {u['author']})
- Installed by user request; skill-governance review receipts were not produced (see the commit body).

Update: `python3 ~/.codex/scripts/sync-pstack.py` then review the diff and commit.
Check: `python3 ~/.codex/scripts/sync-pstack.py --check`.

Local changes: Codex adapter line after the H1 of skills that use Cursor names, frontmatter
names set to the folder slug with a `pstack-` prefix where a user skill already owns the name,
`agents/openai.yaml` (`allow_implicit_invocation: false`) for skills upstream marks
`disable-model-invocation: true`, links to excluded files pointed at GitHub, and agents ported to
`~/.codex/agents/poteto-agent.toml` and `~/.codex/agents/comment-sicko.toml`.

| folder | Codex skill |
| --- | --- |
{rows}
"""


def toml_string(text: str) -> str:
    if "'''" not in text:
        return "'''\n" + text + "'''"
    return json.dumps(text, ensure_ascii=False)


def render_agents(src: Path) -> dict[str, bytes]:
    out = {}
    for path in sorted((src / "pstack" / "agents").glob("*.md")):
        fm, body = split_frontmatter(path.read_text())
        meta = {}
        for line in fm:
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        name = meta.get("name", path.stem)
        text = (
            f"# Generated by scripts/sync-pstack.py from cursor/plugins pstack/agents/{path.name}. Do not edit by hand.\n"
            f"name = {json.dumps(name)}\n"
            f"description = {json.dumps('pstack: ' + meta.get('description', ''), ensure_ascii=False)}\n"
            f"developer_instructions = {toml_string(AGENT_NOTE + chr(10) + body.lstrip())}\n"
        )
        out[f"{name}.toml"] = text.encode()
    return out


def disk_tree() -> dict[str, tuple[bytes, bool]]:
    if not DEST.exists():
        return {}
    return {
        p.relative_to(DEST).as_posix(): (p.read_bytes(), os.access(p, os.X_OK))
        for p in DEST.rglob("*")
        if p.is_file() and p.relative_to(DEST).as_posix() not in LOCAL_FILES
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", help="upstream ref or commit (default: main, or upstream.json's commit with --check)")
    ap.add_argument("--source", type=Path, help="existing cursor/plugins checkout")
    ap.add_argument("--check", action="store_true", help="report drift without writing")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        if args.source:
            src = args.source.resolve()
        else:
            ref = args.ref
            if not ref and args.check:
                ref = json.loads((DEST / "upstream.json").read_text())["commit"]
            src = fetch(ref or "main", Path(tmp))
        sha = run(["git", "rev-parse", "HEAD"], cwd=src)
        files = render(src, sha)
        agents = render_agents(src)

        if args.check:
            have = disk_tree()
            drift = sorted(k for k in set(files) | set(have) if files.get(k) != have.get(k))
            drift += [f"agents/{n}" for n, b in agents.items() if not (AGENTS_DIR / n).exists() or (AGENTS_DIR / n).read_bytes() != b]
            if not (DEST / ADAPTER).exists():
                drift.append(f"skills/pstack/{ADAPTER} (missing local adapter)")
            for d in drift[:30]:
                print(f"DRIFT {d}")
            print("pstack is up to date." if not drift else f"pstack drift: {len(drift)} paths (commit {sha})")
            return 1 if drift else 0

        keep = {rel: (DEST / rel).read_bytes() for rel in LOCAL_FILES if (DEST / rel).exists()}
        if DEST.exists():
            shutil.rmtree(DEST)
        for rel, (data, exe) in {**files, **{k: (v, False) for k, v in keep.items()}}.items():
            path = DEST / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o755 if exe else 0o644)
        for name, data in agents.items():
            (AGENTS_DIR / name).write_bytes(data)
        missing = [rel for rel in LOCAL_FILES if rel not in keep]
        print(f"pstack {sha[:12]}: {len(files)} files, {len(agents)} agents" + (f"; MISSING local {missing}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
