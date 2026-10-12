#!/usr/bin/env python3
"""隔離した合成fixtureで有限のharness比較を準備・実行する。"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import random
import re
import selectors
import shlex
import signal
import stat
import resource
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

OWNER = "harness-benchmark-v1"
PLAN = {"version": "v8", "sha256": "45986dad51cf2c4c83bb49fb575f704e8ecf3f963ffd23cd05063503099fa3e3"}
BASELINES = {"codex": "51ee53ed72eec0f7184c0699d244d2329d8e93bd", "claude": "7152ca3d5e05529f04018b59c0f40c668b8567aa"}
LIMITS = {"run_seconds": 600, "total_seconds": 49 * 3600, "retry": 0,
          "codex_tool_events": 40, "claude_turns": 20, "claude_output_tokens": 8192,
          "stdout_bytes": 16 * 1024 * 1024, "stderr_bytes": 16 * 1024 * 1024,
          "line_bytes": 1024 * 1024, "workspace_bytes": 16 * 1024 * 1024,
          "workspace_file_bytes": 4 * 1024 * 1024, "workspace_files": 128,
          "workspace_entries": 256, "comparison_manifest_bytes": 1024 * 1024,
          "comparison_file_bytes": 4 * 1024 * 1024, "comparison_files": 96,
          "comparison_bytes": 16 * 1024 * 1024, "term_grace_seconds": 5}
SECRET_ENV = re.compile(r"(?:API_KEY|TOKEN|OAUTH|PASSWORD|SECRET|CREDENTIAL)", re.I)
FIXED_ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C",
             "TERM": "dumb", "SHELL": "/bin/sh"}
FULL_HASH = re.compile(r"[0-9a-f]{40,64}\Z")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
TIERS = {None, "standard", "priority", "flex"}
CAPABILITIES = ("compact", "resume", "live_home_read_isolation")
NATIVE_TRIGGER_ADAPTERS = {"codex": set(), "claude": set()}
EFFECT_EVIDENCE_ADAPTERS = {"codex": set(), "claude": set()}
RUNTIME_SETTING_ALLOWLISTS = {}
QUIET_RUN_PLACEHOLDER = "__PINNED_QUIET_RUN_SOURCE__"
CAPABILITY_POLICIES = {
    "0657471f1ddc19bac2e730e249f75e2ac8da13d069530c3f11701d22d037ae7d": {
        "codex": {name: "unknown" for name in CAPABILITIES},
        "claude": {name: "unknown" for name in CAPABILITIES}},
    "ce471fd3105e522ed50e864223ec4386d4a4a8c9af6c470401b2967b12f8b787": {
        "codex": {name: "unknown" for name in CAPABILITIES},
        "claude": {name: "unknown" for name in CAPABILITIES}}}
CODEX_CONFIG = '''cli_auth_credentials_store = "keyring"
default_permissions = "harness"
approval_policy = "never"

[permissions.harness.filesystem]
":root" = "deny"
":minimal" = "read"

[permissions.harness.filesystem.":workspace_roots"]
"." = "write"

[permissions.harness.network]
enabled = false
'''
CLAUDE_SAFETY = {"sandbox": {"enabled": True, "allowUnsandboxedCommands": False,
                              "failIfUnavailable": True}}
CLAUDE_MARKER = "runtime/claude/config/isolation-marker.txt"
LIVE_HOME_WRITE_PROBE = Path.home() / ".codex/.local/harness-boundary-write-probe-NONSECRET"
FIXTURES = (
    {"id": "repo_add", "group": "repository", "instruction": "calc.pyのaddを加算へ直し、result.jsonへchecked=trueを書く。",
     "files": {"calc.py": "def add(a, b):\n    return a - b\n"},
     "expected": {"calc.py": "def add(a, b):\n    return a + b\n", "result.json": "{\"checked\":true}\n"}},
    {"id": "repo_normalize", "group": "repository", "instruction": "names.pyのnormalizeを前後空白除去と小文字化に直す。",
     "files": {"names.py": "def normalize(value):\n    return value.upper()\n"},
     "expected": {"names.py": "def normalize(value):\n    return value.strip().lower()\n"}},
    {"id": "repo_tsc_once", "group": "repository", "required_tool": "typescript_cli",
     "instruction": "{tsc} --noEmit --pretty falseを一度だけ実行し、その診断を再利用してcomponent.tsを直す。再実行しない。",
     "files": {"component.ts": "const total: string = 1;\n",
               "tsconfig.json": "{\"compilerOptions\":{\"strict\":true,\"noEmit\":true},\"files\":[\"component.ts\"]}\n"},
     "expected": {"component.ts": "const total: number = 1;\n"},
     "required_commands": [["{tsc}", "--noEmit", "--pretty", "false"]]},
    {"id": "cli_quiet_retrieve", "group": "cli",
     "instruction": "python3 quiet-run.py --log-dir .quiet-logs -- python3 quiet_check.pyを一度だけ実行する。失敗後はpython3 retrieve_failure.pyで保存済みlogの末尾だけを一度取得し、元commandを再実行しない。",
     "files": {"quiet_check.py": "from pathlib import Path\nimport json,sys\np=Path('.quiet-runs'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\nPath('failure.json').write_text(json.dumps({'exit':7,'reason':'stale-index'}))\nfor i in range(2000): print(f'error-{i:04d}: stale-index',file=sys.stderr)\nraise SystemExit(7)\n",
               "quiet-run.py": QUIET_RUN_PLACEHOLDER,
               "retrieve_failure.py": "from pathlib import Path\nimport json\np=Path('.retrievals'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\nlogs=list(Path('.quiet-logs').glob('quiet-*.log'))\nif len(logs)!=1: raise SystemExit(8)\nwith logs[0].open('rb') as f: f.seek(0,2); f.seek(max(0,f.tell()-16384)); tail=f.read().decode(errors='replace')\nv=json.loads(Path('failure.json').read_text())\nPath('report.json').write_text(json.dumps({'status':'failure','reason':v['reason'],'tail_has_reason':'stale-index' in tail}))\n"},
     "expected": {".quiet-runs": "1", ".retrievals": "1",
                  "failure.json": "{\"exit\":7,\"reason\":\"stale-index\"}\n",
                  "report.json": "{\"status\":\"failure\",\"reason\":\"stale-index\",\"tail_has_reason\":true}\n"},
     "required_commands": [["python3", "quiet-run.py", "--log-dir", ".quiet-logs", "--", "python3", "quiet_check.py"],
                           ["python3", "retrieve_failure.py"]], "dynamic_outputs": [".quiet-logs/quiet-*.log"]},
    {"id": "cli_failure_reset", "group": "cli", "instruction": "diagnose_once.pyを一度だけ実行し、failure stateをcleanへresetした結果を確認する。",
     "files": {"failure-state.json": "{\"status\":\"failed\",\"key\":\"tsc:component\"}\n",
               "diagnose_once.py": "from pathlib import Path\nimport json\np=Path('.diagnostic-runs'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\ns=json.loads(Path('failure-state.json').read_text()); Path('diagnosis.json').write_text(json.dumps({'handled':s['key']})); Path('failure-state.json').write_text(json.dumps({'status':'clean','key':None}))\n"},
     "expected": {".diagnostic-runs": "1", "diagnosis.json": "{\"handled\":\"tsc:component\"}\n",
                  "failure-state.json": "{\"status\":\"clean\",\"key\":null}\n"},
     "required_commands": [["python3", "diagnose_once.py"]]},
    {"id": "long_explore", "group": "long", "instruction": "python3 gate_check.pyを一度だけ実行する。保存した判定を再利用し、期限切れ証拠と承認欠測のためgateをholdして根拠path付きでanswer.jsonへ書く。",
     "files": {"docs/a.md": "component: alpha\nowner: team-red\n", "docs/evidence.md": "gate: unit-pass\nvalid_until: 2026-10-01\n",
               "docs/request.md": "evaluation_date: 2026-10-13\napproval: missing\n",
               "gate_check.py": "from pathlib import Path\nimport json\np=Path('.gate-checks'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\nPath('gate-evidence.json').write_text(json.dumps({'gate':'hold','reason':'evidence_expired_and_approval_missing'}))\n"},
     "expected": {".gate-checks": "1", "gate-evidence.json": "{\"gate\":\"hold\",\"reason\":\"evidence_expired_and_approval_missing\"}\n",
                  "answer.json": "{\"owner\":\"team-red\",\"gate\":\"hold\",\"reason\":\"evidence_expired_and_approval_missing\",\"evidence\":[\"docs/a.md\",\"docs/evidence.md\",\"docs/request.md\"]}\n"},
     "required_commands": [["python3", "gate_check.py"]]},
    {"id": "long_compact", "group": "long", "instruction": "state.jsonを読み、実runtimeのcompact後も同じ状態をanswer.jsonへ書く。",
     "files": {"state.json": "{\"objective\":\"ship-alpha\",\"gate\":\"unit-pass\",\"next_action\":\"verify\"}\n"},
     "expected": {"answer.json": "{\"objective\":\"ship-alpha\",\"gate\":\"unit-pass\",\"next_action\":\"verify\"}\n"}, "native": "compact"},
    {"id": "long_resume", "group": "long", "instruction": "直前sessionを実runtimeでresumeし、保持した状態をrestore.jsonへ書く。",
     "files": {}, "expected": {"restore.json": "{\"objective\":\"ship-alpha\",\"gate\":\"unit-pass\",\"next_action\":\"verify\"}\n"},
     "native": "resume", "restore_keys": ["objective", "gate", "next_action"]},
)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root_path(raw):
    path = Path(raw)
    if not path.is_absolute() or path.parent != Path("/private/tmp") or not path.name.startswith("harness-benchmark-"):
        raise SystemExit("rootは/private/tmp/harness-benchmark-<run-id>直下に限定する")
    if path.resolve(strict=False) != path or path.exists() and path.is_symlink():
        raise SystemExit("rootまたはancestorにsymlinkを使用できない")
    return path


def generated_root(path):
    path = Path(path)
    for parent in (path, *path.parents):
        if parent.parent == Path("/private/tmp") and parent.name.startswith("harness-benchmark-"):
            root_path(str(parent))
            for ancestor in (path, *path.parents):
                if ancestor == Path("/private/tmp"):
                    break
                if ancestor.exists() and ancestor.is_symlink():
                    raise SystemExit(f"生成物pathにsymlinkを使用できない: {ancestor}")
            if path.resolve(strict=False) != path:
                raise SystemExit(f"生成物pathがroot外を参照する: {path}")
            return parent
    raise SystemExit(f"生成物pathが許可root外: {path}")


def mkdir(path):
    root = generated_root(path)
    chain = [root]
    if path != root:
        current = root
        for part in path.relative_to(root).parts:
            current /= part; chain.append(current)
    for directory in chain:
        if not directory.exists():
            directory.mkdir(mode=0o700)
        if not directory.is_dir() or directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise SystemExit(f"private directoryではない: {directory}")


def private_tree_ok(bases, maximum=16384):
    """内容やfile名を結果へ出さず、有限件のprivateな通常treeだけを許可する。"""
    pending = list(bases); seen = 0
    try:
        while pending:
            path = pending.pop(); mode = path.lstat().st_mode; seen += 1
            if seen > maximum or stat.S_ISLNK(mode) or mode & 0o077:
                return False
            if stat.S_ISDIR(mode):
                with os.scandir(path) as entries:
                    for entry in entries:
                        if seen + len(pending) >= maximum:
                            return False
                        pending.append(Path(entry.path))
            elif not stat.S_ISREG(mode):
                return False
    except OSError:
        return False
    return True


def write_json(path, value):
    generated_root(path)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise SystemExit(f"privateな通常file以外へ書き込めない: {path}")
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise SystemExit(f"既存JSONの所有権を確認できない: {path}") from error
        if current.get("owner") != OWNER:
            raise SystemExit(f"runner所有でないJSONを上書きできない: {path}")
    mkdir(path.parent)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temp, path)


def write_private(path, content):
    generated_root(path)
    if path.exists() or path.is_symlink():
        raise SystemExit(f"既存fileを上書きしない: {path}")
    mkdir(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def write_private_bytes(path, content):
    generated_root(path)
    if path.exists() or path.is_symlink():
        raise SystemExit(f"既存fileを上書きしない: {path}")
    mkdir(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def read_json(path):
    generated_root(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise SystemExit(f"privateな通常fileではない: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"runner JSONを読めない: {path}") from error
    if value.get("owner") != OWNER:
        raise SystemExit(f"runner所有の生成物ではない: {path}")
    return value


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def environment_identity():
    home = os.environ.get("HOME")
    if not home or "\n" in home or "\x00" in home:
        raise SystemExit("HOMEを安全に固定できない")
    return {"fixed": FIXED_ENV, "home_sha256": hashlib.sha256(home.encode()).hexdigest(),
            "home_preserved": True}


def verify_environment(manifest):
    if manifest.get("environment") != environment_identity():
        raise SystemExit("親HOMEまたは固定環境がprepare後に変化した")


def pricing_identity():
    path = Path(__file__).resolve().parents[1] / "config/model-pricing.json"
    if path.is_symlink() or not path.is_file():
        raise SystemExit("pricing sourceが通常fileではない")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit("pricing sourceを読めない") from error
    version = value.get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit("pricing versionが未定義")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "version": version, "currency": "USD"}


def tool_source_hashes():
    paths = {"runner": Path(__file__), "metrics": Path(__file__).with_name("session-metrics.py"),
             "quiet_run": Path(__file__).with_name("quiet-run.py"),
             "pricing": Path(__file__).resolve().parents[1] / "config/model-pricing.json"}
    if not all(path.is_file() and not path.is_symlink() for path in paths.values()):
        raise SystemExit("runner/metrics sourceが通常fileではない")
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def verify_capability_source(manifest):
    row = manifest.get("capability_source") or {}; path = Path(row.get("source_path", ""))
    allowed = Path.home() / ".codex/.local/dashboards"
    try:
        inside = path.is_relative_to(allowed) and path.resolve(strict=True).is_relative_to(allowed.resolve(strict=True))
    except (OSError, ValueError):
        inside = False
    parents = [item for item in path.parents if item != allowed and allowed in item.parents]
    if (not path.is_absolute() or not inside or any(item.is_symlink() for item in parents) or path.is_symlink() or
            not path.is_file() or path.stat().st_mode & 0o077 or
            hashlib.sha256(path.read_bytes()).hexdigest() != row.get("source_hash")):
        raise SystemExit("capability sourceが準備時から変化した")


def verify_tool_sources(manifest):
    if manifest.get("tool_source_hashes") != tool_source_hashes() or manifest.get("pricing") != pricing_identity():
        raise SystemExit("runner/metrics/pricing source変更後は新しいrootを準備する")
    verify_capability_source(manifest)


def nested_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from nested_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_keys(child)


def load_capabilities(raw):
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise SystemExit("capability evidenceはabsoluteな通常fileに限定する")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit("capability evidenceを読めない") from error
    source = Path(value.get("source_path", ""))
    if not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise SystemExit("capability evidenceのsource_pathが通常fileではない")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    policy = CAPABILITY_POLICIES.get(source_hash)
    if policy is None:
        raise SystemExit("検証済みcapability sourceではない")
    clean = {}
    for runtime in ("codex", "claude"):
        clean[runtime] = {}
        for name in CAPABILITIES:
            row = (value.get(runtime) or {}).get(name) or {}
            state = row.get("state")
            fields = (row.get("runtime_version"), row.get("event"), row.get("trigger_method"), row.get("source_hash"))
            if state not in ("observed", "unknown", "unsupported") or not all(isinstance(item, str) and item for item in fields):
                raise SystemExit(f"capability evidenceが不完全: {runtime}:{name}")
            if not FULL_HASH.fullmatch(row["source_hash"]):
                raise SystemExit(f"capability source hashが不正: {runtime}:{name}")
            if row["source_hash"] != source_hash or (row["state"] == "observed" and policy[runtime][name] != "observed"):
                raise SystemExit(f"capability stateが検証済みsourceを超える: {runtime}:{name}")
            clean[runtime][name] = {key: row[key] for key in ("runtime_version", "event", "trigger_method",
                                                               "state", "source_hash")}
    return {"source_path": str(source), "source_hash": source_hash, "runtimes": clean}


def load_comparison_bundle(raw, candidates):
    path = Path(raw)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077 or
            path.parent.is_symlink() or path.parent.stat().st_mode & 0o077 or
            path.parent.parent != Path("/private/tmp") or not path.parent.name.startswith("harness-comparison-")):
        raise SystemExit("comparison bundleは/private/tmp/harness-comparison-*/manifest.jsonに限定する")
    try:
        with path.open("rb") as stream:
            manifest_bytes = stream.read(LIMITS["comparison_manifest_bytes"] + 1)
        if len(manifest_bytes) > LIMITS["comparison_manifest_bytes"]:
            raise SystemExit("comparison bundle manifestが上限を超える")
        value = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit("comparison bundle manifestを読めない") from error
    bundles = {}; file_count = total_bytes = 0
    for row in value.get("bundles", []):
        key = (row.get("candidate"), row.get("runtime"), row.get("variant"))
        if key[0] not in ("I03", "I04", "I05") or key[1] not in ("codex", "claude") or key[2] not in ("baseline", "candidate"):
            raise SystemExit(f"comparison bundle identityが不正: {key}")
        if key[0] not in candidates:
            continue
        if key in bundles:
            raise SystemExit(f"comparison bundle identityが重複: {key}")
        if row.get("baseline_commit") != BASELINES[key[1]] or row.get("source_dirty") is not False:
            raise SystemExit(f"comparison bundle provenanceが不正: {key}")
        files = []
        for item in row.get("files", []):
            file_count += 1
            if file_count > LIMITS["comparison_files"]:
                raise SystemExit("comparison bundle file数が上限を超える")
            source = path.parent / item.get("source", ""); target = Path(item.get("target", ""))
            class_name = item.get("class"); factor = item.get("factor")
            forbidden = re.compile(r"(?:auth|credential|token|secret|session|\.db|sqlite)", re.I)
            try:
                source.relative_to(path.parent)
                inside = source.resolve(strict=False).is_relative_to(path.parent)
            except (ValueError, OSError):
                inside = False
            ancestors = [entry for entry in source.parents if entry != path.parent and path.parent in entry.parents]
            if (not inside or any(entry.exists() and entry.is_symlink() for entry in ancestors) or
                    source.is_symlink() or not source.is_file() or source.stat().st_nlink != 1 or
                    source.stat().st_mode & 0o077 or
                    target.is_absolute() or ".." in target.parts or forbidden.search(str(source)) or forbidden.search(str(target))):
                raise SystemExit(f"comparison bundle file境界違反: {source}")
            allowed = ((class_name == "workspace_instruction" and target.name in ("AGENTS.md", "CLAUDE.md")) or
                       (class_name == "runtime_settings" and target.name in ("overrides.json", "settings.json")) or
                       (class_name == "hook_adapter" and target.parts and target.parts[0] == "hooks"))
            try:
                with source.open("rb") as stream:
                    content = stream.read(LIMITS["comparison_file_bytes"] + 1)
            except OSError as error:
                raise SystemExit(f"comparison bundle fileを読めない: {source}") from error
            total_bytes += len(content)
            if (len(content) > LIMITS["comparison_file_bytes"] or
                    total_bytes > LIMITS["comparison_bytes"]):
                raise SystemExit("comparison bundle生成量が上限を超える")
            actual = hashlib.sha256(content).hexdigest()
            if not allowed or actual != item.get("sha256") or factor not in ("fixed", key[0]):
                raise SystemExit(f"comparison bundle file契約違反: {source}")
            files.append({"class": class_name, "source": item["source"], "target": str(target),
                          "sha256": actual, "factor": factor, "content": content})
        bundles[key] = {"files": files, "baseline_commit": row["baseline_commit"], "source_dirty": False}
    required = {(candidate, runtime, variant) for candidate in candidates for runtime in ("codex", "claude")
                for variant in ("baseline", "candidate")}
    if set(bundles) != required:
        raise SystemExit("candidate/runtime/variantごとのcomparison bundleが必要")
    for candidate in candidates:
        for runtime in ("codex", "claude"):
            before = {(row["class"], row["target"]): row for row in bundles[candidate, runtime, "baseline"]["files"]}
            after = {(row["class"], row["target"]): row for row in bundles[candidate, runtime, "candidate"]["files"]}
            if set(before) != set(after):
                raise SystemExit(f"bundle target集合が不一致: {candidate}:{runtime}")
            changed = [key for key in before if before[key]["sha256"] != after[key]["sha256"]]
            if not changed or any(before[key]["factor"] != candidate or after[key]["factor"] != candidate for key in changed):
                raise SystemExit(f"bundle差分factorが一要素でない: {candidate}:{runtime}")
            if any(before[key]["factor"] == "fixed" and before[key]["sha256"] != after[key]["sha256"] for key in before):
                raise SystemExit(f"bundle fixed条件が不一致: {candidate}:{runtime}")
            change_classes = sorted({before[key]["class"] for key in changed})
            bundles[candidate, runtime, "baseline"]["change_classes"] = change_classes
            bundles[candidate, runtime, "candidate"]["change_classes"] = change_classes
            for rows in (before.values(), after.values()):
                classes = {item["class"] for item in rows}
                if "hook_adapter" in classes and "runtime_settings" not in classes:
                    raise SystemExit(f"hook adapterの正式参照設定がない: {candidate}:{runtime}")
    return bundles


def stage_bundles(root, bundles):
    manifest = {}
    for key, source_bundle in bundles.items():
        files = source_bundle["files"]
        candidate, runtime, variant = key; staged = []
        for item in files:
            target = root / "runtime/bundles" / candidate / runtime / variant / item["target"]
            write_private_bytes(target, item["content"])
            staged.append({name: item[name] for name in ("class", "target", "sha256", "factor")})
        classes = set(source_bundle["change_classes"])
        kind = ("hook-unconfined" if "hook_adapter" in classes else
                "implementation" if "runtime_settings" in classes and
                (candidate, runtime) in RUNTIME_SETTING_ALLOWLISTS else
                "settings-unreviewed" if "runtime_settings" in classes else "instruction-only")
        identity = {"files": staged, "baseline_commit": source_bundle["baseline_commit"],
                    "source_dirty": source_bundle["source_dirty"], "change_classes": sorted(classes)}
        manifest[":".join(key)] = {**identity, "bundle_hash": digest(identity), "evaluation_kind": kind}
    return manifest


def runtime_binary(raw, runtime):
    path = Path(raw)
    try:
        real = path.resolve(strict=True)
    except OSError as error:
        raise SystemExit(f"{runtime}実行fileを解決できない") from error
    if not path.is_absolute() or not real.is_file() or real.is_symlink() or not os.access(real, os.X_OK):
        raise SystemExit(f"{runtime}実行fileは実行可能なabsolute realpathに限定する")
    row = {"path": str(real), "sha256": hashlib.sha256(real.read_bytes()).hexdigest()}
    try:
        with real.open("rb") as stream:
            shebang = stream.readline(128).decode("ascii")
    except (OSError, UnicodeDecodeError):
        shebang = ""
    if shebang.strip() == "#!/usr/bin/env node":
        selected = shutil.which("node")
        if not selected:
            raise SystemExit(f"{runtime}のNode interpreterを解決できない")
        node = Path(selected).resolve(strict=True)
        if not node.is_absolute() or not node.is_file() or node.is_symlink() or not os.access(node, os.X_OK):
            raise SystemExit(f"{runtime}のNode interpreterが不正")
        row["interpreter"] = {"path": str(node), "sha256": hashlib.sha256(node.read_bytes()).hexdigest()}
    return row


def runtime_argv(row):
    return ([row["interpreter"]["path"]] if row.get("interpreter") else []) + [row["path"]]


def verify_runtime_binaries(manifest):
    for runtime, row in manifest["runtime_binaries"].items():
        if runtime_binary(row["path"], runtime) != row:
            raise SystemExit(f"{runtime}実行file変更後は新しいrootを準備する")
    for name, tool in (manifest.get("fixture_tools") or {}).items():
        if tool.get("state") == "observed" and runtime_binary(tool["binary"]["path"], name) != tool["binary"]:
            raise SystemExit(f"{name}変更後は新しいrootを準備する")
    python = (manifest.get("fixture_tools") or {}).get("python_cli") or {}
    if python.get("state") != "observed" or runtime_binary(sys.executable, "python_cli") != python.get("binary"):
        raise SystemExit("runner Python変更後は新しいrootを準備する")


def verify_runtime_state(root, manifest):
    verify_environment(manifest)
    path = root / "runtime/codex/home/config.toml"
    expected = manifest.get("runtime_state_hashes", {}).get("codex_config")
    if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077 or
            path.read_text(encoding="utf-8") != CODEX_CONFIG or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
        raise SystemExit("Codex permission configが準備時から変化した")
    required = (root / "runtime/codex/home", root / "runtime/codex/sqlite", root / "runtime/claude/config",
                root / "runtime/claude/home", root / "runtime/claude/home/.local/memory",
                root / "runtime/claude/home/.local/hooks/state",
                root / "runtime/claude/home/.local/hooks/suggestions",
                root / "runtime/claude/home/.local/transcripts", root / "runtime/claude/home/.local/plans",
                root / "runtime/codex/tmp", root / "runtime/claude/tmp")
    if any(item.is_symlink() or not item.is_dir() or item.stat().st_mode & 0o077 for item in required):
        raise SystemExit("専用runtime state directoryがprivateな通常directoryではない")
    marker = root / CLAUDE_MARKER
    expected_marker = manifest.get("runtime_state_hashes", {}).get("claude_marker")
    if (marker.is_symlink() or not marker.is_file() or marker.stat().st_mode & 0o077 or
            hashlib.sha256(marker.read_bytes()).hexdigest() != expected_marker):
        raise SystemExit("Claude境界markerが準備時から変化した")
    if not private_tree_ok((root / "runtime/codex", root / "runtime/claude"), 4096):
        raise SystemExit("専用runtime state treeがprivateな通常treeではない")


def make_schedule(seed, candidates):
    rows = [{"run_id": f"smoke-{runtime}", "kind": "smoke", "runtime": runtime, "order": index}
            for index, runtime in enumerate(("codex", "claude"))]
    order = 2
    for candidate in candidates:
        batch = [{"run_id": f"{candidate}-{runtime}-{variant}-{fixture['id']}-r{repeat}", "kind": "compare",
                  "candidate": candidate, "runtime": runtime, "variant": variant, "fixture": fixture["id"], "repeat": repeat}
                 for runtime in ("codex", "claude") for variant in ("baseline", "candidate")
                 for repeat in range(1, 4) for fixture in FIXTURES]
        random.Random(f"{seed}:{candidate}").shuffle(batch)
        for row in batch:
            row["order"], order = order, order + 1
        rows.extend(batch)
    return rows


def prepare(args):
    root = root_path(args.root)
    if root.exists() and any(root.iterdir()):
        raise SystemExit("既存rootは自動削除・上書きしない。新しいrun-idを使う")
    mkdir(root)
    for name in ("fixtures", "runtime", "work", "results", "logs"):
        mkdir(root / name)
    for path in (root / "runtime/codex/home", root / "runtime/codex/sqlite", root / "runtime/claude/config",
                 root / "runtime/claude/home", root / "runtime/claude/home/.local",
                 root / "runtime/claude/home/.local/memory", root / "runtime/claude/home/.local/hooks",
                 root / "runtime/claude/home/.local/hooks/state",
                 root / "runtime/claude/home/.local/hooks/suggestions",
                 root / "runtime/claude/home/.local/transcripts", root / "runtime/claude/home/.local/plans",
                 root / "runtime/codex/tmp", root / "runtime/claude/tmp"):
        mkdir(path)
    write_private(root / "runtime/codex/home/config.toml", CODEX_CONFIG)
    marker_content = "synthetic nonsecret isolation marker\n"
    write_private(root / CLAUDE_MARKER, marker_content)
    candidates = ["I03", "I04"] + (["I05"] if args.include_i05 else [])
    binaries = {"codex": runtime_binary(args.codex_bin, "codex"),
                "claude": runtime_binary(args.claude_bin, "claude")}
    tsc_bin = getattr(args, "tsc_bin", None)
    fixture_tools = {"python_cli": {"state": "observed", "binary": runtime_binary(sys.executable, "python_cli")},
                     "typescript_cli": ({"state": "observed", "binary": runtime_binary(tsc_bin, "typescript_cli")}
                                          if tsc_bin else {"state": "unsupported",
                                                           "reason": "reviewed_absolute_tsc_binary_missing"})}
    capability_evidence = load_capabilities(args.capability_evidence)
    capabilities = capability_evidence["runtimes"]
    bundles = stage_bundles(root, load_comparison_bundle(args.comparison_bundle, candidates))
    for base_fixture in FIXTURES:
        fixture = resolved_fixture(base_fixture["id"], fixture_tools)
        directory = root / "fixtures" / fixture["id"]
        mkdir(directory)
        write_json(directory / "fixture.json", {"owner": OWNER, "schema": 1, **fixture})
    rows = make_schedule(args.seed, candidates); prepared_at = now(); sources = tool_source_hashes()
    prompt_hashes = {}
    for row in rows:
        spec = resolved_fixture(row["fixture"], fixture_tools) if row["kind"] == "compare" else None
        prompt = prompt_for(row, spec, root / CLAUDE_MARKER)
        prompt_hashes[row["run_id"]] = hashlib.sha256(prompt.encode()).hexdigest()
    write_json(root / "results/manifest.json", {"owner": OWNER, "schema": 1, "prepared_at": prepared_at, "plan": PLAN,
               "schedule_seed": args.seed,
               "sampling": {runtime: {"temperature": None, "seed": None,
                            "state": "unknown", "missing_reason": "runtime_cli_not_supported"}
                            for runtime in ("codex", "claude")},
               "candidates": candidates, "limits": LIMITS,
               "capabilities": capabilities, "capability_hash": digest(capabilities),
               "capability_source": {key: capability_evidence[key] for key in ("source_path", "source_hash")},
               "comparison_bundles": bundles, "runtime_binaries": binaries, "fixture_tools": fixture_tools,
               "runtime_state_hashes": {"codex_config": hashlib.sha256(CODEX_CONFIG.encode()).hexdigest(),
                                        "claude_marker": hashlib.sha256(marker_content.encode()).hexdigest()},
               "tool_source_hashes": sources, "pricing": pricing_identity(), "environment": environment_identity(),
               "prompt_hashes": prompt_hashes,
               "fixture_hashes": {item["id"]: digest(resolved_fixture(item["id"], fixture_tools)) for item in FIXTURES}, "schedule": rows,
               "max_runs": len(rows), "source_epochs": [{"started_at": prepared_at,
               "reason": args.source_change_reason, "max_runs": len(rows), "source_hashes": sources}]})
    print(json.dumps({"prepared": True, "fixtures": 8, "scheduled_runs": len(rows), "login_checked": False,
                      "model_calls": 0}, ensure_ascii=False))
    return 0


def child_env(root, runtime, work=None):
    env = {**FIXED_ENV, "HOME": os.environ["HOME"]}
    temp = (Path(work) / ".tmp") if work else (root / "runtime" / runtime / "tmp")
    mkdir(temp); env["TMPDIR"] = str(temp)
    if runtime == "codex":
        env.update(CODEX_HOME=str(root / "runtime/codex/home"), CODEX_SQLITE_HOME=str(root / "runtime/codex/sqlite"))
    else:
        claude_home = root / "runtime/claude/home"
        env.update(CLAUDE_CONFIG_DIR=str(root / "runtime/claude/config"), CLAUDE_HOME=str(claude_home),
                   SESSION_HANDOVER_MEMORY_DIR=str(claude_home / ".local"),
                   SESSION_HANDOVER_TASK_MEMORY_ROOT=str(claude_home / ".local/memory"),
                   SESSION_HANDOVER_PLAN_ROOT=str(claude_home / ".local/plans"),
                   HOOK_OBSERVATIONS_STATE_DIR=str(claude_home / ".local/hooks/state"),
                   HOOK_OBSERVATIONS_SUGGEST_DIR=str(claude_home / ".local/hooks/suggestions"),
                   HOOK_OBSERVATIONS_TRANSCRIPT_ROOT=str(claude_home / ".local/transcripts"))
    return env


def probe(command, env, capture=False):
    try:
        done = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=20, check=False, umask=0o077)
    except (OSError, subprocess.TimeoutExpired):
        return None if capture else False
    if not capture:
        return done.returncode == 0
    line = done.stdout.decode(errors="replace").strip().splitlines()[:1]
    return line[0][:120] if done.returncode == 0 and line else None


def local_isolation_probe(root, manifest):
    work = root / "runtime/isolation-probe"; mkdir(work)
    inside = work / "inside.txt"; written = work / "written.txt"
    if not inside.exists():
        write_private(inside, "synthetic nonsecret marker\n")
    if (inside.is_symlink() or not inside.is_file() or inside.stat().st_mode & 0o077 or
            written.is_symlink() or written.exists() and (not written.is_file() or written.stat().st_mode & 0o077)):
        raise SystemExit("isolation probe markerがprivateな通常fileではない")
    source = Path(manifest["capability_source"]["source_path"])
    env = child_env(root, "codex")
    codex = runtime_argv(manifest["runtime_binaries"]["codex"])
    config_ok = probe(codex + ["exec", "--strict-config", "--help"], env)
    inside_ok = probe(codex + ["sandbox", "-P", "harness", "-C", str(work), "--", "/bin/sh", "-c",
                       'umask 077; cat inside.txt >/dev/null && printf ok > written.txt'], env)
    outside_denied = not probe(codex + ["sandbox", "-P", "harness", "-C", str(work), "--",
                                "/usr/bin/head", "-c", "1", str(source)], env)
    write_ok = written.is_file() and not written.is_symlink() and written.read_text() == "ok"
    return {"codex": {"configured": True, "supported": config_ok is True, "local_tested": True,
                       "inside_read_write": inside_ok is True and write_ok,
                       "outside_live_home_denied": outside_denied,
                       "qualified": config_ok is True and inside_ok is True and write_ok and outside_denied},
            "claude": {"configured": True, "supported": True, "local_tested": False,
                       "inside_read_write": None, "outside_live_home_denied": None, "qualified": False,
                       "missing_reason": "restricted_file_boundary_requires_authenticated_smoke"}}


def login_attested(root, manifest, runtime, observed, version):
    path = root / "results" / f"login-attestation-{runtime}.json"
    if not observed or not path.exists():
        return False
    value = read_json(path)
    return (value.get("runtime") == runtime and value.get("baseline_authenticated") is False and
            value.get("runtime_identity") == digest(manifest["runtime_binaries"][runtime]) and
            value.get("runtime_version") == version)


def attest_login(args):
    root = root_path(args.root); manifest = read_json(root / "results/manifest.json")
    verify_tool_sources(manifest); verify_runtime_binaries(manifest); verify_runtime_state(root, manifest)
    baseline = read_json(root / "results/auth-baseline.json")
    runtime = args.runtime; binary = manifest["runtime_binaries"][runtime]
    version = probe(runtime_argv(binary) + ["--version"], child_env(root, runtime), True)
    command = ["login", "status"] if runtime == "codex" else ["auth", "status"]
    authenticated = probe(runtime_argv(binary) + command, child_env(root, runtime))
    if baseline.get("authenticated", {}).get(runtime) is not False or authenticated is not True or not version:
        raise SystemExit("prepare後の未認証statusから専用loginへの遷移を確認できない")
    write_json(root / "results" / f"login-attestation-{runtime}.json",
               {"owner": OWNER, "schema": 1, "runtime": runtime, "attested_at": now(),
                "baseline_authenticated": False, "runtime_identity": digest(binary),
                "runtime_version": version, "credential_values_read": False})
    print(json.dumps({"runtime": runtime, "fresh_login_attested": True,
                      "credential_values_read": False}, ensure_ascii=False))
    return 0


def login(args):
    """親のsecret/provider envを継承せず、固定実体の公式対話loginへ置換する。"""
    root = root_path(args.root); manifest = read_json(root / "results/manifest.json")
    verify_tool_sources(manifest); verify_runtime_binaries(manifest); verify_runtime_state(root, manifest)
    baseline = read_json(root / "results/auth-baseline.json"); runtime = args.runtime
    if baseline.get("authenticated", {}).get(runtime) is not False:
        raise SystemExit("専用領域の未認証baselineがないためloginを開始できない")
    base = runtime_argv(manifest["runtime_binaries"][runtime])
    command = base + (["login"] if runtime == "codex" else ["auth", "login"])
    os.execve(command[0], command, child_env(root, runtime))


def status(args):
    root = root_path(args.root)
    manifest = read_json(root / "results/manifest.json")
    verify_tool_sources(manifest); verify_runtime_binaries(manifest); verify_runtime_state(root, manifest)
    binaries = manifest["runtime_binaries"]
    observed_auth = {"codex": probe(runtime_argv(binaries["codex"]) + ["login", "status"], child_env(root, "codex")),
                     "claude": probe(runtime_argv(binaries["claude"]) + ["auth", "status"], child_env(root, "claude"))}
    versions = {runtime: probe(runtime_argv(binary) + ["--version"], child_env(root, runtime), True)
                for runtime, binary in binaries.items()}
    isolation = local_isolation_probe(root, manifest)
    baseline_path = root / "results/auth-baseline.json"
    if not baseline_path.exists():
        write_json(baseline_path, {"owner": OWNER, "schema": 1, "checked_at": now(),
                                   "authenticated": observed_auth})
    auth = {runtime: login_attested(root, manifest, runtime, observed_auth[runtime], versions[runtime])
            for runtime in binaries}
    layout = private_tree_ok((root,), 16384)
    completed = sum((root / "results" / f"run-{row['run_id']}.json").is_file() for row in manifest["schedule"])
    value = {"owner": OWNER, "schema": 1, "checked_at": now(), "auth_observed": observed_auth,
             "auth_ready": auth, "runtime_versions": versions,
             "private_layout": layout, "completed_runs": completed,
             "scheduled_runs": manifest["max_runs"],
             "local_isolation_probe": isolation,
             "isolation_ready": {runtime: row["qualified"] for runtime, row in isolation.items()},
             "capability_states": {runtime: {name: row["state"] for name, row in entries.items()}
                                   for runtime, entries in manifest["capabilities"].items()}}
    write_json(root / "results/status.json", value)
    print(json.dumps({key: value[key] for key in ("auth_ready", "runtime_versions", "private_layout",
                                                   "completed_runs", "scheduled_runs", "isolation_ready",
                                                   "capability_states")}, ensure_ascii=False))
    return 0 if all(auth.values()) and all(versions.values()) and layout and all(row["qualified"] for row in isolation.values()) else 3


def source_matrix(manifest):
    matrix = {"tool_sources": manifest["tool_source_hashes"], "runtime_binaries": manifest["runtime_binaries"],
              "runtime_state_hashes": manifest["runtime_state_hashes"], "fixture_tools": manifest["fixture_tools"],
              "sampling": manifest["sampling"], "environment": manifest["environment"]}
    for candidate in manifest["candidates"]:
        matrix[candidate] = {runtime + "_baseline_commit": BASELINES[runtime] for runtime in BASELINES}
        for runtime in BASELINES:
            for variant in ("baseline", "candidate"):
                key = ":".join((candidate, runtime, variant))
                matrix[candidate][runtime + "_" + variant + "_bundle"] = manifest["comparison_bundles"][key]["bundle_hash"]
    return matrix


def validate_config_args(args):
    values = (args.codex_model, args.claude_model)
    if any(not isinstance(value, str) or not MODEL_ID.fullmatch(value) for value in values):
        raise SystemExit("model IDは単一行の許可文字列に限定する")
    if args.codex_effort not in EFFORTS or args.claude_effort not in EFFORTS:
        raise SystemExit("effortが許可値ではない")
    if args.codex_requested_tier not in TIERS or args.claude_requested_tier not in TIERS:
        raise SystemExit("requested tierが許可値ではない")


def lock_config(root, manifest, args, required_runtimes=("codex", "claude")):
    validate_config_args(args)
    verify_runtime_binaries(manifest); verify_runtime_state(root, manifest)
    status_value = read_json(root / "results/status.json")
    if status_value.get("private_layout") is not True or not private_tree_ok((root,), 16384):
        raise SystemExit("private layoutがstatusまたはrun境界で未確認。preflightはblocked")
    if not all(status_value["auth_ready"].get(runtime) is True for runtime in required_runtimes):
        raise SystemExit("対象runtimeの専用領域への正式loginが未確認。preflightはblocked")
    current_versions = {runtime: probe(runtime_argv(row) + ["--version"], child_env(root, runtime), True)
                        for runtime, row in manifest["runtime_binaries"].items()}
    if current_versions != status_value.get("runtime_versions"):
        raise SystemExit("status後にruntime実体またはversionが変化した。statusを再実行する")
    config = {"owner": OWNER, "schema": 1, "runtime_versions": status_value["runtime_versions"],
              "models": {"codex": args.codex_model, "claude": args.claude_model},
              "efforts": {"codex": args.codex_effort, "claude": args.claude_effort},
              "requested_tiers": {"codex": args.codex_requested_tier, "claude": args.claude_requested_tier},
              "run_timeout_seconds": LIMITS["run_seconds"],
              "runtime_binaries": manifest["runtime_binaries"], "fixture_tools": manifest["fixture_tools"],
              "source_matrix": source_matrix(manifest)}
    path = root / "results/run-config.json"
    if not path.exists():
        config["locked_at"] = now()
        write_json(path, config)
        return config
    existing = read_json(path)
    keys = ("runtime_versions", "models", "efforts", "requested_tiers", "run_timeout_seconds",
            "fixture_tools", "source_matrix")
    if {key: existing.get(key) for key in keys} != {key: config[key] for key in keys}:
        raise SystemExit("source/model/runtime変更後は既存rootを使わず、新しいrootを準備する")
    return existing


def normalized_command(command):
    if isinstance(command, list):
        argv = [str(item) for item in command]
    elif isinstance(command, str):
        try:
            argv = shlex.split(command)
        except ValueError:
            return None
    else:
        return None
    if len(argv) == 3 and Path(argv[0]).name in ("sh", "bash", "zsh") and argv[1] in ("-c", "-lc"):
        try:
            argv = shlex.split(argv[2])
        except ValueError:
            return None
    return argv if argv and len(argv) <= 64 and sum(map(len, argv)) <= 2048 else None


def record_command(seen, command, tool_id=None):
    argv = normalized_command(command)
    if argv:
        seen["commands"].append(argv)
        if tool_id:
            seen["bash_tools"][tool_id] = argv
    return argv


def observe(runtime, line, seen):
    try:
        row = json.loads(line)
    except (UnicodeDecodeError, ValueError):
        return None
    event = row.get("hook_event_name") or row.get("hookEventName")
    if isinstance(event, str) and event:
        seen["hook_events"].add(event)
    message = row.get("message") if isinstance(row.get("message"), dict) else {}
    for source in (row, message):
        for key, target in (("model", "models"), ("effort", "efforts"), ("actual_tier", "tiers"),
                            ("service_tier", "tiers")):
            if isinstance(source.get(key), str) and source[key]:
                seen[target].add(source[key])
    if event in ("PreCompact", "PostCompact"):
        seen["compact_events"] += 1
    if runtime == "codex":
        if row.get("type") == "thread.started":
            seen["session_id"] = row.get("thread_id")
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        if row.get("type") == "item.started":
            item_type = item.get("type")
            if item_type in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                seen["tool_ids"].add(item.get("id") or digest(item))
                if item_type == "command_execution":
                    record_command(seen, item.get("command"), item.get("id"))
            elif item_type not in ("agent_message", "reasoning", "todo_list", "error"):
                seen["unknown_item_types"].add(str(item_type))
                return "unknown_event_type"
        if row.get("type") in ("turn.failed", "error"):
            seen["terminal_status"] = "failure"
        elif row.get("type") in ("turn.interrupted", "interrupt"):
            seen["terminal_status"] = "interruption"
        return "event_limit" if len(seen["tool_ids"]) > LIMITS["codex_tool_events"] else None
    if row.get("permission_denials"):
        seen["rejection"] = True
        seen["terminal_status"] = "rejection"
    if row.get("session_id") or row.get("sessionId"):
        seen["session_id"] = row.get("session_id") or row.get("sessionId")
    content = message.get("content", []) if isinstance(message.get("content"), list) else []
    if row.get("type") == "assistant":
        seen["turn_ids"].add(message.get("id") or digest(message))
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                record_command(seen, (block.get("input") or {}).get("command"), block.get("id"))
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
        output = usage.get("output_tokens")
        if isinstance(output, (int, float)) and not isinstance(output, bool) and output >= 0:
            seen["usage_observed"] = True; seen["output_tokens"] += int(output)
    if row.get("type") == "result" and isinstance(row.get("modelUsage"), dict):
        outputs = [counters.get("outputTokens") for counters in row["modelUsage"].values()
                   if isinstance(counters, dict)]
        if outputs and all(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
                           for value in outputs):
            seen["session_usage_observed"] = True
            seen["session_output_tokens"] = int(sum(outputs))
    for block in content:
        if (isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error") is True and
                block.get("tool_use_id") in seen["bash_tools"]):
            seen["denied_commands"].append(seen["bash_tools"][block["tool_use_id"]])
    if row.get("type") == "result" and row.get("is_error") is True and not seen["rejection"]:
        seen["terminal_status"] = "failure"
    return ("event_limit" if len(seen["turn_ids"]) > LIMITS["claude_turns"] or
            seen["output_tokens"] > LIMITS["claude_output_tokens"] else None)


def usage_limit_reason(runtime, seen):
    if runtime == "claude" and not seen.get("usage_observed"):
        return "output_usage_unknown"
    if runtime == "claude" and seen.get("output_tokens", 0) > LIMITS["claude_output_tokens"]:
        return "event_limit"
    return None


def classify_status(process, quality):
    if quality.get("success"):
        return "success"
    if process.get("rejection") or process.get("terminal_status") == "rejection":
        return "rejection"
    if process.get("terminal_status") == "failure" or (isinstance(process.get("exit_code"), int) and
                                                         process["exit_code"] != 0):
        return "failure"
    if process.get("stop_reason") in ("unknown_event_type", "output_usage_unknown"):
        return "unknown"
    if process.get("stop_reason") or process.get("terminal_status") == "interruption":
        return "interruption"
    return "quality_failure" if process.get("exit_code") == 0 else "unknown"

def stop_group(process, absolute_deadline=None):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + LIMITS["term_grace_seconds"]
    if absolute_deadline is not None:
        deadline = min(deadline, absolute_deadline)
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except OSError:
            return
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass


def workspace_within_limits(work):
    entries, files, stack, total = [], [], [Path(work)], 0
    try:
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as iterator:
                for item in iterator:
                    if len(entries) >= LIMITS["workspace_entries"]:
                        return False, entries, files
                    path = Path(item.path); info = item.stat(follow_symlinks=False); mode = info.st_mode
                    entries.append(path)
                    if stat.S_ISLNK(mode) or mode & 0o077:
                        return False, entries, files
                    if stat.S_ISDIR(mode):
                        stack.append(path)
                    elif stat.S_ISREG(mode):
                        files.append(path); total += info.st_size
                        if (len(files) > LIMITS["workspace_files"] or
                                info.st_size > LIMITS["workspace_file_bytes"] or total > LIMITS["workspace_bytes"]):
                            return False, entries, files
                    else:
                        return False, entries, files
    except OSError:
        return False, entries, files
    return True, entries, files


def apply_child_limits(timeout):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMITS["workspace_file_bytes"], LIMITS["workspace_file_bytes"]))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    cpu = max(1, min(605, int(timeout) + 5))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))

def run_finite(command, prompt, env, stdout_path, stderr_path, runtime, timeout, cwd):
    start, process, selector, reason = time.monotonic(), None, selectors.DefaultSelector(), None
    seen = {"tool_ids": set(), "turn_ids": set(), "models": set(), "efforts": set(), "tiers": set(),
            "unknown_item_types": set(), "hook_events": set(), "commands": [], "bash_tools": {},
            "denied_commands": [], "output_tokens": 0, "usage_observed": False,
            "session_output_tokens": 0, "session_usage_observed": False, "compact_events": 0,
            "session_id": None, "rejection": False, "terminal_status": None}
    for path in (stdout_path, stderr_path):
        generated_root(path)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(descriptor)
    try:
        process = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True, umask=0o077,
                                   preexec_fn=lambda: apply_child_limits(timeout))
        try:
            process.stdin.write(prompt.encode())
        except BrokenPipeError:
            pass
        finally:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        selector.register(process.stdout, selectors.EVENT_READ); selector.register(process.stderr, selectors.EVENT_READ)
        targets = {process.stdout: stdout_path, process.stderr: stderr_path}
        caps = {process.stdout: LIMITS["stdout_bytes"], process.stderr: LIMITS["stderr_bytes"]}
        totals = {process.stdout: 0, process.stderr: 0}; stdout_buffer = b""
        absolute_deadline = start + timeout
        deadline = absolute_deadline - LIMITS["term_grace_seconds"] - min(.1, timeout / 4)
        while selector.get_map() and not reason:
            if time.monotonic() >= deadline:
                reason = "timeout"; break
            if not workspace_within_limits(cwd)[0]:
                reason = "workspace_limit"; break
            for key, _ in selector.select(0.1):
                stream = key.fileobj; chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    selector.unregister(stream); continue
                remaining = caps[stream] - totals[stream]
                if remaining > 0:
                    with targets[stream].open("ab") as target:
                        target.write(chunk[:remaining])
                    totals[stream] += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    reason = "output_limit"; break
                if stream is process.stdout:
                    stdout_buffer += chunk
                    if len(stdout_buffer) > LIMITS["line_bytes"]:
                        reason = "line_limit"; break
                    lines = stdout_buffer.split(b"\n"); stdout_buffer = lines.pop()
                    event_reasons = [observe(runtime, line, seen) for line in lines if line]
                    if any(event_reasons):
                        reason = next(item for item in event_reasons if item); break
        if not reason and stdout_buffer:
            reason = observe(runtime, stdout_buffer, seen)
        if not reason:
            reason = usage_limit_reason(runtime, seen)
        if reason:
            stop_group(process, absolute_deadline)
        try:
            exit_code = process.wait(timeout=max(0, absolute_deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            exit_code = process.wait(timeout=max(.01, absolute_deadline - time.monotonic()))
    except BaseException:
        if process is not None:
            stop_group(process, start + timeout)
        raise
    finally:
        selector.close()
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            stop_group(process, start + timeout)
            if process.poll() is None:
                try:
                    process.wait(timeout=max(.01, start + timeout - time.monotonic()))
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
    return {"exit_code": exit_code, "stop_reason": reason, "session_id": seen["session_id"],
            "tool_events": len(seen["tool_ids"]), "turns": len(seen["turn_ids"]),
            "output_tokens": seen["output_tokens"], "compact_events": seen["compact_events"],
            "session_output_tokens": seen["session_output_tokens"],
            "stdout_bytes": totals[process.stdout], "stderr_bytes": totals[process.stderr],
            "rejection": seen["rejection"], "terminal_status": seen["terminal_status"],
            "effective_model": next(iter(seen["models"])) if len(seen["models"]) == 1 else None,
            "effective_effort": next(iter(seen["efforts"])) if len(seen["efforts"]) == 1 else None,
            "observed_models": sorted(seen["models"]), "observed_efforts": sorted(seen["efforts"]),
            "actual_tier": next(iter(seen["tiers"])) if len(seen["tiers"]) == 1 else None,
            "hook_events": sorted(seen["hook_events"]), "commands": seen["commands"],
            "denied_commands": seen["denied_commands"],
            "unknown_item_types": sorted(seen["unknown_item_types"]),
            "elapsed_seconds": round(time.monotonic() - start, 3)}


def resolved_fixture(fixture_id, fixture_tools=None):
    source = next(item for item in FIXTURES if item["id"] == fixture_id)
    value = json.loads(json.dumps(source))
    if value["id"] == "cli_quiet_retrieve":
        quiet = Path(__file__).with_name("quiet-run.py")
        if quiet.is_symlink() or not quiet.is_file():
            raise SystemExit("quiet-run sourceが通常fileではない")
        value["files"]["quiet-run.py"] = quiet.read_text(encoding="utf-8")
    tools = fixture_tools or {}
    python = ((tools.get("python_cli") or {}).get("binary") or {}).get("path", sys.executable)
    value["instruction"] = value["instruction"].replace("python3", python)
    value["required_commands"] = [[python if part == "python3" else part for part in command]
                                  for command in value.get("required_commands", [])]
    if value["id"] == "repo_tsc_once":
        tool = tools.get("typescript_cli") or {}
        command_prefix = (runtime_argv(tool["binary"]) if tool.get("state") == "observed" else ["{tsc}"])
        value["instruction"] = value["instruction"].replace("{tsc}", shlex.join(command_prefix))
        value["required_commands"] = [command_prefix + command[1:] for command in value["required_commands"]]
    return value


def fixture(fixture_id, manifest=None):
    return resolved_fixture(fixture_id, (manifest or {}).get("fixture_tools"))


def materialize(root, row, manifest=None):
    work = root / "work" / row["run_id"]; mkdir(work)
    mkdir(work / ".tmp")
    for relative, content in fixture(row["fixture"], manifest)["files"].items():
        target = work / relative; mkdir(target.parent)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
    return work


def materialize_smoke(root, row):
    work = root / "work" / row["run_id"]; mkdir(work)
    mkdir(work / ".tmp")
    write_private(work / "inside.txt", "synthetic nonsecret marker\n")
    return work


def materialize_bundle(root, row, work, manifest):
    key = ":".join((row["candidate"], row["runtime"], row["variant"]))
    bundle = manifest["comparison_bundles"][key]; controls = {}
    for item in bundle["files"]:
        source = root / "runtime/bundles" / row["candidate"] / row["runtime"] / row["variant"] / item["target"]
        if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit(f"staged comparison bundleが変化した: {key}:{item['target']}")
        relative = Path(item["target"]) if item["class"] == "workspace_instruction" else Path(".runtime-bundle") / item["target"]
        target = work / relative
        if target.exists() or target.is_symlink():
            raise SystemExit(f"fixtureとcomparison bundleが衝突: {relative}")
        write_private_bytes(target, source.read_bytes()); controls[str(relative)] = item["sha256"]
    runtime_settings = [work / ".runtime-bundle" / item["target"] for item in bundle["files"]
                        if item["class"] == "runtime_settings"]
    if len(runtime_settings) > 1:
        raise SystemExit(f"runtime settingsが複数: {key}")
    return {"bundle_hash": bundle["bundle_hash"], "control_hashes": controls,
            "runtime_settings": str(runtime_settings[0]) if runtime_settings else None,
            "evaluation_kind": bundle["evaluation_kind"], "candidate": row["candidate"]}


def same_content(path, expected):
    if path.is_symlink() or not path.is_file():
        return False
    actual = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            return json.loads(actual) == json.loads(expected)
        except ValueError:
            return False
    return actual == expected


def python_quality(path, fixture_id):
    if path.is_symlink() or not path.is_file():
        return False
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.BinOp, ast.Add,
               ast.Name, ast.Load, ast.Call, ast.Attribute)
    if any(not isinstance(node, allowed) or isinstance(node, ast.Attribute) and node.attr not in ("strip", "lower")
           for node in ast.walk(tree)):
        return False
    namespace = {"__builtins__": {}}
    try:
        exec(compile(tree, str(path), "exec"), namespace)
        if fixture_id == "repo_add":
            return [namespace["add"](*case) for case in ((2, 3), (-1, 2), (0, 0))] == [5, 1, 0]
        return [namespace["normalize"](case) for case in (" Alice ", "BOB", " x Y ")] == ["alice", "bob", "x y"]
    except (KeyError, TypeError, ValueError):
        return False


def score(work, spec, process, controls=None):
    controls = controls or {}
    workspace_within_limit, entries, files = workspace_within_limits(work)
    tests = {name: (python_quality(work / name, spec["id"]) if workspace_within_limit and name.endswith(".py") else
                    same_content(work / name, expected) if workspace_within_limit else False)
             for name, expected in spec["expected"].items()}
    observed = [normalized_command(command) for command in process.get("commands", [])]
    observed = [command for command in observed if command]
    required = spec.get("required_commands", [])
    command_counts = {" ".join(command): sum(command == item for item in observed) for command in required}
    commands_exactly_once = all(count == 1 for count in command_counts.values())
    allowed = set(spec["files"]) | set(spec["expected"])
    actual = {str(path.relative_to(work)) for path in files if str(path.relative_to(work)) not in controls}
    dynamic = {name for name in actual for pattern in spec.get("dynamic_outputs", []) if Path(name).match(pattern)}
    protected = {name: workspace_within_limit and not (work / name).is_symlink() and (work / name).is_file() and
                 (work / name).read_text(encoding="utf-8") == content
                 for name, content in spec["files"].items() if name not in spec["expected"]}
    no_symlinks = not any(path.is_symlink() for path in entries)
    control_hashes_after = {name: (hashlib.sha256((work / name).read_bytes()).hexdigest()
                                   if workspace_within_limit and not (work / name).is_symlink() and
                                   (work / name).is_file() else None) for name in controls}
    controls_unchanged = all(control_hashes_after[name] == expected for name, expected in controls.items())
    dynamic_ok = True
    if spec["id"] == "cli_quiet_retrieve":
        logs = [path for path in files if Path(str(path.relative_to(work))).match(".quiet-logs/quiet-*.log")]
        dynamic_ok = len(logs) == 1 and logs[0].stat().st_size > 16000
    gate = (workspace_within_limit and actual - dynamic <= allowed and dynamic_ok and no_symlinks and
            all(protected.values()) and controls_unchanged and commands_exactly_once)
    restore = True
    if spec.get("restore_keys"):
        restore_path = work / "restore.json"
        try:
            if not workspace_within_limit or restore_path.is_symlink():
                raise OSError("unsafe workspace")
            restored = json.loads(restore_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            restored = {}
        restore = restored == json.loads(spec["expected"]["restore.json"])
    native = spec.get("native") != "compact" or process["compact_events"] > 0
    success = process["exit_code"] == 0 and not process["stop_reason"] and all(tests.values()) and gate and restore and native
    return {"tests": tests, "protected_inputs": protected, "control_files_unchanged": controls_unchanged,
            "control_hashes_after": control_hashes_after, "no_symlinks": no_symlinks,
            "workspace_within_limit": workspace_within_limit, "command_counts": command_counts,
            "dynamic_output_valid": dynamic_ok, "gate": gate, "restore": restore, "native": native,
            "success": success}

def claude_smoke_commands(root):
    return [["/bin/sh", "-c", "cat inside.txt >/dev/null && printf ok > inside-written.txt"],
            ["/usr/bin/head", "-c", "1", str(root / CLAUDE_MARKER)],
            ["/usr/bin/head", "-c", "1", str(root / "runtime/codex/home/config.toml")],
            ["/bin/sh", "-c", f"printf blocked > {shlex.quote(str(LIVE_HOME_WRITE_PROBE))}"]]


def command_for(runtime, config, work, resume, bundle, required_commands=()):
    model, effort = config["models"][runtime], config["efforts"][runtime]
    binary = runtime_argv(config["runtime_binaries"][runtime])
    if runtime == "codex":
        base = binary + ["exec", "--strict-config", "--json", "--model", model,
                "--config", f'model_reasoning_effort="{effort}"', "--cd", str(work), "--skip-git-repo-check"]
        if bundle["runtime_settings"]:
            if (bundle.get("candidate"), runtime) not in RUNTIME_SETTING_ALLOWLISTS:
                raise SystemExit("Codex runtime settingのreview済みallowlistがない")
            try:
                overrides = json.loads(Path(bundle["runtime_settings"]).read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise SystemExit("Codex overrides.jsonを読めない") from error
            if not isinstance(overrides, dict) or any(re.search(r"(?:auth|credential|model|effort|sandbox|approval|provider|permission|network|env|home|path|shell|preload|config.?dir|cache|tmp|proxy|hook|command|tool)", key, re.I)
                                                      for key in nested_keys(overrides)):
                raise SystemExit("Codex runtime override keyが許可外")
            for key, value in sorted(overrides.items()):
                base += ["--config", f"{key}={json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"]
        return base + (["resume", resume, "-"] if resume else ["-"])
    settings = {}
    if bundle["runtime_settings"]:
        if (bundle.get("candidate"), runtime) not in RUNTIME_SETTING_ALLOWLISTS:
            raise SystemExit("Claude runtime settingのreview済みallowlistがない")
        try:
            settings = json.loads(Path(bundle["runtime_settings"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise SystemExit("Claude settings.jsonを読めない") from error
        forbidden = re.compile(r"(?:auth|credential|token|api.?key|env|home|path|shell|preload|config.?dir|cache|tmp|proxy|network|model|effort|sandbox|permission|mcp|hook|command|tool)", re.I)
        if not isinstance(settings, dict) or any(forbidden.search(key) for key in nested_keys(settings)):
            raise SystemExit("Claude runtime setting keyが許可外")
    root = generated_root(work)
    denied = [root / "runtime", root / "results", root / "logs", root / "fixtures", root / "work"]
    filesystem = {"denyRead": ["~/", *(str(path) for path in denied)],
                  "allowRead": [str(work)],
                  "denyWrite": ["~/", *(str(path) for path in denied)],
                  "allowWrite": [str(work)]}
    settings = {**settings, **CLAUDE_SAFETY}
    settings["sandbox"] = {**settings["sandbox"], "filesystem": filesystem}
    allowed = ["Read", "Edit", "Write", "Glob", "Grep"]
    allowed += [f"Bash({shlex.join(command)})" for command in required_commands]
    base = binary + ["--print", "--restricted", "--tools", "Bash,Read,Edit,Write,Glob,Grep", "--strict-mcp-config",
            "--mcp-config", '{"mcpServers":{}}', "--output-format", "stream-json", "--verbose", "--include-hook-events",
            "--model", model, "--effort", effort, "--max-turns", str(LIMITS["claude_turns"]),
            "--permission-mode", "dontAsk", "--allowedTools", ",".join(allowed),
            "--settings", json.dumps(settings, separators=(",", ":"))]
    return base + (["--resume", resume] if resume else [])


def prompt_for(row, spec, outside_marker=None):
    if row["kind"] == "smoke" and row["runtime"] == "claude":
        commands = [shlex.join(command) for command in claude_smoke_commands(generated_root(outside_marker))]
        return ("境界検証専用の合成fixtureです。Bashで次の4 commandを順に各1回、そのまま実行する。"
                f"最初に {commands[0]} 。続けて {commands[1]} 、{commands[2]} 、{commands[3]} 。"
                "後の3件の拒否を回避せず、結果を短く返す。")
    if row["kind"] == "smoke":
        return '合成fixtureの接続確認です。編集や外部アクセスをせず、{"ok":true}だけを返してください。'
    return f"隔離した合成fixtureです。外部通信、認証操作、commit、削除を行わない。{spec['instruction']}"


def smoke_quality(root, row, work, process, manifest):
    if row["runtime"] == "codex":
        local = read_json(root / "results/status.json")["local_isolation_probe"]["codex"]
        boundary = local.get("qualified") is True
    else:
        wrapped_inside, *outside = claude_smoke_commands(root)
        inside = normalized_command(shlex.join(wrapped_inside))
        denied = [normalized_command(shlex.join(command)) for command in outside]
        boundary = (all(sum(command == expected for command in process.get("denied_commands", [])) == 1
                        for expected in denied) and
                    sum(command == inside for command in process.get("commands", [])) == 1 and
                    not LIVE_HOME_WRITE_PROBE.exists() and
                    (work / "inside-written.txt").is_file() and not (work / "inside-written.txt").is_symlink() and
                    not ((work / "inside-written.txt").stat().st_mode & 0o077) and
                    (work / "inside-written.txt").read_text(encoding="utf-8") == "ok")
    return {"boundary_isolation": boundary,
            "success": process["exit_code"] == 0 and not process["stop_reason"] and boundary}


def metrics(root, row, config, stdout, session, status_name, process, timeout=120):
    if not session:
        return {"comparison_qualified": False, "missing_reason": "session_id_unavailable"}
    if timeout <= 0:
        return {"comparison_qualified": False, "missing_reason": "run_deadline_exhausted"}
    children = "no" if row["runtime"] == "claude" else "unknown"
    python = runtime_argv(config["fixture_tools"]["python_cli"]["binary"])
    command = python + [str(Path(__file__).with_name("session-metrics.py")), "metrics", "--transcript", str(stdout),
               "--session-id", session, "--run-id", row["run_id"], "--task-id", row.get("fixture", "smoke"),
               "--status", status_name, "--includes-children", children, "--runtime-version", config["runtime_versions"][row["runtime"]]]
    identity = process.get("runtime_identity") or {}
    if (identity.get("model") or {}).get("confirmed") is True:
        command += ["--model", identity["model"]["value"]]
    if process.get("actual_tier"):
        command += ["--actual-tier", process["actual_tier"]]
    tier = config["requested_tiers"].get(row["runtime"])
    if tier:
        command += ["--requested-tier", tier]
    try:
        done = subprocess.run(command, env=child_env(root, row["runtime"]), capture_output=True, text=True,
                              timeout=min(120, timeout), check=False, umask=0o077)
    except (OSError, subprocess.TimeoutExpired):
        return {"comparison_qualified": False, "missing_reason": "metrics_failed"}
    if done.returncode:
        return {"comparison_qualified": False, "missing_reason": "metrics_failed", "exit_code": done.returncode}
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"comparison_qualified": False, "missing_reason": "metrics_invalid_json"}


def confirm_runtime_identity(runtime, process, config):
    def field(name, argv_allowed):
        requested = config[name + "s"][runtime]
        observed = process.get("observed_" + name + "s")
        if observed is None:
            single = process.get("effective_" + name)
            observed = [single] if single else []
        observed = sorted(set(observed))
        if len(observed) == 1:
            return {"value": observed[0], "source": "runtime_event", "confirmed": observed[0] == requested}
        if len(observed) > 1:
            return {"value": None, "source": "runtime_event_conflict", "confirmed": False}
        return {"value": requested if argv_allowed else None,
                "source": "locked_exact_argv" if argv_allowed else "runtime_event_missing",
                "confirmed": argv_allowed}
    model = field("model", runtime == "codex")
    effort = field("effort", True)
    return {"model": model, "effort": effort, "confirmed": model["confirmed"] and effort["confirmed"]}


def dependency(root, row, config, manifest):
    if row.get("fixture") != "long_resume":
        return None, None
    run_id = row["run_id"].replace("long_resume", "long_compact")
    path = root / "results" / f"run-{run_id}.json"
    if not path.exists():
        return "pending", None
    value = read_json(path)
    predecessor = value.get("run", {})
    identity = all(predecessor.get(key) == row.get(key) for key in ("candidate", "runtime", "variant", "repeat"))
    session = value.get("process", {}).get("session_id")
    measured = value.get("metrics", {}).get("session_id")
    bundle_key = ":".join((row["candidate"], row["runtime"], row["variant"]))
    bundle_matches = value.get("bundle", {}).get("bundle_hash") == manifest["comparison_bundles"][bundle_key]["bundle_hash"]
    valid = (identity and predecessor.get("fixture") == "long_compact" and value.get("status") == "success" and
             value.get("config_hash") == digest(config) and value.get("quality", {}).get("native") is True and
             value.get("quality", {}).get("success") is True and bundle_matches and
             isinstance(session, str) and session and measured == session)
    return (session, None) if valid else ("missing", None)


def claim_run(path, result_path, row):
    generated_root(path); payload = {"owner": OWNER, "schema": 1, "run_id": row["run_id"],
                                     "pid": os.getpid(), "started_at": now()}
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if result_path.exists() and read_json(result_path).get("completed"):
            return "completed"
        existing = read_json(path); pid = existing.get("pid")
        try:
            if isinstance(pid, int) and pid > 0:
                os.kill(pid, 0); return "active"
        except OSError:
            pass
        return "stale"
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True); stream.write("\n")
    return "claimed"


def run_one(root, row, config, manifest, timeout):
    run_started = time.monotonic()
    result_path = root / "results" / f"run-{row['run_id']}.json"
    if result_path.exists() and read_json(result_path).get("completed"):
        return True
    started = root / "results" / f"started-{row['run_id']}.json"
    session, _ = dependency(root, row, config, manifest)
    if session == "pending":
        return False
    if session == "missing":
        write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "run": row,
                                 "status": "unknown", "missing_reason": "resume_session_unavailable"})
        return True
    state = claim_run(started, result_path, row)
    if state == "completed":
        return True
    if state == "active":
        raise SystemExit(f"runは別processが実行中: {row['run_id']}")
    if state == "stale":
        write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "run": row,
                                 "status": "interruption", "missing_reason": "previous_process_interrupted"})
        return True
    try:
        verify_runtime_binaries(manifest); verify_runtime_state(root, manifest)
        binary = manifest["runtime_binaries"][row["runtime"]]
        if probe(runtime_argv(binary) + ["--version"], child_env(root, row["runtime"]), True) != config["runtime_versions"][row["runtime"]]:
            raise SystemExit(f"{row['runtime']}実体またはversionがrun境界で変化した")
    except SystemExit:
        write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "run": row,
                                 "status": "unknown", "missing_reason": "prelaunch_validation_failed"})
        raise
    work = materialize(root, row, manifest) if row["kind"] == "compare" else materialize_smoke(root, row)
    bundle = (materialize_bundle(root, row, work, manifest) if row["kind"] == "compare" else
              {"bundle_hash": None, "control_hashes": {}, "runtime_settings": None, "evaluation_kind": "smoke"})
    stdout = root / "logs" / f"{row['run_id']}.jsonl"; stderr = root / "logs" / f"{row['run_id']}.stderr.log"
    spec = fixture(row["fixture"], manifest) if row["kind"] == "compare" else None
    try:
        required = (spec.get("required_commands", []) if spec else
                    claude_smoke_commands(root) if row["runtime"] == "claude" else [])
        command = command_for(row["runtime"], config, work,
                              session if row.get("fixture") == "long_resume" else None, bundle, required)
    except SystemExit:
        write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "run": row,
                                 "status": "unknown", "missing_reason": "runtime_settings_invalid"})
        return True
    try:
        process_timeout = timeout - (time.monotonic() - run_started)
        if process_timeout <= 0:
            raise subprocess.TimeoutExpired("run setup", timeout)
        prompt = prompt_for(row, spec, root / CLAUDE_MARKER)
        if hashlib.sha256(prompt.encode()).hexdigest() != manifest["prompt_hashes"].get(row["run_id"]):
            raise SystemExit("promptが準備時から変化した")
        process = run_finite(command, prompt, child_env(root, row["runtime"], work), stdout, stderr,
                             row["runtime"], process_timeout, work)
    except (OSError, subprocess.TimeoutExpired) as error:
        process = {"exit_code": None, "stop_reason": "timeout" if isinstance(error, subprocess.TimeoutExpired) else None,
                   "session_id": None, "tool_events": 0,
                   "turns": 0, "output_tokens": 0, "compact_events": 0, "rejection": False,
                   "terminal_status": None, "effective_model": None, "effective_effort": None,
                   "observed_models": [], "observed_efforts": [],
                   "actual_tier": None, "hook_events": [], "commands": [], "denied_commands": [],
                   "unknown_item_types": [],
                   "launch_error": type(error).__name__}
    quality = (score(work, spec, process, bundle["control_hashes"]) if spec else
               smoke_quality(root, row, work, process, manifest))
    process["resume_used"] = bool(session and row.get("fixture") == "long_resume")
    process["runtime_identity"] = confirm_runtime_identity(row["runtime"], process, config)
    quality["runtime_effective"] = process["runtime_identity"]["confirmed"]
    quality["success"] = quality["success"] and quality["runtime_effective"]
    status_name = classify_status(process, quality)
    metric_status = "failure" if status_name == "quality_failure" else status_name
    remaining = timeout - (time.monotonic() - run_started)
    measurement = metrics(root, row, config, stdout, process["session_id"], metric_status, process, remaining)
    write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "completed_at": now(), "run": row,
                             "status": status_name, "config_hash": digest(config), "process": process,
                             "configured_timeout_seconds": config["run_timeout_seconds"],
                             "config_epoch": config["locked_at"],
                             "bundle": {"bundle_hash": bundle["bundle_hash"], "evaluation_kind": bundle["evaluation_kind"],
                                        "source_hashes_before": bundle["control_hashes"],
                                        "source_hashes_after": quality.get("control_hashes_after", {})},
                             "quality": quality, "metrics": measurement,
                             "lifecycle": {"configured": True,
                                           "fired": (fired := bool(process["hook_events"])),
                                           "local_tested": True,
                                           "effective": (effective := quality["success"] and fired and
                                                         bundle["evaluation_kind"] in
                                                         EFFECT_EVIDENCE_ADAPTERS[row["runtime"]]),
                                           "effect_missing_reason": (None if effective else
                                               "candidate_specific_native_effect_not_observed"),
                                           "adopted": False}})
    return True


def metric_ready(metric, name):
    coverage = (metric.get("coverage") or {}).get(name) or {}
    expected_scope = "main" if name in ("tool_calls", "outcome") else "parent_claim"
    field_ready = coverage.get("qualified") is True and coverage.get("scope") == expected_scope
    return field_ready and (name != "cost" or metric.get("comparison_qualified") is True)


def comparison_blockers(root):
    blockers = []
    for runtime in ("codex", "claude"):
        path = root / "results" / f"run-smoke-{runtime}.json"
        if not path.exists():
            blockers.append(f"{runtime}:smoke_missing"); continue
        smoke = read_json(path); metric = smoke.get("metrics", {})
        identity = smoke.get("process", {}).get("runtime_identity") or {}
        if smoke.get("status") != "success":
            blockers.append(f"{runtime}:smoke_failed")
        if smoke.get("quality", {}).get("boundary_isolation") is not True:
            blockers.append(f"{runtime}:boundary_isolation_unverified")
        if (identity.get("model") or {}).get("confirmed") is not True or \
                metric.get("model") != (identity.get("model") or {}).get("value"):
            blockers.append(f"{runtime}:model_unknown")
        if (identity.get("effort") or {}).get("confirmed") is not True:
            blockers.append(f"{runtime}:effort_unknown_or_mismatch")
        if not metric_ready(metric, "usage"):
            blockers.append(f"{runtime}:usage_or_scope_unqualified")
    return blockers


def capability_blockers(root, manifest, include_native, candidate=None, smoke_runtime=None):
    status_value = read_json(root / "results/status.json"); blockers = []
    runtimes = ("codex", "claude") if include_native else (smoke_runtime,)
    for runtime in runtimes:
        local = (status_value.get("local_isolation_probe", {}).get(runtime) or {})
        if runtime == "codex" and local.get("qualified") is not True:
            blockers.append("codex:live_home_read_isolation_local_probe_unqualified")
        if runtime == "claude" and not include_native and not (local.get("configured") and local.get("supported")):
            blockers.append("claude:boundary_smoke_not_configured_or_supported")
        if runtime == "claude" and LIVE_HOME_WRITE_PROBE.exists():
            blockers.append("claude:live_home_write_probe_path_exists")
        names = ("compact", "resume") if include_native else ()
        for name in names:
            row = manifest["capabilities"][runtime][name]
            if row["state"] != "observed":
                blockers.append(f"{runtime}:{name}_{row['state']}")
            if row["trigger_method"] not in NATIVE_TRIGGER_ADAPTERS[runtime]:
                blockers.append(f"{runtime}:{name}_trigger_adapter_missing")
            if status_value["runtime_versions"].get(runtime) != row["runtime_version"]:
                blockers.append(f"{runtime}:{name}_version_mismatch")
        live = manifest["capabilities"][runtime]["live_home_read_isolation"]
        if status_value["runtime_versions"].get(runtime) != live["runtime_version"]:
            blockers.append(f"{runtime}:live_home_read_isolation_version_mismatch")
        if include_native:
            kinds = {manifest["comparison_bundles"][":".join((candidate, runtime, variant))]["evaluation_kind"]
                     for variant in ("baseline", "candidate")}
            if kinds != {"implementation"}:
                blockers.append(f"{candidate}:{runtime}:config_bundle_" + "+".join(sorted(kinds)))
    if include_native and manifest["fixture_tools"]["typescript_cli"]["state"] != "observed":
        blockers.append("fixture:repo_tsc_once:typescript_cli_unsupported")
    return blockers


def adoption_eligible(baseline, candidate, pairs):
    metrics = ("usage", "tool_calls", "outcome", "cost")
    coverage = lambda group: all((group.get("coverage", {}).get(name) or {}).get("complete") is True
                                 for name in metrics)
    return bool(candidate.get("candidate_effect_observed") and candidate.get("complete") and
                coverage(baseline) and coverage(candidate) and
                candidate.get("successes", 0) >= baseline.get("successes", 0) and
                candidate.get("successes") == candidate.get("expected_runs") and
                candidate.get("required_quality_complete") is True and len(pairs) == 24 and
                all(pair.get("complete") and all((pair.get("paired_qualified") or {}).get(name) is True
                                                  for name in metrics) for pair in pairs))


def budget_deadline(root):
    path = root / "results/budget.json"
    if path.exists():
        return read_json(path)["deadline_epoch"]
    started = time.time(); deadline = started + LIMITS["total_seconds"]
    write_json(path, {"owner": OWNER, "schema": 1, "started_epoch": started,
                      "deadline_epoch": deadline, "limit_seconds": LIMITS["total_seconds"]})
    return deadline


def executable_window(requested, remaining):
    reserve = 2 * LIMITS["term_grace_seconds"] + 1
    return requested if requested > reserve and remaining >= requested + reserve else None


def scheduled_complete(root, row):
    path = root / "results" / f"run-{row['run_id']}.json"
    if not path.exists():
        return False
    value = read_json(path)
    return value.get("completed") is True and value.get("run") == row


def run(args):
    root = root_path(args.root)
    manifest = read_json(root / "results/manifest.json")
    verify_tool_sources(manifest)
    if args.smoke_only and not args.smoke_runtime:
        raise SystemExit("--smoke-onlyには--smoke-runtimeを1件指定する")
    if not args.smoke_only and args.smoke_runtime:
        raise SystemExit("--smoke-runtimeは--smoke-only専用")
    config = lock_config(root, manifest, args,
                         (args.smoke_runtime,) if args.smoke_only else ("codex", "claude"))
    if not args.smoke_only and args.candidate not in manifest["candidates"]:
        raise SystemExit("比較runはmanifest内の--candidateを1件指定する")
    capability_failures = capability_blockers(root, manifest, not args.smoke_only, args.candidate,
                                               args.smoke_runtime)
    if capability_failures:
        raise SystemExit("runtime capability未確認: " + ",".join(capability_failures))
    rows = [row for row in manifest["schedule"] if row["kind"] == ("smoke" if args.smoke_only else "compare") and
            ((args.smoke_only and row["runtime"] == args.smoke_runtime) or
             (not args.smoke_only and row.get("candidate") == args.candidate))]
    if not args.smoke_only:
        index = manifest["candidates"].index(args.candidate)
        previous = set(manifest["candidates"][:index])
        unfinished = [row["run_id"] for row in manifest["schedule"]
                      if row.get("candidate") in previous and not scheduled_complete(root, row)]
        if unfinished:
            raise SystemExit(f"candidate順序未達: {manifest['candidates'][index - 1]}を先に完了する")
        blockers = comparison_blockers(root)
        if blockers:
            raise SystemExit("比較開始条件未達: " + ",".join(blockers))
    deadline = budget_deadline(root)
    pending = list(rows)
    while pending and time.time() < deadline:
        progress = False
        for row in list(pending):
            remaining = deadline - time.time()
            timeout = executable_window(config["run_timeout_seconds"], remaining)
            if timeout is None:
                break
            if run_one(root, row, config, manifest, timeout):
                pending.remove(row); progress = True
        if not progress:
            break
    print(json.dumps({"completed": len(rows) - len(pending), "pending": len(pending), "retry": 0,
                      "candidate": args.candidate, "comparison_started": not args.smoke_only}, ensure_ascii=False))
    return 0 if not pending else 4


def metric_pricing(metric):
    version, currency = metric.get("pricing_version"), metric.get("currency")
    return (version, currency) if isinstance(version, str) and isinstance(currency, str) else None


def median_range(series, qualified):
    series = sorted(series)
    if not qualified or not series:
        return {"observed": len(series), "median": None, "range": None}
    middle = len(series) // 2
    median = series[middle] if len(series) % 2 else (series[middle - 1] + series[middle]) / 2
    return {"observed": len(series), "median": median, "range": [series[0], series[-1]]}


def report(args):
    root = root_path(args.root); manifest = read_json(root / "results/manifest.json")
    verify_tool_sources(manifest)
    expected = {row["run_id"]: row for row in manifest["schedule"]}; records = {}
    for run_id, expected_row in expected.items():
        path = root / "results" / f"run-{run_id}.json"
        if path.exists():
            record = read_json(path)
            if record.get("run") != expected_row:
                raise SystemExit(f"run identityがmanifestと不一致: {run_id}")
            records[run_id] = record
    metric_names = ("usage", "tool_calls", "outcome", "cost")
    statuses = ("success", "quality_failure", "rejection", "interruption", "failure", "unknown")

    def value_of(record, name):
        metric = record.get("metrics", {})
        if name == "input_tokens":
            return (metric.get("tokens") or {}).get("input_total", (metric.get("tokens") or {}).get("input_tokens"))
        if name == "tool_calls":
            return (metric.get("tool_calls") or {}).get("total")
        if name == "cost_usd":
            return metric.get("estimated_usd_with_subagents")
        return (record.get("process") or {}).get("elapsed_seconds")

    pairs = []
    for candidate in manifest["candidates"]:
        for runtime in ("codex", "claude"):
            for spec in FIXTURES:
                for repeat in range(1, 4):
                    pair = {variant: records.get(f"{candidate}-{runtime}-{variant}-{spec['id']}-r{repeat}")
                            for variant in ("baseline", "candidate")}
                    item = {"pair_id": f"{candidate}:{runtime}:{spec['id']}:r{repeat}", "candidate": candidate,
                            "runtime": runtime, "fixture": spec["id"], "task_group": spec["group"],
                            "repeat": repeat, "complete": all(pair.values())}
                    for variant, record in pair.items():
                        if not record:
                            item[variant] = None; continue
                        metric = record.get("metrics", {})
                        item[variant] = {"run_id": record["run"]["run_id"], "status": record.get("status"),
                            "quality_success": record.get("quality", {}).get("success") is True,
                            "runtime_identity": (record.get("process") or {}).get("runtime_identity"),
                            "qualified": {name: metric_ready(metric, name) for name in metric_names},
                            "values": {name: value_of(record, name) for name in
                                       ("input_tokens", "tool_calls", "cost_usd", "elapsed_seconds")}}
                    expected_pricing = (manifest["pricing"]["version"], manifest["pricing"]["currency"])
                    pricing_compatible = bool(item["complete"] and
                        all(metric_pricing(pair[v].get("metrics", {})) == expected_pricing
                            for v in ("baseline", "candidate")))
                    item["pricing_compatible"] = pricing_compatible
                    item["paired_qualified"] = {name: bool(item["complete"] and
                                                       all(item[v]["qualified"][name] for v in ("baseline", "candidate")) and
                                                       (name != "cost" or pricing_compatible) and
                                                       (name == "outcome" or all(item[v]["qualified"]["outcome"]
                                                                                 for v in ("baseline", "candidate"))))
                                                  for name in metric_names}
                    item["deltas"] = {}
                    qualification = {"input_tokens": "usage", "tool_calls": "tool_calls", "cost_usd": "cost"}
                    for name in ("input_tokens", "tool_calls", "cost_usd", "elapsed_seconds"):
                        valid = item["complete"] and (name == "elapsed_seconds" or item["paired_qualified"][qualification[name]])
                        before = item["baseline"]["values"][name] if item["complete"] else None
                        after = item["candidate"]["values"][name] if item["complete"] else None
                        item["deltas"][name] = after - before if valid and all(isinstance(v, (int, float)) for v in (before, after)) else None
                    pairs.append(item)

    groups, fixture_summaries, task_groups = {}, {}, {}
    for candidate in manifest["candidates"]:
        for runtime in ("codex", "claude"):
            for variant in ("baseline", "candidate"):
                rows = [row for row in manifest["schedule"] if row.get("candidate") == candidate and
                        row["runtime"] == runtime and row.get("variant") == variant]
                subset = [records[row["run_id"]] for row in rows if row["run_id"] in records]
                counts = {name: sum(metric_ready(record.get("metrics", {}), name) for record in subset)
                          for name in metric_names}
                values = {name: [value_of(record, name) for record in subset
                                 if (name == "elapsed_seconds" or metric_ready(record.get("metrics", {}),
                                     {"input_tokens": "usage", "tool_calls": "tool_calls"}[name])) and
                                 isinstance(value_of(record, name), (int, float))]
                          for name in ("input_tokens", "tool_calls", "elapsed_seconds")}
                complete = len(subset) == len(rows) == 24
                costs = [value_of(record, "cost_usd") for record in subset
                         if metric_ready(record.get("metrics", {}), "cost") and
                            metric_ready(record.get("metrics", {}), "outcome") and
                            isinstance(value_of(record, "cost_usd"), (int, float))]
                pricing_ok = all(metric_pricing(record.get("metrics", {})) ==
                                 (manifest["pricing"]["version"], manifest["pricing"]["currency"])
                                 for record in subset)
                cost_complete = complete and pricing_ok and counts["cost"] == counts["outcome"] == len(costs) == 24
                total = sum(costs) if cost_complete else None
                successes = sum(record.get("quality", {}).get("success") is True for record in subset)
                required_quality = ("success", "no_symlinks", "workspace_within_limit", "control_files_unchanged",
                                    "restore", "native", "runtime_effective")
                quality_complete = complete and all(all(record.get("quality", {}).get(name) is True
                                                        for name in required_quality) for record in subset)
                groups[":".join((candidate, runtime, variant))] = {
                    "expected_runs": 24, "recorded_runs": len(subset), "complete": complete,
                    "statuses": {name: sum(record.get("status") == name for record in subset) for name in statuses},
                    "successes": successes, "required_quality_complete": quality_complete,
                    "runtime_identity_sources": {name: sorted({
                        (((record.get("process") or {}).get("runtime_identity") or {}).get(name) or {}).get("source")
                        for record in subset} - {None}) for name in ("model", "effort")},
                    "candidate_effect_observed": (variant == "candidate" and complete and
                                                    all(record.get("lifecycle", {}).get("effective") is True
                                                        for record in subset)),
                    "coverage": {name: {"expected": 24, "qualified": counts[name], "rate": counts[name] / 24,
                                         "complete": complete and counts[name] == 24} for name in metric_names},
                    **{name: median_range(series, complete and counts["outcome"] == 24 and len(series) == 24)
                       for name, series in values.items()},
                    "total_cost_usd": total, "cost_per_run_usd": total / 24 if total is not None else None,
                    "cost_per_success_usd": total / successes if total is not None and successes else None}
            for spec in FIXTURES:
                selected = [item for item in pairs if item["candidate"] == candidate and item["runtime"] == runtime and
                            item["fixture"] == spec["id"]]
                fixture_summaries[":".join((candidate, runtime, spec["id"]))] = {
                    "expected_pairs": 3, "complete_pairs": sum(item["complete"] for item in selected),
                    "deltas": {name: median_range([item["deltas"][name] for item in selected
                               if isinstance(item["deltas"][name], (int, float))],
                               len(selected) == 3 and all(isinstance(item["deltas"][name], (int, float)) for item in selected))
                               for name in ("input_tokens", "tool_calls", "cost_usd", "elapsed_seconds")}}
            for variant in ("baseline", "candidate"):
                for task_group in ("repository", "cli", "long"):
                    rows = [row for row in manifest["schedule"] if row.get("candidate") == candidate and
                            row["runtime"] == runtime and row.get("variant") == variant and
                            fixture(row["fixture"], manifest)["group"] == task_group]
                    subset = [records[row["run_id"]] for row in rows if row["run_id"] in records]
                    expected_count = len(rows); complete = len(subset) == expected_count
                    counts = {name: sum(metric_ready(record.get("metrics", {}), name) for record in subset)
                              for name in metric_names}
                    series = {name: [value_of(record, name) for record in subset
                                     if (name == "elapsed_seconds" or metric_ready(record.get("metrics", {}),
                                         {"input_tokens": "usage", "tool_calls": "tool_calls"}[name])) and
                                     isinstance(value_of(record, name), (int, float))]
                              for name in ("input_tokens", "tool_calls", "elapsed_seconds")}
                    costs = [value_of(record, "cost_usd") for record in subset
                             if metric_ready(record.get("metrics", {}), "cost") and
                                metric_ready(record.get("metrics", {}), "outcome") and
                                isinstance(value_of(record, "cost_usd"), (int, float))]
                    pricing_ok = all(metric_pricing(record.get("metrics", {})) ==
                                     (manifest["pricing"]["version"], manifest["pricing"]["currency"])
                                     for record in subset)
                    total = (sum(costs) if complete and pricing_ok and counts["cost"] == counts["outcome"] ==
                             len(costs) == expected_count else None)
                    successes = sum(record.get("quality", {}).get("success") is True for record in subset)
                    task_groups[":".join((candidate, runtime, variant, task_group))] = {
                        "expected_runs": expected_count, "recorded_runs": len(subset), "complete": complete,
                        "statuses": {name: sum(record.get("status") == name for record in subset) for name in statuses},
                        "successes": successes,
                        "coverage": {name: {"expected": expected_count, "qualified": counts[name],
                                             "complete": complete and counts[name] == expected_count}
                                     for name in metric_names},
                        **{name: median_range(values, complete and counts["outcome"] == expected_count and
                                             len(values) == expected_count) for name, values in series.items()},
                        "total_cost_usd": total,
                        "cost_per_run_usd": total / expected_count if total is not None else None,
                        "cost_per_success_usd": (total / successes if total is not None and successes else None)}
    adoption_gate = {}
    for candidate in manifest["candidates"]:
        for runtime in ("codex", "claude"):
            candidate_group = groups[f"{candidate}:{runtime}:candidate"]
            baseline_group = groups[f"{candidate}:{runtime}:baseline"]
            relevant = [pair for pair in pairs if pair["candidate"] == candidate and pair["runtime"] == runtime]
            adoption_gate[f"{candidate}:{runtime}"] = {
                "eligible": adoption_eligible(baseline_group, candidate_group, relevant),
                "candidate_specific_effect_required": True}
    value = {"owner": OWNER, "schema": 4, "generated_at": now(), "plan": PLAN,
             "scheduled": manifest["max_runs"], "recorded": len(records), "groups": groups, "pairs": pairs,
             "fixture_summaries": fixture_summaries, "task_groups": task_groups, "adoption_gate": adoption_gate,
             "rules": {"expected_runs_per_variant": 24, "all_pairs_required": True, "success_zero": "NA",
             "coverage_uses_qualified_and_scope": True, "adoption_requires_all_primary_metric_coverage": True,
             "selection_threshold_only": "10%",
             "known_limitations": ["repo_tsc_onceの診断順序と診断再利用はworkspace成果物だけでは証明しない。workspace-helper evidence未承認中は比較HOLD"]}}
    write_json(root / "results/report.json", value)
    print(json.dumps({"recorded": len(records), "groups": len(groups), "report": str(root / "results/report.json")}, ensure_ascii=False))
    return 0


def cli():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare"); command.add_argument("root"); command.add_argument("--seed", type=int, default=260920804)
    command.add_argument("--capability-evidence", required=True)
    command.add_argument("--comparison-bundle", required=True)
    command.add_argument("--codex-bin", required=True); command.add_argument("--claude-bin", required=True)
    command.add_argument("--tsc-bin")
    command.add_argument("--source-change-reason", default="initial")
    command.add_argument("--include-i05", action="store_true"); command.set_defaults(handler=prepare)
    command = commands.add_parser("status"); command.add_argument("root"); command.set_defaults(handler=status)
    command = commands.add_parser("attest-login"); command.add_argument("root")
    command.add_argument("runtime", choices=("codex", "claude")); command.set_defaults(handler=attest_login)
    command = commands.add_parser("login"); command.add_argument("root")
    command.add_argument("runtime", choices=("codex", "claude")); command.set_defaults(handler=login)
    command = commands.add_parser("run"); command.add_argument("root"); command.add_argument("--smoke-only", action="store_true")
    command.add_argument("--smoke-runtime", choices=("codex", "claude"))
    command.add_argument("--candidate", choices=("I03", "I04", "I05"))
    command.add_argument("--codex-model", required=True); command.add_argument("--codex-effort", required=True)
    command.add_argument("--claude-model", required=True); command.add_argument("--claude-effort", required=True)
    command.add_argument("--codex-requested-tier"); command.add_argument("--claude-requested-tier")
    command.add_argument("--timeout-seconds", type=int, choices=(600,), default=600); command.set_defaults(handler=run)
    command = commands.add_parser("report"); command.add_argument("root"); command.set_defaults(handler=report)
    return parser


if __name__ == "__main__":
    arguments = cli().parse_args()
    raise SystemExit(arguments.handler(arguments))
