import argparse
import contextlib
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


SOURCE = Path.home() / ".codex/scripts/harness_benchmark.py"
SPEC = importlib.util.spec_from_file_location("harness_benchmark", SOURCE)
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


class HarnessBenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="harness-benchmark-test-", dir="/private/tmp"))
        self.bundle = Path(tempfile.mkdtemp(prefix="harness-comparison-test-", dir="/private/tmp"))
        self.capability = self.bundle / "capabilities.json"
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
                                  source_change_reason="unit-test", codex_bin=sys.executable, claude_bin=sys.executable)
        with contextlib.redirect_stdout(io.StringIO()): BENCH.prepare(args)
        return BENCH.read_json(self.root / "results/manifest.json")

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
        with mock.patch.dict(os.environ, {"HOME": str(Path.home()), "PATH": "/bin", "ANTHROPIC_API_KEY": "secret",
                                          "ANTHROPIC_PROFILE": "external"}, clear=True), \
             mock.patch.object(BENCH.os, "execve", side_effect=RuntimeError("captured")) as execute, \
             self.assertRaisesRegex(RuntimeError, "captured"):
            BENCH.login(argparse.Namespace(root=str(self.root), runtime="claude"))
        executable, argv, env = execute.call_args.args
        self.assertEqual(BENCH.runtime_argv(manifest["runtime_binaries"]["claude"])[0], executable)
        self.assertEqual(["auth", "login"], argv[-2:]); self.assertEqual(str(Path.home()), env["HOME"])
        self.assertNotIn("ANTHROPIC_API_KEY", env); self.assertNotIn("ANTHROPIC_PROFILE", env)

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
            BENCH.verify_runtime_binaries({"runtime_binaries": {"codex": row}, "fixture_tools": {}})
        manifest = {"runtime_binaries": {}, "fixture_tools": {"python_cli": {
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
        self.assertIsNone(BENCH.executable_window(10, 100)); self.assertIsNone(BENCH.executable_window(600, 10))
        self.assertIsNone(BENCH.executable_window(600, 610))
        self.assertEqual(600, BENCH.executable_window(600, 611))
        self.assertEqual(12, BENCH.executable_window(12, 100))

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

    def test_budget_deadline_persists_across_invocations(self):
        (self.root / "results").mkdir(mode=0o700)
        first = BENCH.budget_deadline(self.root)
        with mock.patch.object(BENCH.time, "time", return_value=first + 1000):
            self.assertEqual(first, BENCH.budget_deadline(self.root))


if __name__ == "__main__":
    unittest.main()
