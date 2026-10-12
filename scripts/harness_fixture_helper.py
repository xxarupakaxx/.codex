#!/usr/bin/env python3
"""Finite host-supervised mechanism fixtures for the harness benchmark."""
from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import resource
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

REQUEST_OWNER = "harness-host-helper-request-v1"
RESULT_OWNER = "harness-host-helper-result-v1"
LEDGER_OWNER = "harness-host-helper-ledger-v1"
SCHEMA = 1
PLAN = {"version": "v13", "sha256": "1193c1efd7467aac5e34934f3e6e1ee0c0de8d99b7c2b4f4fe861c0bcdcf6ec3"}
SLOT = '<mechanism-context schema="host-helper-result-v1">__HOST_RESULT__</mechanism-context>'
SOURCE_POLICY = {"handover_core": "8b9fa9bb7d01bcbe5be06e085496df2ea3b5a246a7d4a875d83b4186979ce3f4",
                 "observations_core": "d16cbc1413f9515eef6c9ba0c2fb2a5d25dfa47571cd90f6ea41fb61fc85058a",
                 "quiet_run": "41fe3a91280e1e2d6f8415f487529a56d85e8f0d8314ed78c0861f684988651a"}
DEPENDENCY_POLICY = {"node": "fdfd102dbe86b0af5dfc540a9c8dcb2fa0c5a3166d4a6c067eaf78d49568af40",
                     "tsc_js": "e8f349eabd48486bdb2bf9dc1a00c89d58297270c54b745838879e2859194419"}
I04_RAW_TEMPLATE = """# Session Handover

> Auto-generated before context compaction
> Session: session-host
> Generated: logical-fixture-time

## Session State

- **Current Phase**: 4 (品質確認)
- **Next Action**: __NEXT_ACTION__

## Task Log (05_log.md)

__REQUIRED_FACTS__

## Plan (30_plan.md)

__PLAN__

## Recent Conversation (last 50 entries)

```
[user]: __OBJECTIVE__
---
[assistant]: __NEXT_ACCEPTANCE__
---
```

## Recovery Instructions

1. Read this file to restore context after compaction
2. Check the memory directory for detailed task files
3. Resume from **Phase 4 (品質確認)** (see Next Action above)
4. Revalidate the required gate before continuing
"""
I04_INJECT_TEMPLATE = """=== SESSION HANDOVER (auto-injected after compaction) ===

__HANDOVER__

=== END HANDOVER ===
"""
BASELINE_CONTROL_B64 = {
    'stop_save': 'IyEvYmluL2Jhc2gKIyBzdG9wLXNhdmUtaGFuZG92ZXIuc2gKIyBDbGF1ZGXlgZzmraLmmYLjgatIQU5ET1ZFUi5tZOOCkuS/neWtmOOBmeOCi++8iOOCouOCr+ODhuOCo+ODluOCv+OCueOCr+aZguOBruOBv++8iQojIC9jbGVhcuWJjeOBq+acgOaWsOeKtuaFi+OCkuS/neaMgeOBmeOCi+OBn+OCgeOAgVN0b3Dmr47jgavmm7TmlrAKCklOUFVUPSQoY2F0KQoKIyDnhKHpmZDjg6vjg7zjg5fpmLLmraIKQUNUSVZFPSQoZWNobyAiJElOUFVUIiB8IGpxIC1yICcuc3RvcF9ob29rX2FjdGl2ZSAvLyBmYWxzZScpCmlmIFsgIiRBQ1RJVkUiID0gInRydWUiIF07IHRoZW4KICBleGl0IDAKZmkKCkNXRD0kKGVjaG8gIiRJTlBVVCIgfCBqcSAtciAnLmN3ZCAvLyAiIicpClRSQU5TQ1JJUFQ9JChlY2hvICIkSU5QVVQiIHwganEgLXIgJy50cmFuc2NyaXB0X3BhdGggLy8gIiInKQpTRVNTSU9OX0lEPSQoZWNobyAiJElOUFVUIiB8IGpxIC1yICcuc2Vzc2lvbl9pZCAvLyAidW5rbm93biInKQoKaWYgWyAteiAiJENXRCIgXTsgdGhlbgogIGV4aXQgMApmaQoKIyDjg6Hjg6Ljg6rjg4fjgqPjg6zjgq/jg4jjg6rjgpLmjqLjgZkKTUVNT1JZX0JBU0U9IiIKZm9yIGRpciBpbiAiJENXRC8ubG9jYWwvbWVtb3J5IiAiJENXRC9tZW1vcnkiOyBkbwogIGlmIFsgLWQgIiRkaXIiIF07IHRoZW4KICAgIE1FTU9SWV9CQVNFPSIkZGlyIgogICAgYnJlYWsKICBmaQpkb25lCgojIOOCouOCr+ODhuOCo+ODluOCv+OCueOCr+OBjOOBquOBhOWgtOWQiOOBr+OCueOCreODg+ODlwppZiBbIC16ICIkTUVNT1JZX0JBU0UiIF07IHRoZW4KICBleGl0IDAKZmkKCkxBVEVTVF9ESVI9JChmaW5kICIkTUVNT1JZX0JBU0UiIC1tYXhkZXB0aCAxIC10eXBlIGQgLW5hbWUgIlswLTldKiIgMj4vZGV2L251bGwgfCBzb3J0IC1yIHwgaGVhZCAtMSkKCiMgMDVfbG9nLm1k44GM5a2Y5Zyo44GX44Gq44GE5aC05ZCI44Gv44K544Kt44OD44OX77yI44K/44K544Kv6Z2e5rS75oCn77yJCmlmIFsgLXogIiRMQVRFU1RfRElSIiBdIHx8IFsgISAtZiAiJExBVEVTVF9ESVIvMDVfbG9nLm1kIiBdOyB0aGVuCiAgZXhpdCAwCmZpCgojIEhBTkRPVkVSLm1kIOOCkuS/neWtmApIQU5ET1ZFUl9ESVI9IiRDV0QvLmxvY2FsIgpta2RpciAtcCAiJEhBTkRPVkVSX0RJUiIKSEFORE9WRVJfRklMRT0iJEhBTkRPVkVSX0RJUi9IQU5ET1ZFUi5tZCIKCnsKICBlY2hvICIjIFNlc3Npb24gSGFuZG92ZXIiCiAgZWNobyAiIgogIGVjaG8gIj4gQXV0by1nZW5lcmF0ZWQgb24gU3RvcCAoZm9yIC9jbGVhciByZWNvdmVyeSkiCiAgZWNobyAiPiBTZXNzaW9uOiAkU0VTU0lPTl9JRCIKICBlY2hvICI+IEdlbmVyYXRlZDogJChkYXRlICcrJVktJW0tJWQgJUg6JU06JVMnKSIKICBlY2hvICIiCgogICMgMDVfbG9nLm1kCiAgaWYgWyAtZiAiJExBVEVTVF9ESVIvMDVfbG9nLm1kIiBdOyB0aGVuCiAgICBlY2hvICIjIyBUYXNrIExvZyAoMDVfbG9nLm1kKSIKICAgIGVjaG8gIiIKICAgIGVjaG8gIk1lbW9yeSBkaXJlY3Rvcnk6IFxgJExBVEVTVF9ESVJcYCIKICAgIGVjaG8gIiIKICAgIGNhdCAiJExBVEVTVF9ESVIvMDVfbG9nLm1kIgogICAgZWNobyAiIgogIGZpCgogICMgMzBfcGxhbi5tZAogIGlmIFsgLWYgIiRMQVRFU1RfRElSLzMwX3BsYW4ubWQiIF07IHRoZW4KICAgIGVjaG8gIiMjIFBsYW4gKDMwX3BsYW4ubWQpIgogICAgZWNobyAiIgogICAgY2F0ICIkTEFURVNUX0RJUi8zMF9wbGFuLm1kIgogICAgZWNobyAiIgogIGZpCgogICMg44OI44Op44Oz44K544Kv44Oq44OX44OI44Gu5pyr5bC+CiAgaWYgWyAtbiAiJFRSQU5TQ1JJUFQiIF0gJiYgWyAtZiAiJFRSQU5TQ1JJUFQiIF07IHRoZW4KICAgIGVjaG8gIiMjIFJlY2VudCBDb252ZXJzYXRpb24gKGxhc3QgMzAgZW50cmllcykiCiAgICBlY2hvICIiCiAgICBlY2hvICdgYGAnCiAgICB0YWlsIC0zMCAiJFRSQU5TQ1JJUFQiIDI+L2Rldi9udWxsIHwgd2hpbGUgSUZTPSByZWFkIC1yIGxpbmU7IGRvCiAgICAgIFJPTEU9JChlY2hvICIkbGluZSIgfCBqcSAtciAnLnJvbGUgLy8gLnR5cGUgLy8gInVua25vd24iJyAyPi9kZXYvbnVsbCkKICAgICAgaWYgWyAiJFJPTEUiID0gImFzc2lzdGFudCIgXSB8fCBbICIkUk9MRSIgPSAidXNlciIgXTsgdGhlbgogICAgICAgIENPTlRFTlQ9JChlY2hvICIkbGluZSIgfCBqcSAtciAnCiAgICAgICAgICBpZiAubWVzc2FnZSB0aGVuIC5tZXNzYWdlWzA6MjAwXQogICAgICAgICAgZWxpZiAuY29udGVudCB0aGVuCiAgICAgICAgICAgIGlmICguY29udGVudCB8IHR5cGUpID09ICJzdHJpbmciIHRoZW4gLmNvbnRlbnRbMDoyMDBdCiAgICAgICAgICAgIGVsaWYgKC5jb250ZW50IHwgdHlwZSkgPT0gImFycmF5IiB0aGVuICguY29udGVudFtdIHwgc2VsZWN0KC50eXBlID09ICJ0ZXh0IikgfCAudGV4dFswOjIwMF0pIC8vICIuLi4iCiAgICAgICAgICAgIGVsc2UgIi4uLiIKICAgICAgICAgICAgZW5kCiAgICAgICAgICBlbHNlICIuLi4iCiAgICAgICAgICBlbmQKICAgICAgICAnIDI+L2Rldi9udWxsKQogICAgICAgIGlmIFsgLW4gIiRDT05URU5UIiBdICYmIFsgIiRDT05URU5UIiAhPSAiLi4uIiBdICYmIFsgIiRDT05URU5UIiAhPSAibnVsbCIgXTsgdGhlbgogICAgICAgICAgZWNobyAiWyRST0xFXTogJENPTlRFTlQiCiAgICAgICAgICBlY2hvICItLS0iCiAgICAgICAgZmkKICAgICAgZmkKICAgIGRvbmUKICAgIGVjaG8gJ2BgYCcKICAgIGVjaG8gIiIKICBmaQoKICBlY2hvICIjIyBSZWNvdmVyeSBJbnN0cnVjdGlvbnMiCiAgZWNobyAiIgogIGVjaG8gIi0gUmVhZCB0aGlzIGZpbGUgdG8gcmVzdG9yZSBjb250ZXh0IGFmdGVyIC9jbGVhciIKICBlY2hvICItIENoZWNrIHRoZSBtZW1vcnkgZGlyZWN0b3J5IGZvciBkZXRhaWxlZCB0YXNrIGZpbGVzIgogIGVjaG8gIi0gQ29udGludWUgZnJvbSB0aGUgcGhhc2UgaW5kaWNhdGVkIGluIHRoZSB0YXNrIGxvZyBhYm92ZSIKCn0gPiAiJEhBTkRPVkVSX0ZJTEUiCgpleGl0IDAK',
    'session_inject': 'IyEvYmluL2Jhc2gKIyBzZXNzaW9uLXN0YXJ0LWluamVjdC5zaAojIOOCs+ODs+ODhuOCreOCueODiOWcp+e4ruW+jOOBq0hBTkRPVkVSLm1k44Gu5YaF5a6544KS5rOo5YWl44GZ44KLCiMgU2Vzc2lvblN0YXJ0IChjb21wYWN0KSDjgafnmbrngasKCklOUFVUPSQoY2F0KQpDV0Q9JChlY2hvICIkSU5QVVQiIHwganEgLXIgJy5jd2QgLy8gIiInKQoKaWYgWyAteiAiJENXRCIgXTsgdGhlbgogIGV4aXQgMApmaQoKSEFORE9WRVJfRklMRT0iJENXRC8ubG9jYWwvSEFORE9WRVIubWQiCgppZiBbIC1mICIkSEFORE9WRVJfRklMRSIgXTsgdGhlbgogIGVjaG8gIj09PSBTRVNTSU9OIEhBTkRPVkVSIChhdXRvLWluamVjdGVkIGFmdGVyIGNvbXBhY3Rpb24pID09PSIKICBlY2hvICIiCiAgY2F0ICIkSEFORE9WRVJfRklMRSIKICBlY2hvICIiCiAgZWNobyAiPT09IEVORCBIQU5ET1ZFUiA9PT0iCmZpCgpleGl0IDAK'}
BASELINE_CONTROLS = {name: base64.b64decode(value) for name, value in BASELINE_CONTROL_B64.items()}
BASELINE_POLICY = {"emitter": "1b8df8f30b739b8a14625dc5ed93d40cb58843a15cbce6ee39603d93098d67eb",
                   "retriever": "c33d73fb0fe26df3e13fe9f7152d62dfe4cc63652429b1b4ee75199611cfe30e",
                   "raw_observer": "bc40c757995ed6b882517790dc6174cf89893939171bcceee774d1b2900b5ef6",
                   "tsc_shim_template": "e9ae206f5601123ee4331bad3aab9253b5e71f7d8c39fe110ccbd7a4931b51aa",
                   "i04_raw_template": "f5cb976c2a6b08f1122d7d24e10e672e212f9bad5b63ace3dbbd281f26339556",
                   "i04_inject_template": "96d70da54bb60958620a2653b18a44e60815abaaccf47f8bc1a1be02ca313f0f",
                   "i04_stop_save_control": "661e0d7b61abf294b4c9d964607e019e78d2756c016a6f321e784a420220380c",
                   "i04_session_inject_control": "7fc3cf65b01a2b64a8a17a500a0f610cce1526b8eb6362f0c25d07425fa08243"}
BASELINE_PROVENANCE = {"codex_commit": "51ee53ed72eec0f7184c0699d244d2329d8e93bd",
                       "claude_commit": "7152ca3d5e05529f04018b59c0f40c668b8567aa",
                       "plan_sha256": PLAN["sha256"], "control_hashes": BASELINE_POLICY}
BASELINE_GOLDEN = {
    "cli_quiet_retrieve": {
        "sources": [{"repo": "codex", "path": "scripts/quiet-run.py",
                     "blob": "6cc34089610c76e4364827a5981142dce48b22ee",
                     "sha256": "41fe3a91280e1e2d6f8415f487529a56d85e8f0d8314ed78c0861f684988651a"}],
        "behavior": {"child_exit": 7, "diagnostic_present": True, "source_runs": 1, "retrieval_runs": 0}},
    "long_explore": {
        "sources": [{"repo": "codex", "path": "claude-compat/hooks/pre-compact-handover.sh",
                     "blob": "3b94e0c328ecf4b4128ad58c38163a8c90f350b3",
                     "sha256": "b15b4844054c1328c7a477ef3b46876c92fbc0c99500d3e5b7eacfb9aee6a974"},
                    {"repo": "claude", "path": "hooks/stop-save-handover.sh",
                     "blob": "11e40a202c6f2334c072537e4d4db30cdb5db26a",
                     "sha256": "661e0d7b61abf294b4c9d964607e019e78d2756c016a6f321e784a420220380c"},
                    {"repo": "codex", "path": "claude-compat/hooks/session-start-inject.sh",
                     "blob": "384c5edd1aea0ec7872856ea05fe468ec8b620c3",
                     "sha256": "7fc3cf65b01a2b64a8a17a500a0f610cce1526b8eb6362f0c25d07425fa08243"},
                    {"repo": "claude", "path": "hooks/session-start-inject.sh",
                     "blob": "384c5edd1aea0ec7872856ea05fe468ec8b620c3",
                     "sha256": "7fc3cf65b01a2b64a8a17a500a0f610cce1526b8eb6362f0c25d07425fa08243"}],
        "behavior": {"gate_status": "passed", "canonical_verified": False,
                     "init_runs": 0, "save_runs": 0, "load_runs": 0,
                     "baseline_save_runs": 1, "baseline_inject_runs": 1}},
    "repo_tsc_once": {
        "sources": [{"repo": "claude", "path": "hooks/post-typescript-check.sh",
                     "blob": "b315211e82b4d483e07b090e6026cd2b00a3b807",
                     "sha256": "2e915ea3b89beea6445a27f5e9191ebbfa54f8001b3e665477f4eded6f5798cb"}],
        "behavior": {"tsc_runs": 2, "diagnostic_reused": False}},
    "cli_failure_reset": {
        "sources": [{"repo": "claude", "path": "hooks/post-failure-escalate.sh",
                     "blob": "00d1259105452e267b251828db29cdebfec4ce39",
                     "sha256": "d89b5b1be179007f522290392eb90e2def60811654bf0f139ed71cac042943ca"}],
        "behavior": {"failure_events": 7, "notifications": 2, "success_resets": 0,
                     "edit_resets": 0, "false_notifications": 1, "forced_stops": 0}}}
LIMITS = {"seconds": 120, "operations": 16, "files": 64, "file_bytes": 4 * 1024 * 1024,
          "total_bytes": 16 * 1024 * 1024, "stdout_bytes": 16 * 1024 * 1024,
          "stderr_bytes": 16 * 1024 * 1024, "request_bytes": 256 * 1024,
          "result_bytes": 256 * 1024, "term_grace": 5}
FIXTURE_TARGETS = {"I03": {"cli_quiet_retrieve"}, "I04": {"long_explore"},
                   "I05": {"repo_tsc_once", "cli_failure_reset"}}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")

EMITTER = """import sys
for i in range(2000): print(f'error-{i:04d}: stale-index', file=sys.stderr)
raise SystemExit(7)
"""
RETRIEVER = """from pathlib import Path
import sys
d=Path(sys.argv[1]); found=list(d.glob('quiet-*.log'))
if len(found)!=1: raise SystemExit(9)
data=found[0].read_bytes(); sys.stdout.buffer.write(data[-16384:])
"""
RAW_OBSERVER = """import json,os,sys
from pathlib import Path
state=Path(sys.argv[1]); outcome=sys.argv[2]
value=json.loads(state.read_text()) if state.exists() else {'failures':0}
if outcome=='failure':
 value['failures']+=1
 if value['failures']%3==0: print('raw-three-failures',file=sys.stderr)
temp=state.with_suffix('.tmp'); fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f: json.dump(value,f,sort_keys=True)
os.replace(temp,state)
"""
TSC_SHIM = """#!{python}
import hashlib,json,os,subprocess,sys
from pathlib import Path
d=Path(os.environ['TSC_SHIM_MARKERS']); slot=os.environ['TSC_SHIM_SLOT']; nonce=os.environ['TSC_SHIM_NONCE']
start=d/f'{slot}.start.json'; done=d/f'{slot}.complete.json'; raw=d/f'{slot}.diagnostic.bin'
fd=os.open(start,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
identity={{'owner':'tsc-shim-v1','run_id':os.environ['TSC_SHIM_RUN_ID'],'task_id':os.environ['TSC_SHIM_TASK_ID'],'nonce':nonce,'slot':slot}}
with os.fdopen(fd,'w') as f: json.dump({{**identity,'argv':sys.argv[1:]}},f,sort_keys=True)
p=subprocess.Popen([os.environ['TSC_NODE'],os.environ['TSC_JS'],*sys.argv[1:]],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
output,_=p.communicate()
fd=os.open(raw,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as f: f.write(output)
record={{**identity,'argv':sys.argv[1:],'shim_pid':os.getpid(),'node_pid':p.pid,
        'exit_code':p.returncode,'diagnostic_sha256':hashlib.sha256(output).hexdigest(),
        'shim_sha256':os.environ['TSC_SHIM_SHA256'],'node_sha256':os.environ['TSC_NODE_SHA256'],
        'tsc_sha256':os.environ['TSC_JS_SHA256']}}
temp=done.with_suffix('.tmp'); fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f: json.dump(record,f,sort_keys=True)
os.replace(temp,done); sys.stdout.buffer.write(output); raise SystemExit(p.returncode)
"""

if {"emitter": hashlib.sha256(EMITTER.encode()).hexdigest(),
    "retriever": hashlib.sha256(RETRIEVER.encode()).hexdigest(),
    "raw_observer": hashlib.sha256(RAW_OBSERVER.encode()).hexdigest(),
    "tsc_shim_template": hashlib.sha256(TSC_SHIM.encode()).hexdigest(),
    "i04_raw_template": hashlib.sha256(I04_RAW_TEMPLATE.encode()).hexdigest(),
    "i04_inject_template": hashlib.sha256(I04_INJECT_TEMPLATE.encode()).hexdigest(),
    "i04_stop_save_control": hashlib.sha256(BASELINE_CONTROLS["stop_save"]).hexdigest(),
    "i04_session_inject_control": hashlib.sha256(BASELINE_CONTROLS["session_inject"]).hexdigest()} != BASELINE_POLICY:
    raise RuntimeError("embedded baseline policy mismatch")


class HelperError(Exception):
    def __init__(self, reason: str, records=None):
        self.reason, self.records = reason, list(records or [])
        super().__init__(reason)


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value) -> str:
    raw = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _private_dir(path: Path, root: Path) -> Path:
    try:
        real = path.resolve(strict=True)
    except OSError as error:
        raise HelperError("binding_directory_missing") from error
    if not _inside(real, root) or path.is_symlink() or not real.is_dir() or stat.S_IMODE(real.stat().st_mode) != 0o700:
        raise HelperError("binding_directory_not_private")
    return real


def _file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _identity(path: Path) -> dict:
    info = path.stat()
    return {"device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "sha256": _file_digest(path)}


def _expected_source_hash(role: str) -> str:
    if role in SOURCE_POLICY:
        return SOURCE_POLICY[role]
    if role in DEPENDENCY_POLICY:
        return DEPENDENCY_POLICY[role]
    if role == "python":
        return _file_digest(Path(sys.executable).resolve(strict=True))
    raise HelperError("source_role_unreviewed")


def _source(row: dict, role: str, executable: bool = False) -> tuple[Path, dict]:
    if set(row) != {"path", "sha256", "role"} or row.get("role") != role or not HEX64.fullmatch(str(row.get("sha256"))):
        raise HelperError("source_descriptor_invalid")
    path = Path(row["path"])
    if path.is_symlink():
        raise HelperError("source_not_regular")
    try:
        real = path.resolve(strict=True)
    except OSError as error:
        raise HelperError("source_missing") from error
    mode = real.stat().st_mode
    if not path.is_absolute() or not stat.S_ISREG(mode) or real.stat().st_nlink != 1:
        raise HelperError("source_not_regular")
    if executable and not os.access(real, os.X_OK):
        raise HelperError("source_not_executable")
    expected = _expected_source_hash(role)
    identity = _identity(real)
    if row["sha256"] != expected or identity["sha256"] != expected:
        raise HelperError("source_hash_mismatch")
    return real, identity


def _check_sources(binding: dict, *, content: bool) -> None:
    for role, path in binding["sources"].items():
        expected = binding["source_identities"][role]
        info = path.stat()
        current = {"device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
                   "mtime_ns": info.st_mtime_ns}
        if current != {key: expected[key] for key in current} or info.st_nlink != 1:
            raise HelperError("source_identity_changed")
        if content and _file_digest(path) != expected["sha256"]:
            raise HelperError("source_content_changed")


def validate_binding(binding: dict) -> dict:
    keys = {"root", "run_id", "nonce", "work_dir", "ledger_dir", "raw_dir", "home_sha256", "sources"}
    if set(binding) != keys or not SAFE_ID.fullmatch(str(binding.get("run_id"))) or not SAFE_ID.fullmatch(str(binding.get("nonce"))):
        raise HelperError("binding_schema_invalid")
    root_input = Path(binding["root"])
    if root_input.is_symlink():
        raise HelperError("binding_root_symlink")
    try:
        root = root_input.resolve(strict=True)
    except OSError as error:
        raise HelperError("binding_root_missing") from error
    if not root.is_dir() or stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise HelperError("binding_root_not_private")
    clean = dict(binding)
    for name in ("work_dir", "ledger_dir", "raw_dir"):
        clean[name] = _private_dir(Path(binding[name]), root)
    home = os.environ.get("HOME", "")
    if (not home or not Path(home).is_absolute() or _inside(root, Path(home)) or
            digest(home.encode()) != binding["home_sha256"]):
        raise HelperError("home_identity_invalid")
    required = {"python", "quiet_run", "handover_core", "observations_core"}
    if not required.issubset(binding["sources"]) or set(binding["sources"]) - (required | {"node", "tsc_js"}):
        raise HelperError("source_set_invalid")
    checked = {name: _source(row, name, name in {"python", "node"})
               for name, row in binding["sources"].items()}
    clean["sources"] = {name: item[0] for name, item in checked.items()}
    clean["source_identities"] = {name: item[1] for name, item in checked.items()}
    clean["home"] = Path(home)
    if ("node" in clean["sources"]) != ("tsc_js" in clean["sources"]):
        raise HelperError("typescript_binding_incomplete")
    return clean


def validate_request(request: dict) -> None:
    if set(request) != {"owner", "schema", "candidate", "fixture", "strategy", "inputs", "limits"}:
        raise HelperError("request_schema_invalid")
    if request["owner"] != REQUEST_OWNER or request["schema"] != SCHEMA:
        raise HelperError("request_identity_invalid")
    candidate, fixture = request["candidate"], request["fixture"]
    if candidate not in FIXTURE_TARGETS or not isinstance(fixture, str) or request["strategy"] not in {"raw", "improved"}:
        raise HelperError("request_value_invalid")
    if request["limits"] != LIMITS or not isinstance(request["inputs"], dict):
        raise HelperError("request_limits_invalid")
    allowed = {"I03": {"reason"}, "I04": {"state"},
               "I05": {"source"} if fixture == "repo_tsc_once" else {"failure_code"}}
    if fixture in FIXTURE_TARGETS[candidate] and set(request["inputs"]) != allowed[candidate]:
        raise HelperError("request_inputs_invalid")
    if fixture not in FIXTURE_TARGETS[candidate] and request["inputs"]:
        raise HelperError("neutral_inputs_not_empty")
    if len(canonical(request)) > LIMITS["request_bytes"]:
        raise HelperError("request_too_large")


def bundle_file_allowed(class_name: str, target: Path, actual: str, factor: str) -> bool:
    return bool(class_name == "host_fixture_helper" and target.parent == Path("host") and
                target.name in SOURCE_POLICY and actual == SOURCE_POLICY[target.name] and factor == "fixed")


def host_bundle_mode(before: dict, after: dict, changed: list) -> bool:
    roles = {Path(key[1]).name for key in before if key[0] == "host_fixture_helper"}
    return roles == set(SOURCE_POLICY) and set(before) == set(after) and not changed


def validate_dependencies(node_path, tsc_path) -> dict:
    rows = {"node": {"path": str(node_path), "sha256": DEPENDENCY_POLICY["node"], "role": "node"},
            "tsc_js": {"path": str(tsc_path), "sha256": DEPENDENCY_POLICY["tsc_js"], "role": "tsc_js"}}
    result = {}
    for role, row in rows.items():
        path, identity = _source(row, role, role == "node")
        result[role] = {"path": str(path), "sha256": identity["sha256"]}
    return result


def _write(path: Path, data: bytes, executable: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o700 if executable else 0o600)
    except OSError as error:
        raise HelperError("output_claim_failed") from error
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _scan(*roots: Path, reserve_files=0, reserve_bytes=0) -> dict:
    pending = list(roots); files = total = entries = 0
    while pending:
        path = pending.pop(); info = path.lstat(); entries += 1
        if entries > LIMITS["files"] + 32 or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o077:
            raise HelperError("generated_tree_invalid")
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(path) as children:
                pending.extend(Path(item.path) for item in children)
        elif stat.S_ISREG(info.st_mode):
            files += 1; total += info.st_size
            if info.st_nlink != 1 or info.st_size > LIMITS["file_bytes"]:
                raise HelperError("generated_file_limit")
        else:
            raise HelperError("generated_special_file")
        if files + reserve_files > LIMITS["files"] or total + reserve_bytes > LIMITS["total_bytes"]:
            raise HelperError("generated_total_limit")
    return {"files": files + reserve_files, "bytes": total + reserve_bytes}


def _profile(work: Path, readable: tuple[Path, ...], home: Path) -> str:
    quote = lambda value: str(value).replace('\\', '\\\\').replace('"', '\\"')
    sources = " ".join(f'(literal "{quote(item)}")' for item in readable)
    source_ancestors = sorted({str(parent) for item in readable for parent in Path(item).parents})
    metadata = " ".join(f'(literal "{quote(item)}")' for item in source_ancestors)
    ancestors = " ".join(f'(literal "{quote(item)}")' for item in work.parents if str(item).startswith("/private"))
    home = quote(home)
    return ("(version 1)\n(allow default)\n(deny network*)\n"
            f"(deny file-read* (subpath \"{home}\") (subpath \"/private/tmp\"))\n"
            f"(deny file-write* (subpath \"{home}\") (subpath \"/private/tmp\"))\n"
            f"(allow file-read-metadata (subpath \"{quote(work.parent)}\") {metadata})\n"
            f"(allow file-read* {ancestors} {sources} (subpath \"{quote(work)}\"))\n"
            f"(allow file-write* (subpath \"{quote(work)}\"))\n")


def _resource_limits(seconds: int) -> dict:
    return {"fsize": LIMITS["stdout_bytes"], "nofile": 64, "nproc": 1024,
            "cpu_soft": max(1, seconds), "cpu_hard": max(2, seconds + 1)}


def _limits(values: dict):
    def apply():
        os.umask(0o077)
        resource.setrlimit(resource.RLIMIT_FSIZE, (values["fsize"], values["fsize"]))
        resource.setrlimit(resource.RLIMIT_NOFILE, (values["nofile"], values["nofile"]))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (values["nproc"], values["nproc"]))
        resource.setrlimit(resource.RLIMIT_CPU, (values["cpu_soft"], values["cpu_hard"]))
    return apply


def _operation_contract(operation: dict) -> dict:
    env = operation["env"]
    return {"name": operation["name"], "argv": operation["argv"],
            "normalized_argv": operation["normalized_argv"], "argv_sha256": digest(operation["argv"]),
            "cwd": operation["cwd"], "stdin_bytes": len(operation["stdin"]),
            "stdin_sha256": digest(operation["stdin"]), "env_keys": sorted(env),
            "env_sha256": digest(env), "allowed_exit": operation["allowed_exit"],
            "timeout_seconds": operation["timeout"],
            "readable": sorted(str(path) for path in operation["readable"]),
            "limits": {**{key: LIMITS[key] for key in ("stdout_bytes", "stderr_bytes", "file_bytes",
                                                         "total_bytes", "term_grace")},
                       **operation["resource_limits"]}}


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop_group(process, deadline: float) -> str | None:
    if process is None:
        return None
    cleanup = None
    if _group_alive(process.pid):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            cleanup = "process_group_uncontrollable"
            try:
                process.terminate()
            except ProcessLookupError:
                pass
    grace_end = min(deadline, time.monotonic() + LIMITS["term_grace"])
    while _group_alive(process.pid) and time.monotonic() < grace_end:
        time.sleep(0.02)
    if _group_alive(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            cleanup = "process_group_uncontrollable"
            try:
                process.kill()
            except ProcessLookupError:
                pass
    try:
        process.wait(timeout=max(0.01, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        try:
            process.kill(); process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except (ProcessLookupError, subprocess.TimeoutExpired):
            return "operation_not_reaped"
    if _group_alive(process.pid):
        return cleanup or "descendant_not_reaped"
    return cleanup


def _normalized_launch(command: list, binding: dict) -> list[str]:
    replacements = [(str(path), f"/source/{role}") for role, path in binding["sources"].items()]
    replacements.extend([(str(binding["work_dir"]), "/fixture"),
                         (str(binding["root"]), "/run"), (str(binding["home"]), "~")])
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    result = []
    for argument in map(str, command):
        for actual, logical in replacements:
            argument = argument.replace(actual, logical)
        result.append(argument)
    private = [str(binding["root"]), str(binding["home"]),
               *(str(path) for path in binding["sources"].values())]
    if any(actual and actual in argument for actual in private for argument in result):
        raise HelperError("launch_argv_not_normalized")
    return result


class Executor:
    def __init__(self, binding: dict, allowed: list[dict], deadline: float):
        self.binding, self.allowed, self.deadline, self.records = binding, allowed, deadline, []
        self.manifest = [_operation_contract(item) for item in allowed]
        self.manifest_hash = digest(self.manifest)

    def run(self) -> dict:
        index = len(self.records)
        if index >= len(self.allowed):
            raise HelperError("operation_manifest_exhausted", self.records)
        operation = self.allowed[index]
        if (index >= len(self.allowed) or index >= LIMITS["operations"] or
                _operation_contract(operation) != self.manifest[index]):
            raise HelperError("operation_manifest_mismatch", self.records)
        _check_sources(self.binding, content=False)
        remaining = min(operation["timeout"], self.deadline - time.monotonic())
        if remaining <= LIMITS["term_grace"]:
            raise HelperError("helper_deadline_exhausted", self.records)
        work, raw = self.binding["work_dir"], self.binding["raw_dir"]
        cwd = Path(operation["cwd"])
        if not _inside(cwd, work) or cwd.is_symlink() or not cwd.is_dir():
            raise HelperError("operation_cwd_invalid", self.records)
        tmp = work / "tmp"
        if not tmp.exists():
            tmp.mkdir(mode=0o700)
        profile = work / f"sandbox-{digest(self.manifest[index])[:16]}.sb"
        _write(profile, _profile(work, tuple(operation["readable"]), Path(self.binding["home"])).encode())
        stdout = raw / f"{index:02d}-{operation['name']}.stdout"; stderr = raw / f"{index:02d}-{operation['name']}.stderr"
        out_fd = os.open(stdout, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        err_fd = os.open(stderr, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        command = ["/usr/bin/sandbox-exec", "-f", str(profile), *operation["argv"]]
        normalized_launch = _normalized_launch(command, self.binding)
        started = time.monotonic(); process = None; stop = cleanup = launch_error_type = None
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            with os.fdopen(out_fd, "wb") as out, os.fdopen(err_fd, "wb") as err:
                process = subprocess.Popen(command, cwd=cwd, env=operation["env"], stdin=subprocess.PIPE,
                                           stdout=out, stderr=err, start_new_session=True,
                                           preexec_fn=_limits(operation["resource_limits"]))
                try:
                    process.communicate(operation["stdin"], timeout=remaining - LIMITS["term_grace"])
                except subprocess.TimeoutExpired:
                    stop = "timeout"
        except (OSError, subprocess.SubprocessError) as error:
            stop, launch_error_type = "launch_error", type(error).__name__
        finally:
            cleanup = _stop_group(process, self.deadline)
        if process is not None and process.poll() is None:
            stop = stop or "operation_not_reaped"
        for path, cap in ((stdout, LIMITS["stdout_bytes"]), (stderr, LIMITS["stderr_bytes"])):
            if path.stat().st_size > cap:
                raise HelperError("operation_output_limit", self.records)
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        contract = self.manifest[index]
        record = {"name": operation["name"], "argv": operation["argv"],
                  "normalized_argv": contract["normalized_argv"],
                  "argv_sha256": contract["argv_sha256"], "manifest_hash": self.manifest_hash,
                  "operation_contract": contract, "operation_manifest": self.manifest,
                  "cwd": operation["cwd"], "env_keys": contract["env_keys"],
                  "env_sha256": contract["env_sha256"], "stdin_bytes": contract["stdin_bytes"],
                  "stdin_sha256": contract["stdin_sha256"], "limits": contract["limits"],
                  "launch_argv": command, "normalized_launch_argv": normalized_launch,
                  "launch_argv_sha256": digest(command),
                  "normalized_launch_argv_sha256": digest(normalized_launch),
                  "sandbox_profile_sha256": _file_digest(profile),
                  "launch_error_type": launch_error_type,
                  "pid": process.pid if process else None,
                  "direct_process_count": int(process is not None),
                  "cpu_user_seconds": round(usage_after.ru_utime - usage_before.ru_utime, 6),
                  "cpu_system_seconds": round(usage_after.ru_stime - usage_before.ru_stime, 6),
                  "source_hashes": {role: identity["sha256"] for role, identity in
                                    self.binding["source_identities"].items()},
                  "stdout_file": stdout.name, "stderr_file": stderr.name,
                  "exit_code": process.returncode if process else None,
                  "stop_reason": stop or cleanup, "process_group_drained": cleanup is None,
                  "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                  "stdout_sha256": digest(stdout.read_bytes()), "stderr_sha256": digest(stderr.read_bytes()),
                  "stdout_bytes": stdout.stat().st_size, "stderr_bytes": stderr.stat().st_size}
        self.records.append(record)
        if stop == "launch_error":
            raise HelperError("operation_launch_failed", self.records)
        if stop or cleanup or process is None or process.returncode not in operation["allowed_exit"]:
            raise HelperError("operation_failed", self.records)
        return {"record": record, "stdout": stdout.read_bytes(), "stderr": stderr.read_bytes()}


def _env(binding: dict, extra=None) -> dict:
    value = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C", "TERM": "dumb",
             "SHELL": "/bin/sh", "HOME": str(binding["home"]), "TMPDIR": str(binding["work_dir"] / "tmp"),
             "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    value.update({key: str(item) for key, item in (extra or {}).items()})
    return {key: str(item) for key, item in value.items()}


def _op(binding, name, argv, *, stdin=b"", env=None, allowed=(0,), timeout=20, readable=(), cwd=None):
    sources = tuple(binding["sources"].values())
    return {"name": name, "argv": [str(item) for item in argv], "normalized_argv": [name, *[Path(str(item)).name for item in argv[1:]]],
            "stdin": stdin, "env": _env(binding, env), "allowed_exit": list(allowed), "timeout": timeout,
            "resource_limits": _resource_limits(max(1, int(timeout - LIMITS["term_grace"]))),
            "cwd": str(cwd or binding["work_dir"]),
            "readable": list(dict.fromkeys((*sources, *readable)))}


def _payload(context: str, facts: dict, diagnostics: list[str]) -> dict:
    return {"context": context, "facts": facts, "diagnostics": diagnostics}


def _i03(request, binding):
    work = binding["work_dir"]; python = binding["sources"]["python"]
    emitter, retriever = work / "emit.py", work / "retrieve.py"
    _write(emitter, EMITTER.encode()); _write(retriever, RETRIEVER.encode())
    reason = request["inputs"]["reason"]
    if reason != "stale-index":
        raise HelperError("i03_input_invalid")
    if request["strategy"] == "raw":
        operations = [_op(binding, "source-command", [python, emitter], allowed=(7,))]
        executor = Executor(binding, operations, time.monotonic() + LIMITS["seconds"]); run = executor.run()
        text = (run["stdout"] + run["stderr"]).decode(errors="replace")
    else:
        logs = work / "quiet-logs"; logs.mkdir(mode=0o700)
        quiet = binding["sources"]["quiet_run"]
        operations = [_op(binding, "quiet-run", [python, quiet, "--log-dir", logs, "--", python, emitter],
                          allowed=(7,)),
                      _op(binding, "retrieve-log", [python, retriever, logs], readable=())]
        executor = Executor(binding, operations, time.monotonic() + LIMITS["seconds"]); first = executor.run()
        found = list(logs.glob("quiet-*.log"))
        if len(found) != 1 or found[0].is_symlink() or found[0].stat().st_nlink != 1:
            raise HelperError("quiet_log_invalid", executor.records)
        second = executor.run()
        text = second["stdout"].decode(errors="replace")
        if first["record"]["exit_code"] != 7:
            raise HelperError("quiet_exit_mismatch", executor.records)
    if reason not in text:
        raise HelperError("diagnostic_missing", executor.records)
    facts = {"child_exit": 7, "diagnostic_present": True, "source_runs": 1,
             "retrieval_runs": sum(row["name"] == "retrieve-log" for row in executor.records)}
    return _payload(text, facts, [reason]), executor.records, ["/fixture/diagnostic"]


def _handover_args(binding, command):
    python, core, work = binding["sources"]["python"], binding["sources"]["handover_core"], binding["work_dir"]
    memory = work / "runtime-home/.local/memory"
    common = ["--runtime", "codex", "--cwd", str(work / "project"), "--session-id", "session-host",
              "--thread-id", "thread-host", "--task-memory-root", str(memory),
              "--project-path", str(work / "project"), "--worktree-path", str(work / "project")]
    return [python, core, command, *common]


def _logical_context(value: str, binding: dict) -> str:
    work = str(binding["work_dir"])
    replacements = ((str(binding["work_dir"] / "project/dashboard.html"), "logical"),
                    (str(binding["work_dir"] / "project"), "/fixture/project"),
                    (work, "/fixture"), (str(binding["root"]), "/run"))
    result = value
    for actual, logical in replacements:
        result = result.replace(actual, logical)
    private_values = {str(binding[name]) for name in ("root", "work_dir", "raw_dir", "ledger_dir")}
    private_values.update(str(path) for path in binding["sources"].values())
    if any(value and value in result for value in private_values):
        raise HelperError("physical_path_not_normalized")
    return result


def _i04_expected_state(request, binding):
    state = json.loads(json.dumps(request["inputs"]["state"]))
    state["plan"]["path"] = str(binding["work_dir"] / "project/dashboard.html")
    section = b'<section id="improvement-plan" data-plan-version="v13">fixture</section>'
    state["plan"]["sha256"] = digest(section)
    return state


def _i04_semantics(state, gate_status):
    logical = json.loads(json.dumps(state)); logical["plan"]["path"] = "logical"
    return {"schema_version": logical["schema_version"], "objective": logical["objective"],
            "next_acceptance": logical["next_acceptance"], "plan": logical["plan"],
            "dependencies": logical["dependencies"], "unanswered_questions": logical["unanswered_questions"],
            "required_gate": {**logical["required_gates"][0], "status": gate_status},
            "evidence": logical["evidence"], "next_action": logical["next_action"]}


def _i04_full_context(state, gate_status):
    semantics = _i04_semantics(state, gate_status)
    return f"""# Session Handover

> Auto-generated on Stop (for /clear recovery)
> Session: session-host
> Generated: logical-fixture-time

## Task Log (05_log.md)

Memory directory: `/fixture/project/.local/memory/20261013`

{canonical(semantics).decode()}

## Plan (30_plan.md)

{canonical(semantics["plan"]).decode()}

## Recent Conversation (last 30 entries)

```
[user]: {semantics["objective"]}
---
[assistant]: {semantics["next_acceptance"]}
---
```

## Recovery Instructions

- Read this file to restore context after /clear
- Check the memory directory for detailed task files
- Continue from the phase indicated in the task log above
"""


def _i04_baseline_documents(state):
    semantics = _i04_semantics(state, "passed")
    task_log = canonical(semantics).decode()
    plan = canonical(semantics["plan"]).decode()
    transcript = b"".join(canonical(row) + b"\n" for row in (
        {"role": "user", "message": semantics["objective"]},
        {"role": "assistant", "message": semantics["next_acceptance"]}))
    return task_log, plan, transcript


def _i04_normalize_raw(value: str, binding):
    value = re.sub(r"(?m)^> Generated: .+$", "> Generated: logical-fixture-time", value)
    return _logical_context(value, binding)


def _i04_expected_injected(state):
    handover = _i04_full_context(state, "passed")
    return I04_INJECT_TEMPLATE.replace("__HANDOVER__", handover.rstrip("\n"))


def _i04_short_context(state, gate_status):
    return canonical(_i04_semantics(state, gate_status)).decode()


def _i04_model_context(state, gate_status, strategy):
    return (_i04_full_context if strategy == "raw" else _i04_short_context)(state, gate_status)


def _i04(request, binding):
    work = binding["work_dir"]; project = work / "project"; project.mkdir(mode=0o700)
    runtime = work / "runtime-home"; runtime.mkdir(mode=0o700); (runtime / ".local").mkdir(mode=0o700)
    (runtime / ".local/memory").mkdir(mode=0o700)
    state = request["inputs"]["state"]
    if not isinstance(state, dict) or set(state) != {"schema_version", "objective", "next_acceptance", "plan", "dependencies",
                                                   "unanswered_questions", "required_gates", "evidence", "next_action"}:
        raise HelperError("i04_state_invalid")
    dashboard = project / "dashboard.html"; _write(dashboard, b'<section id="improvement-plan" data-plan-version="v13">fixture</section>\n')
    state = _i04_expected_state(request, binding)
    state_file = work / "state.json"; _write(state_file, canonical(state))
    changed = work / "fingerprints.json"
    _write(changed, canonical({"diff": "changed", "dependencies": "same", "execution": "same",
                               "plan": "same", "failure": "same"}))
    if request["strategy"] == "raw":
        local = project / ".local"; local.mkdir(mode=0o700)
        memory_root = local / "memory"; memory_root.mkdir(mode=0o700)
        memory = memory_root / "20261013"; memory.mkdir(mode=0o700)
        task_log, plan, transcript_bytes = _i04_baseline_documents(state)
        _write(memory / "05_log.md", (task_log + "\n").encode())
        _write(memory / "30_plan.md", (plan + "\n").encode())
        transcript = work / "synthetic-transcript.jsonl"; _write(transcript, transcript_bytes)
        controls = work / "baseline-controls"; controls.mkdir(mode=0o700)
        stop_save, session_inject = controls / "stop-save-handover.sh", controls / "session-start-inject.sh"
        _write(stop_save, BASELINE_CONTROLS["stop_save"], executable=True)
        _write(session_inject, BASELINE_CONTROLS["session_inject"], executable=True)
        if (_file_digest(stop_save) != BASELINE_POLICY["i04_stop_save_control"] or
                _file_digest(session_inject) != BASELINE_POLICY["i04_session_inject_control"]):
            raise HelperError("baseline_control_hash_mismatch")
        save_event = canonical({"cwd": str(project), "transcript_path": str(transcript),
                                "session_id": "session-host", "stop_hook_active": False})
        inject_event = canonical({"cwd": str(project)})
        operations = [_op(binding, "baseline-handover-save", ["/bin/bash", stop_save], stdin=save_event),
                      _op(binding, "baseline-handover-inject", ["/bin/bash", session_inject], stdin=inject_event)]
        executor = Executor(binding, operations, time.monotonic() + LIMITS["seconds"])
        executor.run(); injected = executor.run()["stdout"].decode(errors="strict"); records = executor.records
        context = _i04_normalize_raw(injected, binding)
        validity = "passed"
    else:
        local = project / ".local"
        env = {"SESSION_HANDOVER_MEMORY_DIR": str(local),
               "SESSION_HANDOVER_TASK_MEMORY_ROOT": str(runtime / ".local/memory"),
               "SESSION_HANDOVER_PLAN_ROOT": str(project), "CODEX_HOME": str(runtime)}
        init = _handover_args(binding, "init") + ["--task-id", "task-host", "--task-title", "Synthetic host task", "--code-change", "true"]
        save = _handover_args(binding, "save") + ["--memory-dir", str(local), "--state-file", str(state_file)]
        load = _handover_args(binding, "load") + ["--memory-dir", str(local), "--plan-root", str(project),
                                                     "--fingerprints-file", str(changed), "--format", "json"]
        operations = [_op(binding, name, argv, env=env) for name, argv in (("handover-init", init), ("handover-save", save), ("handover-load", load))]
        executor = Executor(binding, operations, time.monotonic() + LIMITS["seconds"])
        outputs = [executor.run() for _ in operations]; records = executor.records
        try:
            loaded = json.loads(outputs[-1]["stdout"])
        except (ValueError, UnicodeDecodeError) as error:
            raise HelperError("handover_result_invalid", executor.records) from error
        gates = loaded.get("effective_required_gates") or []
        validity = gates[0].get("status") if gates else None
        if validity != "needs_revalidation":
            raise HelperError("handover_revalidation_missing", executor.records)
        if loaded.get("state") != state:
            raise HelperError("handover_state_roundtrip_invalid", executor.records)
        context = _i04_model_context(state, validity, request["strategy"])
    facts = {"objective": state["objective"], "gate_status": validity, "required_facts_complete": True,
             "canonical_verified": request["strategy"] == "improved",
             "init_runs": sum(row["name"] == "handover-init" for row in records),
             "save_runs": sum(row["name"] == "handover-save" for row in records),
             "load_runs": sum(row["name"] == "handover-load" for row in records),
             "baseline_save_runs": sum(row["name"] == "baseline-handover-save" for row in records),
             "baseline_inject_runs": sum(row["name"] == "baseline-handover-inject" for row in records)}
    return _payload(context, facts, []), records, ["/fixture/task-state"]


def _shim_records(binding, slots):
    directory = binding["work_dir"] / "shim-markers"; records = []
    expected_names = {f"{slot}.{suffix}" for slot in slots for suffix in
                      ("start.json", "complete.json", "diagnostic.bin")}
    if {path.name for path in directory.iterdir()} != expected_names:
        raise HelperError("tsc_marker_set_invalid")
    for slot in slots:
        start, done, raw = directory / f"{slot}.start.json", directory / f"{slot}.complete.json", directory / f"{slot}.diagnostic.bin"
        if any(path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 for path in (start, done, raw)):
            raise HelperError("tsc_marker_missing")
        before, after = json.loads(start.read_text()), json.loads(done.read_text())
        identity = {"owner": "tsc-shim-v1", "run_id": binding["run_id"], "task_id": "repo_tsc_once",
                    "nonce": binding["nonce"], "slot": slot}
        if before != {**identity, "argv": ["--noEmit"]}:
            raise HelperError("tsc_start_invalid")
        if any(after.get(key) != value for key, value in identity.items()):
            raise HelperError("tsc_completion_invalid")
        shim = binding["work_dir"] / "project/node_modules/.bin/tsc"
        expected_complete = {**identity, "argv": ["--noEmit"], "shim_sha256": _file_digest(shim),
                             "node_sha256": binding["source_identities"]["node"]["sha256"],
                             "tsc_sha256": binding["source_identities"]["tsc_js"]["sha256"]}
        if (any(after.get(key) != value for key, value in expected_complete.items()) or
                after.get("diagnostic_sha256") != digest(raw.read_bytes()) or type(after.get("exit_code")) is not int or
                any(type(after.get(key)) is not int or after[key] <= 0 for key in ("shim_pid", "node_pid")) or
                after["shim_pid"] == after["node_pid"]):
            raise HelperError("tsc_diagnostic_mismatch")
        records.append({**after, "diagnostic": raw.read_text(errors="replace")})
    return records


def _joined_shim_records(binding, slots, records, strategy):
    try:
        rows = _shim_records(binding, slots)
    except HelperError as error:
        if not error.records:
            error.records = list(records)
        raise
    if strategy == "raw":
        if [row.get("name") for row in records] != [f"tsc-{slot}" for slot in slots] or len(rows) != len(records):
            raise HelperError("tsc_parent_join_invalid", records)
        for operation, marker in zip(records, rows):
            if operation.get("exit_code") != marker.get("exit_code"):
                raise HelperError("tsc_parent_exit_mismatch", records)
    elif len(records) != 1 or records[0].get("name") != "c-typescript" or records[0].get("exit_code") != 0:
        raise HelperError("tsc_observer_ledger_invalid", records)
    return rows


def _mechanism_evidence(request, binding, payload, records):
    targeted = request["fixture"] in FIXTURE_TARGETS[request["candidate"]]
    component_roots = {"operation_streams": binding["raw_dir"]}
    for name in ("quiet-logs", "shim-markers", "observation-state", "project/.local"):
        path = binding["work_dir"] / name
        if path.is_dir():
            component_roots[name.replace("/", "_")] = path
    component_files = {name: binding["work_dir"] / name for name in ("state.json", "reset-snapshots.json")
                       if (binding["work_dir"] / name).is_file()}
    raw_components, seen = {}, set()
    for name, root in component_roots.items():
        paths = [path for path in root.rglob("*") if path.is_file()]
        raw_components[name] = sum(path.stat().st_size for path in paths)
        seen.update(path.resolve() for path in paths)
    for name, path in component_files.items():
        raw_components[name] = path.stat().st_size; seen.add(path.resolve())
    marker_rows = []
    if targeted and request["fixture"] == "repo_tsc_once":
        slots = ("1", "2") if request["strategy"] == "raw" else ("1",)
        marker_rows = _joined_shim_records(binding, slots, records, request["strategy"])
    marker_pids = [row[key] for row in marker_rows for key in ("shim_pid", "node_pid")]
    direct_pids = [row["pid"] for row in records if type(row.get("pid")) is int]
    if len(marker_pids) != len(set(marker_pids)):
        raise HelperError("process_identity_duplicate", records)
    verified_child_pids = set(marker_pids) - set(direct_pids)
    unverified = bool(records) and request["fixture"] != "repo_tsc_once"
    metrics = {"cpu_user_seconds": round(sum(row.get("cpu_user_seconds", 0) for row in records), 6),
               "cpu_system_seconds": round(sum(row.get("cpu_system_seconds", 0) for row in records), 6),
               "processes": {"direct_observed": len(direct_pids),
                             "mechanism_children_verified": len(verified_child_pids),
                             "verified_pids_unique": len(set(direct_pids + marker_pids)),
                             "unverified_children_possible": unverified,
                             "total_verified": len(set(direct_pids + marker_pids)),
                             "basis": "popen_handles_and_unique_shim_markers_only"},
               "input_bytes": {"request": len(canonical(request)),
                               "operation_stdin": sum(row.get("stdin_bytes", 0) for row in records)},
               "output_bytes": {"operation_stdout_stderr": sum(
                   row.get("stdout_bytes", 0) + row.get("stderr_bytes", 0) for row in records),
                                "helper_payload": len(canonical(payload))},
               "raw_bytes": {"components": raw_components, "mechanism_artifacts_total": sum(raw_components.values())},
               "process_groups_drained": all(row.get("process_group_drained") is True for row in records)}
    artifacts = {"baseline_policy": BASELINE_POLICY, "baseline_golden": BASELINE_GOLDEN,
                 "source_hashes": {role: identity["sha256"] for role, identity in binding["source_identities"].items()},
                 "baseline_provenance": BASELINE_PROVENANCE}
    if targeted and request["fixture"] == "cli_quiet_retrieve" and request["strategy"] == "improved":
        logs = list((binding["work_dir"] / "quiet-logs").glob("quiet-*.log"))
        if len(logs) != 1:
            raise HelperError("quiet_log_invalid", records)
        artifacts["quiet_full_log"] = {"sha256": _file_digest(logs[0]), "bytes": logs[0].stat().st_size,
                                       "source_runs": 1, "retrieval_runs": 1, "reruns": 0}
    if targeted and request["fixture"] == "repo_tsc_once":
        shim = binding["work_dir"] / "project/node_modules/.bin/tsc"
        slots = ("1", "2") if request["strategy"] == "raw" else ("1",)
        rows = marker_rows
        artifacts["typescript"] = {"shim_sha256": _file_digest(shim), "slots": list(slots),
                                   "node_sha256": binding["source_identities"]["node"]["sha256"],
                                   "tsc_sha256": binding["source_identities"]["tsc_js"]["sha256"],
                                   "start_count": len(slots), "complete_count": len(rows),
                                   "actual_exit_codes": [row["exit_code"] for row in rows],
                                   "raw_diagnostic_sha256": [row["diagnostic_sha256"] for row in rows],
                                   "shim_pids": [row["shim_pid"] for row in rows],
                                   "node_pids": [row["node_pid"] for row in rows],
                                   "markers_complete": True}
    if targeted and request["fixture"] == "long_explore" and request["strategy"] == "improved":
        saved = json.loads((binding["work_dir"] / "state.json").read_text())
        artifacts["handover_private"] = {"canonical_artifact_sha256": _canonical_marker(binding, saved)}
    return metrics, artifacts


def _i05_tsc(request, binding):
    if not {"node", "tsc_js"}.issubset(binding["sources"]):
        raise HelperError("typescript_binding_missing")
    work = binding["work_dir"]; project = work / "project"; project.mkdir(mode=0o700)
    markers = work / "shim-markers"; markers.mkdir(mode=0o700)
    component = project / "component.ts"; _write(component, request["inputs"]["source"].encode())
    _write(project / "tsconfig.json", b'{"compilerOptions":{"strict":true,"noEmit":true,"noLib":true},"files":["component.ts"]}\n')
    bindir = project / "node_modules"; bindir.mkdir(mode=0o700); (bindir / ".bin").mkdir(mode=0o700)
    shim_text = TSC_SHIM.replace("{python}", str(binding["sources"]["python"])).replace("{{", "{").replace("}}", "}")
    shim = bindir / ".bin/tsc"; _write(shim, shim_text.encode(), True)
    base_env = {"TSC_NODE": str(binding["sources"]["node"]), "TSC_JS": str(binding["sources"]["tsc_js"]),
                "TSC_SHIM_MARKERS": str(markers), "TSC_SHIM_NONCE": binding["nonce"],
                "TSC_SHIM_RUN_ID": binding["run_id"], "TSC_SHIM_TASK_ID": "repo_tsc_once",
                "TSC_SHIM_SHA256": _file_digest(shim),
                "TSC_NODE_SHA256": binding["source_identities"]["node"]["sha256"],
                "TSC_JS_SHA256": binding["source_identities"]["tsc_js"]["sha256"]}
    argv = [shim, "--noEmit"]
    if request["strategy"] == "raw":
        operations = [_op(binding, f"tsc-{slot}", argv, env={**base_env, "TSC_SHIM_SLOT": slot}, allowed=(1, 2),
                          timeout=30, cwd=project)
                      for slot in ("1", "2")]
    else:
        payload = {"session_id": "session-host", "cwd": str(project), "hook_event_name": "PostToolUse",
                   "tool_name": "Edit", "tool_input": {"file_path": str(component)}}
        env = {**base_env, "TSC_SHIM_SLOT": "1", "HOOK_OBSERVATIONS_STATE_DIR": str(work / "observation-state"),
               "HOOK_OBSERVATIONS_TSC_TIMEOUT": "15"}
        state = work / "observation-state"; state.mkdir(mode=0o700)
        operations = [_op(binding, "c-typescript", [binding["sources"]["python"], binding["sources"]["observations_core"],
                                                     "typescript", "--runtime", "claude"], stdin=canonical(payload), env=env,
                          timeout=30)]
    executor = Executor(binding, operations, time.monotonic() + LIMITS["seconds"])
    outputs = [executor.run() for _ in operations]
    shim_rows = _joined_shim_records(binding, ("1", "2") if request["strategy"] == "raw" else ("1",),
                                     executor.records, request["strategy"])
    diagnostic = shim_rows[0]["diagnostic"]
    if "error TS" not in diagnostic or any(row["diagnostic_sha256"] != shim_rows[0]["diagnostic_sha256"] for row in shim_rows):
        raise HelperError("tsc_diagnostic_invalid", executor.records)
    if request["strategy"] == "improved":
        try:
            emitted = json.loads(outputs[0]["stderr"].decode().splitlines()[-1])
        except (IndexError, ValueError, UnicodeDecodeError) as error:
            raise HelperError("tsc_observation_invalid", executor.records) from error
        first_errors = emitted.get("first_errors", emitted.get("additionalContext", {}).get("first_errors", []))
        if not first_errors or not all(line in diagnostic for line in first_errors):
            raise HelperError("tsc_diagnostic_not_reused", executor.records)
    facts = {"tsc_runs": len(shim_rows), "exit_code": shim_rows[0]["exit_code"],
             "diagnostic_sha256": shim_rows[0]["diagnostic_sha256"],
             "diagnostic_reused": request["strategy"] == "improved",
             "observer_exit_code": outputs[0]["record"]["exit_code"] if request["strategy"] == "improved" else None}
    return _payload(diagnostic if request["strategy"] == "improved" else diagnostic * 2, facts, ["typescript-error"]), executor.records, ["/fixture/component.ts"]


def _failure_payload(work, index, outcome, code):
    value = {"session_id": "session-host", "cwd": str(work), "hook_event_name": "PostToolUse",
             "tool_name": "Bash", "tool_use_id": f"tool-{index}", "tool_input": {"command": "false"}}
    if outcome == "failure":
        value.update({"hook_event_name": "PostToolUseFailure", "exit_code": 1, "is_error": True,
                      "error": {"code": code, "message": "synthetic failure"}})
    elif outcome == "edit":
        value.update({"tool_name": "Edit", "tool_input": {"file_path": str(work / "x.ts")}})
    else:
        value["exit_code"] = 0
    return value


def _i05_failure(request, binding):
    code = request["inputs"]["failure_code"]
    if not isinstance(code, str) or not code:
        raise HelperError("failure_code_invalid")
    sequence = ("failure", "failure", "failure", "success", "failure", "failure", "edit", "failure", "failure")
    if request["strategy"] == "raw":
        script = binding["work_dir"] / "raw-observe.py"; state = binding["work_dir"] / "raw-state.json"
        _write(script, RAW_OBSERVER.encode()); operations = [
            _op(binding, f"raw-observe-{index}-{outcome}",
                [binding["sources"]["python"], script, state, outcome])
            for index, outcome in enumerate(sequence)]
        executor = Executor(binding, operations, time.monotonic() + LIMITS["seconds"])
        outputs = [executor.run() for _ in operations]; records = executor.records
        notifications = sum(b"raw-three-failures" in item["stderr"] for item in outputs)
        facts = {"failure_events": 7, "notifications": notifications, "success_resets": 0, "edit_resets": 0,
                 "false_notifications": max(0, notifications - 1), "forced_stops": 0}
    else:
        state = binding["work_dir"] / "observation-state"; state.mkdir(mode=0o700)
        env = {"HOOK_OBSERVATIONS_STATE_DIR": str(state)}; operations = []
        for index, outcome in enumerate(sequence):
            payload = _failure_payload(binding["work_dir"], index, outcome, code)
            operations.append(_op(binding, f"observe-{index}-{outcome}",
                [binding["sources"]["python"], binding["sources"]["observations_core"], "observe", "--runtime", "claude"],
                stdin=canonical(payload), env=env))
        executor = Executor(binding, operations, time.monotonic() + LIMITS["seconds"])
        outputs, snapshots = [], []
        for index, outcome in enumerate(sequence):
            outputs.append(executor.run())
            entries = []
            for path in sorted(state.glob("failure-*.json")):
                value = json.loads(path.read_text())
                entries.append({"sha256": _file_digest(path), "count": value.get("count"), "state": value})
            snapshots.append({"index": index, "outcome": outcome, "states": entries})
        records = executor.records
        _write(binding["work_dir"] / "reset-snapshots.json", canonical(snapshots))
        notifications = sum(b"same_structured_failure_three_times" in item["stderr"] for item in outputs)
        stored = list(state.glob("failure-*.json"))
        if len(stored) != 1 or json.loads(stored[0].read_text()).get("count") != 2:
            raise HelperError("failure_state_invalid", records)
        facts = {"failure_events": 7, "notifications": notifications, "success_resets": 1, "edit_resets": 1,
                 "false_notifications": max(0, notifications - 1), "forced_stops": 0}
        if facts != {"failure_events": 7, "notifications": 1, "success_resets": 1, "edit_resets": 1,
                     "false_notifications": 0, "forced_stops": 0}:
            raise HelperError("failure_counter_mismatch", records)
    context = json.dumps(facts, sort_keys=True)
    return _payload(context, facts, []), records, ["/fixture/failure-state"]


def _record_bytes(binding, record, stream):
    name = record.get(stream + "_file")
    if not isinstance(name, str) or Path(name).name != name:
        raise HelperError("ledger_artifact_invalid")
    path = binding["raw_dir"] / name
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise HelperError("ledger_artifact_missing")
    data = path.read_bytes()
    if digest(data) != record.get(stream + "_sha256") or len(data) != record.get(stream + "_bytes"):
        raise HelperError("ledger_artifact_mismatch")
    return data


def _validate_i04_state(state):
    top = {"schema_version", "objective", "next_acceptance", "plan", "dependencies", "unanswered_questions",
           "required_gates", "evidence", "next_action"}
    if not isinstance(state, dict) or set(state) != top or state.get("schema_version") != 1:
        raise HelperError("handover_state_schema_invalid")
    if any(not isinstance(state.get(key), str) or not state[key] for key in
           ("objective", "next_acceptance", "next_action")):
        raise HelperError("handover_required_text_invalid")
    plan = state.get("plan")
    if (not isinstance(plan, dict) or set(plan) != {"path", "anchor", "version", "sha256"} or
            plan.get("anchor") != "improvement-plan" or plan.get("version") != "v13" or
            not isinstance(plan.get("path"), str) or not HEX64.fullmatch(str(plan.get("sha256")))):
        raise HelperError("handover_plan_invalid")
    if state.get("dependencies") != ["synthetic-docs"] or state.get("unanswered_questions") != []:
        raise HelperError("handover_dependencies_or_questions_invalid")
    gate = {"name": "unit", "status": "passed", "approval_ref": None, "evidence_refs": ["unit-suite"]}
    evidence = state.get("evidence")
    if state.get("required_gates") != [gate] or not isinstance(evidence, list) or len(evidence) != 1:
        raise HelperError("handover_gate_identity_invalid")
    item = evidence[0]
    fingerprints = {"diff": "old", "dependencies": "same", "execution": "same", "plan": "same", "failure": "same"}
    if item != {"name": "unit-suite", "status": "passed", "command": "unit", "result": "passed",
                "fingerprints": fingerprints}:
        raise HelperError("handover_evidence_invalid")


def _canonical_marker(binding, expected_state):
    directory = binding["work_dir"] / "project/.local/handovers"
    files = list(directory.glob("*.md")) if directory.is_dir() else []
    if len(files) != 1 or files[0].is_symlink() or files[0].stat().st_nlink != 1:
        raise HelperError("handover_canonical_missing")
    first, separator, body = files[0].read_text().partition("\n")
    prefix, suffix = "<!-- codex-session-handover:", " -->"
    if not separator or not first.startswith(prefix) or not first.endswith(suffix):
        raise HelperError("handover_canonical_marker_invalid")
    try:
        metadata = json.loads(base64.urlsafe_b64decode(first[len(prefix):-len(suffix)].encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise HelperError("handover_canonical_marker_invalid") from error
    unsigned = {key: value for key, value in metadata.items() if key != "artifact_sha256"}
    owner = {"runtime": "codex", "session_id": "session-host", "task_id": "task-host", "thread_id": "thread-host"}
    if (metadata.get("kind") != "canonical" or metadata.get("schema_version") != 1 or
            metadata.get("owner") != owner or metadata.get("runtime") != "codex" or
            metadata.get("project_path") != str(binding["work_dir"] / "project") or
            metadata.get("worktree_path") != str(binding["work_dir"] / "project") or
            metadata.get("task_dir") != str(binding["work_dir"] / "runtime-home/.local/memory/task-host") or
            metadata.get("state") != expected_state or
            metadata.get("body_sha256") != digest(body.encode()) or
            metadata.get("artifact_sha256") != digest(canonical(unsigned) + b"\n" + body.encode())):
        raise HelperError("handover_canonical_identity_invalid")
    return metadata["artifact_sha256"]


def _baseline_checked(request: dict, facts: dict) -> dict:
    if request["strategy"] != "raw":
        return facts
    golden = BASELINE_GOLDEN.get(request["fixture"])
    if not golden or any(facts.get(key) != value for key, value in golden["behavior"].items()):
        raise HelperError("baseline_conformance_mismatch")
    return facts


def _calculate(request, binding, payload, records):
    fixture, strategy = request["fixture"], request["strategy"]
    if fixture not in FIXTURE_TARGETS[request["candidate"]]:
        return {"neutral": True}
    if fixture == "cli_quiet_retrieve":
        expected_names = ["source-command"] if strategy == "raw" else ["quiet-run", "retrieve-log"]
        if [row["name"] for row in records] != expected_names or records[0]["exit_code"] != 7:
            raise HelperError("quiet_ledger_invalid", records)
        if strategy == "raw":
            selected = _record_bytes(binding, records[0], "stdout") + _record_bytes(binding, records[0], "stderr")
        else:
            logs = list((binding["work_dir"] / "quiet-logs").glob("quiet-*.log"))
            if len(logs) != 1 or logs[0].is_symlink() or logs[0].stat().st_nlink != 1:
                raise HelperError("quiet_log_invalid", records)
            complete = logs[0].read_bytes(); selected = _record_bytes(binding, records[1], "stdout")
            expected = b"".join(f"error-{index:04d}: stale-index\n".encode() for index in range(2000))
            if complete != expected or len(complete) <= len(selected) or selected != complete[-16384:]:
                raise HelperError("quiet_retrieval_invalid", records)
        if payload.get("context", "").encode() != selected or b"stale-index" not in selected:
            raise HelperError("quiet_payload_mismatch", records)
        return _baseline_checked(request, {"child_exit": 7, "diagnostic_present": True, "source_runs": 1,
                                           "retrieval_runs": int(strategy == "improved")})
    if fixture == "long_explore":
        _validate_i04_state(request["inputs"]["state"])
        saved = json.loads((binding["work_dir"] / "state.json").read_text())
        _validate_i04_state(saved)
        expected_saved = _i04_expected_state(request, binding)
        if saved != expected_saved:
            raise HelperError("handover_saved_state_mismatch", records)
        if strategy == "raw":
            expected_names = ["baseline-handover-save", "baseline-handover-inject"]
            if [row["name"] for row in records] != expected_names:
                raise HelperError("handover_raw_operation_invalid", records)
            handover = binding["work_dir"] / "project/.local/HANDOVER.md"
            if handover.is_symlink() or not handover.is_file() or handover.stat().st_nlink != 1:
                raise HelperError("handover_raw_artifact_missing", records)
            saved_handover = handover.read_text()
            injected = _record_bytes(binding, records[1], "stdout").decode(errors="strict")
            exact_injected = I04_INJECT_TEMPLATE.replace("__HANDOVER__", saved_handover.rstrip("\n"))
            if injected != exact_injected:
                raise HelperError("handover_raw_injection_mismatch", records)
            normalized = _i04_normalize_raw(injected, binding)
            loaded = {"context": normalized, "state": saved,
                      "effective_required_gates": saved["required_gates"]}
            validity = "passed"
            marker_hash = None
        else:
            if [row["name"] for row in records] != ["handover-init", "handover-save", "handover-load"]:
                raise HelperError("handover_ledger_invalid", records)
            try:
                loaded = json.loads(_record_bytes(binding, records[-1], "stdout"))
            except (ValueError, UnicodeDecodeError) as error:
                raise HelperError("handover_load_invalid", records) from error
            if loaded.get("status") != "loaded" or loaded.get("state") != saved:
                raise HelperError("handover_state_roundtrip_invalid", records)
            marker_hash = _canonical_marker(binding, saved)
            if loaded.get("hash") != marker_hash:
                raise HelperError("handover_canonical_hash_mismatch", records)
            gates = loaded.get("effective_required_gates") or []
            validity = gates[0].get("status") if len(gates) == 1 else None
        required = (saved["objective"], saved["next_acceptance"], saved["next_action"],
                    "unit", "unit-suite", "synthetic-docs", "improvement-plan", "v13")
        verified_context = _logical_context(loaded.get("context", ""), binding)
        if not all(item in verified_context for item in required):
            raise HelperError("handover_required_fact_missing", records)
        if strategy == "improved" and validity != "needs_revalidation":
            raise HelperError("handover_revalidation_missing", records)
        expected_context = (_i04_expected_injected(saved) if strategy == "raw" else
                            _i04_model_context(saved, validity, strategy))
        if payload.get("context") != expected_context:
            raise HelperError("handover_model_context_mismatch", records)
        semantics = _i04_semantics(saved, validity)
        if strategy == "raw":
            headings = ("## Task Log (05_log.md)", "## Plan (30_plan.md)",
                        "## Recent Conversation (last 30 entries)", "## Recovery Instructions")
            if (not all(heading in payload["context"] for heading in headings) or
                    canonical(semantics).decode() not in payload["context"] or
                    canonical(semantics["plan"]).decode() not in payload["context"]):
                raise HelperError("handover_raw_conformance_invalid", records)
        else:
            try:
                model_value = json.loads(payload["context"])
            except (TypeError, ValueError) as error:
                raise HelperError("handover_model_context_invalid", records) from error
            if model_value != semantics:
                raise HelperError("handover_model_state_incomplete", records)
        return _baseline_checked(request, {"objective": saved["objective"], "gate_status": validity,
                "required_facts_complete": True, "canonical_verified": marker_hash is not None,
                "init_runs": sum(row["name"] == "handover-init" for row in records),
                "save_runs": sum(row["name"] == "handover-save" for row in records),
                "load_runs": sum(row["name"] == "handover-load" for row in records),
                "baseline_save_runs": sum(row["name"] == "baseline-handover-save" for row in records),
                "baseline_inject_runs": sum(row["name"] == "baseline-handover-inject" for row in records)})
    if fixture == "repo_tsc_once":
        slots = ("1", "2") if strategy == "raw" else ("1",)
        shim_rows = _joined_shim_records(binding, slots, records, strategy); diagnostic = shim_rows[0]["diagnostic"]
        if any(item["diagnostic_sha256"] != shim_rows[0]["diagnostic_sha256"] for item in shim_rows):
            raise HelperError("tsc_diagnostic_mismatch", records)
        reused, observer_exit = False, None
        if strategy == "improved":
            if len(records) != 1 or records[0]["name"] != "c-typescript":
                raise HelperError("tsc_observer_ledger_invalid", records)
            observer_exit = records[0]["exit_code"]
            try:
                emitted = json.loads(_record_bytes(binding, records[0], "stderr").decode().splitlines()[-1])
            except (IndexError, ValueError, UnicodeDecodeError) as error:
                raise HelperError("tsc_observation_invalid", records) from error
            first_errors = emitted.get("first_errors", emitted.get("additionalContext", {}).get("first_errors", []))
            reused = bool(first_errors) and all(line in diagnostic for line in first_errors)
            if not reused:
                raise HelperError("tsc_diagnostic_not_reused", records)
        expected_context = diagnostic if strategy == "improved" else diagnostic * 2
        if payload.get("context") != expected_context:
            raise HelperError("tsc_payload_mismatch", records)
        return _baseline_checked(request, {"tsc_runs": len(shim_rows), "exit_code": shim_rows[0]["exit_code"],
                "diagnostic_sha256": shim_rows[0]["diagnostic_sha256"],
                "diagnostic_reused": reused, "observer_exit_code": observer_exit})
    expected = [f"{'raw-observe' if strategy == 'raw' else 'observe'}-{index}-{outcome}"
                for index, outcome in enumerate(("failure", "failure", "failure", "success", "failure",
                                                 "failure", "edit", "failure", "failure"))]
    if [row["name"] for row in records] != expected:
        raise HelperError("failure_ledger_invalid", records)
    phrase = b"raw-three-failures" if strategy == "raw" else b"same_structured_failure_three_times"
    notification_positions = [index for index, row in enumerate(records)
                              if phrase in _record_bytes(binding, row, "stderr")]
    expected_notifications = [2, 7] if strategy == "raw" else [2]
    if notification_positions != expected_notifications:
        raise HelperError("failure_notification_position_invalid", records)
    notifications = len(notification_positions)
    success_resets = edit_resets = 0
    if strategy == "improved":
        stored = list((binding["work_dir"] / "observation-state").glob("failure-*.json"))
        if len(stored) != 1 or json.loads(stored[0].read_text()).get("count") != 2:
            raise HelperError("failure_state_invalid", records)
        snapshots_path = binding["work_dir"] / "reset-snapshots.json"
        try:
            snapshots = json.loads(snapshots_path.read_text())
        except (OSError, ValueError) as error:
            raise HelperError("failure_snapshot_invalid", records) from error
        outcomes = ("failure", "failure", "failure", "success", "failure", "failure", "edit", "failure", "failure")
        expected_counts = (1, 2, 3, 0, 1, 2, 0, 1, 2)
        expected_identity = {"runtime": "claude", "session": "session-host", "worktree": str(binding["work_dir"])}
        if len(snapshots) != len(outcomes) or any(row.get("index") != index or row.get("outcome") != outcome or
                not isinstance(row.get("states"), list) for index, (row, outcome) in enumerate(zip(snapshots, outcomes))):
            raise HelperError("failure_snapshot_invalid", records)
        for index, outcome in enumerate(outcomes):
            states = snapshots[index]["states"]
            if len(states) != 1:
                raise HelperError("failure_snapshot_invalid", records)
            snapshot = states[0]; state = snapshot.get("state")
            if (not isinstance(state, dict) or snapshot.get("count") != expected_counts[index] or
                    state.get("count") != expected_counts[index] or state.get("identity") != expected_identity or
                    state.get("owner") != "hook-observations" or state.get("schema") != 1 or
                    state.get("marker") != "hook-observations-generated-v1" or
                    snapshot.get("sha256") != digest(canonical(state) + b"\n") or
                    len(state.get("delivery_ids", [])) != index + 1 or
                    len(set(state.get("delivery_ids", []))) != index + 1):
                raise HelperError("failure_snapshot_invalid", records)
            if outcome in {"success", "edit"}:
                before = snapshots[index - 1]["states"] if index else []
                if not before or state.get("count") != 0:
                    raise HelperError("failure_reset_missing", records)
                success_resets += outcome == "success"; edit_resets += outcome == "edit"
    facts = {"failure_events": 7, "notifications": notifications,
             "success_resets": success_resets, "edit_resets": edit_resets,
             "false_notifications": max(0, notifications - 1), "forced_stops": 0}
    if payload.get("context") != json.dumps(facts, sort_keys=True):
        raise HelperError("failure_payload_mismatch", records)
    return _baseline_checked(request, facts)


def _result(request, status, mechanism, payload, references):
    value = {"owner": RESULT_OWNER, "schema": SCHEMA, "candidate": request["candidate"],
             "fixture": request["fixture"], "status": status, "mechanism": mechanism,
             "payload": payload, "references": references}
    value["content_hash"] = digest(value)
    if len(canonical(value)) > LIMITS["result_bytes"]:
        raise HelperError("result_too_large")
    return value


def make_request(row: dict, spec: dict) -> dict:
    inputs = {}
    targeted = row["fixture"] in FIXTURE_TARGETS.get(row["candidate"], set())
    if targeted and row["fixture"] == "cli_quiet_retrieve":
        inputs = {"reason": "stale-index"}
    elif targeted and row["fixture"] == "long_explore":
        fingerprints = {name: "same" for name in ("diff", "dependencies", "execution", "plan", "failure")}
        inputs = {"state": {"schema_version": 1, "objective": "identify owner and hold unsafe gate",
            "next_acceptance": "expired evidence is revalidated", "plan": {"path": "logical", "anchor": "improvement-plan",
            "version": "v13", "sha256": "0" * 64}, "dependencies": ["synthetic-docs"], "unanswered_questions": [],
            "required_gates": [{"name": "unit", "status": "passed", "approval_ref": None,
                                "evidence_refs": ["unit-suite"]}],
            "evidence": [{"name": "unit-suite", "status": "passed", "command": "unit", "result": "passed",
                          "fingerprints": {**fingerprints, "diff": "old"}}], "next_action": "revalidate unit evidence"}}
    elif targeted and row["fixture"] == "repo_tsc_once":
        inputs = {"source": spec["files"]["component.ts"]}
    elif targeted and row["fixture"] == "cli_failure_reset":
        inputs = {"failure_code": "tsc:component"}
    return {"owner": REQUEST_OWNER, "schema": SCHEMA, "candidate": row["candidate"], "fixture": row["fixture"],
            "strategy": "raw" if row["variant"] == "baseline" else "improved", "inputs": inputs, "limits": LIMITS}


def supervise(base: Path, row: dict, spec: dict, staged: dict, dependencies: dict, python: dict,
              home_sha256: str) -> dict:
    for path in (base, base / "work", base / "raw", base / "ledger"):
        path.mkdir(mode=0o700)
    sources = {role: {"path": str(path), "sha256": SOURCE_POLICY[role], "role": role}
               for role, path in staged.items()}
    sources["python"] = {"path": python["path"], "sha256": python["sha256"], "role": "python"}
    dependency_dir = base / "dependencies"; dependency_dir.mkdir(mode=0o700)
    for role, dependency in dependencies.items():
        source_path = Path(dependency["path"])
        if role == "tsc_js":
            exported = dependency_dir / "tsc.js"
            with source_path.open("rb") as source:
                _write(exported, source.read())
            if _file_digest(exported) != dependency["sha256"]:
                raise HelperError("dependency_export_mismatch")
            source_path = exported
        sources[role] = {"path": str(source_path), "sha256": dependency["sha256"], "role": role}
    binding = {"root": str(base), "run_id": row["run_id"], "nonce": digest(row)[:32],
               "work_dir": str(base / "work"), "raw_dir": str(base / "raw"), "ledger_dir": str(base / "ledger"),
               "home_sha256": home_sha256, "sources": sources}
    value = run(make_request(row, spec), binding); encoded = canonical(value["result"]).decode()
    if len(encoded.encode()) > LIMITS["result_bytes"] or encoded.count('"owner":"harness-host-helper-result-v1"') != 1:
        raise HelperError("canonical_result_invalid")
    return {**value, "prompt_context": f'<mechanism-context schema="host-helper-result-v1">{encoded}</mechanism-context>'}


def _claim_binding(binding: dict) -> dict:
    keys = {"root", "run_id", "nonce", "work_dir", "ledger_dir", "raw_dir", "home_sha256", "sources"}
    if set(binding) != keys or not SAFE_ID.fullmatch(str(binding.get("run_id"))):
        raise HelperError("binding_schema_invalid")
    root_input = Path(binding["root"])
    if root_input.is_symlink():
        raise HelperError("binding_root_symlink")
    try:
        root = root_input.resolve(strict=True)
    except OSError as error:
        raise HelperError("binding_root_missing") from error
    if not root.is_dir() or stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise HelperError("binding_root_not_private")
    return {name: _private_dir(Path(binding[name]), root) for name in ("work_dir", "raw_dir", "ledger_dir")}


def run(request: dict, binding: dict) -> dict:
    paths = _claim_binding(binding); request_hash = digest(request)
    claim = paths["ledger_dir"] / f"{binding['run_id']}.claimed.json"
    _write(claim, canonical({"owner": LEDGER_OWNER, "schema": SCHEMA, "run_id": binding["run_id"],
                             "request_hash": request_hash, "status": "claimed"}))
    started = time.monotonic(); records = []; reason = None; clean = None
    mechanism_metrics = {}; artifacts = {}
    try:
        validate_request(request); clean = validate_binding(binding)
        if request["fixture"] not in FIXTURE_TARGETS[request["candidate"]]:
            payload, mechanism, references = _payload("", {"neutral": True}, []), "neutral", []
            status = "neutral"
        elif request["candidate"] == "I03":
            payload, records, references = _i03(request, clean); mechanism, status = "quiet-run", "observed"
        elif request["candidate"] == "I04":
            payload, records, references = _i04(request, clean); mechanism, status = "session-handover", "observed"
        elif request["fixture"] == "repo_tsc_once":
            payload, records, references = _i05_tsc(request, clean); mechanism, status = "typescript-observation", "observed"
        else:
            payload, records, references = _i05_failure(request, clean); mechanism, status = "failure-observation", "observed"
        calculated = _calculate(request, clean, payload, records)
        if payload.get("facts") != calculated:
            raise HelperError("counter_claim_mismatch", records)
        mechanism_metrics, artifacts = _mechanism_evidence(request, clean, payload, records)
        _check_sources(clean, content=True)
        result = _result(request, status, mechanism, payload, references)
    except HelperError as error:
        reason, records = error.reason, error.records or records
        result = _result(request, "failed", "host-helper", _payload("", {"failure_reason": reason}, []), [])
    except Exception:
        reason = "unexpected_helper_exception"
        result = _result(request, "failed", "host-helper", _payload("", {"failure_reason": reason}, []), [])
    elapsed = round((time.monotonic() - started) * 1000, 3)
    if mechanism_metrics:
        mechanism_metrics["output_bytes"]["model_result"] = len(canonical(result))
    evidence = {"helper_mechanism_observed": result["status"] == "observed",
                "model_received_helper_result": False, "task_outcome_passed": False,
                "request_hash": request_hash, "result_hash": result["content_hash"],
                "operations": records, "operation_count": len(records), "elapsed_ms": elapsed,
                "metrics": mechanism_metrics, "artifacts": artifacts, "failure_reason": reason}
    final_path = paths["ledger_dir"] / f"{binding['run_id']}.final.json"
    final_value = {"owner": LEDGER_OWNER, "schema": SCHEMA, "run_id": binding["run_id"],
                   "status": "pre_model_failed" if reason else "helper_complete",
                   "request_hash": request_hash, "result_hash": result["content_hash"],
                   "failure_reason": reason}
    try:
        final_bytes = canonical(final_value)
        evidence["generated"] = _scan(paths["work_dir"], paths["raw_dir"], paths["ledger_dir"],
                                      reserve_files=1, reserve_bytes=len(final_bytes))
    except HelperError as error:
        reason = error.reason; evidence["failure_reason"] = reason
        result = _result(request, "failed", "host-helper", _payload("", {"failure_reason": reason}, []), [])
        evidence["helper_mechanism_observed"] = False
        evidence["result_hash"] = result["content_hash"]
        evidence["generated"] = {"files": None, "bytes": None}
        final_value = {"owner": LEDGER_OWNER, "schema": SCHEMA, "run_id": binding["run_id"],
                       "status": "pre_model_failed", "request_hash": request_hash,
                       "result_hash": result["content_hash"], "failure_reason": reason}
        final_bytes = canonical(final_value)
    _write(final_path, final_bytes)
    if _file_digest(final_path) != digest(final_bytes):
        raise HelperError("terminal_ledger_mismatch")
    return {"result": result, "evidence": evidence, "pair_stop": reason is not None}
