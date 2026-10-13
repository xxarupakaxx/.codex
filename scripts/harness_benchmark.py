#!/usr/bin/env python3
"""隔離した合成fixtureで有限のharness比較を準備・実行する。"""
from __future__ import annotations

import argparse
import ast
import copy
import errno
import fcntl
import hashlib
import importlib.util
import json
import math
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

_HELPER_SPEC = importlib.util.spec_from_file_location("harness_fixture_helper", Path(__file__).with_name("harness_fixture_helper.py"))
host_helper = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(host_helper)

OWNER = "harness-benchmark-v1"
PLAN = {"version": "v8", "sha256": "45986dad51cf2c4c83bb49fb575f704e8ecf3f963ffd23cd05063503099fa3e3"}
HOST_PLAN = host_helper.PLAN
BASELINES = {"codex": "51ee53ed72eec0f7184c0699d244d2329d8e93bd", "claude": "7152ca3d5e05529f04018b59c0f40c668b8567aa"}
LIMITS = {"run_seconds": 600, "total_seconds": 49 * 3600, "retry": 0,
          "codex_tool_events": 40, "claude_turns": 20, "claude_output_tokens": 8192,
          "stdout_bytes": 16 * 1024 * 1024, "stderr_bytes": 16 * 1024 * 1024,
          "line_bytes": 1024 * 1024, "workspace_bytes": 16 * 1024 * 1024,
          "workspace_file_bytes": 4 * 1024 * 1024, "workspace_files": 128,
          "workspace_entries": 256, "comparison_manifest_bytes": 1024 * 1024,
          "comparison_file_bytes": 4 * 1024 * 1024, "comparison_files": 96,
          "comparison_bytes": 16 * 1024 * 1024, "term_grace_seconds": 5,
          "child_nofile_cap": 1024,
          "runtime_generated_files": 64,
          "runtime_generated_dirs": 64,
          "runtime_native_changes": 64,
          "runtime_generated_bytes": 16 * 1024 * 1024}
SECRET_ENV = re.compile(r"(?:API_KEY|TOKEN|OAUTH|PASSWORD|SECRET|CREDENTIAL)", re.I)
FIXED_ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C",
             "TERM": "dumb", "SHELL": "/bin/sh"}
FULL_HASH = re.compile(r"[0-9a-f]{40,64}\Z")
HASH64 = re.compile(r"[0-9a-f]{64}\Z")
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
        "claude": {name: "unknown" for name in CAPABILITIES}},
    "4e7dc9dc4f113ec43c63decbf25313e95b3e1e9de6102cce124dd39c506bf17b": {
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

[features]
plugins = false

[skills.bundled]
enabled = false
'''
CLAUDE_SAFETY = {"sandbox": {"enabled": True, "allowUnsandboxedCommands": False,
                              "failIfUnavailable": True}}
CLAUDE_MARKER = "runtime/claude/config/isolation-marker.txt"
HOST_SLOT, HOST_SOURCE_POLICY = host_helper.SLOT, host_helper.SOURCE_POLICY
LOGIN_CWD = "runtime/login-cwd"
CODEX_ARG0_LINKS = ("applypatch", "apply_patch", "codex-execve-wrapper")
CODEX_ARG0_NAME = re.compile(r"codex-arg0[A-Za-z0-9]{6}\Z")
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


def _runtime_entry(path, allow_public_regular=False, expected=None, allow_public_paths=None):
    try:
        info = Path(path).lstat()
    except OSError as error:
        raise SystemExit("runtime metadataを検証できない") from error
    mode = info.st_mode
    kind = "directory" if stat.S_ISDIR(mode) else "regular" if stat.S_ISREG(mode) else None
    public_regular = stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o644
    allowlisted_public = allow_public_paths is not None and path in allow_public_paths
    if (kind is None or stat.S_ISLNK(mode) or info.st_uid != os.getuid() or
            (kind == "regular" and info.st_nlink != 1) or
            (stat.S_IMODE(mode) & 0o077 and
             not (allow_public_regular and public_regular and expected is not None and
                  (path not in expected or allowlisted_public)))):
        raise SystemExit("runtime metadataがprivateな通常treeではない")
    return (kind, info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(mode),
            info.st_nlink, info.st_size, info.st_mtime_ns)


def runtime_private_snapshot(base, expected=None, allow_public_regular=False,
                             allow_public_paths=None, maximum=4096):
    """Capture metadata only; file bodies and names never leave this process."""
    base = Path(base)
    if base.is_symlink() or not base.is_dir():
        raise SystemExit("runtime rootを検証できない")
    allow_public_paths = None if allow_public_paths is None else set(allow_public_paths)
    pending = [base]; snapshot = {}
    try:
        while pending:
            path = pending.pop()
            if path in snapshot or len(snapshot) >= maximum:
                raise SystemExit("runtime metadata件数が上限を超えた")
            snapshot[path] = _runtime_entry(path, allow_public_regular, expected, allow_public_paths)
            if snapshot[path][0] == "directory":
                with os.scandir(path) as entries:
                    for entry in entries:
                        pending.append(Path(entry.path))
    except OSError as error:
        raise SystemExit("runtime metadataを検証できない") from error
    return snapshot


def runtime_protected_paths(runtime_root):
    """Return the one parent-managed path belonging to this runtime tree."""
    runtime_root = Path(runtime_root)
    root = runtime_root.parent.parent
    protected = {root / "runtime/codex/home/config.toml", root / CLAUDE_MARKER}
    selected = {path for path in protected if runtime_root in path.parents}
    if selected != ({root / "runtime/codex/home/config.toml"} if runtime_root.name == "codex"
                    else {root / CLAUDE_MARKER} if runtime_root.name == "claude" else set()):
        raise SystemExit("runtime parent-managed pathの構成が許可外")
    return selected


def runtime_native_inventory(before, protected_paths):
    """Build a bounded inventory of private regular native state without reading bodies."""
    protected_paths = {Path(path) for path in protected_paths}
    if not protected_paths or any(not path.is_absolute() or path not in before for path in protected_paths):
        raise SystemExit("runtime parent-managed pathが起動前snapshotにない")
    for path in protected_paths:
        if before[path][0] != "regular" or before[path][5] != 1:
            raise SystemExit("runtime parent-managed pathのshapeが許可外")
    inventory = {path for path, metadata in before.items()
                 if metadata[0] == "regular" and path not in protected_paths}
    if len(before) > 4096:
        raise SystemExit("runtime metadata件数が上限を超えた")
    return inventory


def _runtime_same_entry(before, after):
    if before[0] != after[0] or before[1:5] != after[1:5]:
        return False
    if before[0] == "regular":
        return before[5:] == after[5:]
    return True


def _runtime_existing_entry(before, after):
    """Preserve existing identity and mode while allowing normal runtime writes."""
    if before[0] != after[0] or before[1:5] != after[1:5]:
        return False
    return before[0] != "regular" or before[5] == after[5]


def _runtime_ancestors_private(path, base, before, after):
    parent = Path(path).parent
    while parent != base:
        if parent not in after or after[parent][0] != "directory":
            return False
        if (parent in before and not _runtime_existing_entry(before[parent], after[parent])):
            return False
        if after[parent][3] != os.getuid() or after[parent][4] != 0o700:
            return False
        parent = parent.parent
    return (parent == base and base in before and base in after and
            _runtime_existing_entry(before[base], after[base]) and
            after[base][0] == "directory" and after[base][3] == os.getuid() and
            after[base][4] == 0o700)


def _runtime_visible_matches(path, expected, descriptor, label):
    """Bind a visible NOFOLLOW path to its already-held descriptor."""
    try:
        visible = os.stat(path, follow_symlinks=False)
        held = os.fstat(descriptor)
    except OSError as error:
        raise SystemExit(f"runtime {label} pathを再検証できない") from error
    if (visible.st_dev, visible.st_ino, visible.st_uid, stat.S_IMODE(visible.st_mode),
            visible.st_nlink, visible.st_mtime_ns) != expected:
        raise SystemExit(f"runtime {label} pathが検証中に変化した")
    if (held.st_dev, held.st_ino, held.st_uid, stat.S_IMODE(held.st_mode),
            held.st_nlink, held.st_mtime_ns) != expected:
        raise SystemExit(f"runtime {label} descriptorが検証中に変化した")


def _tighten_runtime_file(path, observed, parent_observed, after, base):
    if observed[0] != "regular" or observed[3] != os.getuid() or observed[5] != 1:
        raise SystemExit("runtime generated fileのshapeが許可外")
    if observed[4] not in (0o600, 0o644) or observed[6] > LIMITS["comparison_file_bytes"]:
        raise SystemExit("runtime generated fileのmodeまたはsizeが許可外")
    directory_fds = []; directory_paths = []; descriptor = None
    try:
        relative_parent = Path(path).parent.relative_to(Path(base))
        current_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        directory_fds.append(current_fd)
        directory_paths.append(Path(base))
        base_observed = after.get(Path(base))
        opened_base = os.fstat(current_fd)
        if (base_observed is None or base_observed[0] != "directory" or
                (opened_base.st_dev, opened_base.st_ino, opened_base.st_uid,
                 stat.S_IMODE(opened_base.st_mode)) !=
                (base_observed[1], base_observed[2], os.getuid(), 0o700)):
            raise SystemExit("runtime base directoryが検証中に変化した")
        _runtime_visible_matches(Path(base),
                                 (base_observed[1], base_observed[2], os.getuid(), 0o700,
                                  base_observed[5], base_observed[7]),
                                 directory_fds[0], "base")
        current = Path(base)
        for part in relative_parent.parts:
            child = current / part
            current_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 dir_fd=current_fd)
            directory_fds.append(current_fd)
            current = child
            directory_paths.append(current)
            expected_dir = after.get(current)
            opened_dir = os.fstat(current_fd)
            if (expected_dir is None or expected_dir[0] != "directory" or
                    (opened_dir.st_dev, opened_dir.st_ino, opened_dir.st_uid,
                     stat.S_IMODE(opened_dir.st_mode)) !=
                    (expected_dir[1], expected_dir[2], os.getuid(), 0o700)):
                raise SystemExit("runtime generated fileのancestorが検証中に変化した")
            _runtime_visible_matches(current,
                                     (expected_dir[1], expected_dir[2], os.getuid(), 0o700,
                                      expected_dir[5], expected_dir[7]),
                                     current_fd, "ancestor")
        parent_fd = directory_fds[-1]
        parent_info = os.fstat(parent_fd)
        if (parent_info.st_dev, parent_info.st_ino, parent_info.st_uid,
                stat.S_IMODE(parent_info.st_mode)) != (parent_observed[1], parent_observed[2],
                                                       os.getuid(), 0o700):
            raise SystemExit("runtime generated fileのparentが検証中に変化した")
        dirent = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (dirent.st_dev, dirent.st_ino, dirent.st_uid, stat.S_IMODE(dirent.st_mode),
                dirent.st_nlink, dirent.st_size, dirent.st_mtime_ns) != (observed[1], observed[2], observed[3],
                                                                           observed[4], observed[5], observed[6], observed[7]):
            raise SystemExit("runtime generated fileが検証中に変化した")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        held = os.fstat(descriptor)
        if (held.st_dev, held.st_ino, held.st_uid, stat.S_IMODE(held.st_mode),
                held.st_nlink, held.st_size, held.st_mtime_ns) != (observed[1], observed[2], observed[3],
                                                                    observed[4], observed[5], observed[6], observed[7]):
            raise SystemExit("runtime generated fileのidentityが検証中に変化した")
        _runtime_visible_matches(path,
                                 (observed[1], observed[2], observed[3], observed[4],
                                  observed[5], observed[7]),
                                 descriptor, "file")
        # Rebind every visible root/ancestor after the file FD check and
        # immediately before fchmod; a moved inode must not follow a new root.
        for index, directory_path in enumerate(directory_paths):
            expected_dir = after.get(directory_path)
            if expected_dir is None or expected_dir[0] != "directory":
                raise SystemExit("runtime generated fileのancestorが検証中に変化した")
            _runtime_visible_matches(
                directory_path,
                (expected_dir[1], expected_dir[2], os.getuid(), 0o700,
                 expected_dir[5], expected_dir[7]),
                directory_fds[index], "base" if index == 0 else "ancestor")
        if observed[4] == 0o644:
            os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        final = os.fstat(descriptor)
        if (final.st_dev, final.st_ino, final.st_uid, final.st_nlink, final.st_size,
                final.st_mtime_ns, stat.S_IMODE(final.st_mode)) != (observed[1], observed[2], observed[3],
                                                                      observed[5], observed[6], observed[7], 0o600):
            raise SystemExit("runtime generated fileのtighten後検証に失敗した")
        dirent_after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (dirent_after.st_dev, dirent_after.st_ino, dirent_after.st_uid,
                stat.S_IMODE(dirent_after.st_mode), dirent_after.st_nlink,
                dirent_after.st_size, dirent_after.st_mtime_ns) != (observed[1], observed[2], observed[3], 0o600,
                                                                      observed[5], observed[6], observed[7]):
            raise SystemExit("runtime generated fileのdirentが検証中に変化した")
        _runtime_visible_matches(path,
                                 (observed[1], observed[2], observed[3], 0o600,
                                  observed[5], observed[7]),
                                 descriptor, "file")
    except (OSError, ValueError) as error:
        raise SystemExit("runtime generated fileを安全にtightenできない") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)
    return observed[4] == 0o644


def _validate_native_replacement(path, observed, before, after, base):
    """Validate a trusted native regular replacement without reading its body."""
    if (observed[0] != "regular" or observed[3] != os.getuid() or observed[5] != 1 or
            observed[4] not in (0o600, 0o644) or observed[6] > LIMITS["comparison_file_bytes"]):
        raise SystemExit("native replacementのshapeが許可外")
    if not _runtime_ancestors_private(path, Path(base), before, after):
        raise SystemExit("native replacementのancestorがprivateではない")


def tighten_fresh_runtime_files(base, before, process_group_reaped, native_paths=(), protected_paths=()):
    """Preserve normal writes and tighten fresh files plus explicitly trusted native changes."""
    if process_group_reaped is not True:
        raise SystemExit("child process groupの回収を確認できない")
    native_paths = {Path(path) for path in native_paths}
    protected_paths = {Path(path) for path in protected_paths}
    if native_paths & protected_paths:
        raise SystemExit("parent-managed pathをnative inventoryへ含められない")
    if any((not path.is_absolute() or path != path.resolve(strict=False) or
            path not in before or before[path][0] != "regular") for path in native_paths):
        raise SystemExit("native pathが起動前のregular fileではない")
    if any((not path.is_absolute() or path not in before or before[path][0] != "regular" or
            before[path][5] != 1) for path in protected_paths):
        raise SystemExit("parent-managed pathが起動前のregular fileではない")
    after = runtime_private_snapshot(base, expected=before, allow_public_regular=True,
                                     allow_public_paths=native_paths)
    for path in protected_paths:
        if path not in after or not _runtime_same_entry(before[path], after[path]):
            raise SystemExit("parent-managed runtime pathが変化した")
    missing = set(before) - set(after)
    native_removed = sorted(missing & native_paths, key=str)
    if missing - set(native_removed):
        raise SystemExit("runtimeの既存entryが失われた")
    native_replacements = []
    for path in sorted(native_paths, key=str):
        if path not in after:
            continue
        old = before[path]; new = after[path]
        if old[0] != new[0]:
            raise SystemExit("native pathのtypeが変化した")
        if old[1] != new[1] or old[2] != new[2]:
            native_replacements.append(path)
    if len(native_removed) + len(native_replacements) > LIMITS["runtime_native_changes"]:
        raise SystemExit("native metadata change件数が上限を超えた")
    for path in before:
        if path in protected_paths:
            continue
        if path in native_removed:
            continue
        if path in native_replacements:
            _validate_native_replacement(path, after[path], before, after, base)
        elif not _runtime_existing_entry(before[path], after[path]):
            raise SystemExit("runtimeの既存entryが変化した")
    native_bytes = 0
    for path in native_replacements:
        native_bytes += after[path][6]
        if native_bytes > LIMITS["runtime_generated_bytes"]:
            raise SystemExit("native replacement合計sizeが上限を超えた")
    fresh = sorted(set(after) - set(before), key=str)
    fresh_dirs = [path for path in fresh if after[path][0] == "directory"]
    fresh_files = [path for path in fresh if after[path][0] == "regular"]
    if len(fresh_dirs) > LIMITS["runtime_generated_dirs"]:
        raise SystemExit("runtime generated directory件数が上限を超えた")
    for path in fresh_dirs:
        observed = after[path]
        if (observed[3] != os.getuid() or observed[4] != 0o700 or
                not _runtime_ancestors_private(path, Path(base), before, after)):
            raise SystemExit("runtime generated directoryのshapeが許可外")
    total_bytes = native_bytes; tightened = 0; native_tightened = 0
    if len(fresh_files) > LIMITS["runtime_generated_files"]:
        raise SystemExit("runtime generated file件数が上限を超えた")
    fresh_entries = []
    for path in fresh_files:
        observed = after[path]
        if (observed[0] != "regular" or observed[3] != os.getuid() or observed[5] != 1 or
                observed[4] not in (0o600, 0o644) or observed[6] > LIMITS["comparison_file_bytes"]):
            raise SystemExit("runtime generated fileのshapeが許可外")
        if not _runtime_ancestors_private(path, Path(base), before, after):
            raise SystemExit("runtime generated fileのancestorがprivateではない")
        total_bytes += observed[6]
        if total_bytes > LIMITS["runtime_generated_bytes"]:
            raise SystemExit("runtime generated file合計sizeが上限を超えた")
        fresh_entries.append((path, observed))
    for path in native_replacements:
        native_tightened += _tighten_runtime_file(path, after[path], after[path.parent], after, Path(base))
    for path, observed in fresh_entries:
        tightened += _tighten_runtime_file(path, observed, after[path.parent], after, Path(base))
    final = runtime_private_snapshot(base, expected=before)
    expected_paths = (set(before) - set(native_removed)) | set(fresh)
    if set(final) != expected_paths:
        raise SystemExit("runtime generated fileの最終treeが変化した")
    replacement_set = set(native_replacements)
    for path in before:
        if path in native_removed:
            continue
        if path in replacement_set:
            observed = after[path]; current = final[path]
            if (current[0] != "regular" or current[1:4] != observed[1:4] or
                    current[5] != observed[5] or current[6] != observed[6] or
                    current[7] != observed[7] or current[4] != 0o600):
                raise SystemExit("native replacementの最終metadataが変化した")
        elif path in protected_paths:
            if not _runtime_same_entry(before[path], final[path]):
                raise SystemExit("parent-managed runtime pathの最終metadataが変化した")
        elif not _runtime_existing_entry(before[path], final[path]):
            raise SystemExit("runtimeの既存entryが最終検証で変化した")
    for path in fresh_dirs:
        if not _runtime_same_entry(after[path], final[path]) or final[path][4] != 0o700:
            raise SystemExit("runtime generated directoryの最終treeが変化した")
    for path in fresh_files:
        if (final[path][0] != "regular" or final[path][1:4] != after[path][1:4] or
                final[path][5] != after[path][5] or final[path][6] != after[path][6] or
                final[path][7] != after[path][7] or
                final[path][4] != 0o600):
            raise SystemExit("runtime generated fileがowner専用modeではない")
    result = {"status": "passed", "fresh_dirs": len(fresh_dirs), "fresh_files": len(fresh_files),
              "fresh_bytes": sum(after[path][6] for path in fresh_files),
              "files_tightened": tightened + native_tightened}
    if native_paths:
        result["native_inventory_count"] = len(native_paths)
        result["native_changes"] = {"removed": len(native_removed),
                                     "replaced": len(native_replacements),
                                     "total": len(native_removed) + len(native_replacements)}
        result["native_replaced_bytes"] = native_bytes
    return result


def private_empty_dir(path, label):
    """Validate a known owner-only empty directory before using it as cwd."""
    path = Path(path)
    try:
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or
                stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid()):
            raise SystemExit(f"{label}がowner専用directoryではない")
        with os.scandir(path) as entries:
            if next(entries, None) is not None:
                raise SystemExit(f"{label}がemptyではない")
    except OSError as error:
        raise SystemExit(f"{label}を検証できない") from error
    return path


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
    return {"path": str(path), "sha256": sha256_path(path),
            "version": version, "currency": "USD"}


def tool_source_hashes():
    paths = {"runner": Path(__file__), "metrics": Path(__file__).with_name("session-metrics.py"),
             "quiet_run": Path(__file__).with_name("quiet-run.py"),
             "host_helper": Path(__file__).with_name("harness_fixture_helper.py"),
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
    bundles = {}; file_count = total_bytes = 0; counted_sources = set()
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
            try:
                with source.open("rb") as stream:
                    content = stream.read(LIMITS["comparison_file_bytes"] + 1)
            except OSError as error:
                raise SystemExit(f"comparison bundle fileを読めない: {source}") from error
            actual = hashlib.sha256(content).hexdigest()
            source_identity = (str(source.resolve()), actual)
            if source_identity not in counted_sources:
                total_bytes += len(content); counted_sources.add(source_identity)
            if (len(content) > LIMITS["comparison_file_bytes"] or
                    total_bytes > LIMITS["comparison_bytes"]):
                raise SystemExit("comparison bundle生成量が上限を超える")
            host_allowed = host_helper.bundle_file_allowed(class_name, target, actual, factor)
            allowed = (host_allowed or (class_name == "workspace_instruction" and target.name in ("AGENTS.md", "CLAUDE.md")) or
                       (class_name == "runtime_settings" and target.name in ("overrides.json", "settings.json")) or
                       (class_name == "hook_adapter" and target.parts and target.parts[0] == "hooks"))
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
            baseline_entries = bundles[candidate, runtime, "baseline"]["files"]
            candidate_entries = bundles[candidate, runtime, "candidate"]["files"]
            host_seen = any(item["class"] == "host_fixture_helper"
                            for item in (*baseline_entries, *candidate_entries))
            expected_host_keys = {("host_fixture_helper", f"host/{role}")
                                  for role in HOST_SOURCE_POLICY}
            if host_seen:
                for variant, entries in (("baseline", baseline_entries), ("candidate", candidate_entries)):
                    entry_keys = [(item["class"], item["target"]) for item in entries]
                    if len(entry_keys) != len(expected_host_keys) or set(entry_keys) != expected_host_keys:
                        raise SystemExit(f"host bundle entry契約違反: {candidate}:{runtime}:{variant}")
            before = {(row["class"], row["target"]): row for row in baseline_entries}
            after = {(row["class"], row["target"]): row for row in candidate_entries}
            if set(before) != set(after):
                raise SystemExit(f"bundle target集合が不一致: {candidate}:{runtime}")
            changed = [key for key in before if before[key]["sha256"] != after[key]["sha256"]]
            host_mode = host_helper.host_bundle_mode(before, after, changed)
            if host_seen and not host_mode:
                raise SystemExit(f"host bundle mode契約違反: {candidate}:{runtime}")
            if not host_mode and (not changed or any(before[key]["factor"] != candidate or after[key]["factor"] != candidate for key in changed)):
                raise SystemExit(f"bundle差分factorが一要素でない: {candidate}:{runtime}")
            if any(before[key]["factor"] == "fixed" and before[key]["sha256"] != after[key]["sha256"] for key in before):
                raise SystemExit(f"bundle fixed条件が不一致: {candidate}:{runtime}")
            change_classes = ["host_fixture_helper"] if host_mode else sorted({before[key]["class"] for key in changed})
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
            target = (root / "runtime/host-sources" / Path(item["target"]).name
                      if item["class"] == "host_fixture_helper" else
                      root / "runtime/bundles" / candidate / runtime / variant / item["target"])
            if target.exists():
                if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
                    raise SystemExit("共有host sourceが不一致")
            else:
                write_private_bytes(target, item["content"])
            if item["class"] == "host_fixture_helper" and item["target"] == "host/node":
                os.chmod(target, 0o700)
            staged.append({name: item[name] for name in ("class", "target", "sha256", "factor")})
        classes = set(source_bundle["change_classes"])
        kind = ("host-supervised-helper" if classes == {"host_fixture_helper"} else
                "hook-unconfined" if "hook_adapter" in classes else
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
    row = {"path": str(real), "sha256": sha256_path(real)}
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
        row["interpreter"] = {"path": str(node), "sha256": sha256_path(node)}
    return row


def runtime_argv(row):
    return ([row["interpreter"]["path"]] if row.get("interpreter") else []) + [row["path"]]


def sha256_path(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def pinned_executable(raw, label):
    """Return the immutable identity used for Codex's private arg0 symlinks."""
    path = Path(raw)
    try:
        info = path.lstat(); real = path.resolve(strict=True)
    except OSError as error:
        raise SystemExit(f"{label}を解決できない") from error
    if (not path.is_absolute() or real != path or stat.S_ISLNK(info.st_mode) or
            not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != 0o755 or info.st_nlink != 1 or info.st_size <= 0 or
            not os.access(path, os.X_OK)):
        raise SystemExit(f"{label}はowner所有0755・nlink1のabsolute regular executableに限定する")
    return {"path": str(path), "sha256": sha256_path(path),
            "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode), "nlink": info.st_nlink,
            "size": info.st_size, "device": info.st_dev, "inode": info.st_ino}


def _private_directory(path):
    info = Path(path).lstat()
    return (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and
            info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)


def cleanup_codex_arg0_helpers(root, manifest, after_cleanup=None):
    """Remove only verified, idle Codex arg0 links; every unknown shape fails closed."""
    expected = manifest.get("codex_arg0_native")
    if not isinstance(expected, dict) or pinned_executable(expected.get("path", ""), "Codex native pin") != expected:
        raise SystemExit("Codex native pin変更後は新しいrootを準備する")
    home = root / "runtime/codex/home"; temp = home / "tmp"; arg0 = temp / "arg0"

    def finish():
        if after_cleanup is not None:
            after_cleanup()
        if not private_tree_ok((root / "runtime/codex",), 4096):
            raise SystemExit("Codex arg0回収後のruntime treeがstrict検査に失敗")

    try:
        for directory in (root, root / "runtime", root / "runtime/codex", home):
            if not _private_directory(directory):
                raise SystemExit("Codex arg0 ancestorがprivateな通常directoryではない")
        if not os.path.lexists(temp):
            finish()
            return 0
        if not _private_directory(temp):
            raise SystemExit("Codex arg0 tempがprivateな通常directoryではない")
        if not os.path.lexists(arg0):
            finish()
            return 0
        if not _private_directory(arg0):
            raise SystemExit("Codex arg0 rootがprivateな通常directoryではない")
        entries = list(os.scandir(arg0))
        if len(entries) > 32:
            raise SystemExit("Codex arg0 helper件数が上限を超えた")
        if not entries:
            arg0.rmdir()
            if not any(temp.iterdir()):
                temp.rmdir()
            finish()
            return 0
    except OSError as error:
        raise SystemExit("Codex arg0 treeを検証できない") from error

    locks, helpers = [], []
    required = {".lock", *CODEX_ARG0_LINKS}
    try:
        for entry in entries:
            helper = Path(entry.path)
            if not CODEX_ARG0_NAME.fullmatch(entry.name) or not _private_directory(helper):
                raise SystemExit("Codex arg0 helper shapeが許可外")
            names = {item.name for item in os.scandir(helper)}
            if names != required:
                raise SystemExit("Codex arg0 helper entryがexact setではない")
            lock_path = helper / ".lock"; lock_info = lock_path.lstat()
            if (not stat.S_ISREG(lock_info.st_mode) or stat.S_ISLNK(lock_info.st_mode) or
                    lock_info.st_uid != os.getuid() or stat.S_IMODE(lock_info.st_mode) != 0o600 or
                    lock_info.st_nlink != 1 or lock_info.st_size != 0):
                raise SystemExit("Codex arg0 lockが許可shapeではない")
            descriptor = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            actual = os.fstat(descriptor)
            if (actual.st_dev, actual.st_ino) != (lock_info.st_dev, lock_info.st_ino):
                os.close(descriptor); raise SystemExit("Codex arg0 lockが検証中に変化した")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                os.close(descriptor); raise SystemExit("Codex arg0 lockが使用中") from error
            locks.append(descriptor)
            for name in CODEX_ARG0_LINKS:
                link = helper / name; info = link.lstat()
                target = Path(os.readlink(link))
                if (not stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or
                        not target.is_absolute() or link.resolve(strict=True) != Path(expected["path"])):
                    raise SystemExit("Codex arg0 linkがpin済みtargetと不一致")
            helpers.append(helper)
        if pinned_executable(expected["path"], "Codex native pin") != expected:
            raise SystemExit("Codex native pinが検証中に変化した")
        for helper in helpers:
            if {item.name for item in os.scandir(helper)} != required:
                raise SystemExit("Codex arg0 helperが検証中に変化した")
        for helper in helpers:
            for name in CODEX_ARG0_LINKS:
                (helper / name).unlink()
            (helper / ".lock").unlink(); helper.rmdir()
        arg0.rmdir()
        if not any(temp.iterdir()):
            temp.rmdir()
    except (OSError, RuntimeError) as error:
        raise SystemExit("Codex arg0 helperを安全に回収できない") from error
    finally:
        for descriptor in locks:
            try:
                os.close(descriptor)
            except OSError:
                pass
    finish()
    return len(helpers)


def verify_runtime_binaries(manifest):
    native = manifest.get("codex_arg0_native") or {}
    if pinned_executable(native.get("path", ""), "Codex native pin") != native:
        raise SystemExit("Codex native pin変更後は新しいrootを準備する")
    for runtime, row in manifest["runtime_binaries"].items():
        if runtime_binary(row["path"], runtime) != row:
            raise SystemExit(f"{runtime}実行file変更後は新しいrootを準備する")
    for name, tool in (manifest.get("fixture_tools") or {}).items():
        if tool.get("state") == "observed" and runtime_binary(tool["binary"]["path"], name) != tool["binary"]:
            raise SystemExit(f"{name}変更後は新しいrootを準備する")
    python = (manifest.get("fixture_tools") or {}).get("python_cli") or {}
    if python.get("state") != "observed" or runtime_binary(sys.executable, "python_cli") != python.get("binary"):
        raise SystemExit("runner Python変更後は新しいrootを準備する")
    host = manifest.get("host_dependencies") or {}
    if host:
        node, tsc = host.get("node") or {}, host.get("tsc_js") or {}
        path = Path(tsc.get("path", ""))
        if runtime_binary(node.get("path"), "host_node") != node or path.is_symlink() or not path.is_file() or \
                hashlib.sha256(path.read_bytes()).hexdigest() != tsc.get("sha256"):
            raise SystemExit("host helper dependency変更後は新しいrootを準備する")


def verify_runtime_state(root, manifest):
    verify_environment(manifest)
    cleanup_codex_arg0_helpers(root, manifest)
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
    private_empty_dir(root / LOGIN_CWD, "login-cwd")
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
    mkdir(root / LOGIN_CWD)
    mkdir(root / "runtime/host-helper")
    write_private(root / "runtime/codex/home/config.toml", CODEX_CONFIG)
    marker_content = "synthetic nonsecret isolation marker\n"
    write_private(root / CLAUDE_MARKER, marker_content)
    candidates = ["I03", "I04"] + (["I05"] if args.include_i05 else [])
    binaries = {"codex": runtime_binary(args.codex_bin, "codex"),
                "claude": runtime_binary(args.claude_bin, "claude")}
    codex_arg0_native = pinned_executable(args.codex_native_bin, "Codex native pin")
    tsc_bin = getattr(args, "tsc_bin", None)
    fixture_tools = {"python_cli": {"state": "observed", "binary": runtime_binary(sys.executable, "python_cli")},
                     "typescript_cli": ({"state": "observed", "binary": runtime_binary(tsc_bin, "typescript_cli")}
                                          if tsc_bin else {"state": "unsupported",
                                                           "reason": "reviewed_absolute_tsc_binary_missing"})}
    capability_evidence = load_capabilities(args.capability_evidence)
    capabilities = capability_evidence["runtimes"]
    bundles = stage_bundles(root, load_comparison_bundle(args.comparison_bundle, candidates))
    host_active = any(row["evaluation_kind"] == "host-supervised-helper" for row in bundles.values())
    host_dependencies = {}
    if host_active:
        try:
            host_dependencies = host_helper.validate_dependencies(args.host_node_bin, args.host_tsc_js)
        except host_helper.HelperError as error:
            raise SystemExit("host helper dependencyがreview済みallowlistと不一致") from error
    for base_fixture in FIXTURES:
        fixture = resolved_fixture(base_fixture["id"], fixture_tools)
        directory = root / "fixtures" / fixture["id"]
        mkdir(directory)
        write_json(directory / "fixture.json", {"owner": OWNER, "schema": 1, **fixture})
    rows = make_schedule(args.seed, candidates); prepared_at = now(); sources = tool_source_hashes()
    prompt_hashes = {}
    for row in rows:
        spec = resolved_fixture(row["fixture"], fixture_tools) if row["kind"] == "compare" else None
        key = ":".join((row.get("candidate", ""), row["runtime"], row.get("variant", "")))
        mechanism = HOST_SLOT if row["kind"] == "compare" and bundles[key]["evaluation_kind"] == "host-supervised-helper" else None
        prompt = prompt_for(row, spec, root / CLAUDE_MARKER, mechanism)
        prompt_hashes[row["run_id"]] = hashlib.sha256(prompt.encode()).hexdigest()
    write_json(root / "results/manifest.json", {"owner": OWNER, "schema": 1, "prepared_at": prepared_at, "plan": PLAN,
               "schedule_seed": args.seed,
               "sampling": {runtime: {"temperature": None, "seed": None,
                            "state": "unknown", "missing_reason": "runtime_cli_not_supported"}
                            for runtime in ("codex", "claude")},
               "candidates": candidates, "limits": LIMITS,
               "capabilities": capabilities, "capability_hash": digest(capabilities),
               "capability_source": {key: capability_evidence[key] for key in ("source_path", "source_hash")},
               "comparison_bundles": bundles, "runtime_binaries": binaries,
               "codex_arg0_native": codex_arg0_native, "fixture_tools": fixture_tools,
               "host_helper_plan": HOST_PLAN, "host_dependencies": host_dependencies,
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
    cleanup_codex_arg0_helpers(root, manifest)
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
    if runtime == "codex":
        cleanup_codex_arg0_helpers(root, manifest)
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
    login_cwd = private_empty_dir(root / LOGIN_CWD, "login-cwd")
    base = runtime_argv(manifest["runtime_binaries"][runtime])
    command = base + (["login"] if runtime == "codex" else ["auth", "login"])
    os.umask(0o077)
    os.chdir(str(login_cwd))
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
    cleanup_codex_arg0_helpers(root, manifest)
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
              "codex_arg0_native": manifest["codex_arg0_native"],
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
    cleanup_codex_arg0_helpers(root, manifest)
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
    if not isinstance(row, dict):
        return "critical_schema_type"
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
        if row.get("type") == "item.completed":
            if item.get("type") == "agent_message":
                seen["model_response_observed"] = True
            elif item.get("type") == "error":
                seen["warning_items"] += 1
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
        elif row.get("type") == "turn.completed":
            seen["turn_completed"] = True
        return "event_limit" if len(seen["tool_ids"]) > LIMITS["codex_tool_events"] else None
    if row.get("permission_denials"):
        seen["rejection"] = True
        seen["terminal_status"] = "rejection"
    if row.get("session_id") or row.get("sessionId"):
        seen["session_id"] = row.get("session_id") or row.get("sessionId")
    content = message.get("content", []) if isinstance(message.get("content"), list) else []
    if row.get("type") == "assistant":
        seen["model_response_observed"] = True
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
    if (runtime == "codex" and not seen.get("terminal_status") and
            (not seen.get("turn_completed") or not seen.get("model_response_observed"))):
        return "incomplete_turn"
    if runtime == "claude" and not seen.get("usage_observed"):
        return "output_usage_unknown"
    if runtime == "claude" and seen.get("output_tokens", 0) > LIMITS["claude_output_tokens"]:
        return "event_limit"
    return None


def classify_status(process, quality):
    if process.get("rejection") or process.get("terminal_status") == "rejection":
        return "rejection"
    if process.get("terminal_status") == "failure":
        return "failure"
    if process.get("stop_reason") in ("unknown_event_type", "critical_schema_type",
                                      "output_usage_unknown", "incomplete_turn"):
        return "unknown"
    if isinstance(process.get("exit_code"), int) and process["exit_code"] != 0:
        return "failure"
    if process.get("stop_reason") or process.get("terminal_status") == "interruption":
        return "interruption"
    if quality.get("success"):
        return "success"
    return "quality_failure" if process.get("exit_code") == 0 else "unknown"


def record_metadata_failure(process, reason):
    """Keep a provider/runtime cause primary while recording fixed metadata failure labels."""
    process["metadata_failure"] = reason
    if not process.get("stop_reason") and not process.get("terminal_status"):
        process["stop_reason"] = reason


def final_quality_success(process, quality):
    return bool(quality.get("success") and quality.get("runtime_effective") and
                not process.get("stop_reason") and not process.get("terminal_status") and
                process.get("codex_arg0_cleanup") != "failed" and
                process.get("runtime_metadata_tightening") != "failed")

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
        except OSError as error:
            if error.errno == errno.ESRCH:
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
    parent_hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    nofile_cap = LIMITS["child_nofile_cap"] if parent_hard == resource.RLIM_INFINITY else min(
        LIMITS["child_nofile_cap"], parent_hard)
    if not isinstance(nofile_cap, int) or nofile_cap < 1:
        raise RuntimeError("parent RLIMIT_NOFILE hard limitが不正")
    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile_cap, nofile_cap))
    cpu = max(1, min(605, int(timeout) + 5))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))

def run_finite(command, prompt, env, stdout_path, stderr_path, runtime, timeout, cwd):
    start, process, selector, reason = time.monotonic(), None, selectors.DefaultSelector(), None
    process_group_reaped = True
    prompt_bytes = prompt.encode()
    process_started = prompt_sent = False
    launch_error = None; exit_code = None
    targets = {}; totals = {}
    seen = {"tool_ids": set(), "turn_ids": set(), "models": set(), "efforts": set(), "tiers": set(),
            "unknown_item_types": set(), "hook_events": set(), "commands": [], "bash_tools": {},
            "denied_commands": [], "output_tokens": 0, "usage_observed": False,
            "session_output_tokens": 0, "session_usage_observed": False, "compact_events": 0,
            "session_id": None, "rejection": False, "terminal_status": None,
            "warning_items": 0, "turn_completed": False}
    seen["model_response_observed"] = False
    for path in (stdout_path, stderr_path):
        generated_root(path)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(descriptor)
    try:
        process = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True, umask=0o077,
                                   preexec_fn=lambda: apply_child_limits(timeout))
        process_started = True
        try:
            written = process.stdin.write(prompt_bytes)
            process.stdin.close()
            prompt_sent = written == len(prompt_bytes)
        except (BrokenPipeError, OSError):
            prompt_sent = False
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
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
    except OSError as error:
        launch_error = type(error).__name__
        reason = "launch_error" if not process_started else "io_error"
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
            try:
                os.killpg(process.pid, 0)
            except OSError as error:
                process_group_reaped = error.errno == errno.ESRCH
            else:
                process_group_reaped = False
    elapsed_seconds = round(time.monotonic() - start, 3)
    return {"exit_code": exit_code, "stop_reason": reason, "session_id": seen["session_id"],
            "process_started": process_started, "prompt_sent": prompt_sent,
            "materialized_prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "materialized_prompt_bytes": len(prompt_bytes),
            "sent_prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest() if prompt_sent else None,
            "sent_prompt_bytes": len(prompt_bytes) if prompt_sent else None,
            "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest() if prompt_sent else None,
            "model_called": bool(process_started and prompt_sent),
            "model_response_observed": seen["model_response_observed"],
            "launch_error": launch_error,
            "tool_events": len(seen["tool_ids"]), "turns": len(seen["turn_ids"]),
            "output_tokens": seen["output_tokens"], "compact_events": seen["compact_events"],
            "session_output_tokens": seen["session_output_tokens"],
            "stdout_bytes": totals.get(process.stdout, 0) if process is not None else 0,
            "stderr_bytes": totals.get(process.stderr, 0) if process is not None else 0,
            "rejection": seen["rejection"], "terminal_status": seen["terminal_status"],
            "warning_items": seen["warning_items"], "turn_completed": seen["turn_completed"],
            "effective_model": next(iter(seen["models"])) if len(seen["models"]) == 1 else None,
            "effective_effort": next(iter(seen["efforts"])) if len(seen["efforts"]) == 1 else None,
            "observed_models": sorted(seen["models"]), "observed_efforts": sorted(seen["efforts"]),
            "actual_tier": next(iter(seen["tiers"])) if len(seen["tiers"]) == 1 else None,
            "hook_events": sorted(seen["hook_events"]), "commands": seen["commands"],
            "denied_commands": seen["denied_commands"],
            "unknown_item_types": sorted(seen["unknown_item_types"]),
            "elapsed_seconds": elapsed_seconds,
            "elapsed_ms": round(elapsed_seconds * 1000, 3),
            "process_group_reaped": process_group_reaped}


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
    bundle = manifest["comparison_bundles"][key]; controls = {}; host_sources = {}
    for item in bundle["files"]:
        source = (root / "runtime/host-sources" / Path(item["target"]).name
                  if item["class"] == "host_fixture_helper" else
                  root / "runtime/bundles" / row["candidate"] / row["runtime"] / row["variant"] / item["target"])
        if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit(f"staged comparison bundleが変化した: {key}:{item['target']}")
        if item["class"] == "host_fixture_helper":
            host_sources[Path(item["target"]).name] = source
            continue
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
            "evaluation_kind": bundle["evaluation_kind"], "candidate": row["candidate"],
            "host_sources": host_sources}


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


def prompt_for(row, spec, outside_marker=None, mechanism=None):
    if row["kind"] == "smoke" and row["runtime"] == "claude":
        commands = [shlex.join(command) for command in claude_smoke_commands(generated_root(outside_marker))]
        return ("境界検証専用の合成fixtureです。Bashで次の4 commandを順に各1回、そのまま実行する。"
                f"最初に {commands[0]} 。続けて {commands[1]} 、{commands[2]} 、{commands[3]} 。"
                "後の3件の拒否を回避せず、結果を短く返す。")
    if row["kind"] == "smoke":
        return '合成fixtureの接続確認です。編集や外部アクセスをせず、{"ok":true}だけを返してください。'
    base = f"隔離した合成fixtureです。外部通信、認証操作、commit、削除を行わない。{spec['instruction']}"
    return base + (("\n" + mechanism) if mechanism else "")


def run_host_helper(root, row, spec, bundle, manifest):
    if bundle["evaluation_kind"] != "host-supervised-helper":
        return None
    base = root / "runtime/host-helper" / row["run_id"]
    python = manifest["fixture_tools"]["python_cli"]["binary"]
    # HOME itself is a live boundary input.  The prepared manifest carries
    # only its digest; pass that existing binding and never persist the path.
    home_sha256 = (manifest.get("environment") or {}).get("home_sha256")
    if not isinstance(home_sha256, str) or len(home_sha256) != 64:
        raise host_helper.HelperError("home_identity_unavailable")
    dependencies = (manifest.get("host_dependencies") or {}) if row.get("fixture") == "repo_tsc_once" else {}
    host = host_helper.supervise(base, row, spec, bundle["host_sources"], dependencies,
                                 python, home_sha256)
    try:
        return validate_host_hashes(row, spec, host)
    except host_helper.HelperError as error:
        error.host = host
        raise


def host_pre_model_failure(row, reason, elapsed_ms=0, host=None, binding_valid=None, normalized=None):
    """Close a helper preflight failure as one consumed, model-free attempt."""
    reason = str(reason)[:256]
    try:
        elapsed_ms = max(0, round(float(elapsed_ms), 3))
    except (TypeError, ValueError):
        elapsed_ms = 0
    if (isinstance(host, dict) and isinstance(host.get("result"), dict) and
            isinstance(host.get("evidence"), dict)):
        preserved = copy.deepcopy(host)
        evidence = preserved["evidence"]
        evidence.update(model_received_helper_result=False, task_outcome_passed=False,
                        failure_reason=reason, pre_model_failed=True, pair_stop=True)
        if normalized is False:
            evidence.setdefault("raw_helper_mechanism_observed",
                                evidence.get("helper_mechanism_observed"))
            evidence["helper_mechanism_observed"] = False
            evidence["normalized"] = False
        elif normalized is True:
            evidence["normalized"] = True
        if binding_valid is False:
            evidence.setdefault("raw_helper_mechanism_observed",
                                evidence.get("helper_mechanism_observed"))
            evidence["helper_mechanism_observed"] = False
            evidence["binding_valid"] = False
        elif binding_valid is True:
            evidence["binding_valid"] = True
        preserved["pair_stop"] = True
        return preserved
    owner = getattr(host_helper, "RESULT_OWNER", "harness-host-helper-result-v1")
    schema = getattr(host_helper, "SCHEMA", 1)
    result = {"owner": owner, "schema": schema, "candidate": row["candidate"],
              "fixture": row["fixture"], "status": "failed", "mechanism": "host-helper",
              "payload": {"context": "", "facts": {"failure_reason": reason}, "diagnostics": []},
              "references": []}
    result["content_hash"] = host_helper.digest(result)
    evidence = {"helper_mechanism_observed": False, "model_received_helper_result": False,
                "task_outcome_passed": False, "request_hash": None,
                "result_hash": result["content_hash"], "operations": [], "operation_count": 0,
                "elapsed_ms": elapsed_ms, "generated": {"files": None, "bytes": None},
                "failure_reason": reason, "pre_model_failed": True, "pair_stop": True,
                "binding_valid": False, "normalized": False}
    return {"result": result, "evidence": evidence, "pair_stop": True}


def exception_reason(error):
    reason = getattr(error, "reason", None)
    if reason is None:
        reason = str(error)
    return str(reason or type(error).__name__)[:256]


def host_contract_error(reason, host, binding_valid=False):
    error = host_helper.HelperError(reason)
    error.host, error.binding_valid = host, binding_valid
    return error


def host_request(row, spec):
    request_row = dict(row)
    request_row.setdefault("variant", "baseline")
    return host_helper.make_request(request_row, spec)


def valid_hash64(value):
    return isinstance(value, str) and HASH64.fullmatch(value) is not None


def validate_host_hashes(row, spec, host):
    """Require the helper's signed request/result hashes before model launch."""
    if not isinstance(host, dict) or not isinstance(host.get("result"), dict) or \
            not isinstance(host.get("evidence"), dict):
        raise host_contract_error("helper_result_schema_invalid", host)
    result, evidence = host["result"], host["evidence"]
    request_hash = evidence.get("request_hash")
    if not valid_hash64(request_hash):
        raise host_contract_error("helper_request_hash_invalid", host)
    result_hash = evidence.get("result_hash")
    if not valid_hash64(result_hash):
        raise host_contract_error("helper_result_hash_invalid", host)
    content_hash = result.get("content_hash")
    if not valid_hash64(content_hash):
        raise host_contract_error("helper_result_content_hash_invalid", host)
    if result_hash != content_hash:
        raise host_contract_error("helper_result_hash_mismatch", host)
    unsigned = dict(result)
    unsigned.pop("content_hash", None)
    if host_helper.digest(unsigned) != content_hash:
        raise host_contract_error("helper_result_content_hash_mismatch", host)
    expected_request_hash = host_helper.digest(host_request(row, spec))
    if request_hash != expected_request_hash:
        raise host_contract_error("helper_request_hash_mismatch", host)
    evidence["binding_valid"] = True
    return host


def write_host_pre_model_result(root, result_path, row, template_sha256, prompt_audit, host,
                                run_started, helper_started_at, model_finished_at,
                                helper_wall_elapsed_ms, process=None):
    end_to_end = (max(0, round((model_finished_at - helper_started_at) * 1000, 3))
                  if helper_started_at is not None and model_finished_at is not None else None)
    run_elapsed = (max(0, round((model_finished_at - run_started) * 1000, 3))
                   if model_finished_at is not None else None)
    reason = host["evidence"].get("failure_reason")
    timing = {"run_elapsed_ms": run_elapsed,
              "helper_elapsed_ms": host["evidence"].get("elapsed_ms"),
              "helper_wall_elapsed_ms": helper_wall_elapsed_ms, "model_elapsed_ms": None,
              "helper_to_model_end_elapsed_ms": end_to_end, "end_to_end_elapsed_ms": end_to_end}
    write_json(root / f"results/host-blocked-{row['candidate']}.json",
               {"owner": OWNER, "schema": 1, "candidate": row["candidate"], "run_id": row["run_id"],
                "status": "pending_helper_blocked", "reason": reason})
    write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "run": row,
                             "status": "pre_model_failed", "missing_reason": "pre_model_helper_failed",
                             "failure_reason": reason, "model_called": False, "prompt_sent": False,
                             "model_received_helper_result": False, "template_sha256": template_sha256,
                             "materialized_prompt_sha256": prompt_audit["materialized_prompt_sha256"],
                             "materialized_prompt_bytes": prompt_audit["materialized_prompt_bytes"],
                             "sent_prompt_sha256": None, "sent_prompt_bytes": None,
                             "model_response_observed": False, "process": process or {
                                 "process_started": False, "prompt_sent": False, "model_called": False,
                                 "model_response_observed": False, "stop_reason": "pre_model_failed"},
                             "prompt": prompt_audit, "timing": timing,
                             "end_to_end_elapsed_ms": end_to_end, "host_helper": host})
    return True


def normalize_host_result(row, host, spec=None):
    """Validate the cross-process result contract before model invocation."""
    validate_host_hashes(row, spec or fixture(row["fixture"]), host)
    result, evidence = host["result"], host["evidence"]
    if result.get("owner") != getattr(host_helper, "RESULT_OWNER", "harness-host-helper-result-v1") or \
            result.get("schema") != getattr(host_helper, "SCHEMA", 1) or \
            result.get("candidate") != row.get("candidate") or result.get("fixture") != row.get("fixture"):
        raise host_helper.HelperError("helper_result_identity_invalid")
    payload = result.get("payload")
    unsigned = dict(result); claimed_hash = unsigned.pop("content_hash", None)
    if (not isinstance(payload, dict) or set(payload) != {"context", "facts", "diagnostics"} or
            not isinstance(payload["context"], str) or not isinstance(payload["facts"], dict) or
            not isinstance(payload["diagnostics"], list) or
            not isinstance(claimed_hash, str) or host_helper.digest(unsigned) != claimed_hash):
        raise host_helper.HelperError("helper_result_payload_invalid")
    try:
        encoded_result = host_helper.canonical(result).decode("utf-8")
    except (UnicodeDecodeError, TypeError, ValueError) as error:
        raise host_helper.HelperError("helper_result_canonical_invalid") from error
    expected_prompt_context = f'<mechanism-context schema="host-helper-result-v1">{encoded_result}</mechanism-context>'
    if "prompt_context" in host and host["prompt_context"] != expected_prompt_context:
        raise host_helper.HelperError("helper_prompt_context_invalid")
    host["prompt_context"] = expected_prompt_context
    required = {"helper_mechanism_observed", "failure_reason", "operation_count"}
    if not required <= set(evidence) or not isinstance(host.get("pair_stop"), bool) or \
            not isinstance(evidence.get("helper_mechanism_observed"), bool) or \
            not isinstance(evidence.get("operation_count"), int) or evidence["operation_count"] < 0:
        raise host_helper.HelperError("helper_evidence_schema_invalid")
    evidence["pair_stop"] = host["pair_stop"]
    target = row.get("fixture") in getattr(host_helper, "FIXTURE_TARGETS", {}).get(row.get("candidate"), set())
    if target and result.get("status") not in {"observed", "failed"}:
        raise host_helper.HelperError("target_result_status_invalid")
    if not target and (evidence.get("operation_count") != 0 or evidence.get("helper_mechanism_observed") is not False):
        raise host_helper.HelperError("neutral_helper_observation_invalid")
    if target and result.get("status") == "observed" and evidence.get("helper_mechanism_observed") is not True:
        raise host_helper.HelperError("target_helper_observation_missing")
    if not target and result.get("status") != "neutral":
        raise host_helper.HelperError("neutral_result_status_invalid")
    if result.get("status") == "failed" and host["pair_stop"] is not True:
        raise host_helper.HelperError("failed_result_not_pair_stop")
    evidence["normalized"] = True
    return host


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
        if row["runtime"] == "codex":
            cleanup_codex_arg0_helpers(root, manifest)
    except SystemExit:
        write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "run": row,
                                 "status": "unknown", "missing_reason": "prelaunch_validation_failed"})
        raise
    bundle_key = ":".join((row["candidate"], row["runtime"], row["variant"])) if row["kind"] == "compare" else None
    declared_bundle = (manifest.get("comparison_bundles", {}).get(bundle_key) or {}) if bundle_key else {}
    host_manifest_expected = declared_bundle.get("evaluation_kind") == "host-supervised-helper"
    try:
        work = materialize(root, row, manifest) if row["kind"] == "compare" else materialize_smoke(root, row)
        bundle = (materialize_bundle(root, row, work, manifest) if row["kind"] == "compare" else
                  {"bundle_hash": None, "control_hashes": {}, "runtime_settings": None,
                   "evaluation_kind": "smoke", "host_sources": {}})
    except (Exception, SystemExit) as error:
        if not host_manifest_expected:
            raise
        finished_at = time.monotonic()
        reason = exception_reason(error)
        elapsed_ms = max(0, round((finished_at - run_started) * 1000, 3))
        template_sha256 = (manifest.get("prompt_hashes", {}) or {}).get(row["run_id"])
        if not isinstance(template_sha256, str):
            template_sha256 = None
        prompt_audit = {"template_sha256": template_sha256, "materialized_prompt_sha256": None,
                        "materialized_prompt_bytes": None, "sent_prompt_sha256": None,
                        "sent_prompt_bytes": None, "materialized_prompt_status": "not_materialized",
                        "materialized_prompt_reason": reason,
                        "helper_result_sha256": None, "helper_context_sha256": None}
        host = host_pre_model_failure(row, reason, elapsed_ms)
        prompt_audit["helper_result_sha256"] = host["result"]["content_hash"]
        return write_host_pre_model_result(root, result_path, row, template_sha256, prompt_audit, host,
                                           run_started, run_started, finished_at, elapsed_ms)
    stdout = root / "logs" / f"{row['run_id']}.jsonl"; stderr = root / "logs" / f"{row['run_id']}.stderr.log"
    spec = fixture(row["fixture"], manifest) if row["kind"] == "compare" else None
    host_expected = bool(spec and bundle["evaluation_kind"] == "host-supervised-helper")
    template = prompt_for(row, spec, root / CLAUDE_MARKER, HOST_SLOT if host_expected else None)
    template_sha256 = hashlib.sha256(template.encode()).hexdigest()
    prompt_audit = {"template_sha256": template_sha256, "materialized_prompt_sha256": None,
                    "materialized_prompt_bytes": None, "sent_prompt_sha256": None,
                    "sent_prompt_bytes": None, "materialized_prompt_status": "not_materialized",
                    "materialized_prompt_reason": "pending",
                    "helper_result_sha256": None, "helper_context_sha256": None}
    host = None
    helper_started_at = helper_finished_at = model_finished_at = None
    helper_wall_elapsed_ms = None
    if host_expected:
        helper_started_at = time.monotonic()
        raw_host = None
        try:
            raw_host = run_host_helper(root, row, spec, bundle, manifest)
            host = normalize_host_result(row, raw_host, spec)
        except Exception as error:
            # Helper validation is a pre-model gate.  It consumes this attempt
            # and closes the result locally so no model can run on unverified
            # evidence and no retry can silently change the denominator.
            helper_finished_at = time.monotonic()
            helper_wall_elapsed_ms = max(0, round((helper_finished_at - helper_started_at) * 1000, 3))
            reason = exception_reason(error)
            preserved_host = getattr(error, "host", None)
            if preserved_host is None:
                preserved_host = raw_host
            binding_valid = getattr(error, "binding_valid", None)
            if binding_valid is None:
                binding_valid = bool(isinstance(preserved_host, dict) and
                                     isinstance(preserved_host.get("evidence"), dict) and
                                     preserved_host["evidence"].get("binding_valid") is True)
            host = host_pre_model_failure(row, reason, helper_wall_elapsed_ms, preserved_host,
                                          binding_valid=binding_valid, normalized=False)
            prompt_audit["materialized_prompt_reason"] = reason
        else:
            helper_finished_at = time.monotonic()
            helper_wall_elapsed_ms = max(0, round((helper_finished_at - helper_started_at) * 1000, 3))
        prompt_audit["helper_result_sha256"] = (host.get("result") or {}).get("content_hash")
        if isinstance(host.get("prompt_context"), str):
            prompt_audit["helper_context_sha256"] = hashlib.sha256(host["prompt_context"].encode()).hexdigest()
    if host and host["pair_stop"]:
        model_finished_at = helper_finished_at
        return write_host_pre_model_result(root, result_path, row, template_sha256, prompt_audit, host,
                                           run_started, helper_started_at, model_finished_at,
                                           helper_wall_elapsed_ms)
    try:
        required = (spec.get("required_commands", []) if spec else
                    claude_smoke_commands(root) if row["runtime"] == "claude" else [])
        command = command_for(row["runtime"], config, work,
                              session if row.get("fixture") == "long_resume" else None, bundle, required)
    except SystemExit as error:
        model_finished_at = time.monotonic()
        if host_expected:
            reason = exception_reason(error)
            elapsed_ms = (max(0, round((model_finished_at - helper_started_at) * 1000, 3))
                          if helper_started_at is not None else max(0, round((model_finished_at - run_started) * 1000, 3)))
            host = host_pre_model_failure(row, reason, elapsed_ms, host)
            prompt_audit.update(materialized_prompt_reason=reason,
                                helper_result_sha256=(host.get("result") or {}).get("content_hash"),
                                helper_context_sha256=(hashlib.sha256(host["prompt_context"].encode()).hexdigest()
                                                       if isinstance(host.get("prompt_context"), str) else None))
            return write_host_pre_model_result(root, result_path, row, template_sha256, prompt_audit, host,
                                               run_started, helper_started_at, model_finished_at,
                                               helper_wall_elapsed_ms)
        end_to_end = (max(0, round((model_finished_at - helper_started_at) * 1000, 3))
                      if helper_started_at is not None else None)
        write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "run": row,
                                 "status": "unknown", "missing_reason": "runtime_settings_invalid",
                                 "model_called": False, "template_sha256": template_sha256,
                                 "materialized_prompt_sha256": None, "materialized_prompt_bytes": None,
                                 "sent_prompt_sha256": None, "sent_prompt_bytes": None,
                                 "model_response_observed": False, "prompt": {**prompt_audit,
                                     "materialized_prompt_reason": "runtime_settings_invalid"},
                                 "timing": {"run_elapsed_ms": round((model_finished_at - run_started) * 1000, 3),
                                            "helper_elapsed_ms": (host["evidence"].get("elapsed_ms") if host else None),
                                            "helper_wall_elapsed_ms": helper_wall_elapsed_ms,
                                            "model_elapsed_ms": None, "helper_to_model_end_elapsed_ms": end_to_end,
                                            "end_to_end_elapsed_ms": end_to_end},
                                 "end_to_end_elapsed_ms": end_to_end})
        return True
    prompt = None; materialized_sha256 = None; materialized_prompt_bytes = None
    try:
        process_timeout = timeout - (time.monotonic() - run_started)
        if process_timeout <= 0:
            raise subprocess.TimeoutExpired("run setup", timeout)
        context = host["prompt_context"] if host else None
        prompt = prompt_for(row, spec, root / CLAUDE_MARKER, context)
        materialized_prompt_bytes = prompt.encode()
        materialized_sha256 = hashlib.sha256(materialized_prompt_bytes).hexdigest()
        prompt_audit.update(materialized_prompt_sha256=materialized_sha256,
                            materialized_prompt_bytes=len(materialized_prompt_bytes),
                            materialized_prompt_status="materialized")
        if template_sha256 != manifest["prompt_hashes"].get(row["run_id"]):
            raise SystemExit("promptが準備時から変化した")
        runtime_root = root / "runtime" / row["runtime"]
        runtime_before = runtime_private_snapshot(runtime_root)
        protected_runtime_paths = runtime_protected_paths(runtime_root)
        native_runtime_inventory = runtime_native_inventory(runtime_before, protected_runtime_paths)
        process = run_finite(command, prompt, child_env(root, row["runtime"], work), stdout, stderr,
                             row["runtime"], process_timeout, work)
    except SystemExit as error:
        if not host_expected:
            raise
        failed_at = time.monotonic()
        reason = exception_reason(error)
        elapsed_ms = (max(0, round((failed_at - helper_started_at) * 1000, 3))
                      if helper_started_at is not None else max(0, round((failed_at - run_started) * 1000, 3)))
        host = host_pre_model_failure(row, reason, elapsed_ms, host)
        prompt_audit.update(materialized_prompt_reason=reason,
                            sent_prompt_sha256=None, sent_prompt_bytes=None,
                            helper_result_sha256=host["result"]["content_hash"],
                            helper_context_sha256=(hashlib.sha256(host["prompt_context"].encode()).hexdigest()
                                                   if isinstance(host.get("prompt_context"), str) else None))
        return write_host_pre_model_result(root, result_path, row, template_sha256, prompt_audit, host,
                                           run_started, helper_started_at, failed_at,
                                           helper_wall_elapsed_ms)
    except (OSError, subprocess.TimeoutExpired) as error:
        process = {"exit_code": None, "stop_reason": ("timeout" if isinstance(error, subprocess.TimeoutExpired)
                                                        else "launch_error"),
                   "process_started": False, "prompt_sent": False, "prompt_sha256": None,
                   "materialized_prompt_sha256": materialized_sha256,
                   "materialized_prompt_bytes": materialized_prompt_bytes and len(materialized_prompt_bytes),
                   "sent_prompt_sha256": None, "sent_prompt_bytes": None, "model_called": False,
                   "model_response_observed": False,
                   "session_id": None, "tool_events": 0,
                   "turns": 0, "output_tokens": 0, "compact_events": 0, "rejection": False,
                   "terminal_status": None, "effective_model": None, "effective_effort": None,
                   "observed_models": [], "observed_efforts": [],
                   "actual_tier": None, "hook_events": [], "commands": [], "denied_commands": [],
                   "unknown_item_types": [],
                   "launch_error": type(error).__name__}
    actual_runtime_post = "runtime_before" in locals() and "process_group_reaped" in process
    if actual_runtime_post:
        try:
            if row["runtime"] == "codex":
                def tighten_after_cleanup():
                    process["runtime_metadata_tightening"] = tighten_fresh_runtime_files(
                        runtime_root, runtime_before, process["process_group_reaped"],
                        native_runtime_inventory, protected_runtime_paths)
                cleanup_codex_arg0_helpers(root, manifest, after_cleanup=tighten_after_cleanup)
                process["codex_arg0_cleanup"] = "passed"
            else:
                process["runtime_metadata_tightening"] = tighten_fresh_runtime_files(
                    runtime_root, runtime_before, process["process_group_reaped"],
                    native_runtime_inventory, protected_runtime_paths)
        except SystemExit as error:
            process["runtime_metadata_tightening"] = "failed"
            process["runtime_metadata_tightening_reason"] = exception_reason(error)
            record_metadata_failure(process, "runtime_metadata_tightening_failed")
    elif row["runtime"] == "codex":
        try:
            cleanup_codex_arg0_helpers(root, manifest)
            process["codex_arg0_cleanup"] = "passed"
        except SystemExit as error:
            process["codex_arg0_cleanup"] = "failed"
            process["codex_arg0_cleanup_reason"] = exception_reason(error)
            process["stop_reason"] = "codex_arg0_cleanup_failed"
    model_finished_at = time.monotonic()
    sent_prompt_sha256 = process.get("sent_prompt_sha256")
    sent_prompt_bytes = process.get("sent_prompt_bytes")
    if process.get("prompt_sent") is True:
        prompt_audit.update(sent_prompt_sha256=sent_prompt_sha256,
                            sent_prompt_bytes=sent_prompt_bytes)
    else:
        prompt_audit.update(sent_prompt_sha256=None, sent_prompt_bytes=None)
    if host_expected and (process.get("process_started") is not True or process.get("prompt_sent") is not True):
        reason = process.get("stop_reason") or "model_not_started"
        host = host_pre_model_failure(row, reason, max(0, round((model_finished_at - helper_started_at) * 1000, 3)), host)
        prompt_audit["materialized_prompt_reason"] = reason
        return write_host_pre_model_result(root, result_path, row, template_sha256, prompt_audit, host,
                                           run_started, helper_started_at, model_finished_at,
                                           helper_wall_elapsed_ms, process=process)
    prompt_verified = bool(process.get("process_started") is True and process.get("prompt_sent") is True and
                           materialized_sha256 and sent_prompt_sha256 == materialized_sha256 and
                           sent_prompt_bytes == len(materialized_prompt_bytes or b""))
    if prompt_verified:
        prompt_audit.update(materialized_prompt_status="sent", materialized_prompt_reason=None)
    elif process.get("process_started") is not True:
        prompt_audit["materialized_prompt_reason"] = "process_not_started"
    elif process.get("prompt_sent") is not True:
        prompt_audit["materialized_prompt_reason"] = "stdin_not_sent"
    else:
        prompt_audit["materialized_prompt_reason"] = "materialized_prompt_hash_mismatch"
        process["stop_reason"] = "materialized_prompt_hash_mismatch"
    end_to_end = (max(0, round((model_finished_at - helper_started_at) * 1000, 3))
                  if helper_started_at is not None else None)
    quality = (score(work, spec, process, bundle["control_hashes"]) if spec else
               smoke_quality(root, row, work, process, manifest))
    process["resume_used"] = bool(session and row.get("fixture") == "long_resume")
    process["runtime_identity"] = confirm_runtime_identity(row["runtime"], process, config)
    quality["runtime_effective"] = process["runtime_identity"]["confirmed"]
    quality["success"] = final_quality_success(process, quality)
    status_name = classify_status(process, quality)
    metric_status = "failure" if status_name == "quality_failure" else status_name
    remaining = timeout - (time.monotonic() - run_started)
    measurement = metrics(root, row, config, stdout, process["session_id"], metric_status, process, remaining)
    timing = {"run_elapsed_ms": max(0, round((model_finished_at - run_started) * 1000, 3)),
              "helper_elapsed_ms": (host["evidence"].get("elapsed_ms") if host else None),
              "helper_wall_elapsed_ms": helper_wall_elapsed_ms,
              "model_elapsed_ms": (max(0, round(float(process["elapsed_seconds"]) * 1000, 3))
                                   if isinstance(process.get("elapsed_seconds"), (int, float)) else None),
              "helper_to_model_end_elapsed_ms": end_to_end, "end_to_end_elapsed_ms": end_to_end}
    model_called = bool(process.get("process_started") is True and process.get("prompt_sent") is True)
    model_response_observed = process.get("model_response_observed") is True
    helper_received = bool(host and prompt_verified and model_response_observed)
    write_json(result_path, {"owner": OWNER, "schema": 1, "completed": True, "completed_at": now(), "run": row,
                             "status": status_name, "config_hash": digest(config), "process": process,
                             "configured_timeout_seconds": config["run_timeout_seconds"],
                             "config_epoch": config["locked_at"],
                             "bundle": {"bundle_hash": bundle["bundle_hash"], "evaluation_kind": bundle["evaluation_kind"],
                                        "source_hashes_before": bundle["control_hashes"],
                                        "source_hashes_after": quality.get("control_hashes_after", {})},
                             "quality": quality, "metrics": measurement, "model_called": model_called,
                             "template_sha256": template_sha256,
                             "materialized_prompt_bytes": prompt_audit["materialized_prompt_bytes"],
                             "materialized_prompt_sha256": prompt_audit["materialized_prompt_sha256"],
                             "sent_prompt_bytes": prompt_audit["sent_prompt_bytes"],
                             "sent_prompt_sha256": prompt_audit["sent_prompt_sha256"],
                             "model_response_observed": model_response_observed,
                             "prompt": prompt_audit, "timing": timing,
                             "end_to_end_elapsed_ms": end_to_end,
                             "host_helper": ({"result": host["result"], "evidence": {**host["evidence"],
                                 "model_received_helper_result": helper_received,
                                 "task_outcome_passed": bool(helper_received and quality["success"])},
                                 "pair_stop": False} if host else None),
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


HOST_PARENT_USAGE_REASON = "includes_children_unknown"


def _actual_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def host_parent_usage_ready(metric, record):
    """Allow only complete parent usage when child scope is the sole unknown."""
    coverage = (metric.get("coverage") or {}).get("usage") or {}
    identity = (record.get("process") or {}).get("runtime_identity") or {}
    model = identity.get("model") or {}
    if (model.get("confirmed") is not True or not isinstance(model.get("value"), str)
            or metric.get("model") != model.get("value")):
        return False
    tokens = metric.get("tokens")
    if not isinstance(tokens, dict):
        return False
    input_tokens = tokens.get("input_total")
    if input_tokens is None:
        input_tokens = tokens.get("input_tokens")
    output_tokens = tokens.get("output_tokens")
    if not (_actual_number(input_tokens) and _actual_number(output_tokens)):
        return False
    if coverage.get("scope") != "parent_claim":
        return False
    expected = coverage.get("expected")
    observed = coverage.get("observed")
    rate = coverage.get("rate")
    if not (_actual_number(expected) and expected > 0 and _actual_number(observed)
            and observed == expected and _actual_number(rate) and rate == 1):
        return False
    reasons = coverage.get("reasons")
    if metric_ready(metric, "usage") and reasons == []:
        return True
    return (reasons == [HOST_PARENT_USAGE_REASON]
            and (record.get("run") or {}).get("runtime") == "codex")


def host_selection_metric_ready(metric, name, record):
    if name == "usage":
        return host_parent_usage_ready(metric, record)
    return metric_ready(metric, name)


def comparison_blockers(root, allow_host_parent_usage=False):
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
        usage_ready = (host_parent_usage_ready(metric, smoke)
                       if allow_host_parent_usage else metric_ready(metric, "usage"))
        if not usage_ready:
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


def host_subset_blockers(root, manifest, candidate):
    blockers = comparison_blockers(root, allow_host_parent_usage=True)
    for runtime in ("codex", "claude"):
        kinds = {manifest["comparison_bundles"][":".join((candidate, runtime, variant))]["evaluation_kind"]
                 for variant in ("baseline", "candidate")}
        if kinds != {"host-supervised-helper"}:
            blockers.append(f"{candidate}:{runtime}:host_helper_bundle_missing")
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
    if args.smoke_only and args.host_subset:
        raise SystemExit("--host-subsetは比較run専用")
    config = lock_config(root, manifest, args,
                         (args.smoke_runtime,) if args.smoke_only else ("codex", "claude"))
    if not args.smoke_only and args.candidate not in manifest["candidates"]:
        raise SystemExit("比較runはmanifest内の--candidateを1件指定する")
    if args.host_subset and (root / "results" / f"host-blocked-{args.candidate}.json").exists():
        raise SystemExit("helper前処理失敗済みのためcandidate残scheduleはpending_helper_blocked")
    capability_failures = ([] if args.host_subset else
        capability_blockers(root, manifest, not args.smoke_only, args.candidate, args.smoke_runtime))
    if capability_failures:
        raise SystemExit("runtime capability未確認: " + ",".join(capability_failures))
    rows = [row for row in manifest["schedule"] if row["kind"] == ("smoke" if args.smoke_only else "compare") and
            ((args.smoke_only and row["runtime"] == args.smoke_runtime) or
             (not args.smoke_only and row.get("candidate") == args.candidate)) and
            (not args.host_subset or row.get("fixture") not in ("long_compact", "long_resume"))]
    if not args.smoke_only:
        index = manifest["candidates"].index(args.candidate)
        previous = set(manifest["candidates"][:index])
        unfinished = [row["run_id"] for row in manifest["schedule"]
                      if row.get("candidate") in previous and
                      (not args.host_subset or row.get("fixture") not in ("long_compact", "long_resume")) and
                      not scheduled_complete(root, row)]
        if unfinished:
            raise SystemExit(f"candidate順序未達: {manifest['candidates'][index - 1]}を先に完了する")
        blockers = host_subset_blockers(root, manifest, args.candidate) if args.host_subset else comparison_blockers(root)
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
            if (root / "results" / f"host-blocked-{args.candidate}.json").exists():
                progress = False; break
        if not progress:
            break
    print(json.dumps({"completed": len(rows) - len(pending), "pending": len(pending), "retry": 0,
                      "candidate": args.candidate, "host_subset": args.host_subset,
                      "native_pending": 24 if args.host_subset else 0,
                      "comparison_started": not args.smoke_only}, ensure_ascii=False))
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


def host_metric_coverage(pairs, metric_names, qualification_key="paired_qualified"):
    expected = len(pairs)
    qualified = lambda item, name: (item.get(qualification_key) or {}).get(name) is True
    return {name: {"expected_pairs": expected,
                   "qualified_pairs": sum(qualified(item, name) for item in pairs),
                   "complete": expected > 0 and all(qualified(item, name) for item in pairs),
                   "rate": (sum(qualified(item, name) for item in pairs) / expected if expected else 0)}
            for name in metric_names}


def host_quality_violations(records):
    """Count explicit quality failures; missing fields are covered separately."""
    fields = ("gate", "no_symlinks", "workspace_within_limit", "control_files_unchanged",
              "restore", "native", "runtime_effective")
    by_field = {name: sum(record.get("quality", {}).get(name) is False for record in records)
                for name in fields}
    boundary = sum(record.get("quality", {}).get("gate") is False for record in records)
    quality0 = sum(any(record.get("quality", {}).get(name) is False for name in fields)
                   for record in records)
    return {"boundary": boundary, "quality0": quality0, "by_field": by_field}


def host_quality_coverage(records, expected=None):
    fields = ("success", "gate", "no_symlinks", "workspace_within_limit", "control_files_unchanged",
              "restore", "native", "runtime_effective")
    expected = len(records) if expected is None else expected
    return {name: {"expected": expected,
                   "observed": sum(isinstance((record.get("quality") or {}).get(name), bool)
                                    for record in records),
                   "complete": expected > 0 and
                               sum(isinstance((record.get("quality") or {}).get(name), bool)
                                   for record in records) == expected,
                   "rate": (sum(isinstance((record.get("quality") or {}).get(name), bool)
                             for record in records) / expected if expected else 0)}
            for name in fields}


def host_status_coverage(records, statuses, expected=None):
    expected = len(records) if expected is None else expected
    counts = {status: sum(record.get("status") == status for record in records)
              for status in statuses}
    unknown = sorted({record.get("status") for record in records
                      if record.get("status") not in statuses}, key=lambda value: str(value))
    observed = sum(counts.values())
    return {"allowed": list(statuses), "expected": expected, "observed": observed,
            "counts": counts, "unknown": unknown,
            "complete": expected > 0 and len(records) == expected and observed == expected,
            "rate": observed / expected if expected else 0}


def host_model_received_coverage(records, expected=None):
    expected = len(records) if expected is None else expected
    observed = sum((record.get("host_helper") or {}).get("evidence", {}).get(
        "model_received_helper_result") is True for record in records)
    return {"expected": expected, "observed": observed,
            "complete": expected > 0 and len(records) == expected and observed == expected,
            "rate": observed / expected if expected else 0}


def host_pair_stop(record):
    """A stopped helper consumes its run but makes the pair unqualified."""
    if not record:
        return False
    helper = record.get("host_helper") or {}
    evidence = helper.get("evidence") or {}
    return (record.get("status") == "pre_model_failed" or helper.get("pair_stop") is True or
            evidence.get("pair_stop") is True or evidence.get("pre_model_failed") is True)


def host_success_non_decrease(rows, records):
    """Compare success counts independently for each host category/runtime."""
    result = {}
    for runtime in ("codex", "claude"):
        runtime_result = {}
        for variant in ("baseline", "candidate"):
            expected = [row for row in rows if row["runtime"] == runtime and row["variant"] == variant]
            selected = [records[row["run_id"]] for row in expected if row["run_id"] in records]
            runtime_result[variant] = {
                "expected_runs": len(expected), "recorded_runs": len(selected),
                "successes": sum(record.get("quality", {}).get("success") is True for record in selected),
                "complete": len(selected) == len(expected)}
        baseline = runtime_result["baseline"]; candidate = runtime_result["candidate"]
        runtime_result.update({
            "holds": candidate["successes"] >= baseline["successes"],
            "complete": baseline["complete"] and candidate["complete"],
        })
        result[runtime] = runtime_result
    return result


def host_input_token_reduction(pairs, qualification_key="paired_qualified"):
    """Return the paired median reduction for target input tokens."""
    reductions = []
    for item in pairs:
        if not item.get("complete") or (item.get(qualification_key) or {}).get("usage") is not True:
            continue
        baseline = (item.get("baseline") or {}).get("values", {}).get("input_tokens")
        candidate = (item.get("candidate") or {}).get("values", {}).get("input_tokens")
        if isinstance(baseline, (int, float)) and isinstance(candidate, (int, float)) and baseline > 0:
            reductions.append((baseline - candidate) / baseline)
    reductions.sort()
    observed = len(reductions)
    median = (reductions[observed // 2] if observed % 2 else
              (reductions[observed // 2 - 1] + reductions[observed // 2]) / 2 if observed else None)
    return {"observed_pairs": observed, "median": median, "threshold": 0.10,
            "threshold_percent": 10, "eligible": median is not None and median >= 0.10}


def host_category_summary(rows, records, pairs, metric_names, helper_expected=True,
                          qualification_key="paired_qualified"):
    selected = [records[row["run_id"]] for row in rows if row["run_id"] in records]
    fixture_ids = {row["fixture"] for row in rows}
    candidate_id = rows[0]["candidate"] if rows else None
    selected_pairs = [item for item in pairs if item["fixture"] in fixture_ids and
                      item["candidate_id"] == candidate_id]
    expected_runs = len(rows); recorded_runs = len(selected)
    helper_observed = sum((record.get("host_helper") or {}).get("evidence", {}).get(
        "helper_mechanism_observed") is True for record in selected)
    primary_passed = sum((record.get("host_helper") or {}).get("evidence", {}).get(
        "task_outcome_passed") is True for record in selected)
    expected_helper_observations = expected_runs if helper_expected else 0
    return {"expected_runs": expected_runs, "recorded_runs": recorded_runs,
            "expected_pairs": len(selected_pairs),
            "complete": recorded_runs == expected_runs,
            "complete_pairs": sum(item.get("complete") is True for item in selected_pairs),
            "pair_complete": len(selected_pairs) > 0 and all(item.get("complete") is True
                                                               for item in selected_pairs),
            "helper_observed": {"expected": expected_helper_observations, "observed": helper_observed,
                                 "complete": recorded_runs == expected_runs and
                                 helper_observed == expected_helper_observations},
            "primary_outcome": {"expected": expected_runs, "passed": primary_passed,
                                "complete": recorded_runs == expected_runs and primary_passed == expected_runs},
            "metric_coverage": host_metric_coverage(selected_pairs, metric_names, qualification_key),
            "quality_field_coverage": host_quality_coverage(selected, expected_runs),
            "quality_violations": host_quality_violations(selected),
            "success_non_decrease": host_success_non_decrease(rows, records),
            "helper_expected": helper_expected}


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
    host_selection_metrics = ("usage", "tool_calls", "outcome")
    statuses = ("success", "quality_failure", "rejection", "interruption", "failure", "pre_model_failed", "unknown")

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
                    item = {"pair_id": f"{candidate}:{runtime}:{spec['id']}:r{repeat}", "candidate_id": candidate,
                            "runtime": runtime, "fixture": spec["id"], "task_group": spec["group"],
                            "repeat": repeat}
                    for variant, record in pair.items():
                        if not record:
                            item[variant] = None; continue
                        metric = record.get("metrics", {})
                        item[variant] = {"run_id": record["run"]["run_id"], "status": record.get("status"),
                            "quality_success": record.get("quality", {}).get("success") is True,
                            "runtime_identity": (record.get("process") or {}).get("runtime_identity"),
                            "qualified": {name: metric_ready(metric, name) for name in metric_names},
                            "host_qualified": {name: host_selection_metric_ready(metric, name, record)
                                                for name in metric_names},
                            "values": {name: value_of(record, name) for name in
                                       ("input_tokens", "tool_calls", "cost_usd", "elapsed_seconds")}}
                    stopped = any(host_pair_stop(record) for record in pair.values())
                    recorded_pair = all(pair.values())
                    item["pre_model_failed"] = any(
                        record and (record.get("status") == "pre_model_failed" or
                                    (record.get("host_helper") or {}).get("evidence", {}).get(
                                        "pre_model_failed") is True)
                        for record in pair.values())
                    item["pair_stop"] = stopped
                    item["unpaired"] = not (recorded_pair and not stopped)
                    item["complete"] = recorded_pair and not stopped
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
                    item["host_paired_qualified"] = {name: bool(item["complete"] and
                                                            all(item[v]["host_qualified"][name]
                                                                for v in ("baseline", "candidate")) and
                                                            (name != "cost" or pricing_compatible) and
                                                            (name == "outcome" or all(
                                                                item[v]["host_qualified"]["outcome"]
                                                                for v in ("baseline", "candidate"))))
                                                       for name in metric_names}
                    item["deltas"] = {}
                    qualification = {"input_tokens": "usage", "tool_calls": "tool_calls", "cost_usd": "cost"}
                    for name in ("input_tokens", "tool_calls", "cost_usd", "elapsed_seconds"):
                        valid = item["complete"] and (name == "elapsed_seconds" or item["paired_qualified"][qualification[name]])
                        before = item["baseline"]["values"][name] if item["complete"] else None
                        after = item["candidate"]["values"][name] if item["complete"] else None
                        item["deltas"][name] = after - before if valid and all(isinstance(v, (int, float)) for v in (before, after)) else None
                    item["host_deltas"] = {}
                    for name in ("input_tokens", "tool_calls", "cost_usd", "elapsed_seconds"):
                        valid = item["complete"] and (name == "elapsed_seconds" or
                                                        item["host_paired_qualified"][qualification[name]])
                        before = item["baseline"]["values"][name] if item["complete"] else None
                        after = item["candidate"]["values"][name] if item["complete"] else None
                        item["host_deltas"][name] = (after - before
                                                       if valid and all(_actual_number(v) for v in (before, after))
                                                       else None)
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
                selected = [item for item in pairs if item["candidate_id"] == candidate and item["runtime"] == runtime and
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
            relevant = [pair for pair in pairs if pair["candidate_id"] == candidate and pair["runtime"] == runtime]
            adoption_gate[f"{candidate}:{runtime}"] = {
                "eligible": adoption_eligible(baseline_group, candidate_group, relevant),
                "candidate_specific_effect_required": True}
    host_expected = [row for row in manifest["schedule"] if row.get("fixture") not in ("long_compact", "long_resume")
                     and row["kind"] == "compare"]
    native_expected = [row for row in manifest["schedule"] if row.get("fixture") in ("long_compact", "long_resume")]
    host_records = [records[row["run_id"]] for row in host_expected if row["run_id"] in records]
    host_by_candidate = {}
    native_by_candidate = {}
    host_fixture_ids = {row["fixture"] for row in host_expected}
    for candidate in manifest["candidates"]:
        expected_rows = [row for row in host_expected if row["candidate"] == candidate]
        actual_rows = [records[row["run_id"]] for row in expected_rows if row["run_id"] in records]
        candidate_pairs = [item for item in pairs if item["candidate_id"] == candidate and
                           item["fixture"] in host_fixture_ids]
        target_ids = set(host_helper.FIXTURE_TARGETS.get(candidate, set())) & host_fixture_ids
        neutral_ids = host_fixture_ids - target_ids
        category = {}
        for label, fixture_ids in (("target", target_ids), ("neutral", neutral_ids)):
            category[label] = host_category_summary(
                [row for row in expected_rows if row["fixture"] in fixture_ids],
                records, candidate_pairs, metric_names, helper_expected=label == "target",
                qualification_key="host_paired_qualified")
        target_helpers = {fixture_id: host_category_summary(
            [row for row in expected_rows if row["fixture"] == fixture_id],
            records, candidate_pairs, metric_names, helper_expected=True,
            qualification_key="host_paired_qualified")
            for fixture_id in sorted(target_ids)}
        neutral_fixtures = {fixture_id: host_category_summary(
            [row for row in expected_rows if row["fixture"] == fixture_id],
            records, candidate_pairs, metric_names, helper_expected=False,
            qualification_key="host_paired_qualified")
            for fixture_id in sorted(neutral_ids)}
        baseline_success = {runtime: sum(
            records[row["run_id"]].get("quality", {}).get("success") is True
            for row in expected_rows if row["run_id"] in records and row["runtime"] == runtime and
            row["variant"] == "baseline") for runtime in ("codex", "claude")}
        candidate_success = {runtime: sum(
            records[row["run_id"]].get("quality", {}).get("success") is True
            for row in expected_rows if row["run_id"] in records and row["runtime"] == runtime and
            row["variant"] == "candidate") for runtime in ("codex", "claude")}
        success_non_decrease = {runtime: {"baseline": baseline_success[runtime],
                                          "candidate": candidate_success[runtime],
                                          "holds": candidate_success[runtime] >= baseline_success[runtime]}
                                for runtime in ("codex", "claude")}
        target_pairs = [item for item in candidate_pairs if item["fixture"] in target_ids]
        required_metric_coverage = host_metric_coverage(candidate_pairs, host_selection_metrics,
                                                        "host_paired_qualified")
        quality_field_coverage = host_quality_coverage(actual_rows, len(expected_rows))
        status_coverage = host_status_coverage(actual_rows, statuses, len(expected_rows))
        model_received = host_model_received_coverage(actual_rows, len(expected_rows))
        paired = {"expected_pairs": len(candidate_pairs),
                  "complete_pairs": sum(item.get("complete") is True for item in candidate_pairs),
                  "complete": len(candidate_pairs) > 0 and all(item.get("complete") is True
                                                               for item in candidate_pairs),
                  "metric_coverage": host_metric_coverage(candidate_pairs, metric_names,
                                                          "host_paired_qualified"),
                  "required_metric_coverage": required_metric_coverage,
                  "unpaired_pairs": sum(item.get("unpaired") is True for item in candidate_pairs),
                  "pair_stop_pairs": sum(item.get("pair_stop") is True for item in candidate_pairs),
                  "pre_model_failed_pairs": sum(item.get("pre_model_failed") is True for item in candidate_pairs),
                  "success_non_decrease": success_non_decrease}
        violations = host_quality_violations(actual_rows)
        pre_model_failed = sum(record.get("status") == "pre_model_failed" or
                               (record.get("host_helper") or {}).get("evidence", {}).get("pre_model_failed") is True
                               for record in actual_rows)
        host_by_candidate[candidate] = {"expected_runs": 72, "recorded_runs": len(actual_rows),
                                       "complete": len(actual_rows) == 72,
                                       "paired": paired, "target_vs_neutral": category,
                                       "target_helpers": target_helpers, "neutral_fixtures": neutral_fixtures,
                                       "target_input_token_reduction": host_input_token_reduction(
                                           target_pairs, "host_paired_qualified"),
                                       "host_deltas": {item["pair_id"]: item.get("host_deltas", {})
                                                       for item in candidate_pairs},
                                       "quality_field_coverage": quality_field_coverage,
                                       "status_coverage": status_coverage,
                                       "model_received": model_received,
                                       "quality_violations": violations,
                                       "pre_model_failed": pre_model_failed,
                                       "pair_stop": sum(host_pair_stop(record) for record in actual_rows)}
        native_by_candidate[candidate] = {"expected_runs": 24,
            "recorded_runs": sum(row["run_id"] in records for row in native_expected if row["candidate"] == candidate),
            "state": "pending_native_capability"}
    host_selection = {}
    for candidate in manifest["candidates"]:
        host = host_by_candidate[candidate]
        blockers = []
        required_coverage = host["paired"]["required_metric_coverage"]
        coverage_complete = all(item["complete"] and item["rate"] == 1 for item in required_coverage.values())
        category_success = {
            label: host["target_vs_neutral"][label]["success_non_decrease"]
            for label in ("target", "neutral")}
        success_complete = all(details["complete"] and details["holds"]
                               for scope in category_success.values() for details in scope.values())
        token_reduction = host["target_input_token_reduction"]
        quality = host["quality_violations"]
        quality_field_coverage = host["quality_field_coverage"]
        quality_coverage_complete = all(item["complete"] for item in quality_field_coverage.values())
        status_coverage = host["status_coverage"]
        helper_observation_complete = all(host["target_vs_neutral"][label]["helper_observed"]["complete"]
                                          for label in ("target", "neutral"))
        model_received = host["model_received"]
        if not host["paired"]["complete"]:
            blockers.append("pair_incomplete")
        if not coverage_complete:
            blockers.append("metric_coverage_incomplete")
        if not success_complete:
            blockers.append("success_regression_or_incomplete")
        if not status_coverage["complete"]:
            blockers.append("status_coverage_incomplete")
        if not quality_coverage_complete:
            blockers.append("quality_field_coverage_incomplete")
        if not helper_observation_complete:
            blockers.append("helper_observation_incomplete")
        if not model_received["complete"]:
            blockers.append("model_received_incomplete")
        if quality["boundary"]:
            blockers.append("boundary_violation")
        if quality["quality0"]:
            blockers.append("quality0_violation")
        if not token_reduction["eligible"]:
            blockers.append("target_input_token_reduction_below_10_percent")
        eligible = not blockers
        host_selection[candidate] = {
            "state": "PASS" if eligible else "HOLD", "eligible": eligible,
            "scope": "host-exploration", "host_effect": "unknown",
            "reason": ("host探索の採択条件を満たす。native effectは未確認のためnative/adoptionは別gateでHOLD"
                       if eligible else "host探索の採択条件が未達"),
            "blocking_reasons": blockers,
            "pair_complete": host["paired"]["complete"],
            "unpaired_pairs": host["paired"]["unpaired_pairs"],
            "metric_coverage": required_coverage,
            "required_metrics": list(host_selection_metrics),
            "metric_coverage_complete": coverage_complete,
            "all_metric_coverage": host["paired"]["metric_coverage"],
            "success_non_decrease": category_success,
            "success_non_decrease_complete": success_complete,
            "status_coverage": status_coverage,
            "quality_field_coverage": quality_field_coverage,
            "quality_field_coverage_complete": quality_coverage_complete,
            "helper_observation_complete": helper_observation_complete,
            "target_helper_observation_complete": host["target_vs_neutral"]["target"]["helper_observed"]["complete"],
            "neutral_helper_observation_complete": host["target_vs_neutral"]["neutral"]["helper_observed"]["complete"],
            "model_received": model_received,
            "model_received_complete": model_received["complete"],
            "boundary_violations": quality["boundary"],
            "quality0_violations": quality["quality0"],
            "target_input_token_reduction": token_reduction,
            "cost_tier": {"cost": {"state": "NA", "blocking": False,
                                     "reason": "host探索gateの採択条件に含めない"},
                          "tier": {"state": "NA", "blocking": False,
                                   "reason": "host探索gateの採択条件に含めない"}},
        }
    host_summary = {"expected_runs": len(host_expected), "per_candidate_expected": 72,
        "recorded_runs": len(host_records), "by_candidate": host_by_candidate,
        "paired_metrics": host_metric_coverage(
            [item for item in pairs if item["fixture"] in host_fixture_ids], metric_names,
            "host_paired_qualified"),
        "paired_required_metrics": host_metric_coverage(
            [item for item in pairs if item["fixture"] in host_fixture_ids], host_selection_metrics,
            "host_paired_qualified"),
        "target_vs_neutral": {candidate: host_by_candidate[candidate]["target_vs_neutral"]
                              for candidate in manifest["candidates"]},
        "target_helpers": {candidate: host_by_candidate[candidate]["target_helpers"]
                           for candidate in manifest["candidates"]},
        "mechanism_observed": sum((row.get("host_helper") or {}).get("evidence", {}).get("helper_mechanism_observed") is True
                                  for row in host_records),
        "model_received": sum((row.get("host_helper") or {}).get("evidence", {}).get("model_received_helper_result") is True
                              for row in host_records),
        "assisted_task_successes": sum((row.get("host_helper") or {}).get("evidence", {}).get("task_outcome_passed") is True
                                       for row in host_records),
        "pre_model_failed": sum(record.get("status") == "pre_model_failed" for record in host_records),
        "pair_stop": sum(host_pair_stop(record) for record in host_records),
        "complete": len(host_records) == len(host_expected), "native_effect": False, "adopted": False,
        "selection_gate": host_selection,
        "selection_state": "HOLD" if any(item["state"] == "HOLD" for item in host_selection.values()) else "PASS"}
    value = {"owner": OWNER, "schema": 5, "generated_at": now(), "plan": PLAN, "host_helper_plan": HOST_PLAN,
             "scheduled": manifest["max_runs"], "recorded": len(records), "groups": groups, "pairs": pairs,
             "fixture_summaries": fixture_summaries, "task_groups": task_groups, "adoption_gate": adoption_gate,
             "host_subset": host_summary,
             "selection_gate": {"host_subset": host_selection,
                                "native_subset": {"state": "HOLD", "reason": "native capability evidence pending"},
                                "adoption_subset": {"state": "HOLD", "reason": "host探索gateはgeneral adoptionと分離"}},
             "native_subset": {"expected_runs": len(native_expected), "per_candidate_expected": 24,
                               "recorded_runs": sum(row["run_id"] in records for row in native_expected),
                               "state": "pending_native_capability", "by_candidate": native_by_candidate},
             "rules": {"expected_runs_per_variant": 24, "all_pairs_required": True, "success_zero": "NA",
             "coverage_uses_qualified_and_scope": True, "adoption_requires_all_primary_metric_coverage": True,
             "selection_threshold_only": "10%",
             "known_limitations": ["native-specific helper evidenceは未承認のためnative comparisonはHOLD"]}}
    write_json(root / "results/report.json", value)
    print(json.dumps({"recorded": len(records), "groups": len(groups), "report": str(root / "results/report.json")}, ensure_ascii=False))
    return 0


def cli():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare"); command.add_argument("root"); command.add_argument("--seed", type=int, default=260920804)
    command.add_argument("--capability-evidence", required=True)
    command.add_argument("--comparison-bundle", required=True)
    command.add_argument("--codex-bin", required=True); command.add_argument("--claude-bin", required=True)
    command.add_argument("--codex-native-bin", required=True)
    command.add_argument("--tsc-bin")
    command.add_argument("--host-node-bin"); command.add_argument("--host-tsc-js")
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
    command.add_argument("--host-subset", action="store_true")
    command.add_argument("--timeout-seconds", type=int, choices=(600,), default=600); command.set_defaults(handler=run)
    command = commands.add_parser("report"); command.add_argument("root"); command.set_defaults(handler=report)
    return parser


if __name__ == "__main__":
    arguments = cli().parse_args()
    raise SystemExit(arguments.handler(arguments))
