import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SOURCE = Path(os.environ.get("HARNESS_BENCHMARK_SOURCE", Path.home() / ".codex/scripts/harness_benchmark.py"))
SPEC = importlib.util.spec_from_file_location("harness_benchmark", SOURCE)
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


class HarnessBenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="harness-benchmark-test-", dir="/private/tmp"))
        self.bundle = Path(tempfile.mkdtemp(prefix="harness-comparison-test-", dir="/private/tmp"))
        self.capability = self.bundle / "capabilities.json"
        self.codex_native = self.bundle / "codex-native"
        self.codex_native.write_bytes(b"synthetic reviewed codex native\n"); self.codex_native.chmod(0o755)
        capability_source = Path.home() / ".codex/.local/dashboards/01a12e4c-8b93-7273-b714-2ef118579c49/evidence/runtime-capabilities.md"
        source_hash = hashlib.sha256(capability_source.read_bytes()).hexdigest()
        BENCH.CAPABILITY_POLICIES[source_hash] = {
            runtime: {name: "unknown" for name in BENCH.CAPABILITIES} for runtime in ("codex", "claude")}
        versions = {"codex": "codex-cli 0.153.4", "claude": "2.1.251 (Claude Code)"}
        evidence = {runtime: {name: {"runtime_version": versions[runtime], "event": name,
                    "trigger_method": "official-cli", "state": "unknown", "source_hash": source_hash}
                    for name in BENCH.CAPABILITIES} for runtime in ("codex", "claude")}
        evidence["source_path"] = str(capability_source)
        self.private_write(self.capability, evidence)
        bundles = []
        for candidate in ("I03", "I04", "I05"):
            for runtime in ("codex", "claude"):
                target = "AGENTS.md" if runtime == "codex" else "CLAUDE.md"
                for variant in ("baseline", "candidate"):
                    name = f"{candidate}-{runtime}-{variant}.txt"
                    content = f"{candidate}:{runtime}:{variant}\n".encode()
                    (self.bundle / name).write_bytes(content); (self.bundle / name).chmod(0o600)
                    bundles.append({"candidate": candidate, "runtime": runtime, "variant": variant,
                                    "baseline_commit": BENCH.BASELINES[runtime], "source_dirty": False,
                                    "files": [{"class": "workspace_instruction", "source": name, "target": target,
                                               "sha256": hashlib.sha256(content).hexdigest(), "factor": candidate}]})
        self.bundle_manifest = self.bundle / "manifest.json"
        self.private_write(self.bundle_manifest, {"bundles": bundles})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True); shutil.rmtree(self.bundle, ignore_errors=True)

    @staticmethod
    def private_write(path, value):
        path.write_text(json.dumps(value)); path.chmod(0o600)

    def prepare(self, include_i05=False):
        args = argparse.Namespace(root=str(self.root), seed=17, include_i05=include_i05,
                                  capability_evidence=str(self.capability), comparison_bundle=str(self.bundle_manifest),
                                  source_change_reason="unit-test", codex_bin=sys.executable, claude_bin=sys.executable,
                                  codex_native_bin=str(self.codex_native), tsc_bin=None,
                                  host_node_bin="/opt/homebrew/Cellar/node/25.8.2/bin/node",
                                  host_tsc_js="/Users/yoshiki/ghq/github.com/THA-inc/arupaka-test-slack/node_modules/.pnpm/typescript@5.9.3/node_modules/typescript/lib/_tsc.js")
        with contextlib.redirect_stdout(io.StringIO()): BENCH.prepare(args)
        return BENCH.read_json(self.root / "results/manifest.json")

    def test_runtime_binary_hashes_executable_and_node_without_read_bytes(self):
        launcher = self.bundle / "node-launcher"; launcher.write_bytes(b"#!/usr/bin/env node\n"); launcher.chmod(0o755)
        node = self.bundle / "node"; node.write_bytes(b"synthetic node\n"); node.chmod(0o755)
        with mock.patch.object(BENCH.shutil, "which", return_value=str(node)), \
             mock.patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read forbidden")):
            row = BENCH.runtime_binary(str(launcher), "fixture runtime")
        self.assertEqual(hashlib.sha256(b"#!/usr/bin/env node\n").hexdigest(), row["sha256"])
        self.assertEqual(hashlib.sha256(b"synthetic node\n").hexdigest(), row["interpreter"]["sha256"])

    def make_codex_arg0(self, manifest, suffix="A1b2C3", target=None):
        helper = self.root / "runtime/codex/home/tmp/arg0" / f"codex-arg0{suffix}"
        helper.mkdir(parents=True, mode=0o700)
        for parent in (helper.parent.parent, helper.parent, helper):
            parent.chmod(0o700)
        lock = helper / ".lock"; lock.touch(mode=0o600); lock.chmod(0o600)
        native = Path(target or manifest["codex_arg0_native"]["path"])
        for name in BENCH.CODEX_ARG0_LINKS:
            (helper / name).symlink_to(native)
        return helper

    def test_codex_arg0_cleanup_accepts_only_exact_idle_shape(self):
        manifest = self.prepare(); helper = self.make_codex_arg0(manifest)
        self.assertFalse(BENCH.private_tree_ok((self.root / "runtime/codex",), 4096))
        self.assertEqual(1, BENCH.cleanup_codex_arg0_helpers(self.root, manifest))
        self.assertFalse(helper.exists()); self.assertFalse((self.root / "runtime/codex/home/tmp").exists())
        self.assertTrue(BENCH.private_tree_ok((self.root / "runtime/codex",), 4096))

    def test_file_fd_root_move_refuses_before_fchmod(self):
        base = self.root / "runtime"
        BENCH.mkdir(base)
        before = BENCH.runtime_private_snapshot(base)
        target = base / "fresh.log"
        target.write_bytes(b"fresh\n"); target.chmod(0o644)
        old = base.with_name(base.name + "-old")
        moved = {"done": False}
        original_visible = BENCH._runtime_visible_matches

        def race_visible(path, expected, descriptor, label):
            if not moved["done"] and label == "file":
                moved["done"] = True
                base.rename(old)
                BENCH.mkdir(base)
                os.rename(old / target.name, base / target.name)
            return original_visible(path, expected, descriptor, label)

        with mock.patch.object(BENCH, "_runtime_visible_matches", side_effect=race_visible):
            with self.assertRaisesRegex(SystemExit, "base pathが検証中に変化"):
                BENCH.tighten_fresh_runtime_files(base, before, True)
        self.assertTrue(moved["done"])
        self.assertEqual(0o644, stat.S_IMODE((base / target.name).stat().st_mode))
        self.assertFalse((old / target.name).exists())

    def test_codex_cleanup_runs_fresh_file_tightening_after_helper_removal(self):
        manifest = self.prepare()
        runtime = self.root / "runtime/codex"
        before = BENCH.runtime_private_snapshot(runtime)
        helper = self.make_codex_arg0(manifest)
        fresh = runtime / "generated.log"
        fresh.write_text("generated\n"); fresh.chmod(0o644)
        observed = []

        def after_cleanup():
            observed.append(helper.exists())
            observed.append(BENCH.tighten_fresh_runtime_files(runtime, before, True))

        self.assertEqual(1, BENCH.cleanup_codex_arg0_helpers(manifest=manifest, root=self.root,
                                                             after_cleanup=after_cleanup))
        self.assertEqual([False, {"status": "passed", "fresh_dirs": 0, "fresh_files": 1,
                                  "fresh_bytes": len(b"generated\n"), "files_tightened": 1}], observed)
        self.assertEqual(0o600, stat.S_IMODE(fresh.stat().st_mode))
        self.assertTrue(BENCH.private_tree_ok((runtime,), 4096))

    def test_fresh_file_tightening_checks_base_fd_identity(self):
        base = self.root / "runtime/codex"
        base.mkdir(parents=True, mode=0o700)
        base.chmod(0o700)
        nested = base / "cache"
        nested.mkdir(mode=0o700)
        nested.chmod(0o700)
        before = BENCH.runtime_private_snapshot(base)
        fresh = nested / "fresh.log"
        fresh.write_text("fresh\n"); fresh.chmod(0o644)
        after = BENCH.runtime_private_snapshot(base, expected=before, allow_public_regular=True)
        tampered = dict(after)
        observed = tampered[base]
        tampered[base] = (observed[0], observed[1] + 1, *observed[2:])
        with self.assertRaises(SystemExit):
            BENCH._tighten_runtime_file(fresh, tampered[fresh], tampered[nested], tampered, base)
        self.assertEqual(0o644, stat.S_IMODE(fresh.stat().st_mode))

    def test_codex_arg0_cleanup_rejects_unknown_target_ancestor_and_active_lock_without_mutation(self):
        manifest = self.prepare()
        cases = ("unknown", "target", "ancestor", "active", "second_invalid")
        for index, kind in enumerate(cases):
            with self.subTest(kind=kind):
                arg0 = self.root / "runtime/codex/home/tmp/arg0"
                if os.path.lexists(arg0):
                    if arg0.is_symlink(): arg0.unlink()
                    else: shutil.rmtree(arg0.parent)
                descriptor = None
                if kind == "ancestor":
                    outside = self.bundle / f"arg0-{index}"; outside.mkdir(mode=0o700)
                    arg0.parent.mkdir(parents=True, mode=0o700); arg0.parent.chmod(0o700)
                    arg0.symlink_to(outside, target_is_directory=True)
                    sentinel = arg0
                else:
                    wrong = self.bundle / f"wrong-{index}"
                    wrong.write_bytes(b"wrong native"); wrong.chmod(0o755)
                    helper = self.make_codex_arg0(manifest, f"A1b2{index}Z",
                                                   wrong if kind == "target" else None)
                    if kind == "unknown":
                        (helper / "unknown").write_text("x"); (helper / "unknown").chmod(0o600)
                    if kind == "active":
                        descriptor = os.open(helper / ".lock", os.O_RDWR)
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if kind == "second_invalid":
                        second = self.make_codex_arg0(manifest, "S2c3D4")
                        (second / "unknown").write_text("x"); (second / "unknown").chmod(0o600)
                    sentinel = helper
                before = sorted(path.name for path in sentinel.iterdir()) if sentinel.is_dir() else []
                try:
                    with self.assertRaisesRegex(SystemExit, "Codex arg0"):
                        BENCH.cleanup_codex_arg0_helpers(self.root, manifest)
                    self.assertTrue(os.path.lexists(sentinel))
                    if sentinel.is_dir() and not sentinel.is_symlink():
                        self.assertEqual(before, sorted(path.name for path in sentinel.iterdir()))
                    if kind == "second_invalid":
                        self.assertTrue(second.is_dir())
                finally:
                    if descriptor is not None:
                        fcntl.flock(descriptor, fcntl.LOCK_UN); os.close(descriptor)

    def test_status_cleans_helpers_recreated_by_codex_probe(self):
        manifest = self.prepare(); answers = iter([False, False, "codex-cli 0.153.4", "2.1.251 (Claude Code)"])
        isolation = {runtime: {"qualified": False} for runtime in ("codex", "claude")}
        def recreate(*_args, **_kwargs):
            self.make_codex_arg0(manifest)
            return isolation
        with mock.patch.object(BENCH, "probe", side_effect=lambda *args, **kwargs: next(answers)), \
             mock.patch.object(BENCH, "local_isolation_probe", side_effect=recreate):
            with contextlib.redirect_stdout(io.StringIO()): code = BENCH.status(argparse.Namespace(root=str(self.root)))
        self.assertEqual(3, code)
        self.assertTrue(BENCH.read_json(self.root / "results/status.json")["private_layout"])
        self.assertFalse((self.root / "runtime/codex/home/tmp/arg0").exists())

    def use_host_bundle(self):
        actual = {"handover_core": Path.home() / ".codex/scripts/session_handover.py",
                  "observations_core": Path.home() / ".claude/scripts/hook_observations.py",
                  "quiet_run": Path.home() / ".codex/scripts/quiet-run.py"}
        files = []
        for role, source in actual.items():
            target = self.bundle / role; shutil.copy2(source, target); target.chmod(0o600)
            files.append({"class": "host_fixture_helper", "source": role, "target": f"host/{role}",
                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "factor": "fixed"})
        bundles = [{"candidate": candidate, "runtime": runtime, "variant": variant,
                    "baseline_commit": BENCH.BASELINES[runtime], "source_dirty": False, "files": files}
                   for candidate in ("I03", "I04", "I05") for runtime in ("codex", "claude")
                   for variant in ("baseline", "candidate")]
        self.private_write(self.bundle_manifest, {"bundles": bundles})

    def use_mixed_host_bundle(self, class_name):
        self.use_host_bundle()
        targets = {"workspace_instruction": "AGENTS.md",
                   "runtime_settings": "overrides.json", "hook_adapter": "hooks/adapter.py"}
        source_name = f"mixed-{class_name}.txt"
        content = f"mixed {class_name}\n".encode()
        source = self.bundle / source_name
        source.write_bytes(content); source.chmod(0o600)
        value = json.loads(self.bundle_manifest.read_text())
        for row in value["bundles"]:
            row["files"].append({"class": class_name, "source": source_name,
                                  "target": targets[class_name],
                                  "sha256": hashlib.sha256(content).hexdigest(), "factor": "fixed"})
        self.private_write(self.bundle_manifest, value)

    def use_candidate_mixed_host_bundle(self, class_name):
        self.use_host_bundle()
        targets = {"workspace_instruction": "AGENTS.md",
                   "runtime_settings": "overrides.json", "hook_adapter": "hooks/adapter.py"}
        sources = {}
        for variant in ("baseline", "candidate"):
            source_name = f"candidate-mixed-{class_name}-{variant}.txt"
            content = f"candidate mixed {class_name} {variant}\n".encode()
            source = self.bundle / source_name
            source.write_bytes(content); source.chmod(0o600)
            sources[variant] = (source_name, hashlib.sha256(content).hexdigest())
        value = json.loads(self.bundle_manifest.read_text())
        for row in value["bundles"]:
            source_name, source_hash = sources[row["variant"]]
            row["files"].append({"class": class_name, "source": source_name,
                                  "target": targets[class_name], "sha256": source_hash,
                                  "factor": row["candidate"]})
        self.private_write(self.bundle_manifest, value)

    def use_partial_host_bundle(self, variant):
        self.use_host_bundle()
        value = json.loads(self.bundle_manifest.read_text())
        for row in value["bundles"]:
            if row["variant"] == variant:
                row["files"] = row["files"][:-1]
        self.private_write(self.bundle_manifest, value)

    @staticmethod
    def neutral_host_result(row):
        request_row = dict(row); request_row.setdefault("variant", "baseline")
        request = BENCH.host_helper.make_request(request_row, BENCH.fixture(row["fixture"]))
        result = {"owner": BENCH.host_helper.RESULT_OWNER, "schema": BENCH.host_helper.SCHEMA,
                  "candidate": row["candidate"], "fixture": row["fixture"], "status": "neutral",
                  "mechanism": "neutral", "payload": {"context": "", "facts": {"neutral": True},
                  "diagnostics": []}, "references": []}
        result["content_hash"] = BENCH.host_helper.digest(result)
        encoded = BENCH.host_helper.canonical(result).decode()
        return {"result": result,
                "evidence": {"helper_mechanism_observed": False, "operation_count": 0,
                             "failure_reason": None,
                             "request_hash": BENCH.host_helper.digest(request),
                             "result_hash": result["content_hash"]}, "pair_stop": False,
                "prompt_context": f'<mechanism-context schema="host-helper-result-v1">{encoded}</mechanism-context>'}

    def test_prepare_is_private_finite_and_immutable(self):
        manifest = self.prepare(True)
        self.assertEqual(8, len(list((self.root / "fixtures").iterdir())))
        self.assertEqual(290, manifest["max_runs"])
        self.assertEqual(["I03", "I04", "I05"], manifest["candidates"])
        self.assertEqual(17, manifest["schedule_seed"])
        self.assertTrue(all(row["state"] == "unknown" for row in manifest["sampling"].values()))
        self.assertTrue(all(row["evaluation_kind"] == "instruction-only"
                            for row in manifest["comparison_bundles"].values()))
        self.assertEqual(BENCH.CODEX_CONFIG,
                         (self.root / "runtime/codex/home/config.toml").read_text())
        self.assertEqual("unsupported", manifest["fixture_tools"]["typescript_cli"]["state"])
        self.assertEqual("observed", manifest["fixture_tools"]["python_cli"]["state"])
        self.assertEqual(BENCH.FIXED_ENV, manifest["environment"]["fixed"])
        self.assertNotIn(str(Path.home()), json.dumps(manifest["environment"]))
        quiet = BENCH.read_json(self.root / "fixtures/cli_quiet_retrieve/fixture.json")
        self.assertEqual((Path.home() / ".codex/scripts/quiet-run.py").read_text(), quiet["files"]["quiet-run.py"])
        for path in (self.root, *self.root.rglob("*")):
            self.assertEqual(0, stat.S_IMODE(path.stat().st_mode) & 0o077)

    def test_schedule_is_seeded_and_has_96_runs_per_candidate(self):
        first = BENCH.make_schedule(23, ["I03", "I04", "I05"])
        self.assertEqual(first, BENCH.make_schedule(23, ["I03", "I04", "I05"]))
        self.assertEqual(290, len(first))
        for candidate in ("I03", "I04", "I05"):
            rows = [row for row in first if row.get("candidate") == candidate]
            self.assertEqual((96, 96), (len(rows), len({row["run_id"] for row in rows})))

    def test_symlink_and_foreign_owner_are_rejected(self):
        target = Path(tempfile.mkdtemp(prefix="harness-target-", dir="/private/tmp"))
        link = Path("/private/tmp/harness-benchmark-link-" + next(tempfile._get_candidate_names()))
        link.symlink_to(target, target_is_directory=True)
        try:
            with self.assertRaises(SystemExit): BENCH.root_path(str(link))
            self.prepare(); result = self.root / "results/status.json"
            self.private_write(result, {"owner": "other"})
            with self.assertRaisesRegex(SystemExit, "所有"): BENCH.write_json(result, {"owner": BENCH.OWNER})
        finally:
            link.unlink(missing_ok=True); shutil.rmtree(target, ignore_errors=True)

    def test_bundle_hash_and_source_boundary_are_enforced(self):
        value = json.loads(self.bundle_manifest.read_text()); value["bundles"][0]["files"][0]["sha256"] = "0" * 64
        self.private_write(self.bundle_manifest, value)
        with self.assertRaisesRegex(SystemExit, "契約違反"): self.prepare()

    def test_bundle_file_count_is_bounded_before_staging(self):
        value = json.loads(self.bundle_manifest.read_text())
        item = value["bundles"][0]["files"][0]
        value["bundles"][0]["files"] = [dict(item) for _ in range(BENCH.LIMITS["comparison_files"] + 1)]
        self.private_write(self.bundle_manifest, value)
        with self.assertRaisesRegex(SystemExit, "file数が上限"):
            self.prepare()

    def test_child_environment_is_allowlisted_and_preserves_home(self):
        with mock.patch.dict(os.environ, {"HOME": "/kept", "PATH": "/bin", "TMPDIR": "/shared",
                                          "GITHUB_TOKEN": "hidden", "CLAUDE_CODE_USE_BEDROCK": "1",
                                          "AWS_PROFILE": "p", "VISIBLE": "yes"}, clear=True):
            env = BENCH.child_env(self.root, "codex")
            claude = BENCH.child_env(self.root, "claude")
        self.assertEqual("/kept", env["HOME"]); self.assertEqual(BENCH.FIXED_ENV["PATH"], env["PATH"])
        self.assertEqual("C", env["LC_ALL"])
        self.assertEqual(str(self.root / "runtime/codex/tmp"), env["TMPDIR"])
        self.assertEqual(str(self.root / "runtime/claude/tmp"), claude["TMPDIR"])
        work = self.root / "work/run"; BENCH.mkdir(work)
        self.assertEqual(str(work / ".tmp"), BENCH.child_env(self.root, "claude", work)["TMPDIR"])
        self.assertNotIn("GITHUB_TOKEN", env); self.assertNotIn("AWS_PROFILE", env)
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env); self.assertNotIn("VISIBLE", env)
        self.assertEqual("/kept", claude["HOME"])
        self.assertEqual(str(self.root / "runtime/claude/config"), claude["CLAUDE_CONFIG_DIR"])
        self.assertEqual(str(self.root / "runtime/claude/home"), claude["CLAUDE_HOME"])
        self.assertEqual(str(self.root / "runtime/claude/home/.local/memory"),
                         claude["SESSION_HANDOVER_TASK_MEMORY_ROOT"])
        self.assertEqual(str(self.root / "runtime/claude/home/.local"), claude["SESSION_HANDOVER_MEMORY_DIR"])
        self.assertEqual(str(self.root / "runtime/claude/home/.local/plans"), claude["SESSION_HANDOVER_PLAN_ROOT"])
        self.assertEqual(str(self.root / "runtime/claude/home/.local/hooks/state"),
                         claude["HOOK_OBSERVATIONS_STATE_DIR"])
        self.assertEqual(str(self.root / "runtime/claude/home/.local/hooks/suggestions"),
                         claude["HOOK_OBSERVATIONS_SUGGEST_DIR"])
        self.assertEqual(str(self.root / "runtime/claude/home/.local/transcripts"),
                         claude["HOOK_OBSERVATIONS_TRANSCRIPT_ROOT"])

    def test_runtime_state_rejects_claude_metadata_symlink(self):
        manifest = self.prepare()
        state = self.root / "runtime/claude/home/.local/hooks/state"
        state.rmdir(); state.symlink_to(self.root / "runtime/claude/home/.local/memory", target_is_directory=True)
        with self.assertRaisesRegex(SystemExit, "runtime state"):
            BENCH.verify_runtime_state(self.root, manifest)

    def test_private_tree_rejects_nested_public_file_and_special_entry(self):
        manifest = self.prepare(); exposed = self.root / "runtime/claude/home/exposed"
        exposed.write_text("nonsecret"); exposed.chmod(0o644)
        self.assertFalse(BENCH.private_tree_ok((self.root,), 16384))
        with self.assertRaisesRegex(SystemExit, "runtime state tree"):
            BENCH.verify_runtime_state(self.root, manifest)
        exposed.unlink(); os.mkfifo(exposed, 0o600)
        self.assertFalse(BENCH.private_tree_ok((self.root,), 16384))

    def test_status_records_only_nonsecret_boolean_and_versions(self):
        self.prepare(); answers = iter([False, False, "codex-cli 0.153.4", "2.1.251 (Claude Code)"])
        BENCH.mkdir(self.root / "runtime/isolation-probe")
        isolation = {runtime: {"qualified": False} for runtime in ("codex", "claude")}
        with mock.patch.object(BENCH, "probe", side_effect=lambda *args, **kwargs: next(answers)), \
             mock.patch.object(BENCH, "local_isolation_probe", return_value=isolation):
            with contextlib.redirect_stdout(io.StringIO()): code = BENCH.status(argparse.Namespace(root=str(self.root)))
        value = BENCH.read_json(self.root / "results/status.json")
        self.assertEqual(3, code); self.assertEqual({"codex": False, "claude": False}, value["auth_ready"])
        self.assertEqual({"codex": False, "claude": False}, value["auth_observed"])
        self.assertNotIn("token", json.dumps(value).lower())

    def test_login_requires_false_baseline_attestation_and_private_layout(self):
        manifest = self.prepare(); runtime = "claude"; version = "2.1.251 (Claude Code)"
        BENCH.write_json(self.root / "results/login-attestation-claude.json", {"owner": BENCH.OWNER,
            "runtime": runtime, "baseline_authenticated": False,
            "runtime_identity": BENCH.digest(manifest["runtime_binaries"][runtime]), "runtime_version": version})
        self.assertTrue(BENCH.login_attested(self.root, manifest, runtime, True, version))
        self.assertFalse(BENCH.login_attested(self.root, manifest, runtime, True, "changed"))
        BENCH.write_json(self.root / "results/status.json", {"owner": BENCH.OWNER, "schema": 1,
            "auth_ready": {"codex": True, "claude": True}, "private_layout": False,
            "runtime_versions": {"codex": "x", "claude": "y"}})
        args = argparse.Namespace(codex_model="c", claude_model="a", codex_effort="high", claude_effort="high",
                                  codex_requested_tier=None, claude_requested_tier=None)
        with self.assertRaisesRegex(SystemExit, "private layout"):
            BENCH.lock_config(self.root, manifest, args)

    def test_login_exec_uses_fixed_binary_and_sanitized_environment(self):
        manifest = self.prepare(); BENCH.write_json(self.root / "results/auth-baseline.json",
            {"owner": BENCH.OWNER, "authenticated": {"codex": False, "claude": False}})
        original_cwd = os.getcwd()
        with mock.patch.dict(os.environ, {"HOME": str(Path.home()), "PATH": "/bin", "ANTHROPIC_API_KEY": "secret",
                                          "ANTHROPIC_PROFILE": "external"}, clear=True), \
             mock.patch.object(BENCH.os, "execve", side_effect=RuntimeError("captured")) as execute, \
             self.assertRaisesRegex(RuntimeError, "captured"):
            try:
                BENCH.login(argparse.Namespace(root=str(self.root), runtime="claude"))
            finally:
                observed_cwd = os.getcwd()
                os.chdir(original_cwd)
        executable, argv, env = execute.call_args.args
        self.assertEqual(BENCH.runtime_argv(manifest["runtime_binaries"]["claude"])[0], executable)
        self.assertEqual(["auth", "login"], argv[-2:]); self.assertEqual(str(Path.home()), env["HOME"])
        self.assertNotIn("ANTHROPIC_API_KEY", env); self.assertNotIn("ANTHROPIC_PROFILE", env)
        self.assertEqual(str(self.root / BENCH.LOGIN_CWD), observed_cwd)

    def test_login_rejects_nonprivate_or_nonempty_login_cwd_before_exec(self):
        self.prepare(); BENCH.write_json(self.root / "results/auth-baseline.json",
            {"owner": BENCH.OWNER, "authenticated": {"codex": False, "claude": False}})
        login_cwd = self.root / BENCH.LOGIN_CWD
        original_uid = os.getuid()
        cases = ("nonempty", "symlink", "mode", "owner")
        for kind in cases:
            with self.subTest(kind=kind):
                if kind == "nonempty":
                    BENCH.write_private(login_cwd / "sentinel", "login cwd must stay empty\n")
                elif kind == "symlink":
                    login_cwd.rmdir()
                    login_cwd.symlink_to(self.root / "runtime/codex/home", target_is_directory=True)
                elif kind == "mode":
                    login_cwd.chmod(0o755)
                uid_patch = (mock.patch.object(BENCH.os, "getuid", return_value=original_uid + 1)
                             if kind == "owner" else contextlib.nullcontext())
                binary_patch = (mock.patch.object(BENCH, "verify_runtime_binaries")
                                if kind == "owner" else contextlib.nullcontext())
                state_patch = (mock.patch.object(BENCH, "verify_runtime_state")
                               if kind == "owner" else contextlib.nullcontext())
                with uid_patch, binary_patch, state_patch, mock.patch.object(BENCH.os, "execve") as execute, \
                     self.assertRaisesRegex(SystemExit, "login-cwd"):
                    BENCH.login(argparse.Namespace(root=str(self.root), runtime="codex"))
                execute.assert_not_called()
                if login_cwd.is_symlink():
                    login_cwd.unlink()
                elif (login_cwd / "sentinel").exists():
                    (login_cwd / "sentinel").unlink()
                login_cwd.mkdir(exist_ok=True)
                login_cwd.chmod(0o700)

    def test_preflight_blocks_login_capability_and_instruction_only_bundle(self):
        manifest = self.prepare()
        BENCH.write_json(self.root / "results/status.json", {"owner": BENCH.OWNER, "schema": 1,
            "auth_ready": {"codex": False, "claude": False},
            "private_layout": True,
            "runtime_versions": {"codex": "codex-cli 0.153.4", "claude": "2.1.251 (Claude Code)"}})
        args = argparse.Namespace(codex_model="c", claude_model="a", codex_effort="high", claude_effort="high",
                                  codex_requested_tier=None, claude_requested_tier=None)
        with self.assertRaisesRegex(SystemExit, "login"): BENCH.lock_config(self.root, manifest, args)
        blockers = BENCH.capability_blockers(self.root, manifest, True, "I03")
        self.assertIn("codex:compact_unknown", blockers)
        self.assertIn("codex:compact_trigger_adapter_missing", blockers)
        self.assertEqual(96, sum(not BENCH.scheduled_complete(self.root, row) for row in manifest["schedule"]
                                 if row.get("candidate") == "I03"))
        self.assertIn("I03:codex:config_bundle_instruction-only", blockers)
        bundle = {"runtime_settings": None}
        binaries = {runtime: BENCH.runtime_binary(sys.executable, runtime) for runtime in ("codex", "claude")}
        config = {"models": {"codex": "c", "claude": "a"}, "efforts": {"codex": "high", "claude": "high"},
                  "runtime_binaries": binaries}
        codex = BENCH.command_for("codex", config, self.root, None, bundle)
        claude = BENCH.command_for("claude", config, self.root, None, bundle)
        self.assertIn("--strict-config", codex); self.assertNotIn("--sandbox", codex); self.assertNotIn("--approve-for-me", codex)
        self.assertIn("--restricted", claude); self.assertIn("--strict-mcp-config", claude)
        self.assertIn("Bash,Read,Edit,Write,Glob,Grep", claude)
        self.assertEqual("dontAsk", claude[claude.index("--permission-mode") + 1])
        self.assertEqual("Read,Edit,Write,Glob,Grep", claude[claude.index("--allowedTools") + 1])
        settings = json.loads(claude[claude.index("--settings") + 1])
        self.assertTrue(settings["sandbox"]["enabled"]); self.assertFalse(settings["sandbox"]["allowUnsandboxedCommands"])
        filesystem = settings["sandbox"]["filesystem"]
        self.assertIn(str(self.root / "runtime"), filesystem["denyRead"])
        self.assertIn(str(self.root / "runtime"), filesystem["denyWrite"])
        self.assertIn("~/", filesystem["denyWrite"])
        self.assertEqual([str(self.root)], settings["sandbox"]["filesystem"]["allowRead"])
        scoped = BENCH.command_for("claude", config, self.root, None, bundle,
                                   [[sys.executable, "quiet-run.py", "--", "false"]])
        rules = scoped[scoped.index("--allowedTools") + 1]
        self.assertIn(f"Bash({sys.executable} quiet-run.py -- false)", rules)
        self.assertNotIn("Bash,", rules)

    def test_prompt_is_identical_between_variants_and_hash_pinned(self):
        manifest = self.prepare()
        for candidate in manifest["candidates"]:
            for runtime in ("codex", "claude"):
                for spec in BENCH.FIXTURES:
                    for repeat in range(1, 4):
                        ids = [f"{candidate}-{runtime}-{variant}-{spec['id']}-r{repeat}"
                               for variant in ("baseline", "candidate")]
                        self.assertEqual(manifest["prompt_hashes"][ids[0]], manifest["prompt_hashes"][ids[1]])

    def test_host_bundle_has_no_file_delta_and_stays_outside_model_workspace(self):
        self.use_host_bundle(); manifest = self.prepare(True)
        self.assertTrue(all(row["evaluation_kind"] == "host-supervised-helper"
                            for row in manifest["comparison_bundles"].values()))
        self.assertEqual(BENCH.HOST_PLAN, manifest["host_helper_plan"])
        row = next(row for row in manifest["schedule"] if row.get("candidate") == "I03" and
                   row.get("fixture") == "repo_add")
        work = BENCH.materialize(self.root, row, manifest)
        bundle = BENCH.materialize_bundle(self.root, row, work, manifest)
        self.assertEqual(set(BENCH.HOST_SOURCE_POLICY), set(bundle["host_sources"]))
        self.assertFalse((work / ".runtime-bundle/host").exists())
        self.assertEqual(BENCH.HOST_SOURCE_POLICY,
                         {name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for name, path in bundle["host_sources"].items()})

    def test_host_bundle_rejects_mixed_workspace_instruction(self):
        self.use_mixed_host_bundle("workspace_instruction")
        with self.assertRaisesRegex(SystemExit, "host bundle entry"):
            self.prepare()

    def test_host_bundle_rejects_mixed_runtime_settings(self):
        self.use_mixed_host_bundle("runtime_settings")
        with self.assertRaisesRegex(SystemExit, "host bundle entry"):
            self.prepare()

    def test_host_bundle_rejects_mixed_hook_adapter(self):
        self.use_mixed_host_bundle("hook_adapter")
        with self.assertRaisesRegex(SystemExit, "host bundle entry"):
            self.prepare()

    def test_host_bundle_rejects_candidate_workspace_delta(self):
        self.use_candidate_mixed_host_bundle("workspace_instruction")
        with self.assertRaisesRegex(SystemExit, "host bundle"):
            self.prepare()

    def test_host_bundle_rejects_candidate_runtime_delta(self):
        self.use_candidate_mixed_host_bundle("runtime_settings")
        with self.assertRaisesRegex(SystemExit, "host bundle"):
            self.prepare()

    def test_host_bundle_rejects_candidate_hook_delta(self):
        self.use_candidate_mixed_host_bundle("hook_adapter")
        with self.assertRaisesRegex(SystemExit, "host bundle"):
            self.prepare()

    def test_host_bundle_rejects_baseline_partial_roles(self):
        self.use_partial_host_bundle("baseline")
        with self.assertRaisesRegex(SystemExit, "host bundle entry"):
            self.prepare()

    def test_host_bundle_rejects_candidate_partial_roles(self):
        self.use_partial_host_bundle("candidate")
        with self.assertRaisesRegex(SystemExit, "host bundle entry"):
            self.prepare()

    def test_host_prompt_has_one_slot_and_only_payload_materializes(self):
        self.use_host_bundle(); manifest = self.prepare()
        rows = [row for row in manifest["schedule"] if row.get("candidate") == "I03" and
                row.get("runtime") == "codex" and row.get("fixture") == "repo_add" and row.get("repeat") == 1]
        prompts = []
        for row in rows:
            spec = BENCH.fixture(row["fixture"], manifest)
            template = BENCH.prompt_for(row, spec, self.root / BENCH.CLAUDE_MARKER, BENCH.HOST_SLOT)
            prompts.append(template)
            self.assertEqual(1, template.count(BENCH.HOST_SLOT))
            self.assertEqual(manifest["prompt_hashes"][row["run_id"]], hashlib.sha256(template.encode()).hexdigest())
        self.assertEqual(prompts[0], prompts[1])

    def test_host_parent_executes_neutral_once_and_hides_strategy(self):
        self.use_host_bundle(); manifest = self.prepare()
        results = []
        for variant in ("baseline", "candidate"):
            row = next(row for row in manifest["schedule"] if row.get("candidate") == "I03" and
                       row.get("runtime") == "codex" and row.get("variant") == variant and
                       row.get("fixture") == "repo_add" and row.get("repeat") == 1)
            work = BENCH.materialize(self.root, row, manifest)
            bundle = BENCH.materialize_bundle(self.root, row, work, manifest)
            results.append(BENCH.run_host_helper(self.root, row, BENCH.fixture("repo_add", manifest), bundle, manifest))
        self.assertEqual(results[0]["result"], results[1]["result"])
        self.assertTrue(all(item["evidence"]["operation_count"] == 0 for item in results))
        self.assertTrue(all(item["evidence"]["helper_mechanism_observed"] is False for item in results))
        self.assertNotIn("strategy", json.dumps(results[0]["result"]))

    def test_host_report_keeps_72_and_24_denominators_separate(self):
        self.use_host_bundle(); manifest = self.prepare(True)
        with contextlib.redirect_stdout(io.StringIO()): BENCH.report(argparse.Namespace(root=str(self.root)))
        report = BENCH.read_json(self.root / "results/report.json")
        self.assertEqual((216, 0), (report["host_subset"]["expected_runs"], report["host_subset"]["recorded_runs"]))
        self.assertEqual(72, report["host_subset"]["per_candidate_expected"])
        self.assertEqual((72, "pending_native_capability"),
                         (report["native_subset"]["expected_runs"], report["native_subset"]["state"]))
        self.assertEqual(24, report["native_subset"]["per_candidate_expected"])
        self.assertFalse(report["host_subset"]["native_effect"]); self.assertFalse(report["host_subset"]["adopted"])
        self.assertEqual("HOLD", report["host_subset"]["selection_state"])
        self.assertEqual("HOLD", report["selection_gate"]["native_subset"]["state"])
        host = report["host_subset"]["by_candidate"]["I03"]
        self.assertEqual(72, host["expected_runs"])
        self.assertEqual(36, host["paired"]["expected_pairs"])
        self.assertFalse(host["paired"]["complete"])
        self.assertEqual(12, host["target_vs_neutral"]["target"]["expected_runs"])
        self.assertEqual(60, host["target_vs_neutral"]["neutral"]["expected_runs"])
        self.assertEqual(12, host["target_vs_neutral"]["target"]["helper_observed"]["expected"])
        self.assertEqual(0, host["target_vs_neutral"]["neutral"]["helper_observed"]["expected"])
        self.assertEqual(0, host["target_vs_neutral"]["target"]["helper_observed"]["observed"])
        self.assertIn("cli_quiet_retrieve", host["target_helpers"])
        self.assertEqual(6, host["target_helpers"]["cli_quiet_retrieve"]["expected_pairs"])

    def test_host_selection_ignores_missing_cost_and_tier(self):
        self.use_host_bundle(); manifest = self.prepare(True)
        target_ids = set(BENCH.host_helper.FIXTURE_TARGETS["I03"])
        rows = [row for row in manifest["schedule"] if row.get("candidate") == "I03" and
                row.get("fixture") not in ("long_compact", "long_resume") and row["kind"] == "compare"]
        for row in rows:
            target = row["fixture"] in target_ids
            input_tokens = 80 if target and row["variant"] == "candidate" else 100
            model = "gpt-6.1-sol" if row["runtime"] == "codex" else "claude-sonnet-5"
            coverage = {"usage": {"qualified": True, "scope": "parent_claim",
                                   "expected": 1, "observed": 1, "rate": 1, "reasons": []},
                        "tool_calls": {"qualified": True, "scope": "main"},
                        "outcome": {"qualified": True, "scope": "main"}}
            quality = {name: True for name in ("success", "gate", "no_symlinks", "workspace_within_limit",
                                               "control_files_unchanged", "restore", "native", "runtime_effective")}
            BENCH.write_json(self.root / "results" / f"run-{row['run_id']}.json", {
                "owner": BENCH.OWNER, "schema": 1, "completed": True, "run": row,
                "status": "success", "quality": quality,
                "process": {"elapsed_seconds": 1,
                            "runtime_identity": {"model": {"confirmed": True, "value": model}}},
                "metrics": {"coverage": coverage, "model": model,
                             "tokens": {"input_total": input_tokens, "output_tokens": 10},
                             "tool_calls": {"total": 1}},
                "host_helper": {"evidence": {"helper_mechanism_observed": target,
                                                "model_received_helper_result": True,
                                                "task_outcome_passed": True}}})
        with contextlib.redirect_stdout(io.StringIO()): BENCH.report(argparse.Namespace(root=str(self.root)))
        report = BENCH.read_json(self.root / "results/report.json")
        gate = report["selection_gate"]["host_subset"]["I03"]
        self.assertEqual("PASS", gate["state"])
        self.assertTrue(gate["eligible"])
        self.assertTrue(gate["metric_coverage_complete"])
        self.assertTrue(gate["target_input_token_reduction"]["eligible"])
        self.assertEqual("NA", gate["cost_tier"]["cost"]["state"])
        self.assertEqual("NA", gate["cost_tier"]["tier"]["state"])
        self.assertEqual("HOLD", report["selection_gate"]["native_subset"]["state"])

    def test_host_selection_holds_for_missing_quality_status_observation(self):
        self.use_host_bundle(); manifest = self.prepare(True)
        target_ids = set(BENCH.host_helper.FIXTURE_TARGETS["I03"])
        rows = [row for row in manifest["schedule"] if row.get("candidate") == "I03" and
                row.get("fixture") not in ("long_compact", "long_resume") and row["kind"] == "compare"]
        quality = {name: True for name in ("success", "gate", "no_symlinks", "workspace_within_limit",
                                           "control_files_unchanged", "restore", "native", "runtime_effective")}
        originals = {}
        for row in rows:
            target = row["fixture"] in target_ids
            input_tokens = 80 if target and row["variant"] == "candidate" else 100
            model = "gpt-6.1-sol" if row["runtime"] == "codex" else "claude-sonnet-5"
            value = {"owner": BENCH.OWNER, "schema": 1, "completed": True, "run": row,
                     "status": "success", "quality": dict(quality),
                     "process": {"elapsed_seconds": 1,
                                 "runtime_identity": {"model": {"confirmed": True, "value": model}}},
                     "metrics": {"model": model,
                                 "coverage": {"usage": {"qualified": True, "scope": "parent_claim",
                                                         "expected": 1, "observed": 1, "rate": 1, "reasons": []},
                                                 "tool_calls": {"qualified": True, "scope": "main"},
                                                 "outcome": {"qualified": True, "scope": "main"}},
                                 "tokens": {"input_total": input_tokens, "output_tokens": 10},
                                 "tool_calls": {"total": 1}},
                     "host_helper": {"evidence": {"helper_mechanism_observed": target,
                                                    "model_received_helper_result": True,
                                                    "task_outcome_passed": True}}}
            path = self.root / "results" / f"run-{row['run_id']}.json"
            BENCH.write_json(path, value); originals[row["run_id"]] = value

        def gate():
            with contextlib.redirect_stdout(io.StringIO()):
                BENCH.report(argparse.Namespace(root=str(self.root)))
            return BENCH.read_json(self.root / "results/report.json")["selection_gate"]["host_subset"]["I03"]

        self.assertEqual("PASS", gate()["state"])
        target_row = next(row for row in rows if row["fixture"] in target_ids)
        neutral_row = next(row for row in rows if row["fixture"] not in target_ids)
        cases = (
            ("quality", target_row, lambda value: value["quality"].pop("restore"),
             "quality_field_coverage_incomplete"),
            ("status", target_row, lambda value: value.update(status="outside_enum"),
             "status_coverage_incomplete"),
            ("model", target_row, lambda value: value["host_helper"]["evidence"].update(
                model_received_helper_result=False), "model_received_incomplete"),
            ("target-helper", target_row, lambda value: value["host_helper"]["evidence"].update(
                helper_mechanism_observed=False), "helper_observation_incomplete"),
            ("neutral-helper", neutral_row, lambda value: value["host_helper"]["evidence"].update(
                helper_mechanism_observed=True), "helper_observation_incomplete"),
        )
        for name, row, mutate, blocker in cases:
            with self.subTest(name=name):
                path = self.root / "results" / f"run-{row['run_id']}.json"
                value = json.loads(json.dumps(originals[row["run_id"]]))
                mutate(value); BENCH.write_json(path, value)
                failed = gate()
                self.assertEqual("HOLD", failed["state"])
                self.assertIn(blocker, failed["blocking_reasons"])
                BENCH.write_json(path, originals[row["run_id"]])

    def test_host_source_hash_drift_is_rejected(self):
        self.use_host_bundle(); target = self.bundle / "quiet_run"
        target.write_text("changed\n"); target.chmod(0o600)
        with self.assertRaisesRegex(SystemExit, "契約違反"):
            self.prepare()

    def test_helper_pre_model_failure_consumes_attempt_and_holds_pair(self):
        row = {"candidate": "I03", "fixture": "repo_add", "run_id": "I03-codex-baseline-repo_add-r1"}
        value = BENCH.host_pre_model_failure(row, "source_hash_mismatch")
        self.assertTrue(value["pair_stop"])
        self.assertEqual("failed", value["result"]["status"])
        self.assertFalse(value["evidence"]["helper_mechanism_observed"])
        self.assertTrue(value["evidence"]["pre_model_failed"])
        self.assertEqual("source_hash_mismatch", value["evidence"]["failure_reason"])

    def test_run_one_records_helper_outer_elapsed_without_sleep(self):
        self.use_host_bundle(); manifest = self.prepare()
        row = next(item for item in manifest["schedule"] if item.get("candidate") == "I03" and
                   item.get("runtime") == "codex" and item.get("variant") == "baseline" and
                   item.get("fixture") == "repo_add" and item.get("repeat") == 1)
        config = {"runtime_versions": {"codex": "codex-test"}}
        with mock.patch.object(BENCH, "probe", return_value="codex-test"), \
             mock.patch.object(BENCH, "run_host_helper",
                               side_effect=BENCH.host_helper.HelperError("source_hash_mismatch")), \
             mock.patch.object(BENCH.time, "monotonic", side_effect=[10.0, 20.0, 20.25]):
            self.assertTrue(BENCH.run_one(self.root, row, config, manifest, 10))
        value = BENCH.read_json(self.root / "results" / f"run-{row['run_id']}.json")
        self.assertEqual("pre_model_failed", value["status"])
        self.assertEqual(250.0, value["host_helper"]["evidence"]["elapsed_ms"])
        self.assertEqual(250.0, value["timing"]["helper_to_model_end_elapsed_ms"])
        self.assertEqual(250.0, value["end_to_end_elapsed_ms"])
        self.assertIsNone(value["materialized_prompt_sha256"])
        self.assertEqual("source_hash_mismatch", value["prompt"]["materialized_prompt_reason"])

    def test_host_stage_failure_after_claim_closes_pair_and_blocks_candidate(self):
        self.use_host_bundle(); manifest = self.prepare()
        row = next(item for item in manifest["schedule"] if item.get("candidate") == "I03" and
                   item.get("runtime") == "codex" and item.get("variant") == "baseline" and
                   item.get("fixture") == "repo_add" and item.get("repeat") == 1)
        staged = self.root / "runtime/host-sources/quiet_run"
        staged.unlink()
        config = {"runtime_versions": {"codex": "codex-test"}}
        with mock.patch.object(BENCH, "probe", return_value="codex-test"):
            self.assertTrue(BENCH.run_one(self.root, row, config, manifest, 10))
        reason = f"staged comparison bundleが変化した: I03:codex:baseline:host/quiet_run"
        value = BENCH.read_json(self.root / "results" / f"run-{row['run_id']}.json")
        marker = BENCH.read_json(self.root / "results/host-blocked-I03.json")
        self.assertTrue(value["completed"]); self.assertEqual("pre_model_failed", value["status"])
        self.assertEqual(reason, value["failure_reason"])
        self.assertFalse(value["model_called"]); self.assertFalse(value["prompt_sent"])
        self.assertFalse(value["model_received_helper_result"])
        self.assertIsNone(value["materialized_prompt_sha256"]); self.assertIsNone(value["sent_prompt_sha256"])
        self.assertEqual(reason, value["host_helper"]["evidence"]["failure_reason"])
        self.assertTrue(value["host_helper"]["evidence"]["pre_model_failed"])
        self.assertTrue(value["host_helper"]["evidence"]["pair_stop"])
        self.assertGreaterEqual(value["timing"]["run_elapsed_ms"], 0)
        self.assertEqual(("pending_helper_blocked", reason), (marker["status"], marker["reason"]))

    def test_host_template_hash_drift_after_helper_closes_pair(self):
        self.use_host_bundle(); manifest = self.prepare()
        row = next(item for item in manifest["schedule"] if item.get("candidate") == "I03" and
                   item.get("runtime") == "codex" and item.get("variant") == "baseline" and
                   item.get("fixture") == "repo_add" and item.get("repeat") == 1)
        manifest["prompt_hashes"][row["run_id"]] = "0" * 64
        config = {"runtime_versions": {"codex": "codex-test"}}
        with mock.patch.object(BENCH, "probe", return_value="codex-test"), \
             mock.patch.object(BENCH, "run_host_helper",
                               side_effect=lambda *args: self.neutral_host_result(args[1])), \
             mock.patch.object(BENCH, "command_for", return_value=["/bin/true"]), \
             mock.patch.object(BENCH, "run_finite") as execute:
            self.assertTrue(BENCH.run_one(self.root, row, config, manifest, 10))
        execute.assert_not_called()
        value = BENCH.read_json(self.root / "results" / f"run-{row['run_id']}.json")
        self.assertTrue(value["completed"]); self.assertEqual("pre_model_failed", value["status"])
        self.assertEqual("promptが準備時から変化した", value["failure_reason"])
        self.assertFalse(value["model_called"]); self.assertFalse(value["prompt_sent"])
        self.assertFalse(value["model_received_helper_result"])
        self.assertIsNotNone(value["materialized_prompt_sha256"])
        self.assertIsNone(value["sent_prompt_sha256"]); self.assertIsNone(value["sent_prompt_bytes"])
        self.assertEqual("promptが準備時から変化した", value["prompt"]["materialized_prompt_reason"])
        self.assertTrue(value["host_helper"]["evidence"]["pair_stop"])

    def test_host_hash_fields_are_required_and_bound_to_request_result(self):
        row = {"candidate": "I03", "fixture": "repo_add", "variant": "baseline"}
        original = self.neutral_host_result(row)
        cases = (("request", "request_hash", "helper_request_hash_mismatch"),
                 ("result", "result_hash", "helper_result_hash_mismatch"),
                 ("request-missing", "request_hash", "helper_request_hash_invalid"),
                 ("result-missing", "result_hash", "helper_result_hash_invalid"))
        for name, field, reason in cases:
            with self.subTest(name=name):
                value = json.loads(json.dumps(original))
                if name.endswith("missing"):
                    value["evidence"].pop(field)
                else:
                    value["evidence"][field] = "0" * 64
                with self.assertRaisesRegex(BENCH.host_helper.HelperError, reason):
                    BENCH.normalize_host_result(row, value)
        value = json.loads(json.dumps(original))
        value["result"]["payload"]["facts"]["tampered"] = True
        with self.assertRaisesRegex(BENCH.host_helper.HelperError, "helper_result_content_hash_mismatch"):
            BENCH.normalize_host_result(row, value)
        self.assertFalse(value["evidence"].get("binding_valid", False))

    def test_valid_hash_normalization_failure_keeps_binding_but_unqualified(self):
        self.use_host_bundle(); manifest = self.prepare()
        rows = [row for row in manifest["schedule"] if row.get("candidate") == "I03" and
                row.get("runtime") == "codex" and row.get("variant") == "baseline" and
                row.get("fixture") == "cli_quiet_retrieve" and row.get("repeat") in (1, 2)]
        cases = ((rows[0], "payload", "helper_result_payload_invalid"),
                 (rows[1], "context", "helper_prompt_context_invalid"))
        for row, failure, expected_reason in cases:
            with self.subTest(failure=failure):
                helper_row = dict(row); helper_row["run_id"] = row["run_id"] + "-helper"
                work = BENCH.materialize(self.root, helper_row, manifest)
                bundle = BENCH.materialize_bundle(self.root, helper_row, work, manifest)
                observed = BENCH.run_host_helper(self.root, helper_row,
                                                 BENCH.fixture(row["fixture"], manifest), bundle, manifest)
                self.assertTrue(observed["evidence"]["helper_mechanism_observed"])
                self.assertTrue(observed["evidence"]["binding_valid"])
                supplied = json.loads(json.dumps(observed))
                if failure == "payload":
                    supplied["result"]["payload"]["extra"] = True
                    unsigned = dict(supplied["result"])
                    unsigned.pop("content_hash", None)
                    content_hash = BENCH.host_helper.digest(unsigned)
                    supplied["result"]["content_hash"] = content_hash
                    supplied["evidence"]["result_hash"] = content_hash
                else:
                    supplied["prompt_context"] += "\n"
                config = {"runtime_versions": {"codex": "codex-test"}}
                with mock.patch.object(BENCH, "probe", return_value="codex-test"), \
                     mock.patch.object(BENCH, "run_host_helper", return_value=supplied), \
                     mock.patch.object(BENCH, "run_finite") as execute:
                    self.assertTrue(BENCH.run_one(self.root, row, config, manifest, 10))
                value = BENCH.read_json(self.root / "results" / f"run-{row['run_id']}.json")
                evidence = value["host_helper"]["evidence"]
                self.assertEqual("pre_model_failed", value["status"])
                self.assertEqual(expected_reason, value["failure_reason"])
                self.assertFalse(value["model_called"]); self.assertFalse(value["prompt_sent"])
                self.assertFalse(value["model_received_helper_result"])
                self.assertTrue(evidence["binding_valid"])
                self.assertFalse(evidence["normalized"])
                self.assertFalse(evidence["helper_mechanism_observed"])
                self.assertTrue(evidence["raw_helper_mechanism_observed"])
                self.assertEqual(supplied["evidence"]["request_hash"], evidence["request_hash"])
                self.assertEqual(supplied["evidence"]["result_hash"], evidence["result_hash"])
                self.assertEqual(supplied["evidence"]["metrics"], evidence["metrics"])
                self.assertTrue(evidence["pre_model_failed"]); self.assertTrue(evidence["pair_stop"])
                execute.assert_not_called()

    def test_target_helper_evidence_survives_pre_model_hash_and_command_failures(self):
        self.use_host_bundle(); manifest = self.prepare()
        rows = [row for row in manifest["schedule"] if row.get("candidate") == "I03" and
                row.get("runtime") == "codex" and row.get("variant") == "baseline" and
                row.get("fixture") == "cli_quiet_retrieve" and row.get("repeat") in (1, 2, 3)]
        cases = ((rows[0], "hash", "helper_request_hash_mismatch"),
                 (rows[1], "command", "command_pre_model_failure"),
                 (rows[2], "launch", "launch_error"))
        for row, failure, expected_reason in cases:
            with self.subTest(failure=failure):
                helper_row = dict(row); helper_row["run_id"] = row["run_id"] + "-helper"
                work = BENCH.materialize(self.root, helper_row, manifest)
                bundle = BENCH.materialize_bundle(self.root, helper_row, work, manifest)
                observed = BENCH.run_host_helper(self.root, helper_row,
                                                 BENCH.fixture(row["fixture"], manifest), bundle, manifest)
                self.assertTrue(observed["evidence"]["helper_mechanism_observed"])
                original = json.loads(json.dumps(observed))
                supplied = json.loads(json.dumps(observed))
                if failure == "hash":
                    supplied["evidence"]["request_hash"] = "0" * 64
                config = {"runtime_versions": {"codex": "codex-test"}}
                command_patch = (mock.patch.object(BENCH, "command_for",
                                                   side_effect=SystemExit(expected_reason))
                                 if failure == "command" else
                                 mock.patch.object(BENCH, "command_for", return_value=["/bin/true"])
                                 if failure == "launch" else contextlib.nullcontext())
                with mock.patch.object(BENCH, "probe", return_value="codex-test"), \
                     mock.patch.object(BENCH, "run_host_helper", return_value=supplied), \
                     mock.patch.object(BENCH, "run_finite") as execute, command_patch:
                    if failure == "launch":
                        execute.side_effect = OSError("blocked")
                    self.assertTrue(BENCH.run_one(self.root, row, config, manifest, 10))
                value = BENCH.read_json(self.root / "results" / f"run-{row['run_id']}.json")
                self.assertEqual("pre_model_failed", value["status"])
                self.assertEqual(expected_reason, value["failure_reason"])
                self.assertFalse(value["model_called"]); self.assertFalse(value["prompt_sent"])
                self.assertFalse(value["model_received_helper_result"])
                self.assertEqual(original["result"], value["host_helper"]["result"])
                actual_evidence = value["host_helper"]["evidence"]
                expected_evidence = supplied["evidence"]
                for field in ("request_hash", "result_hash", "operations",
                              "operation_count", "metrics", "artifacts", "elapsed_ms"):
                    self.assertEqual(expected_evidence.get(field), actual_evidence.get(field), field)
                if failure == "hash":
                    self.assertFalse(actual_evidence["helper_mechanism_observed"])
                    self.assertFalse(actual_evidence["binding_valid"])
                    self.assertTrue(actual_evidence["raw_helper_mechanism_observed"])
                    self.assertFalse(actual_evidence["normalized"])
                else:
                    self.assertTrue(actual_evidence["helper_mechanism_observed"])
                    self.assertTrue(actual_evidence["binding_valid"])
                    self.assertTrue(actual_evidence["normalized"])
                self.assertFalse(actual_evidence["model_received_helper_result"])
                self.assertFalse(actual_evidence["task_outcome_passed"])
                self.assertTrue(actual_evidence["pre_model_failed"])
                self.assertTrue(actual_evidence["pair_stop"])
                if failure == "launch":
                    self.assertEqual("OSError", value["process"]["launch_error"])
                    execute.assert_called_once()
                else:
                    execute.assert_not_called()

    def test_run_one_records_materialized_prompt_and_rejects_hash_mismatch(self):
        self.use_host_bundle(); manifest = self.prepare()
        rows = {item["variant"]: item for item in manifest["schedule"]
                if item.get("candidate") == "I03" and item.get("runtime") == "codex" and
                item.get("fixture") == "repo_add" and item.get("repeat") == 1}
        config = {"runtime_versions": {"codex": "codex-test"}, "run_timeout_seconds": 10, "locked_at": "test"}
        calls = []

        def fake_finite(command, prompt, *args):
            calls.append(prompt)
            self.make_codex_arg0(manifest, "P0sT%02d" % len(calls))
            prompt_bytes = prompt.encode()
            return {"exit_code": 0, "stop_reason": None, "process_started": True, "prompt_sent": True,
                    "materialized_prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
                    "materialized_prompt_bytes": len(prompt_bytes),
                    "sent_prompt_sha256": (hashlib.sha256(prompt_bytes).hexdigest()
                                            if len(calls) == 1 else "0" * 64),
                    "sent_prompt_bytes": len(prompt_bytes),
                    "prompt_sha256": (hashlib.sha256(prompt_bytes).hexdigest() if len(calls) == 1 else "0" * 64),
                    "model_called": True, "model_response_observed": True,
                    "session_id": None, "hook_events": [], "rejection": False, "terminal_status": None,
                    "elapsed_seconds": 0.25}

        with mock.patch.object(BENCH, "probe", return_value="codex-test"), \
             mock.patch.object(BENCH, "run_host_helper", side_effect=lambda *args: self.neutral_host_result(args[1])), \
             mock.patch.object(BENCH, "command_for", return_value=["/bin/true"]), \
             mock.patch.object(BENCH, "run_finite", side_effect=fake_finite), \
             mock.patch.object(BENCH, "score", return_value={"success": True}), \
             mock.patch.object(BENCH, "confirm_runtime_identity", return_value={"confirmed": True}), \
             mock.patch.object(BENCH, "metrics", return_value={}):
            self.assertTrue(BENCH.run_one(self.root, rows["baseline"], config, manifest, 10))
            self.assertTrue(BENCH.run_one(self.root, rows["candidate"], config, manifest, 10))
        spec = BENCH.fixture("repo_add", manifest)
        template = BENCH.prompt_for(rows["baseline"], spec, self.root / BENCH.CLAUDE_MARKER, BENCH.HOST_SLOT)
        context = self.neutral_host_result(rows["baseline"])["prompt_context"]
        expected = template.replace(BENCH.HOST_SLOT, context)
        baseline = BENCH.read_json(self.root / "results" / f"run-{rows['baseline']['run_id']}.json")
        candidate = BENCH.read_json(self.root / "results" / f"run-{rows['candidate']['run_id']}.json")
        self.assertEqual(baseline["template_sha256"], candidate["template_sha256"])
        self.assertEqual(hashlib.sha256(template.encode()).hexdigest(), baseline["template_sha256"])
        self.assertEqual(hashlib.sha256(expected.encode()).hexdigest(), baseline["materialized_prompt_sha256"])
        self.assertEqual(len(expected.encode()), baseline["materialized_prompt_bytes"])
        self.assertEqual(baseline["materialized_prompt_sha256"], baseline["sent_prompt_sha256"])
        self.assertEqual(baseline["materialized_prompt_bytes"], baseline["sent_prompt_bytes"])
        self.assertTrue(baseline["host_helper"]["evidence"]["model_received_helper_result"])
        self.assertEqual("materialized_prompt_hash_mismatch", candidate["prompt"]["materialized_prompt_reason"])
        self.assertEqual(hashlib.sha256(calls[1].encode()).hexdigest(), candidate["materialized_prompt_sha256"])
        self.assertNotEqual(candidate["materialized_prompt_sha256"], candidate["sent_prompt_sha256"])
        self.assertFalse(candidate["host_helper"]["evidence"]["model_received_helper_result"])
        self.assertEqual("passed", baseline["process"]["codex_arg0_cleanup"])
        self.assertFalse((self.root / "runtime/codex/home/tmp/arg0").exists())

    def test_post_model_arg0_cleanup_failure_preserves_process_evidence_and_fails_run(self):
        manifest = self.prepare(); row = next(item for item in manifest["schedule"]
                                               if item["kind"] == "compare" and item["runtime"] == "codex")
        config = {"runtime_versions": {"codex": "codex-test"}, "run_timeout_seconds": 10,
                  "locked_at": "test"}
        def fake_finite(_command, prompt, *_args):
            helper = self.make_codex_arg0(manifest)
            (helper / "unknown").write_text("x"); (helper / "unknown").chmod(0o600)
            body = prompt.encode(); source_hash = hashlib.sha256(body).hexdigest()
            return {"exit_code": 0, "stop_reason": None, "process_started": True, "prompt_sent": True,
                    "materialized_prompt_sha256": source_hash, "materialized_prompt_bytes": len(body),
                    "sent_prompt_sha256": source_hash, "sent_prompt_bytes": len(body),
                    "prompt_sha256": source_hash, "model_called": True, "model_response_observed": True,
                    "session_id": "observed-session", "hook_events": [], "rejection": False,
                    "terminal_status": None, "elapsed_seconds": .1}
        with mock.patch.object(BENCH, "probe", return_value="codex-test"), \
             mock.patch.object(BENCH, "command_for", return_value=["/bin/true"]), \
             mock.patch.object(BENCH, "run_finite", side_effect=fake_finite), \
             mock.patch.object(BENCH, "score", return_value={"success": True}), \
             mock.patch.object(BENCH, "confirm_runtime_identity", return_value={"confirmed": True}), \
             mock.patch.object(BENCH, "metrics", return_value={}):
            self.assertTrue(BENCH.run_one(self.root, row, config, manifest, 10))
        value = BENCH.read_json(self.root / "results" / f"run-{row['run_id']}.json")
        self.assertEqual("interruption", value["status"])
        self.assertTrue(value["model_called"]); self.assertTrue(value["model_response_observed"])
        self.assertEqual("observed-session", value["process"]["session_id"])
        self.assertEqual("failed", value["process"]["codex_arg0_cleanup"])
        self.assertEqual("codex_arg0_cleanup_failed", value["process"]["stop_reason"])
        self.assertFalse(value["quality"]["success"])

    def test_report_retains_pre_model_failed_mate_as_unpaired(self):
        self.use_host_bundle(); manifest = self.prepare(True)
        rows = {row["variant"]: row for row in manifest["schedule"]
                if row.get("candidate") == "I03" and row.get("runtime") == "codex" and
                row.get("fixture") == "repo_add" and row.get("repeat") == 1}
        failed = BENCH.host_pre_model_failure(rows["baseline"], "source_hash_mismatch")
        BENCH.write_json(self.root / "results" / f"run-{rows['baseline']['run_id']}.json",
                         {"owner": BENCH.OWNER, "schema": 1, "completed": True,
                          "run": rows["baseline"], "status": "pre_model_failed",
                          "model_called": False, "host_helper": failed})
        BENCH.write_json(self.root / "results" / f"run-{rows['candidate']['run_id']}.json",
                         {"owner": BENCH.OWNER, "schema": 1, "completed": True,
                          "run": rows["candidate"], "status": "success",
                          "quality": {"success": True}, "metrics": {}, "model_called": True})
        with contextlib.redirect_stdout(io.StringIO()): BENCH.report(argparse.Namespace(root=str(self.root)))
        report = BENCH.read_json(self.root / "results/report.json")
        pair = next(item for item in report["pairs"]
                    if item["pair_id"] == "I03:codex:repo_add:r1")
        self.assertEqual("pre_model_failed", pair["baseline"]["status"])
        self.assertFalse(pair["complete"])
        self.assertTrue(pair["unpaired"])
        self.assertTrue(pair["pair_stop"])
        self.assertTrue(pair["pre_model_failed"])

    def test_host_token_reduction_negative_is_not_eligible(self):
        pairs = [{"complete": True, "paired_qualified": {"usage": True},
                  "baseline": {"values": {"input_tokens": 100}},
                  "candidate": {"values": {"input_tokens": 95}}}]
        reduction = BENCH.host_input_token_reduction(pairs)
        self.assertEqual(0.05, reduction["median"])
        self.assertFalse(reduction["eligible"])

    def test_neutral_result_contract_rejects_observed_mechanism(self):
        row = {"candidate": "I03", "fixture": "repo_add"}
        result = {"owner": BENCH.host_helper.RESULT_OWNER, "schema": BENCH.host_helper.SCHEMA,
                  "candidate": "I03", "fixture": "repo_add", "status": "neutral",
                  "mechanism": "neutral", "payload": {"context": "", "facts": {"neutral": True},
                  "diagnostics": []}, "references": []}
        result["content_hash"] = BENCH.host_helper.digest(result)
        request = BENCH.host_helper.make_request({**row, "variant": "baseline"}, BENCH.fixture(row["fixture"]))
        neutral = {"result": result,
                   "evidence": {"helper_mechanism_observed": False, "operation_count": 0,
                                "failure_reason": None,
                                "request_hash": BENCH.host_helper.digest(request),
                                "result_hash": result["content_hash"]}, "pair_stop": False}
        self.assertIs(BENCH.normalize_host_result(row, neutral), neutral)
        neutral["evidence"]["helper_mechanism_observed"] = True
        with self.assertRaisesRegex(BENCH.host_helper.HelperError, "neutral_helper_observation_invalid"):
            BENCH.normalize_host_result(row, neutral)
        target_row = {"candidate": "I03", "fixture": "cli_quiet_retrieve"}
        target = self.neutral_host_result(target_row)
        with self.assertRaisesRegex(BENCH.host_helper.HelperError, "target_result_status_invalid"):
            BENCH.normalize_host_result(target_row, target)

    def test_host_prompt_context_is_reconstructed_and_wrapper_drift_rejected(self):
        row = {"candidate": "I03", "fixture": "repo_add"}
        value = self.neutral_host_result(row)
        value.pop("prompt_context")
        normalized = BENCH.normalize_host_result(row, value)
        expected = f'<mechanism-context schema="host-helper-result-v1">{BENCH.host_helper.canonical(value["result"]).decode()}</mechanism-context>'
        self.assertEqual(expected, normalized["prompt_context"])
        value["prompt_context"] = expected + "\n"
        with self.assertRaisesRegex(BENCH.host_helper.HelperError, "helper_prompt_context_invalid"):
            BENCH.normalize_host_result(row, value)

    def test_runtime_settings_reject_environment_injection(self):
        config = {"models": {"codex": "c", "claude": "a"},
                  "efforts": {"codex": "high", "claude": "high"},
                  "runtime_binaries": {runtime: BENCH.runtime_binary(sys.executable, runtime)
                                       for runtime in ("codex", "claude")}}
        path = self.root / "settings.json"; self.private_write(path, {"env": {"HOME": "/live"}})
        for value in ({"env": {"HOME": "/live"}}, {"enabledPlugins": {"x@y": True}},
                      {"mcp_servers": {"x": {"url": "https://invalid"}}}, {"unknown": True}):
            self.private_write(path, value)
            with self.assertRaisesRegex(SystemExit, "allowlist"):
                BENCH.command_for("claude", config, self.root, None,
                                  {"runtime_settings": str(path), "candidate": "I03"})

    def test_model_effort_and_tier_reject_config_injection(self):
        base = dict(codex_model="gpt-5.6", claude_model="claude-x", codex_effort="high",
                    claude_effort="high", codex_requested_tier="priority", claude_requested_tier=None)
        BENCH.validate_config_args(argparse.Namespace(**base))
        for key, value in (("codex_model", '-c'), ("codex_model", 'gpt"\nnetwork=true'),
                           ("claude_effort", "high\n"), ("codex_requested_tier", "unknown")):
            changed = {**base, key: value}
            with self.assertRaises(SystemExit):
                BENCH.validate_config_args(argparse.Namespace(**changed))

    def test_env_shebang_interpreter_is_pinned_and_path_drift_rejected(self):
        launcher = self.root / "launcher.js"; launcher.write_text("#!/usr/bin/env node\n")
        launcher.chmod(0o700)
        with mock.patch.object(BENCH.shutil, "which", return_value=sys.executable):
            row = BENCH.runtime_binary(str(launcher), "codex")
        self.assertEqual([str(Path(sys.executable).resolve()), str(launcher)], BENCH.runtime_argv(row))
        spec = BENCH.resolved_fixture("repo_tsc_once", {"typescript_cli": {"state": "observed", "binary": row}})
        self.assertEqual([str(Path(sys.executable).resolve()), str(launcher), "--noEmit", "--pretty", "false"],
                         spec["required_commands"][0])
        self.assertIn(BENCH.shlex.join(BENCH.runtime_argv(row)), spec["instruction"])
        with mock.patch.object(BENCH.shutil, "which", return_value=None), \
             self.assertRaisesRegex(SystemExit, "interpreter"):
            BENCH.verify_runtime_binaries({"runtime_binaries": {"codex": row}, "fixture_tools": {},
                                             "codex_arg0_native": BENCH.pinned_executable(
                                                 str(self.codex_native), "test native")})
        manifest = {"runtime_binaries": {}, "codex_arg0_native": BENCH.pinned_executable(
                        str(self.codex_native), "test native"), "fixture_tools": {"python_cli": {
            "state": "observed", "binary": BENCH.runtime_binary(sys.executable, "python_cli")}}}
        with mock.patch.object(BENCH.sys, "executable", "/bin/sh"), \
             self.assertRaisesRegex(SystemExit, "runner Python"):
            BENCH.verify_runtime_binaries(manifest)

    def test_capability_source_hash_and_allowed_path_are_rechecked(self):
        manifest = self.prepare()
        manifest["capability_source"]["source_hash"] = "0" * 64
        with self.assertRaisesRegex(SystemExit, "capability source"):
            BENCH.verify_capability_source(manifest)
        copied = self.root / "outside.md"; copied.write_bytes(self.capability.read_bytes()); copied.chmod(0o600)
        manifest["capability_source"] = {"source_path": str(copied),
            "source_hash": hashlib.sha256(copied.read_bytes()).hexdigest()}
        with self.assertRaisesRegex(SystemExit, "capability source"):
            BENCH.verify_capability_source(manifest)

    def test_adoption_rejects_success_regression_and_quality_gap(self):
        metrics = ("usage", "tool_calls", "outcome", "cost")
        pairs = [{"complete": True, "paired_qualified": {name: True for name in metrics}} for _ in range(24)]
        coverage = {name: {"complete": True} for name in metrics}
        baseline = {"successes": 24, "coverage": coverage}
        candidate = {"candidate_effect_observed": True, "complete": True, "expected_runs": 24,
                     "successes": 23, "required_quality_complete": True, "coverage": coverage}
        self.assertFalse(BENCH.adoption_eligible(baseline, candidate, pairs))
        candidate["successes"] = 24
        self.assertTrue(BENCH.adoption_eligible(baseline, candidate, pairs))
        pairs[0]["paired_qualified"]["cost"] = False
        self.assertFalse(BENCH.adoption_eligible(baseline, candidate, pairs))

    def test_usage_unknown_is_not_misclassified_as_interruption(self):
        process = {"rejection": False, "terminal_status": None, "exit_code": 0,
                   "stop_reason": "output_usage_unknown"}
        self.assertEqual("unknown", BENCH.classify_status(process, {"success": False}))
        process["terminal_status"] = "failure"; process["exit_code"] = 1
        self.assertEqual("failure", BENCH.classify_status(process, {"success": False}))

    def test_runtime_identity_uses_runtime_specific_fail_closed_sources(self):
        config = {"models": {"codex": "gpt-c", "claude": "claude-c"},
                  "efforts": {"codex": "high", "claude": "high"}}
        codex = BENCH.confirm_runtime_identity("codex", {"observed_models": [], "observed_efforts": []}, config)
        self.assertTrue(codex["confirmed"])
        self.assertEqual(("locked_exact_argv", "locked_exact_argv"),
                         (codex["model"]["source"], codex["effort"]["source"]))
        claude_missing = BENCH.confirm_runtime_identity(
            "claude", {"observed_models": [], "observed_efforts": []}, config)
        self.assertFalse(claude_missing["confirmed"])
        self.assertEqual("runtime_event_missing", claude_missing["model"]["source"])
        claude = BENCH.confirm_runtime_identity(
            "claude", {"observed_models": ["claude-c"], "observed_efforts": []}, config)
        self.assertTrue(claude["confirmed"])
        self.assertEqual(("runtime_event", "locked_exact_argv"),
                         (claude["model"]["source"], claude["effort"]["source"]))
        conflict = BENCH.confirm_runtime_identity(
            "codex", {"observed_models": ["gpt-c", "other"], "observed_efforts": ["high"]}, config)
        self.assertFalse(conflict["confirmed"])
        self.assertEqual("runtime_event_conflict", conflict["model"]["source"])

    def test_score_runs_functional_checks_and_protects_inputs(self):
        work = self.root / "work"; work.mkdir(mode=0o700)
        (work / "calc.py").write_text("def add(a,b):\n return b+a\n"); (work / "result.json").write_text('{"checked": true}')
        for path in work.iterdir(): path.chmod(0o600)
        process = {"exit_code": 0, "stop_reason": None, "compact_events": 0, "commands": []}
        self.assertTrue(BENCH.score(work, BENCH.fixture("repo_add"), process)["success"])
        shutil.rmtree(work); work.mkdir(mode=0o700)
        tool = {"typescript_cli": {"state": "observed", "binary": {"path": "/reviewed/tsc"}}}
        spec = BENCH.resolved_fixture("repo_tsc_once", tool)
        process["commands"] = [["/reviewed/tsc", "--noEmit", "--pretty", "false"]]
        for name, content in {**spec["files"], **spec["expected"]}.items():
            target = work / name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700); target.write_text(content)
            target.chmod(0o600)
        self.assertTrue(BENCH.score(work, spec, process)["success"])
        process["commands"] = [["echo", "/reviewed/tsc --noEmit --pretty false"]]
        self.assertFalse(BENCH.score(work, spec, process)["success"])
        (work / "bad-link").symlink_to(work / "component.ts")
        self.assertFalse(BENCH.score(work, spec, process)["no_symlinks"])
        shutil.rmtree(work); work.mkdir(mode=0o700)
        spec = BENCH.fixture("long_resume")
        for name, content in {**spec["files"], **spec["expected"]}.items():
            (work / name).write_text(content); (work / name).chmod(0o600)
        with mock.patch.object(BENCH, "workspace_within_limits", return_value=(False, [], [])), \
             mock.patch.object(Path, "read_text", side_effect=AssertionError("unsafe read")):
            limited = BENCH.score(work, spec, {"exit_code": 0, "stop_reason": None,
                                                "compact_events": 0, "commands": []})
        self.assertFalse(limited["restore"])

    def test_actual_quiet_run_saves_large_log_and_retrieves_once(self):
        work = self.root / "quiet"; work.mkdir(mode=0o700)
        spec = BENCH.fixture("cli_quiet_retrieve")
        for name, content in spec["files"].items():
            target = work / name; target.write_text(content); target.chmod(0o600)
        first = subprocess.run([sys.executable, "quiet-run.py", "--log-dir", ".quiet-logs", "--",
                                sys.executable, "quiet_check.py"], cwd=work, capture_output=True,
                               check=False, timeout=10, umask=0o077)
        second = subprocess.run([sys.executable, "retrieve_failure.py"], cwd=work, capture_output=True,
                                check=False, timeout=10, umask=0o077)
        self.assertEqual((7, 0), (first.returncode, second.returncode))
        process = {"exit_code": 0, "stop_reason": None, "compact_events": 0,
                   "commands": [[sys.executable, "quiet-run.py", "--log-dir", ".quiet-logs", "--",
                                  sys.executable, "quiet_check.py"],
                                 [sys.executable, "retrieve_failure.py"]]}
        quality = BENCH.score(work, spec, process)
        self.assertTrue(quality["success"]); self.assertTrue(quality["dynamic_output_valid"])

    def test_workspace_scan_rejects_entries_modes_and_fifo_without_unbounded_list(self):
        work = self.root / "scan"; work.mkdir(mode=0o700)
        for index in range(BENCH.LIMITS["workspace_entries"] + 1):
            (work / f"f{index}").write_text("x"); (work / f"f{index}").chmod(0o600)
        self.assertFalse(BENCH.workspace_within_limits(work)[0])
        shutil.rmtree(work); work.mkdir(mode=0o700)
        os.mkfifo(work / "pipe", 0o600)
        self.assertFalse(BENCH.workspace_within_limits(work)[0])
        (work / "pipe").unlink(); (work / "open.txt").write_text("x"); (work / "open.txt").chmod(0o644)
        self.assertFalse(BENCH.workspace_within_limits(work)[0])

    def test_claude_boundary_smoke_requires_native_denial_event(self):
        manifest = self.prepare(); row = next(row for row in manifest["schedule"] if row["run_id"] == "smoke-claude")
        work = BENCH.materialize_smoke(self.root, row)
        (work / "inside-written.txt").write_text("ok"); (work / "inside-written.txt").chmod(0o600)
        wrapped_inside, *outside = BENCH.claude_smoke_commands(self.root)
        inside = BENCH.normalized_command(BENCH.shlex.join(wrapped_inside))
        process = {"exit_code": 0, "stop_reason": None, "commands": [inside], "denied_commands": []}
        self.assertFalse(BENCH.smoke_quality(self.root, row, work, process, manifest)["success"])
        process["denied_commands"] = [BENCH.normalized_command(BENCH.shlex.join(command)) for command in outside]
        self.assertTrue(BENCH.smoke_quality(self.root, row, work, process, manifest)["success"])
        process["denied_commands"].pop()
        self.assertFalse(BENCH.smoke_quality(self.root, row, work, process, manifest)["success"])
        process["denied_commands"] = [BENCH.normalized_command(BENCH.shlex.join(command)) for command in outside]
        process["commands"] = [wrapped_inside]
        self.assertFalse(BENCH.smoke_quality(self.root, row, work, process, manifest)["success"])

    def test_finite_process_caps_output_and_kills_orphan_pipe_holder(self):
        logs = self.root / "logs"; logs.mkdir(mode=0o700)
        with mock.patch.dict(BENCH.LIMITS, {"stdout_bytes": 64, "line_bytes": 32, "term_grace_seconds": .1}):
            limited = BENCH.run_finite([sys.executable, "-c", "print('x'*100)"], "x", os.environ.copy(),
                                       logs / "one.jsonl", logs / "one.err", "codex", 2, self.root)
            self.assertIn(limited["stop_reason"], ("line_limit", "output_limit"))
            code = "import os,time; p=os.fork(); os._exit(0) if p else time.sleep(10)"
            start = time.monotonic()
            timed = BENCH.run_finite([sys.executable, "-c", code], "x", os.environ.copy(),
                                     logs / "two.jsonl", logs / "two.err", "codex", .1, self.root)
            ignore = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
            start_ignore = time.monotonic()
            ignored = BENCH.run_finite([sys.executable, "-c", ignore], "x", os.environ.copy(),
                                       logs / "three.jsonl", logs / "three.err", "codex", .4, self.root)
        self.assertEqual("timeout", timed["stop_reason"]); self.assertLess(time.monotonic() - start, 2)
        self.assertEqual("timeout", ignored["stop_reason"]); self.assertLess(time.monotonic() - start_ignore, .4)
        self.assertTrue(limited["process_started"] and limited["prompt_sent"])
        self.assertTrue(timed["process_started"] and timed["prompt_sent"])
        self.assertIsNone(BENCH.executable_window(10, 100)); self.assertIsNone(BENCH.executable_window(600, 10))
        self.assertIsNone(BENCH.executable_window(600, 610))
        self.assertEqual(600, BENCH.executable_window(600, 611))
        self.assertEqual(12, BENCH.executable_window(12, 100))

    def test_finite_launch_oserror_returns_completed_unproven_result(self):
        logs = self.root / "logs"; logs.mkdir(mode=0o700)
        with mock.patch.object(BENCH.subprocess, "Popen", side_effect=OSError("blocked")):
            value = BENCH.run_finite([sys.executable, "-c", "pass"], "x", os.environ.copy(),
                                     logs / "launch.jsonl", logs / "launch.err", "codex", 2, self.root)
        self.assertEqual("launch_error", value["stop_reason"])
        self.assertFalse(value["process_started"]); self.assertFalse(value["prompt_sent"])
        self.assertFalse(value["model_called"]); self.assertFalse(value["model_response_observed"])
        self.assertIsNone(value["sent_prompt_sha256"]); self.assertIsNone(value["sent_prompt_bytes"])
        self.assertEqual(hashlib.sha256(b"x").hexdigest(), value["materialized_prompt_sha256"])
        self.assertEqual(1, value["materialized_prompt_bytes"])
        self.assertEqual("OSError", value["launch_error"])
        self.assertGreaterEqual(value["elapsed_ms"], 0)
        self.assertEqual(0, value["stdout_bytes"]); self.assertEqual(0, value["stderr_bytes"])

    def test_run_one_setup_timeout_keeps_model_unproven(self):
        manifest = self.prepare()
        row = next(item for item in manifest["schedule"]
                   if item["kind"] == "smoke" and item["runtime"] == "codex")
        config = {"runtime_versions": {"codex": "codex-test"},
                  "models": {"codex": "model"}, "efforts": {"codex": "high"},
                  "requested_tiers": {"codex": None}, "fixture_tools": manifest["fixture_tools"],
                  "run_timeout_seconds": 10, "locked_at": "test"}
        with mock.patch.object(BENCH, "verify_runtime_binaries"), \
             mock.patch.object(BENCH, "verify_runtime_state"), \
             mock.patch.object(BENCH, "probe", return_value="codex-test"), \
             mock.patch.object(BENCH, "command_for", return_value=["/bin/true"]), \
             mock.patch.object(BENCH, "run_finite") as execute, \
             mock.patch.object(BENCH, "smoke_quality", return_value={"success": False}), \
             mock.patch.object(BENCH, "confirm_runtime_identity", return_value={"confirmed": False}), \
             mock.patch.object(BENCH, "metrics", return_value={}), \
             mock.patch.object(BENCH.time, "monotonic", side_effect=[10.0, 20.0, 20.0, 20.0]):
            self.assertTrue(BENCH.run_one(self.root, row, config, manifest, 10))
        execute.assert_not_called()
        value = BENCH.read_json(self.root / "results" / f"run-{row['run_id']}.json")
        self.assertTrue(value["completed"])
        self.assertFalse(value["model_called"]); self.assertFalse(value["model_response_observed"])
        self.assertIsNone(value["materialized_prompt_sha256"])
        self.assertEqual("timeout", value["process"]["stop_reason"])
        self.assertFalse(value["process"]["process_started"])
        self.assertFalse(value["process"]["prompt_sent"])

    def test_finite_model_response_requires_structured_event(self):
        logs = self.root / "logs"; logs.mkdir(mode=0o700)
        response = json.dumps({"type": "item.completed", "item": {"type": "agent_message",
                                                                        "text": "done"}})
        observed = BENCH.run_finite([sys.executable, "-c", f"print({response!r})"], "x", os.environ.copy(),
                                    logs / "response.jsonl", logs / "response.err", "codex", 10, self.root)
        self.assertTrue(observed["model_response_observed"])
        crash = BENCH.run_finite([sys.executable, "-c", "import json; print(json.dumps({'type':'turn.failed'}))"],
                                 "x", os.environ.copy(), logs / "crash.jsonl", logs / "crash.err", "codex", 10, self.root)
        self.assertFalse(crash["model_response_observed"])

    def test_resume_requires_exact_predecessor_identity_and_separate_workspace(self):
        manifest = self.prepare(); config = {"owner": BENCH.OWNER, "locked_at": "epoch"}
        resume = next(row for row in manifest["schedule"] if row.get("fixture") == "long_resume")
        compact = next(row for row in manifest["schedule"] if row.get("fixture") == "long_compact" and
                       all(row[key] == resume[key] for key in ("candidate", "runtime", "variant", "repeat")))
        bundle = manifest["comparison_bundles"][":".join((resume["candidate"], resume["runtime"], resume["variant"]))]
        BENCH.write_json(self.root / "results" / f"run-{compact['run_id']}.json", {"owner": BENCH.OWNER,
            "completed": True, "run": compact, "config_hash": BENCH.digest(config), "bundle": {"bundle_hash": bundle["bundle_hash"]},
            "status": "success", "process": {"session_id": "s1"}, "metrics": {"session_id": "s1"},
            "quality": {"native": True, "success": True}})
        self.assertEqual(("s1", None), BENCH.dependency(self.root, resume, config, manifest))
        value = BENCH.read_json(self.root / "results" / f"run-{compact['run_id']}.json")
        value["status"] = "quality_failure"; BENCH.write_json(self.root / "results" / f"run-{compact['run_id']}.json", value)
        self.assertEqual(("missing", None), BENCH.dependency(self.root, resume, config, manifest))
        work = BENCH.materialize(self.root, resume)
        self.assertFalse((work / "state.json").exists()); self.assertNotEqual(work.name, compact["run_id"])

    def test_completed_run_is_not_repeated_and_started_becomes_interruption(self):
        manifest = self.prepare(); row = next(item for item in manifest["schedule"] if item["kind"] == "compare")
        result = self.root / "results" / f"run-{row['run_id']}.json"
        BENCH.write_json(result, {"owner": BENCH.OWNER, "completed": True, "run": row})
        with mock.patch.object(BENCH, "run_finite") as execute:
            self.assertTrue(BENCH.run_one(self.root, row, {}, manifest, 1))
        execute.assert_not_called(); result.unlink()
        BENCH.write_json(self.root / "results" / f"started-{row['run_id']}.json",
                         {"owner": BENCH.OWNER, "run_id": row["run_id"]})
        self.assertTrue(BENCH.run_one(self.root, row, {}, manifest, 1))
        self.assertEqual("interruption", BENCH.read_json(result)["status"])
        claim = self.root / "results/started-atomic.json"; atomic_result = self.root / "results/run-atomic.json"
        self.assertEqual("claimed", BENCH.claim_run(claim, atomic_result, {"run_id": "atomic"}))
        self.assertEqual("active", BENCH.claim_run(claim, atomic_result, {"run_id": "atomic"}))

    def test_metric_qualification_uses_field_scope_and_accepts_zero_tools(self):
        metric = {"comparison_qualified": False,
                  "coverage": {"usage": {"qualified": True, "scope": "parent_claim"},
                               "tool_calls": {"qualified": True, "scope": "main", "expected": 0, "observed": 0},
                               "outcome": {"qualified": True, "scope": "main"},
                               "cost": {"qualified": True, "scope": "parent_claim"}}}
        self.assertTrue(BENCH.metric_ready(metric, "usage")); self.assertTrue(BENCH.metric_ready(metric, "tool_calls"))
        self.assertFalse(BENCH.metric_ready(metric, "cost"))
        for child_scope in ("no", "unknown"):
            metric["includes_children"] = child_scope
            metric["comparison_qualified"] = False
            metric["estimated_usd"] = .01
            metric["reference_usd"] = .02
            self.assertFalse(BENCH.metric_ready(metric, "cost"))
        metric["comparison_qualified"] = True
        metric["estimated_usd_with_subagents"] = .03
        self.assertTrue(BENCH.metric_ready(metric, "cost"))
        seen = {"hook_events": set(), "models": set(), "efforts": set(), "tiers": set(), "compact_events": 0,
                "session_id": None, "rejection": False, "turn_ids": set(), "output_tokens": 0, "terminal_status": None}
        BENCH.observe("claude", json.dumps({"type": "assistant", "message": {"id": "m1", "model": "claude-x",
                      "effort": "high", "usage": {"output_tokens": 3}}}), seen)
        self.assertEqual(({"claude-x"}, {"high"}, 3), (seen["models"], seen["efforts"], seen["output_tokens"]))
        before = seen["output_tokens"]
        reason = BENCH.observe("claude", json.dumps({"type": "result", "modelUsage": {
            "claude-x": {"outputTokens": BENCH.LIMITS["claude_output_tokens"] + 1}}}), seen)
        self.assertIsNone(reason); self.assertEqual(before, seen["output_tokens"])
        self.assertGreater(seen["session_output_tokens"], BENCH.LIMITS["claude_output_tokens"])
        self.assertEqual("output_usage_unknown", BENCH.usage_limit_reason("claude", {
            "usage_observed": False, "output_tokens": 0, "session_usage_observed": True,
            "session_output_tokens": BENCH.LIMITS["claude_output_tokens"] + 1}))
        self.assertEqual("output_usage_unknown", BENCH.usage_limit_reason("claude", {"output_tokens": 0}))

    def test_partial_report_uses_fixed_denominator_and_hides_median(self):
        manifest = self.prepare(); row = next(item for item in manifest["schedule"] if item["kind"] == "compare")
        coverage = {name: {"qualified": True, "scope": "main" if name in ("tool_calls", "outcome") else "parent_claim"}
                    for name in ("usage", "tool_calls", "outcome", "cost")}
        BENCH.write_json(self.root / "results" / f"run-{row['run_id']}.json", {"owner": BENCH.OWNER, "completed": True,
            "run": row, "status": "success", "quality": {"success": True}, "process": {"elapsed_seconds": 1.25,
                "runtime_identity": {"model": {"source": "locked_exact_argv", "confirmed": True},
                                     "effort": {"source": "locked_exact_argv", "confirmed": True}}},
            "metrics": {"comparison_qualified": True, "coverage": coverage, "tokens": {"input_total": 12},
                        "tool_calls": {"total": 0}, "estimated_usd_with_subagents": .01,
                        "pricing_version": manifest["pricing"]["version"], "currency": "USD"}})
        with contextlib.redirect_stdout(io.StringIO()): BENCH.report(argparse.Namespace(root=str(self.root)))
        group = BENCH.read_json(self.root / "results/report.json")["groups"][f"{row['candidate']}:{row['runtime']}:{row['variant']}"]
        self.assertEqual((1, 24, 1 / 24), (group["recorded_runs"], group["expected_runs"], group["coverage"]["usage"]["rate"]))
        self.assertFalse(group["complete"]); self.assertIsNone(group["input_tokens"]["median"])
        self.assertEqual(["locked_exact_argv"], group["runtime_identity_sources"]["model"])
        self.assertIsNone(group["total_cost_usd"]); self.assertIsNone(group["cost_per_run_usd"])
        report = BENCH.read_json(self.root / "results/report.json")
        self.assertEqual(3, report["fixture_summaries"][f"{row['candidate']}:{row['runtime']}:{row['fixture']}"]["expected_pairs"])
        task = report["task_groups"][f"{row['candidate']}:{row['runtime']}:{row['variant']}:repository"]
        self.assertEqual(9, task["expected_runs"]); self.assertIsNone(task["cost_per_success_usd"])
        same_group = [item for item in manifest["schedule"] if item.get("candidate") == row["candidate"] and
                      item["runtime"] == row["runtime"] and item.get("variant") == row["variant"]]
        for other in same_group:
            path = self.root / "results" / f"run-{other['run_id']}.json"
            if path.exists():
                continue
            BENCH.write_json(path, {"owner": BENCH.OWNER, "completed": True, "run": other,
                "status": "success", "quality": {"success": True}, "process": {"elapsed_seconds": 1},
                "metrics": {"comparison_qualified": True, "coverage": coverage,
                            "tokens": {"input_total": 1}, "tool_calls": {"total": 0},
                            "reference_usd": .02, "estimated_usd": .01,
                            "pricing_version": ("mixed-version" if other == same_group[-1]
                                                else manifest["pricing"]["version"]), "currency": "USD"}})
        with contextlib.redirect_stdout(io.StringIO()): BENCH.report(argparse.Namespace(root=str(self.root)))
        group = BENCH.read_json(self.root / "results/report.json")["groups"][f"{row['candidate']}:{row['runtime']}:{row['variant']}"]
        self.assertTrue(group["complete"])
        self.assertIsNone(group["total_cost_usd"])
        task = BENCH.read_json(self.root / "results/report.json")["task_groups"][
            f"{row['candidate']}:{row['runtime']}:{row['variant']}:repository"]
        self.assertIsNone(task["total_cost_usd"]); self.assertIsNone(task["cost_per_success_usd"])

    def test_child_nofile_limit_uses_parent_hard_cap(self):
        calls = []
        with mock.patch.object(BENCH.resource, "getrlimit", return_value=(64, 4096)), \
             mock.patch.object(BENCH.resource, "setrlimit",
                               side_effect=lambda resource_id, value: calls.append((resource_id, value))):
            BENCH.apply_child_limits(10)
        values = [value for resource_id, value in calls
                  if resource_id == BENCH.resource.RLIMIT_NOFILE]
        self.assertEqual([(1024, 1024)], values)
        calls.clear()
        with mock.patch.object(BENCH.resource, "getrlimit", return_value=(64, 64)), \
             mock.patch.object(BENCH.resource, "setrlimit",
                               side_effect=lambda resource_id, value: calls.append((resource_id, value))):
            BENCH.apply_child_limits(10)
        values = [value for resource_id, value in calls
                  if resource_id == BENCH.resource.RLIMIT_NOFILE]
        self.assertEqual([(64, 64)], values)

    def test_fresh_runtime_public_file_is_tightened_after_reap(self):
        base = self.root / "runtime/codex"
        base.mkdir(parents=True, mode=0o700)
        base.chmod(0o700)
        existing = base / "existing.log"
        existing.write_text("existing")
        existing.chmod(0o600)
        before = BENCH.runtime_private_snapshot(base)
        fresh = base / "fresh.log"
        fresh.write_text("fresh")
        fresh.chmod(0o644)
        result = BENCH.tighten_fresh_runtime_files(base, before, True)
        self.assertEqual(1, result["files_tightened"])
        self.assertEqual(0o600, stat.S_IMODE(fresh.stat().st_mode))
        self.assertEqual(before[existing], BENCH.runtime_private_snapshot(base)[existing])

    def test_budget_deadline_persists_across_invocations(self):
        (self.root / "results").mkdir(mode=0o700)
        first = BENCH.budget_deadline(self.root)
        with mock.patch.object(BENCH.time, "time", return_value=first + 1000):
            self.assertEqual(first, BENCH.budget_deadline(self.root))

    def test_host_parent_usage_contract_and_per_runtime_smoke_gate(self):
        model = "gpt-6.1-sol"

        def usage_case(runtime="codex", unknown=False, input_total=120, output_tokens=40):
            coverage = {"qualified": not unknown, "scope": "parent_claim",
                        "expected": 2, "observed": 2, "rate": 1,
                        "reasons": ["includes_children_unknown"] if unknown else []}
            metrics = {"model": model, "includes_children": "unknown" if unknown else "no",
                       "comparison_qualified": False,
                       "tokens": {"input_total": input_total, "output_tokens": output_tokens},
                       "coverage": {"usage": coverage}}
            record = {"owner": BENCH.OWNER, "schema": 1, "completed": True,
                      "run": {"run_id": f"usage-{runtime}", "kind": "smoke", "runtime": runtime},
                      "status": "success",
                      "process": {"runtime_identity": {
                          "model": {"confirmed": True, "value": model},
                          "effort": {"confirmed": True, "value": "medium"}}},
                      "metrics": metrics}
            return metrics, record

        strict_metrics, strict_record = usage_case(unknown=False)
        unknown_metrics, unknown_record = usage_case(unknown=True)
        self.assertTrue(BENCH.metric_ready(strict_metrics, "usage"))
        self.assertTrue(BENCH.host_parent_usage_ready(strict_metrics, strict_record))
        self.assertFalse(BENCH.metric_ready(unknown_metrics, "usage"))
        self.assertTrue(BENCH.host_parent_usage_ready(unknown_metrics, unknown_record))
        self.assertFalse(BENCH.metric_ready(unknown_metrics, "cost"))

        rejects = (
            ("runtime_missing", lambda value: value["record"]["run"].pop("runtime")),
            ("runtime_null", lambda value: value["record"]["run"].update(runtime=None)),
            ("runtime_not_codex", lambda value: value["record"]["run"].update(runtime="claude")),
            ("boolean_rate", lambda value: value["metrics"]["coverage"]["usage"].update(rate=True)),
            ("boolean_expected", lambda value: value["metrics"]["coverage"]["usage"].update(expected=True)),
            ("negative_input", lambda value: value["metrics"]["tokens"].update(input_total=-1)),
            ("negative_output", lambda value: value["metrics"]["tokens"].update(output_tokens=-1)),
            ("boolean_input", lambda value: value["metrics"]["tokens"].update(input_total=True)),
            ("boolean_output", lambda value: value["metrics"]["tokens"].update(output_tokens=True)),
            ("unknown_warning", lambda value: value["metrics"]["coverage"]["usage"].update(
                reasons=["includes_children_unknown", "unknown_warning"])),
            ("scope_mismatch", lambda value: value["metrics"]["coverage"]["usage"].update(scope="main")),
        )
        for name, mutate in rejects:
            with self.subTest(name=name):
                value = json.loads(json.dumps({"metrics": unknown_metrics, "record": unknown_record}))
                mutate(value)
                self.assertFalse(BENCH.host_parent_usage_ready(value["metrics"], value["record"]))

        smoke_root = self.root / "host-smoke"; smoke_root.mkdir(mode=0o700)
        results = smoke_root / "results"; results.mkdir(mode=0o700)

        def smoke(runtime, metrics):
            return {"owner": BENCH.OWNER, "schema": 1, "completed": True,
                    "run": {"run_id": f"smoke-{runtime}", "kind": "smoke", "runtime": runtime},
                    "status": "success", "quality": {"boundary_isolation": True},
                    "process": {"runtime_identity": {
                        "model": {"confirmed": True, "value": metrics["model"]},
                        "effort": {"confirmed": True, "value": "medium"}}},
                    "metrics": metrics}

        self.private_write(results / "run-smoke-codex.json", smoke("codex", unknown_metrics))
        self.private_write(results / "run-smoke-claude.json", smoke("claude", strict_metrics))
        self.assertEqual(["codex:usage_or_scope_unqualified"],
                         BENCH.comparison_blockers(smoke_root))
        self.assertEqual([], BENCH.comparison_blockers(smoke_root, allow_host_parent_usage=True))
        host_manifest = {"comparison_bundles": {
            f"I03:{runtime}:{variant}": {"evaluation_kind": "host-supervised-helper"}
            for runtime in ("codex", "claude") for variant in ("baseline", "candidate")}}
        self.assertEqual([], BENCH.host_subset_blockers(smoke_root, host_manifest, "I03"))

    def test_host_report_separates_strict_pairs_host_deltas_and_adoption_hold(self):
        schedule = [
            {"run_id": "I03-codex-baseline-repo_add-r1", "kind": "compare", "candidate": "I03",
             "runtime": "codex", "variant": "baseline", "fixture": "repo_add", "repeat": 1},
            {"run_id": "I03-codex-candidate-repo_add-r1", "kind": "compare", "candidate": "I03",
             "runtime": "codex", "variant": "candidate", "fixture": "repo_add", "repeat": 1},
            {"run_id": "I03-codex-baseline-cli_failure_reset-r1", "kind": "compare", "candidate": "I03",
             "runtime": "codex", "variant": "baseline", "fixture": "cli_failure_reset", "repeat": 1},
            {"run_id": "I03-codex-candidate-cli_failure_reset-r1", "kind": "compare", "candidate": "I03",
             "runtime": "codex", "variant": "candidate", "fixture": "cli_failure_reset", "repeat": 1},
            {"run_id": "I03-codex-baseline-long_compact-r1", "kind": "compare", "candidate": "I03",
             "runtime": "codex", "variant": "baseline", "fixture": "long_compact", "repeat": 1},
            {"run_id": "I03-codex-candidate-long_compact-r1", "kind": "compare", "candidate": "I03",
             "runtime": "codex", "variant": "candidate", "fixture": "long_compact", "repeat": 1},
        ]
        for variant in ("baseline", "candidate"):
            for fixture_id in ("repo_add", "cli_failure_reset", "long_compact"):
                schedule.append({"run_id": f"I03-claude-{variant}-{fixture_id}-r1", "kind": "compare",
                                 "candidate": "I03", "runtime": "claude", "variant": variant,
                                 "fixture": fixture_id, "repeat": 1})
        manifest = {"owner": BENCH.OWNER, "schema": 1, "plan": BENCH.PLAN,
                    "candidates": ["I03"], "schedule": schedule, "max_runs": len(schedule),
                    "pricing": {"version": "unit-test", "currency": "USD"},
                    "host_helper_plan": BENCH.HOST_PLAN}
        results = self.root / "results"; results.mkdir(mode=0o700)
        rows = [row for row in schedule if row.get("candidate") == "I03" and row["runtime"] == "codex" and
                row["fixture"] == "repo_add" and row["repeat"] == 1]
        self.assertEqual({"baseline", "candidate"}, {row["variant"] for row in rows})
        self.private_write(results / "manifest.json", manifest)
        quality = {name: True for name in ("success", "gate", "no_symlinks", "workspace_within_limit",
                                           "control_files_unchanged", "restore", "native", "runtime_effective")}

        for row in rows:
            input_total = 100 if row["variant"] == "baseline" else 80
            metrics = {"model": "gpt-6.1-sol", "includes_children": "unknown",
                       "comparison_qualified": False,
                       "tokens": {"input_total": input_total, "output_tokens": 40},
                       "coverage": {
                           "usage": {"qualified": False, "scope": "parent_claim", "expected": 2,
                                     "observed": 2, "rate": 1,
                                     "reasons": ["includes_children_unknown"]},
                           "tool_calls": {"qualified": True, "scope": "main"},
                           "outcome": {"qualified": True, "scope": "main"}},
                       "tool_calls": {"total": 1}}
            value = {"owner": BENCH.OWNER, "schema": 1, "completed": True, "run": row,
                     "status": "success", "quality": quality,
                     "process": {"elapsed_seconds": 1,
                                 "runtime_identity": {
                                     "model": {"confirmed": True, "value": "gpt-6.1-sol"},
                                     "effort": {"confirmed": True, "value": "medium"}}},
                     "metrics": metrics,
                     "host_helper": {"evidence": {
                         "helper_mechanism_observed": False,
                         "model_received_helper_result": True,
                         "task_outcome_passed": True}}}
            self.private_write(results / f"run-{row['run_id']}.json", value)

        with mock.patch.object(BENCH, "verify_tool_sources"):
            with contextlib.redirect_stdout(io.StringIO()):
                BENCH.report(argparse.Namespace(root=str(self.root)))
        report = BENCH.read_json(results / "report.json")
        pair = next(item for item in report["pairs"]
                    if item["pair_id"] == "I03:codex:repo_add:r1")
        self.assertTrue(pair["complete"])
        self.assertFalse(pair["paired_qualified"]["usage"])
        self.assertTrue(pair["host_paired_qualified"]["usage"])
        self.assertIsNone(pair["deltas"]["input_tokens"])
        self.assertEqual(-20, pair["host_deltas"]["input_tokens"])
        self.assertEqual("HOLD", report["selection_gate"]["host_subset"]["I03"]["state"])
        self.assertFalse(report["adoption_gate"]["I03:codex"]["eligible"])


if __name__ == "__main__":
    unittest.main()
