from __future__ import annotations

import importlib.util
import base64
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "session_handover.py"
ADAPTER = ROOT / "hooks" / "session-handover.py"


def load_core():
    spec = importlib.util.spec_from_file_location("session_handover", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load_core()


class SessionHandoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.worktree = (Path(self.temp_dir.name) / "worktree").resolve()
        self.worktree.mkdir()
        self.task_memory = (Path(self.temp_dir.name) / "runtime-home" / ".local" / "memory").resolve()
        self.task_memory.mkdir(parents=True)
        self.plan = self.worktree / "dashboard.html"
        self.plan.write_text(
            '<main>before</main>\n<section id="improvement-plan" data-plan-version="v10">\n'
            '<article><section id="nested">nested</section></article>\n</section>\n<footer>after</footer>\n',
            encoding="utf-8",
        )
        self.plan_hash = core.plan_section_hash(self.plan, "#improvement-plan")
        self.add_task("task-one", session_id="session-1", thread_id="thread-1")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_task(self, name: str, **updates: object) -> Path:
        task = self.task_memory / name
        task.mkdir()
        metadata: dict[str, object] = {
            "schema_version": 1,
            "task_id": name,
            "task_title": f"Synthetic {name}",
            "project_path": str(self.worktree),
            "worktree_path": str(self.worktree),
            "task_state": "active",
            "code_change": True,
            "created_at": "2026-10-13T00:00:00+09:00",
            "updated_at": "2026-10-13T00:00:00+09:00",
        }
        metadata.update(updates)
        (task / "task-meta.json").write_text(json.dumps(metadata), encoding="utf-8")
        return task

    def state(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "objective": "Restore the exact synthetic session.",
            "next_acceptance": "AC01 exact identity and AC04 evidence validity.",
            "plan": {
                "path": str(self.plan),
                "anchor": "#improvement-plan",
                "version": "v10",
                "sha256": self.plan_hash,
            },
            "dependencies": ["synthetic dependency"],
            "unanswered_questions": ["synthetic approval still pending"],
            "required_gates": [
                {
                    "name": "independent-review",
                    "status": "pending",
                    "approval_ref": "approval-fixture-1",
                    "evidence_refs": ["unit-suite"],
                }
            ],
            "evidence": [
                {
                    "name": "unit-suite",
                    "status": "passed",
                    "command": "python3 -m unittest synthetic",
                    "result": "exit 0",
                    "fingerprints": {
                        "diff": "diff-a",
                        "dependencies": "deps-a",
                        "execution": "exec-a",
                        "plan": self.plan_hash,
                        "failure": "none-a",
                    },
                }
            ],
            "next_action": "Run the next synthetic acceptance fixture.",
        }

    def request(self, **updates: object) -> dict[str, object]:
        request: dict[str, object] = {
            "runtime": "codex",
            "cwd": str(self.worktree),
            "session_id": "session-1",
            "thread_id": "thread-1",
            "task_memory_root": str(self.task_memory),
            "project_path": str(self.worktree),
            "worktree_path": str(self.worktree),
            "short_state": self.state(),
        }
        request.update(updates)
        return request

    def init_fixture(self, runtime: str, label: str = "new") -> tuple[dict[str, object], dict[str, str], Path, Path, dict[str, object]]:
        runtime_home = (Path(self.temp_dir.name) / f"{label}-{runtime}-home").resolve()
        worktree = (Path(self.temp_dir.name) / f"{label}-{runtime}-worktree").resolve()
        runtime_home.mkdir()
        worktree.mkdir()
        plan = worktree / "dashboard.html"
        plan.write_text(
            '<section id="improvement-plan" data-plan-version="v10">fixture</section>',
            encoding="utf-8",
        )
        root = runtime_home / ".local" / "memory"
        request: dict[str, object] = {
            "runtime": runtime, "cwd": str(worktree),
            "project_path": str(worktree), "worktree_path": str(worktree),
            "task_memory_root": str(root), "task_id": f"task-{label}",
            "task_title": f"Synthetic {label}", "session_id": f"session-{label}",
            "thread_id": f"thread-{label}", "code_change": True,
        }
        state: dict[str, object] = {
            "schema_version": 1, "objective": "Resume initialized task.",
            "next_acceptance": "The initialized task resolves and restores.",
            "plan": {"path": str(plan), "anchor": "#improvement-plan", "version": "v10",
                     "sha256": core.plan_section_hash(plan, "#improvement-plan")},
            "dependencies": [], "unanswered_questions": [], "required_gates": [],
            "evidence": [], "next_action": "Continue the initialized task.",
        }
        variable = "CODEX_HOME" if runtime == "codex" else "CLAUDE_HOME"
        return request, {variable: str(runtime_home)}, root, worktree, state

    def assert_error(self, code: str, callback) -> None:
        with self.assertRaises(core.HandoverError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def run_hook(self, runtime: str, event: str, payload: dict[str, object]):
        environment = {"SESSION_HANDOVER_TASK_MEMORY_ROOT": str(self.task_memory)}
        with mock.patch.dict(os.environ, environment, clear=False):
            return core.run_hook(runtime, event, payload)

    def test_init_resolve_save_load_for_both_runtimes(self) -> None:
        required = core.REQUIRED_META | {"session_id", "thread_id"}
        for runtime in ("codex", "claude"):
            request, environment, root, worktree, state = self.init_fixture(runtime, runtime)
            request["code_change"] = runtime == "codex"
            with mock.patch.dict(os.environ, environment, clear=False):
                created = core.init_task(request)
                task, metadata = core.resolve_task(
                    worktree, request["session_id"], request["thread_id"], runtime=runtime,
                    expected_project=worktree, expected_worktree=worktree,
                    explicit_memory_base=root,
                )
                handover = core.save_handover({
                    **request, "short_state": state, "memory_dir": str(worktree / ".local"),
                })
                loaded = core.load_handover({
                    **request, "short_state": None, "memory_dir": str(worktree / ".local"),
                })
            self.assertEqual(created["status"], "created")
            self.assertEqual(Path(created["path"]), task / "task-meta.json")
            self.assertEqual(set(metadata), required)
            self.assertNotIn("runtime", metadata)
            self.assertNotIn("short_state", metadata)
            self.assertIs(metadata["code_change"], request["code_change"])
            self.assertEqual(handover["canonical"]["status"], "saved")
            self.assertEqual(loaded["state"]["objective"], state["objective"])
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(task.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(Path(created["path"]).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((root / ".session-handover-init.lock").stat().st_mode), 0o600)
            self.assertTrue(metadata["created_at"].endswith("+00:00"))
            self.assertEqual(metadata["created_at"], metadata["updated_at"])

    def test_init_rejects_identity_context_and_untrusted_roots_without_creation(self) -> None:
        request, environment, root, worktree, _ = self.init_fixture("codex", "negative")
        outside = (Path(self.temp_dir.name) / "outside-root").resolve()
        outside.mkdir()
        other = (Path(self.temp_dir.name) / "other-worktree").resolve()
        other.mkdir()
        cases = [
            ("missing_identity", {"session_id": None, "thread_id": None}),
            ("unsafe_identity", {"task_id": "../bad"}),
            ("context_mismatch", {"worktree_path": str(other)}),
            ("invalid_context_path", {"project_path": str(other / "missing")}),
            ("memory_root_escape", {"task_memory_root": str(outside)}),
            ("memory_root_escape", {"task_memory_root": ".local/memory"}),
            ("metadata_too_large", {"task_title": "x" * (core.MAX_JSON_BYTES + 1)}),
        ]
        with mock.patch.dict(os.environ, environment, clear=False):
            for reason, updates in cases:
                candidate = dict(request)
                candidate.update(updates)
                self.assert_error(reason, lambda candidate=candidate: core.init_task(candidate))
        self.assertFalse(root.exists())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(list(worktree.iterdir()), [worktree / "dashboard.html"])

    def test_init_identity_conflicts_are_independent(self) -> None:
        request, environment, root, worktree, _ = self.init_fixture("codex", "conflict")
        root.mkdir(parents=True)
        existing = root / "existing"
        existing.mkdir()
        base = {
            "schema_version": 1, "task_id": "existing", "task_title": "Existing",
            "project_path": str(worktree), "worktree_path": str(worktree),
            "task_state": "active", "code_change": True,
            "created_at": "2026-10-13T00:00:00+00:00", "updated_at": "2026-10-13T00:00:00+00:00",
        }
        meta_path = existing / "task-meta.json"
        with mock.patch.dict(os.environ, environment, clear=False):
            meta_path.write_text(json.dumps({**base, "session_id": request["session_id"], "thread_id": "other"}))
            self.assert_error("identity_conflict", lambda: core.init_task(request))
            meta_path.write_text(json.dumps({**base, "session_id": "other", "thread_id": request["thread_id"]}))
            self.assert_error("identity_conflict", lambda: core.init_task(request))
        self.assertFalse((root / request["task_id"]).exists())

    def test_init_accepts_each_identity_independently(self) -> None:
        for field, omitted in (("session_id", "thread_id"), ("thread_id", "session_id")):
            request, environment, _, _, _ = self.init_fixture("codex", field)
            request[omitted] = None
            with mock.patch.dict(os.environ, environment, clear=False):
                result = core.init_task(request)
            metadata = json.loads(Path(result["path"]).read_text())
            self.assertIn(field, metadata)
            self.assertNotIn(omitted, metadata)

    def test_init_preserves_existing_task_files_modes_and_metadata(self) -> None:
        request, environment, root, _, _ = self.init_fixture("codex", "preserve")
        root.mkdir(parents=True)
        root.parent.chmod(0o755)
        root.chmod(0o755)
        lock = root / ".session-handover-init.lock"
        lock.write_bytes(b"existing lock bytes\n")
        lock.chmod(0o644)
        task = root / request["task_id"]
        task.mkdir(mode=0o755)
        dirty = task / "05_log.md"
        dirty.write_bytes(b"user-owned\n")
        before = dirty.read_bytes()
        with mock.patch.dict(os.environ, environment, clear=False):
            created = core.init_task(request)
        self.assertEqual(created["status"], "created")
        self.assertEqual(dirty.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(root.parent.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o755)
        self.assertEqual(lock.read_bytes(), b"existing lock bytes\n")
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(task.stat().st_mode), 0o755)
        metadata = Path(created["path"])
        metadata_before = metadata.read_bytes()
        with mock.patch.dict(os.environ, environment, clear=False):
            self.assert_error("metadata_exists", lambda: core.init_task(request))
        self.assertEqual(metadata.read_bytes(), metadata_before)
        self.assertEqual(dirty.read_bytes(), before)

    def test_init_rejects_root_and_task_symlinks(self) -> None:
        request, environment, root, _, _ = self.init_fixture("codex", "symlink")
        outside = (Path(self.temp_dir.name) / "outside-init").resolve()
        outside.mkdir()
        root.parent.mkdir(parents=True)
        try:
            root.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with mock.patch.dict(os.environ, environment, clear=False):
            self.assert_error("memory_root_escape", lambda: core.init_task(request))
        root.unlink()
        root.mkdir()
        (root / request["task_id"]).symlink_to(outside, target_is_directory=True)
        with mock.patch.dict(os.environ, environment, clear=False):
            self.assert_error("task_path_escape", lambda: core.init_task(request))
        (root / request["task_id"]).unlink()
        task = root / request["task_id"]
        task.mkdir()
        foreign = outside / "foreign-meta.json"
        foreign.write_bytes(b"foreign\n")
        (task / "task-meta.json").symlink_to(foreign)
        with mock.patch.dict(os.environ, environment, clear=False):
            self.assert_error("path_symlink", lambda: core.init_task(request))
        self.assertEqual(foreign.read_bytes(), b"foreign\n")
        (task / "task-meta.json").unlink()
        task.rmdir()
        (root / ".hidden-link").symlink_to(outside, target_is_directory=True)
        with mock.patch.dict(os.environ, environment, clear=False):
            self.assert_error("task_path_escape", lambda: core.init_task(request))
        self.assertEqual(set(outside.iterdir()), {foreign})

    def test_init_rejects_hidden_task_directory_before_identity_can_be_skipped(self) -> None:
        request, environment, root, worktree, _ = self.init_fixture("codex", "hidden-task")
        hidden = root / ".shadow"
        hidden.mkdir(parents=True)
        (hidden / "task-meta.json").write_text(json.dumps({
            "schema_version": 1, "task_id": "shadow", "task_title": "Hidden",
            "project_path": str(worktree), "worktree_path": str(worktree),
            "task_state": "active", "code_change": True,
            "created_at": "2026-10-13T00:00:00+00:00",
            "updated_at": "2026-10-13T00:00:00+00:00",
            "session_id": request["session_id"], "thread_id": request["thread_id"],
        }))
        with mock.patch.dict(os.environ, environment, clear=False):
            self.assert_error("task_path_escape", lambda: core.init_task(request))
        self.assertFalse((root / request["task_id"]).exists())

    def test_init_accepts_trusted_runtime_home_symlink_and_preserves_ancestors(self) -> None:
        request, environment, root, _, _ = self.init_fixture("codex", "home-alias")
        physical_home = Path(environment["CODEX_HOME"])
        alias_home = Path(self.temp_dir.name) / "runtime-home-alias"
        physical_home.chmod(0o755)
        try:
            alias_home.symlink_to(physical_home, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        environment["CODEX_HOME"] = str(alias_home)
        request["task_memory_root"] = str(alias_home / ".local" / "memory")
        with mock.patch.dict(os.environ, environment, clear=False):
            result = core.init_task(request)
        self.assertEqual(result["status"], "created")
        self.assertEqual(Path(result["path"]), root / request["task_id"] / "task-meta.json")
        self.assertEqual(stat.S_IMODE(physical_home.stat().st_mode), 0o755)

    def test_init_faults_leave_no_metadata_temp_or_new_task_directory(self) -> None:
        request, environment, root, _, _ = self.init_fixture("codex", "fault")
        with mock.patch.dict(os.environ, environment, clear=False):
            with mock.patch.object(core.os, "fsync", side_effect=OSError("synthetic partial write")):
                with self.assertRaises(OSError):
                    core.init_task(request)
            self.assertFalse((root / request["task_id"]).exists())
            request["task_id"] = "task-link-fault"
            with mock.patch.object(core.os, "link", side_effect=OSError("synthetic publish failure")):
                with self.assertRaises(OSError):
                    core.init_task(request)
            request["task_id"] = "task-directory-fsync-fault"
            with mock.patch.object(core.os, "fsync", side_effect=[None, OSError("synthetic directory fsync failure")]):
                with self.assertRaises(OSError):
                    core.init_task(request)
            request["task_id"] = "task-directory-open-fault"
            real_open = core.os.open

            def fail_new_task_open(path, flags, mode=0o777, *, dir_fd=None):
                if path == request["task_id"] and flags & getattr(core.os, "O_DIRECTORY", 0):
                    raise OSError("synthetic task directory open failure")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(core.os, "open", side_effect=fail_new_task_open):
                self.assert_error("task_path_escape", lambda: core.init_task(request))
        self.assertFalse((root / "task-link-fault").exists())
        self.assertFalse((root / "task-directory-fsync-fault").exists())
        self.assertFalse((root / "task-directory-open-fault").exists())
        self.assertEqual(list(root.rglob(".task-meta.json.*")), [])

    def test_init_rollback_never_deletes_foreign_replacement(self) -> None:
        request, environment, root, _, _ = self.init_fixture("codex", "foreign-replacement")
        meta_path = root / request["task_id"] / "task-meta.json"
        calls = 0

        def replace_on_directory_fsync(_fd: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                meta_path.unlink()
                meta_path.write_bytes(b"foreign replacement\n")
                raise OSError("synthetic directory fsync failure")

        with mock.patch.dict(os.environ, environment, clear=False):
            with mock.patch.object(core.os, "fsync", side_effect=replace_on_directory_fsync):
                with self.assertRaises(OSError):
                    core.init_task(request)
        self.assertEqual(meta_path.read_bytes(), b"foreign replacement\n")
        self.assertEqual(list(root.rglob(".task-meta.json.*")), [])

    def test_init_cleanup_never_removes_replaced_task_directory(self) -> None:
        request, environment, root, _, _ = self.init_fixture("codex", "foreign-directory")
        task_dir = root / request["task_id"]
        displaced = root / "displaced-created-directory"

        def replace_directory(*_args, **_kwargs) -> None:
            task_dir.rename(displaced)
            task_dir.mkdir()
            (task_dir / "foreign.txt").write_bytes(b"foreign directory\n")
            raise OSError("synthetic publish failure")

        with mock.patch.dict(os.environ, environment, clear=False):
            with mock.patch.object(core.os, "link", side_effect=replace_directory):
                with self.assertRaises(OSError):
                    core.init_task(request)
        self.assertEqual((task_dir / "foreign.txt").read_bytes(), b"foreign directory\n")
        self.assertTrue(displaced.is_dir())
        self.assertEqual(list(displaced.iterdir()), [])

    def test_init_cli_json_contract_and_cross_process_no_replace(self) -> None:
        request, environment, root, _, _ = self.init_fixture("codex", "cli")
        args = [
            "python3", str(CORE_PATH), "init", "--runtime", "codex",
            "--cwd", str(request["cwd"]), "--project-path", str(request["project_path"]),
            "--worktree-path", str(request["worktree_path"]),
            "--task-memory-root", str(root), "--task-id", str(request["task_id"]),
            "--task-title", str(request["task_title"]), "--session-id", str(request["session_id"]),
            "--thread-id", str(request["thread_id"]), "--code-change", "true",
        ]
        process_env = {**os.environ, **environment}
        processes = [subprocess.Popen(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=process_env) for _ in range(2)]
        results = [process.communicate(timeout=10) + (process.returncode,) for process in processes]
        self.assertEqual(sorted(result[2] for result in results), [0, 2])
        success = next(result for result in results if result[2] == 0)
        rejected = next(result for result in results if result[2] == 2)
        created = json.loads(success[0])
        self.assertEqual(created["status"], "created")
        self.assertEqual(created["hash"], core._sha(Path(created["path"]).read_bytes()))
        self.assertEqual(success[1], "")
        self.assertEqual(rejected[0], "")
        self.assertEqual(json.loads(rejected[1])["status"], "rejected")
        invalid = subprocess.run(args[:-2], text=True, capture_output=True, env=process_env, check=False)
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(invalid.stdout, "")
        self.assertEqual(json.loads(invalid.stderr)["reason"], "invalid_arguments")
        legacy_invalid = subprocess.run(
            ["python3", str(CORE_PATH), "save"], text=True, capture_output=True,
            env=process_env, check=False,
        )
        self.assertEqual(legacy_invalid.returncode, 2)
        self.assertTrue(legacy_invalid.stderr.startswith("usage:"))
        self.assertNotIn('"reason"', legacy_invalid.stderr)
        self.assertEqual(len(list(root.rglob("task-meta.json"))), 1)
        self.assertEqual(list(root.rglob(".task-meta.json.*")), [])

    def test_exact_session_save_and_load_preserve_short_state_only(self) -> None:
        saved = core.save_handover(self.request())
        loaded = core.load_handover(
            self.request(short_state=None, current_fingerprints={
                "diff": "diff-a",
                "dependencies": "deps-a",
                "execution": "exec-a",
                "plan": self.plan_hash,
                "failure": "none-a",
            })
        )

        self.assertEqual(saved["canonical"]["status"], "saved")
        self.assertEqual(loaded["evidence_validity"][0]["status"], "current")
        self.assertIn("synthetic approval still pending", loaded["context"])
        self.assertIn("approval-fixture-1", loaded["context"])
        self.assertNotIn("transcript", loaded["context"].lower())
        self.assertNotIn("05_log", loaded["context"])

    def test_session_input_never_falls_back_to_matching_thread(self) -> None:
        self.assert_error(
            "task_not_found",
            lambda: core.save_handover(self.request(session_id="session-missing")),
        )
        self.assertFalse((self.worktree / ".local" / "handovers").exists())

    def test_both_provided_ids_must_match_same_task(self) -> None:
        self.assert_error(
            "task_not_found",
            lambda: core.save_handover(self.request(thread_id="thread-other")),
        )

    def test_thread_is_used_only_when_session_is_absent(self) -> None:
        result = core.save_handover(self.request(session_id=None))
        self.assertEqual(Path(result["canonical"]["path"]).name, "thread-thread-1.md")
        loaded = core.load_handover(self.request(session_id=None, short_state=None))
        self.assertEqual(loaded["status"], "loaded")

    def test_missing_identity_and_single_active_fallback_are_rejected(self) -> None:
        self.assert_error(
            "missing_identity",
            lambda: core.save_handover(self.request(session_id=None, thread_id=None)),
        )

    def test_unsafe_identity_is_rejected_instead_of_sanitized(self) -> None:
        self.assert_error(
            "unsafe_identity",
            lambda: core.save_handover(self.request(session_id="session/../../bad")),
        )
        self.assert_error(
            "unsafe_identity",
            lambda: core.save_handover(self.request(session_id="unknown")),
        )

    def test_unrelated_broad_context_is_filtered_before_validation(self) -> None:
        self.add_task(
            "unrelated", session_id="other-session", thread_id="other-thread",
            project_path="/", worktree_path="/",
        )
        result = core.save_handover(self.request())
        self.assertEqual(result["canonical"]["status"], "saved")

    def test_duplicate_exact_identity_is_rejected(self) -> None:
        self.add_task("task-two", session_id="session-1", thread_id="thread-1")
        self.assert_error("ambiguous_task", lambda: core.save_handover(self.request()))

    def test_invalid_metadata_and_context_mismatch_are_rejected(self) -> None:
        meta_path = self.task_memory / "task-one" / "task-meta.json"
        metadata = json.loads(meta_path.read_text())
        del metadata["updated_at"]
        meta_path.write_text(json.dumps(metadata))
        self.assert_error("invalid_task_metadata", lambda: core.save_handover(self.request()))

        metadata["updated_at"] = "2026-10-13T00:00:00+09:00"
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        metadata["worktree_path"] = str(outside)
        meta_path.write_text(json.dumps(metadata))
        self.assert_error("context_mismatch", lambda: core.save_handover(self.request()))

    def test_legacy_metadata_is_read_only_across_resolve_init_save_and_load(self) -> None:
        meta_path = self.task_memory / "task-one" / "task-meta.json"
        canonical = json.loads(meta_path.read_text())
        legacy_values = {
            "project": "/legacy/project-that-must-not-drive-context",
            "run_id": "session-new",
            "title": "Legacy display title",
            "workspace_root": "/legacy/worktree-that-must-not-drive-context",
        }
        for key, value in legacy_values.items():
            with self.subTest(key=key):
                meta_path.write_text(json.dumps({**canonical, key: value}), encoding="utf-8")
                task, metadata = core.resolve_task(
                    self.worktree, "session-1", "thread-1", runtime="codex",
                    expected_project=self.worktree, expected_worktree=self.worktree,
                    explicit_memory_base=self.task_memory,
                )
                self.assertEqual(task.name, "task-one")
                self.assertEqual(metadata[key], value)
                self.assertEqual(metadata["project_path"], str(self.worktree))
                self.assertEqual(metadata["worktree_path"], str(self.worktree))

        content = (json.dumps({**canonical, **legacy_values}, ensure_ascii=False, indent=2) + "\n").encode()
        meta_path.write_bytes(content)
        meta_path.chmod(0o640)
        fixed_mtime = 1_700_000_000_123_456_789
        os.utime(meta_path, ns=(fixed_mtime, fixed_mtime))
        before = meta_path.stat()

        task, metadata = core.resolve_task(
            self.worktree, "session-1", "thread-1", runtime="codex",
            expected_project=self.worktree, expected_worktree=self.worktree,
            explicit_memory_base=self.task_memory,
        )
        self.assertEqual(task.name, "task-one")
        self.assertEqual(metadata["session_id"], "session-1")
        saved = core.save_handover(self.request())
        loaded = core.load_handover(self.request(short_state=None))
        self.assertEqual(saved["canonical"]["status"], "saved")
        self.assertEqual(loaded["status"], "loaded")

        runtime_home = self.task_memory.parents[1]
        init_request = {
            "runtime": "codex", "cwd": str(self.worktree),
            "project_path": str(self.worktree), "worktree_path": str(self.worktree),
            "task_memory_root": str(self.task_memory), "task_id": "task-new",
            "task_title": "New task", "session_id": "session-new",
            "thread_id": "thread-new", "code_change": True,
        }
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(runtime_home)}, clear=False):
            created = core.init_task(init_request)
        created_metadata = json.loads(Path(created["path"]).read_text())
        self.assertTrue(core.LEGACY_READONLY_META.isdisjoint(created_metadata))

        after = meta_path.stat()
        self.assertEqual(meta_path.read_bytes(), content)
        self.assertEqual(stat.S_IMODE(after.st_mode), stat.S_IMODE(before.st_mode))
        self.assertEqual(after.st_mtime_ns, fixed_mtime)

    def test_legacy_metadata_values_are_strictly_bounded(self) -> None:
        meta_path = self.task_memory / "task-one" / "task-meta.json"
        canonical = json.loads(meta_path.read_text())
        boundary = "é" * (core.LEGACY_META_MAX_BYTES // 2)
        meta_path.write_text(json.dumps({
            **canonical, **{key: boundary for key in core.LEGACY_READONLY_META},
        }))
        task, _ = core.resolve_task(
            self.worktree, "session-1", "thread-1", runtime="codex",
            expected_project=self.worktree, expected_worktree=self.worktree,
            explicit_memory_base=self.task_memory,
        )
        self.assertEqual(task.name, "task-one")

        invalid_values = (None, True, 1, "", " \t\n", "bad\x00value", boundary + "é", "\ud800")
        for key in core.LEGACY_READONLY_META:
            for invalid in invalid_values:
                with self.subTest(key=key, invalid=repr(invalid)):
                    meta_path.write_text(json.dumps({**canonical, key: invalid}))
                    self.assert_error(
                        "invalid_task_metadata",
                        lambda: core.resolve_task(
                            self.worktree, "session-1", "thread-1", runtime="codex",
                            expected_project=self.worktree, expected_worktree=self.worktree,
                            explicit_memory_base=self.task_memory,
                        ),
                    )

        meta_path.write_text(json.dumps({**canonical, "unknown_legacy_key": "value"}))
        self.assert_error(
            "invalid_task_metadata",
            lambda: core.resolve_task(
                self.worktree, "session-1", "thread-1", runtime="codex",
                expected_project=self.worktree, expected_worktree=self.worktree,
                explicit_memory_base=self.task_memory,
            ),
        )

    def test_schema_versions_reject_bool_and_float_values(self) -> None:
        meta_path = self.task_memory / "task-one" / "task-meta.json"
        metadata = json.loads(meta_path.read_text())
        for version in (True, 1.0):
            changed = dict(metadata)
            changed["schema_version"] = version
            meta_path.write_text(json.dumps(changed))
            self.assert_error("invalid_task_metadata", lambda: core.save_handover(self.request()))
        meta_path.write_text(json.dumps(metadata))

        for version in (True, 1.0):
            state = self.state()
            state["schema_version"] = version
            self.assert_error(
                "invalid_short_state", lambda state=state: core.save_handover(self.request(short_state=state))
            )

        generated = core._marker("canonical", {}, "body")
        first, body = generated.split("\n", 1)
        encoded = first[len(core.MARKER_PREFIX):-len(core.MARKER_SUFFIX)]
        record = json.loads(base64.urlsafe_b64decode(encoded))
        for version in (True, 1.0):
            changed = dict(record)
            changed["schema_version"] = version
            marker = base64.urlsafe_b64encode(core._json(changed).encode()).decode()
            content = f"{core.MARKER_PREFIX}{marker}{core.MARKER_SUFFIX}\n{body}"
            self.assert_error(
                "unknown_generated_format",
                lambda content=content: core._parse_generated_text(content, "canonical"),
            )

    def test_symlinked_memory_root_escape_is_rejected(self) -> None:
        outside = Path(self.temp_dir.name) / "outside-memory"
        outside.mkdir()
        local_memory = self.task_memory
        for child in list(local_memory.iterdir()):
            for item in child.iterdir():
                item.unlink()
            child.rmdir()
        local_memory.rmdir()
        try:
            local_memory.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        self.assert_error("memory_root_escape", lambda: core.save_handover(self.request()))

    def test_trusted_memory_root_with_symlinked_ancestor_is_canonicalized(self) -> None:
        real_home = Path(self.temp_dir.name) / "runtime-home-real"
        alias_home = Path(self.temp_dir.name) / "runtime-home-alias"
        real_memory = real_home / ".local" / "memory"
        real_memory.mkdir(parents=True)
        try:
            alias_home.symlink_to(real_home, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        local_memory = self.task_memory
        self.task_memory = real_memory
        try:
            self.add_task("task-real-root", session_id="session-1", thread_id="thread-1")
            self.task_memory = alias_home / ".local" / "memory"
            result = core.save_handover(self.request())
        finally:
            self.task_memory = local_memory
        self.assertEqual(result["canonical"]["status"], "saved")

    def test_default_memory_roots_deduplicate_alias_and_physical_path(self) -> None:
        runtime_home = self.task_memory.parents[1]
        alias_home = Path(self.temp_dir.name) / "runtime-home-alias"
        try:
            alias_home.symlink_to(runtime_home, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        environment = {
            "CODEX_HOME": str(runtime_home),
            "SESSION_HANDOVER_TASK_MEMORY_ROOT": str(alias_home / ".local" / "memory"),
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            result = core.save_handover(self.request(task_memory_root=None))
        self.assertEqual(result["canonical"]["status"], "saved")

    def test_concurrent_sessions_keep_both_canonicals_and_foreign_pointer(self) -> None:
        self.add_task("task-two", session_id="session-2", thread_id="thread-2")
        results: dict[str, object] = {}

        def save(name: str, session: str, thread: str) -> None:
            results[name] = core.save_handover(self.request(session_id=session, thread_id=thread))

        first = threading.Thread(target=save, args=("one", "session-1", "thread-1"))
        second = threading.Thread(target=save, args=("two", "session-2", "thread-2"))
        first.start()
        second.start()
        first.join()
        second.join()

        handovers = self.worktree / ".local" / "handovers"
        self.assertTrue((handovers / "session-1.md").is_file())
        self.assertTrue((handovers / "session-2.md").is_file())
        pointer_statuses = {results["one"]["pointer"]["status"], results["two"]["pointer"]["status"]}
        self.assertEqual(pointer_statuses, {"saved", "conflict"})

    def test_dirty_canonical_and_legacy_pointer_are_preserved(self) -> None:
        saved = core.save_handover(self.request())
        canonical = Path(saved["canonical"]["path"])
        canonical.write_text(canonical.read_text() + "user edit\n")
        dirty = canonical.read_bytes()
        result = core.save_handover(self.request())
        self.assertEqual(result["canonical"]["reason"], "dirty_generated_file")
        self.assertEqual(canonical.read_bytes(), dirty)

        canonical.unlink()
        pointer = self.worktree / ".local" / "HANDOVER.md"
        pointer.write_text("# legacy full handover\n")
        legacy = pointer.read_bytes()
        result = core.save_handover(self.request())
        self.assertEqual(result["canonical"]["status"], "saved")
        self.assertEqual(result["pointer"]["reason"], "unknown_generated_format")
        self.assertEqual(pointer.read_bytes(), legacy)

    def test_compare_and_swap_conflict_preserves_generated_file(self) -> None:
        saved = core.save_handover(self.request())
        canonical = Path(saved["canonical"]["path"])
        before = canonical.read_bytes()
        result = core.save_handover(self.request(expected_canonical_hash="0" * 64))
        self.assertEqual(result["canonical"]["reason"], "cas_mismatch")
        self.assertEqual(canonical.read_bytes(), before)

    def test_oversized_state_and_artifact_preserve_existing_files(self) -> None:
        saved = core.save_handover(self.request())
        canonical = Path(saved["canonical"]["path"])
        pointer = Path(saved["pointer"]["path"])
        before_canonical = canonical.read_bytes()
        before_pointer = pointer.read_bytes()
        oversized = self.state()
        oversized["objective"] = "x" * (core.MAX_JSON_BYTES + 1)
        request = self.request(
            short_state=oversized,
            expected_canonical_hash=saved["canonical"]["hash"],
            expected_pointer_hash=saved["pointer"]["hash"],
        )
        self.assert_error("short_state_too_large", lambda: core.save_handover(request))
        with mock.patch.object(core, "MAX_STATE_BYTES", core.MAX_JSON_BYTES * 2):
            self.assert_error("artifact_too_large", lambda: core.save_handover(request))
        self.assertEqual(canonical.read_bytes(), before_canonical)
        self.assertEqual(pointer.read_bytes(), before_pointer)

    def test_atomic_update_failure_preserves_files_and_removes_temp(self) -> None:
        saved = core.save_handover(self.request())
        canonical = Path(saved["canonical"]["path"])
        pointer = Path(saved["pointer"]["path"])
        before_canonical = canonical.read_bytes()
        before_pointer = pointer.read_bytes()
        updated = self.state()
        updated["objective"] = "objective after an interrupted atomic update"
        request = self.request(
            short_state=updated,
            expected_canonical_hash=saved["canonical"]["hash"],
            expected_pointer_hash=saved["pointer"]["hash"],
        )
        with mock.patch.object(core.os, "rename", side_effect=OSError("synthetic rename failure")):
            with self.assertRaises(OSError):
                core.save_handover(request)
        self.assertEqual(canonical.read_bytes(), before_canonical)
        self.assertEqual(pointer.read_bytes(), before_pointer)
        self.assertEqual(list(canonical.parent.glob(f".{canonical.name}.*")), [])

    def test_expected_hash_never_recreates_missing_canonical_or_pointer(self) -> None:
        saved = core.save_handover(self.request())
        canonical = Path(saved["canonical"]["path"])
        pointer = Path(saved["pointer"]["path"])
        canonical.unlink()
        result = core.save_handover(self.request(
            expected_canonical_hash=saved["canonical"]["hash"],
        ))
        self.assertEqual(result["canonical"]["reason"], "missing_expected_target")
        self.assertFalse(canonical.exists())

        recreated = core.save_handover(self.request())
        pointer_hash = recreated["pointer"]["hash"]
        pointer.unlink()
        result = core.save_handover(self.request(expected_pointer_hash=pointer_hash))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["pointer"]["reason"], "missing_expected_target")
        self.assertFalse(pointer.exists())

    def test_update_requires_previous_artifact_hash(self) -> None:
        saved = core.save_handover(self.request())
        updated = self.state()
        updated["objective"] = "new objective"
        result = core.save_handover(self.request(short_state=updated))
        self.assertEqual(result["canonical"]["reason"], "missing_expected_hash")
        applied = core.save_handover(self.request(
            short_state=updated, expected_canonical_hash=saved["canonical"]["hash"],
        ))
        self.assertEqual(applied["canonical"]["status"], "saved")

    def test_full_record_tamper_is_rejected_and_cas_uses_artifact_hash(self) -> None:
        saved = core.save_handover(self.request())
        canonical = Path(saved["canonical"]["path"])
        first, body = canonical.read_text().split("\n", 1)
        encoded = first[len(core.MARKER_PREFIX):-len(core.MARKER_SUFFIX)]
        record = json.loads(base64.urlsafe_b64decode(encoded))
        self.assertEqual(saved["canonical"]["hash"], record["artifact_sha256"])
        record["state"]["objective"] = "tampered marker state"
        changed = base64.urlsafe_b64encode(core._json(record).encode()).decode()
        canonical.write_text(f"{core.MARKER_PREFIX}{changed}{core.MARKER_SUFFIX}\n{body}")
        before = canonical.read_bytes()
        result = core.save_handover(self.request(expected_canonical_hash=saved["canonical"]["hash"]))
        self.assertEqual(result["canonical"]["reason"], "dirty_generated_file")
        self.assertEqual(canonical.read_bytes(), before)

    def test_cross_runtime_cannot_load_or_overwrite_same_identity(self) -> None:
        core.save_handover(self.request(runtime="codex"))
        self.assert_error(
            "owner_mismatch",
            lambda: core.load_handover(self.request(runtime="claude", short_state=None)),
        )
        result = core.save_handover(self.request(runtime="claude"))
        self.assertEqual(result["canonical"]["reason"], "owner_mismatch")

    def test_permissions_are_private(self) -> None:
        saved = core.save_handover(self.request())
        canonical = Path(saved["canonical"]["path"])
        pointer = Path(saved["pointer"]["path"])
        lock_dir = self.worktree / ".local" / "runtime" / "locks"
        lock = lock_dir / "session-handover.lock"
        self.assertEqual(stat.S_IMODE(canonical.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(pointer.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(canonical.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(lock_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

    def test_nested_memory_override_preserves_existing_parent_modes(self) -> None:
        parent = self.worktree / "existing-parent"
        cache = parent / "cache"
        cache.mkdir(parents=True)
        parent.chmod(0o755)
        cache.chmod(0o750)
        local_root = cache / ".local"
        result = core.save_handover(self.request(memory_dir=str(local_root)))
        self.assertEqual(result["canonical"]["status"], "saved")
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(local_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((local_root / "handovers").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((local_root / "runtime" / "locks").stat().st_mode), 0o700)

    def test_missing_or_changed_fingerprints_are_not_treated_as_pass(self) -> None:
        state = self.state()
        state["required_gates"][0]["status"] = "passed"
        core.save_handover(self.request(short_state=state))
        unknown = core.load_handover(self.request(short_state=None))
        self.assertEqual(unknown["evidence_validity"][0]["status"], "stale_or_unknown")
        self.assertIn("diff:unknown", unknown["evidence_validity"][0]["reasons"])
        self.assertEqual(unknown["effective_required_gates"][0]["status"], "needs_revalidation")
        self.assertIn("independent-review: needs_revalidation", unknown["context"])

        changed = core.load_handover(self.request(short_state=None, current_fingerprints={
            "diff": "diff-b",
            "dependencies": "deps-a",
            "execution": "exec-a",
            "plan": self.plan_hash,
            "failure": "none-a",
        }))
        self.assertIn("diff:changed", changed["evidence_validity"][0]["reasons"])
        self.assertIn("Use effective gate status", changed["context"])

        current = core.load_handover(self.request(short_state=None, current_fingerprints={
            "diff": "diff-a", "dependencies": "deps-a", "execution": "exec-a",
            "plan": self.plan_hash, "failure": "none-a",
        }))
        self.assertEqual(current["effective_required_gates"][0]["status"], "passed")

    def test_gate_only_accepts_its_named_current_evidence(self) -> None:
        state = self.state()
        state["required_gates"][0]["status"] = "passed"
        state["required_gates"][0]["evidence_refs"] = ["missing-evidence"]
        core.save_handover(self.request(short_state=state))
        loaded = core.load_handover(self.request(short_state=None, current_fingerprints={
            "diff": "diff-a", "dependencies": "deps-a", "execution": "exec-a",
            "plan": self.plan_hash, "failure": "none-a",
        }))
        gate = loaded["effective_required_gates"][0]
        self.assertEqual(gate["status"], "needs_revalidation")
        self.assertIn("missing-evidence", gate["reasons"][0])

    def test_empty_fingerprints_are_unknown_and_cannot_pass_gate(self) -> None:
        state = self.state()
        state["evidence"][0]["fingerprints"]["diff"] = ""
        self.assert_error(
            "invalid_short_state",
            lambda: core.save_handover(self.request(short_state=state)),
        )
        state = self.state()
        state["required_gates"][0]["status"] = "passed"
        core.save_handover(self.request(short_state=state))
        loaded = core.load_handover(self.request(short_state=None, current_fingerprints={
            "diff": "", "dependencies": "deps-a", "execution": "exec-a",
            "plan": self.plan_hash, "failure": "none-a",
        }))
        self.assertIn("diff:unknown", loaded["evidence_validity"][0]["reasons"])
        self.assertEqual(loaded["effective_required_gates"][0]["status"], "needs_revalidation")

    def test_plan_hash_uses_exact_anchor_section_and_load_marks_change_stale(self) -> None:
        expected_section = (
            '<section id="improvement-plan" data-plan-version="v10">\n'
            '<article><section id="nested">nested</section></article>\n</section>'
        )
        self.assertEqual(self.plan_hash, core._sha(expected_section))
        core.save_handover(self.request())
        self.plan.write_text(self.plan.read_text().replace("nested", "changed"), encoding="utf-8")
        loaded = core.load_handover(self.request(short_state=None))
        self.assertIn("Plan: stale (plan_hash_changed)", loaded["context"])
        self.assertIn("plan:stale", loaded["evidence_validity"][0]["reasons"])

    def test_plan_version_and_allowed_root_are_checked_on_save_and_load(self) -> None:
        wrong = self.state()
        wrong["plan"]["version"] = "v7"
        self.assert_error(
            "plan_version_mismatch",
            lambda: core.save_handover(self.request(short_state=wrong)),
        )
        outside = Path(self.temp_dir.name).resolve() / "external-plan"
        outside.mkdir()
        plan = outside / "dashboard.html"
        section = '<section id="improvement-plan" data-plan-version="v10">external</section>'
        plan.write_text(section)
        external = self.state()
        external["plan"]["path"] = str(plan)
        external["plan"]["sha256"] = core._sha(section)
        self.assert_error(
            "plan_path_not_allowed",
            lambda: core.save_handover(self.request(short_state=external)),
        )
        core.save_handover(self.request(short_state=external, plan_root=str(outside)))
        loaded = core.load_handover(self.request(short_state=None))
        self.assertIn("Plan: unknown (plan_path_not_allowed)", loaded["context"])

    def test_duplicate_anchor_on_any_element_is_rejected(self) -> None:
        self.plan.write_text(
            '<div id="improvement-plan"></div>\n<section id="improvement-plan">x</section>\n',
            encoding="utf-8",
        )
        self.assert_error(
            "plan_anchor_not_unique",
            lambda: core.plan_section_hash(self.plan, "#improvement-plan"),
        )
        self.plan.write_text(
            '<section id="improvement-plan"><section id="improvement-plan">x</section></section>',
            encoding="utf-8",
        )
        self.assert_error(
            "plan_anchor_not_unique",
            lambda: core.plan_section_hash(self.plan, "#improvement-plan"),
        )

    def test_schema_rejects_transcript_and_nested_extra_keys(self) -> None:
        cases = []
        state = self.state()
        state["transcript"] = "must not persist"
        cases.append(state)
        state = self.state()
        state["required_gates"][0]["raw"] = "must not persist"
        cases.append(state)
        state = self.state()
        state["evidence"][0]["transcript"] = "must not persist"
        cases.append(state)
        for state in cases:
            with self.subTest(keys=state.keys()):
                self.assert_error(
                    "invalid_short_state",
                    lambda value=state: core.save_handover(self.request(short_state=value)),
                )

    def test_gate_and_evidence_names_are_unique(self) -> None:
        state = self.state()
        state["required_gates"].append(dict(state["required_gates"][0]))
        self.assert_error(
            "invalid_short_state",
            lambda: core.save_handover(self.request(short_state=state)),
        )
        state = self.state()
        state["evidence"].append(json.loads(json.dumps(state["evidence"][0])))
        self.assert_error(
            "invalid_short_state",
            lambda: core.save_handover(self.request(short_state=state)),
        )

    def test_manual_seed_hook_update_and_restore_workflow(self) -> None:
        first = self.state()
        saved = core.save_handover(self.request(short_state=first))
        updated = self.state()
        updated["objective"] = "Restore the updated synthetic session."
        updated["next_action"] = "Resume from the updated state."
        payload = {
            "cwd": str(self.worktree), "session_id": "session-1", "thread_id": "thread-1",
            "short_state": updated, "expected_canonical_hash": saved["canonical"]["hash"],
        }
        self.assertEqual(self.run_hook("codex", "PreCompact", payload), ("", ""))
        stdout, stderr = self.run_hook("codex", "SessionStart", {
            key: value for key, value in payload.items() if key != "short_state"
        })
        self.assertEqual(stderr, "")
        self.assertIn("Restore the updated synthetic session", json.loads(stdout)["hookSpecificOutput"]["additionalContext"])

    def test_approval_state_is_compatible_but_metadata_cannot_produce_state(self) -> None:
        meta_path = self.task_memory / "task-one" / "task-meta.json"
        metadata = json.loads(meta_path.read_text())
        metadata["approval_state"] = "approved"
        meta_path.write_text(json.dumps(metadata))
        stdout, stderr = self.run_hook("codex", "PreCompact", {
            "cwd": str(self.worktree), "session_id": "session-1", "thread_id": "thread-1",
        })
        self.assertEqual(stdout, "")
        self.assertIn("missing_short_state", stderr)
        metadata["short_state"] = self.state()
        meta_path.write_text(json.dumps(metadata))
        self.assert_error("invalid_task_metadata", lambda: core.save_handover(self.request(short_state=None)))

    def test_symlinked_generated_paths_are_never_followed(self) -> None:
        local = self.worktree / ".local"
        local.mkdir()
        outside = Path(self.temp_dir.name).resolve() / "outside"
        outside.mkdir()
        handovers = local / "handovers"
        try:
            handovers.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        self.assert_error("path_symlink", lambda: core.save_handover(self.request()))
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_lock_directory_is_never_followed(self) -> None:
        local = self.worktree / ".local"
        runtime = local / "runtime"
        runtime.mkdir(parents=True)
        outside = Path(self.temp_dir.name).resolve() / "outside-lock"
        outside.mkdir()
        try:
            (runtime / "locks").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        self.assert_error("path_symlink", lambda: core.save_handover(self.request()))
        self.assertEqual(list(outside.iterdir()), [])

    def test_canonical_and_pointer_symlinks_are_preserved(self) -> None:
        local = self.worktree / ".local"
        handovers = local / "handovers"
        handovers.mkdir(parents=True)
        outside = Path(self.temp_dir.name).resolve() / "outside-file"
        outside.write_text("outside")
        canonical = handovers / "session-1.md"
        try:
            canonical.symlink_to(outside)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        result = core.save_handover(self.request())
        self.assertEqual(result["canonical"]["reason"], "path_symlink")
        self.assertEqual(outside.read_text(), "outside")

    def test_pointer_symlink_is_preserved_after_canonical_save(self) -> None:
        local = self.worktree / ".local"
        local.mkdir()
        outside = Path(self.temp_dir.name).resolve() / "outside-pointer"
        outside.write_text("outside")
        try:
            (local / "HANDOVER.md").symlink_to(outside)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        result = core.save_handover(self.request())
        self.assertEqual(result["canonical"]["status"], "saved")
        self.assertEqual(result["pointer"]["reason"], "path_symlink")
        self.assertEqual(outside.read_text(), "outside")

    def test_cli_returns_nonzero_when_pointer_conflicts(self) -> None:
        local = self.worktree / ".local"
        local.mkdir()
        (local / "HANDOVER.md").write_text("legacy pointer")
        state_file = Path(self.temp_dir.name).resolve() / "state.json"
        state_file.write_text(json.dumps(self.state()))
        result = subprocess.run([
            "python3", str(CORE_PATH), "save", "--runtime", "codex",
            "--cwd", str(self.worktree), "--session-id", "session-1",
            "--thread-id", "thread-1", "--task-memory-root", str(self.task_memory),
            "--project-path", str(self.worktree), "--worktree-path", str(self.worktree),
            "--state-file", str(state_file),
        ], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["status"], "partial")

    def test_local_root_symlink_is_rejected(self) -> None:
        outside = Path(self.temp_dir.name).resolve() / "outside-local"
        outside.mkdir()
        try:
            (self.worktree / ".local").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        self.assert_error("local_root_symlink", lambda: core.save_handover(self.request()))
        self.assertEqual(list(outside.iterdir()), [])

    def test_relative_local_root_escape_and_hook_payload_override_are_rejected(self) -> None:
        outside = self.worktree.parent / "escape-output"
        self.assert_error(
            "local_root_escape",
            lambda: core.save_handover(self.request(memory_dir="../escape-output")),
        )
        self.assertFalse(outside.exists())
        payload = {
            "cwd": str(self.worktree), "session_id": "session-1", "thread_id": "thread-1",
            "memory_dir": "../escape-output", "task_memory_root": str(outside),
            "short_state": self.state(),
        }
        self.assertEqual(self.run_hook("codex", "PreCompact", payload), ("", ""))
        self.assertFalse(outside.exists())
        self.assertTrue((self.worktree / ".local" / "handovers" / "session-1.md").is_file())

    def test_non_regular_canonical_pointer_and_lock_are_rejected_without_reading(self) -> None:
        local = self.worktree / ".local"
        handovers = local / "handovers"
        handovers.mkdir(parents=True)
        canonical = handovers / "session-1.md"
        try:
            os.mkfifo(canonical)
        except OSError as error:
            self.skipTest(f"FIFO unavailable: {error}")
        result = core.save_handover(self.request())
        self.assertEqual(result["canonical"]["reason"], "non_regular_file")
        canonical.unlink()

        pointer = local / "HANDOVER.md"
        pointer.mkdir()
        result = core.save_handover(self.request())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["pointer"]["reason"], "non_regular_file")
        pointer.rmdir()
        (handovers / "session-1.md").unlink()

        locks = local / "runtime" / "locks"
        lock = locks / "session-handover.lock"
        lock.unlink()
        os.mkfifo(lock)
        self.assert_error("non_regular_file", lambda: core.save_handover(self.request()))

    def test_non_regular_task_metadata_is_rejected_without_reading(self) -> None:
        meta = self.task_memory / "task-one" / "task-meta.json"
        meta.unlink()
        try:
            os.mkfifo(meta)
        except OSError as error:
            self.skipTest(f"FIFO unavailable: {error}")
        self.assert_error("non_regular_file", lambda: core.save_handover(self.request()))

    def test_hook_unexpected_exception_is_fail_open_without_traceback(self) -> None:
        original = core.save_handover
        core.save_handover = lambda request: (_ for _ in ()).throw(OSError("synthetic"))
        try:
            stdout, stderr = self.run_hook("codex", "PreCompact", {"cwd": str(self.worktree)})
        finally:
            core.save_handover = original
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "session-handover: internal_error\n")
        self.assertNotIn("Traceback", stderr)

    def test_core_hook_rejects_oversized_stdin_and_fails_open(self) -> None:
        stdin = io.StringIO('{"value":"' + "x" * 64 + '"}')
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(core, "MAX_JSON_BYTES", 32),
            mock.patch.object(core.sys, "stdin", stdin),
            mock.patch.object(core.sys, "stdout", stdout),
            mock.patch.object(core.sys, "stderr", stderr),
        ):
            result = core.main(["hook", "--runtime", "claude", "--event", "Stop"])
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "session-handover: invalid_hook_json\n")
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_native_adapter_import_failure_is_fail_open(self) -> None:
        invalid_core = Path(self.temp_dir.name).resolve() / "invalid-core.py"
        invalid_core.write_text("this is not valid python !!!")
        environment = dict(os.environ)
        environment["SESSION_HANDOVER_CORE"] = str(invalid_core)
        result = subprocess.run(
            ["python3", str(ADAPTER)], input="{}", text=True,
            capture_output=True, check=False, env=environment,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("internal_error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_passed_gate_without_evidence_requires_revalidation(self) -> None:
        state = self.state()
        state["required_gates"][0]["status"] = "passed"
        state["evidence"] = []
        core.save_handover(self.request(short_state=state))
        loaded = core.load_handover(self.request(short_state=None))
        self.assertEqual(loaded["effective_required_gates"][0]["status"], "needs_revalidation")

    def test_first_hook_save_requires_explicit_state_but_existing_resume_does_not(self) -> None:
        stdout, stderr = self.run_hook("claude", "PreCompact", {
            "cwd": str(self.worktree), "session_id": "session-1", "thread_id": "thread-1",
        })
        self.assertEqual(stdout, "")
        self.assertIn("missing_short_state", stderr)
        core.save_handover(self.request(runtime="claude"))
        stdout, stderr = self.run_hook("claude", "PreCompact", {
            "cwd": str(self.worktree), "session_id": "session-1", "thread_id": "thread-1",
        })
        self.assertEqual((stdout, stderr), ("", ""))

    def test_native_adapter_outputs_context_only_for_session_start(self) -> None:
        core.save_handover(self.request())
        payload = {
            "hook_event_name": "SessionStart", "cwd": str(self.worktree),
            "session_id": "session-1", "thread_id": "thread-1",
        }
        environment = dict(os.environ)
        environment["SESSION_HANDOVER_TASK_MEMORY_ROOT"] = str(self.task_memory)
        result = subprocess.run(
            ["python3", str(ADAPTER)], input=json.dumps(payload), text=True,
            capture_output=True, check=False, env=environment,
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("Restore the exact synthetic session", output["hookSpecificOutput"]["additionalContext"])

        payload["hook_event_name"] = "Stop"
        result = subprocess.run(
            ["python3", str(ADAPTER)], input=json.dumps(payload), text=True,
            capture_output=True, check=False, env=environment,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
