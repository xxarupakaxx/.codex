import copy
import hashlib
import importlib.util
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

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_ROOT = Path.home() / ".claude"
MODULE = Path(os.environ.get("HARNESS_HELPER_SOURCE", REPO_ROOT / "scripts/harness_fixture_helper.py"))
SPEC = importlib.util.spec_from_file_location("harness_fixture_helper", MODULE)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# SOURCE_POLICY pins these files; they live in this repo and the sibling ~/.claude checkout.
SOURCES = {
    "python": Path(sys.executable).resolve(),
    "quiet_run": REPO_ROOT / "scripts/quiet-run.py",
    "handover_core": REPO_ROOT / "scripts/session_handover.py",
    "observations_core": CLAUDE_ROOT / "scripts/hook_observations.py",
}


def reviewed_typescript():
    # DEPENDENCY_POLICY pins exact node/tsc builds, so they are optional and overridable per machine.
    paths = {"node": Path(os.environ.get("HARNESS_NODE_BIN", "/opt/homebrew/Cellar/node/25.8.2/bin/node")),
             "tsc_js": Path(os.environ.get("HARNESS_TSC_JS", Path.home() / "ghq/github.com/THA-inc/arupaka-test-slack/"
                                           "node_modules/.pnpm/typescript@5.9.3/node_modules/typescript/lib/_tsc.js"))}
    for role, path in paths.items():
        if not path.is_file():
            return {}, f"{role} not found at {path}; set HARNESS_NODE_BIN and HARNESS_TSC_JS"
        if sha(path) != helper.DEPENDENCY_POLICY[role]:
            return {}, f"{role} at {path} does not match DEPENDENCY_POLICY; set HARNESS_NODE_BIN and HARNESS_TSC_JS"
    return paths, ""


TYPESCRIPT, TYPESCRIPT_SKIP_REASON = reviewed_typescript()
requires_typescript = unittest.skipUnless(TYPESCRIPT, TYPESCRIPT_SKIP_REASON)


@unittest.skipUnless(SOURCES["observations_core"].is_file(),
                     f"{SOURCES['observations_core']} is required by SOURCE_POLICY")
class HelperTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="host-helper-", dir="/private/tmp")
        self.root = Path(self.temp.name); os.chmod(self.root, 0o700)
        for name in ("work", "raw", "ledger", "fake-home", "exports"):
            (self.root / name).mkdir(mode=0o700)
        source_rows = {}
        for role, source in {**SOURCES, **TYPESCRIPT}.items():
            # Interpreters stay in place like supervise(); framework Pythons break when copied.
            target = source if role in {"python", "node"} else self.root / "exports" / role
            if target != source:
                shutil.copy2(source, target); os.chmod(target, 0o600)
            source_rows[role] = {"path": str(target), "sha256": sha(target), "role": role}
        self.binding = {"root": str(self.root), "run_id": "run-1", "nonce": "nonce-1",
                        "work_dir": str(self.root / "work"), "raw_dir": str(self.root / "raw"),
                        "ledger_dir": str(self.root / "ledger"),
                        "home_sha256": helper.digest(os.environ["HOME"].encode()),
                        "sources": source_rows}

    def tearDown(self):
        self.temp.cleanup()

    def request(self, candidate, fixture, strategy="improved", inputs=None):
        return {"owner": helper.REQUEST_OWNER, "schema": helper.SCHEMA, "candidate": candidate,
                "fixture": fixture, "strategy": strategy, "inputs": inputs or {},
                "limits": copy.deepcopy(helper.LIMITS)}

    def fresh(self, suffix):
        target = self.root / suffix; target.mkdir(mode=0o700)
        for name in ("work", "raw", "ledger"):
            (target / name).mkdir(mode=0o700)
        value = copy.deepcopy(self.binding); value.update({"root": str(target), "run_id": suffix,
            "work_dir": str(target / "work"), "raw_dir": str(target / "raw"),
            "ledger_dir": str(target / "ledger")})
        exports = target / "exports"; shutil.copytree(self.root / "exports", exports)
        for path in exports.iterdir():
            os.chmod(path, 0o600)
            value["sources"][path.name] = {"path": str(path), "sha256": sha(path), "role": path.name}
        return value

    def test_request_schema_and_single_factor_are_closed(self):
        request = self.request("I03", "cli_quiet_retrieve", inputs={"reason": "stale-index"})
        helper.validate_request(request)
        for mutation in ({"strategy": "candidate"}, {"score": 1}, {"limits": {}}):
            bad = copy.deepcopy(request); bad.update(mutation)
            with self.assertRaises(helper.HelperError): helper.validate_request(bad)

    def test_runner_request_changes_only_private_strategy(self):
        row = {"candidate": "I03", "variant": "baseline", "fixture": "repo_add"}
        spec = {"inputs": {}, "host_mechanism": True}
        baseline = helper.make_request(row, spec)
        candidate = helper.make_request({**row, "variant": "candidate"}, spec)
        changed = {key for key in baseline if baseline[key] != candidate[key]}
        self.assertEqual(changed, {"strategy"})
        self.assertEqual((baseline["strategy"], candidate["strategy"]), ("raw", "improved"))

    def test_bundle_contract_accepts_only_fixed_reviewed_roles(self):
        roles = {("host_fixture_helper", f"host/{name}"): {"sha256": value}
                 for name, value in helper.SOURCE_POLICY.items()}
        self.assertTrue(helper.host_bundle_mode(roles, copy.deepcopy(roles), []))
        self.assertFalse(helper.host_bundle_mode(roles, copy.deepcopy(roles), ["quiet_run"]))
        self.assertTrue(helper.bundle_file_allowed("host_fixture_helper", Path("host/quiet_run"),
                                                   helper.SOURCE_POLICY["quiet_run"], "fixed"))
        self.assertFalse(helper.bundle_file_allowed("host_fixture_helper", Path("host/unknown"),
                                                    "0" * 64, "fixed"))

    @requires_typescript
    def test_dependencies_are_exact_absolute_reviewed_files(self):
        rows = helper.validate_dependencies(TYPESCRIPT["node"], TYPESCRIPT["tsc_js"])
        self.assertEqual(set(rows), {"node", "tsc_js"})
        bad = self.root / "wrong-node"; bad.write_bytes(b"not node"); os.chmod(bad, 0o700)
        with self.assertRaisesRegex(helper.HelperError, "source_hash_mismatch"):
            helper.validate_dependencies(bad, TYPESCRIPT["tsc_js"])

    @requires_typescript
    def test_supervise_exports_tsc_to_private_run_root(self):
        base = self.root / "supervised"
        staged = {role: Path(self.binding["sources"][role]["path"])
                  for role in ("quiet_run", "handover_core", "observations_core")}
        dependencies = helper.validate_dependencies(TYPESCRIPT["node"], TYPESCRIPT["tsc_js"])
        python = self.binding["sources"]["python"]
        row = {"candidate": "I05", "variant": "candidate", "fixture": "repo_tsc_once", "run_id": "supervised-tsc"}
        result = helper.supervise(base, row, {"files": {"component.ts": "const value: = ;\n"}},
                                  staged, dependencies, python, self.binding["home_sha256"])
        exported = base / "dependencies/tsc.js"
        self.assertFalse(result["pair_stop"]); self.assertTrue(exported.is_file())
        self.assertTrue(helper._inside(exported, base)); self.assertEqual(helper.DEPENDENCY_POLICY["tsc_js"], sha(exported))

    def test_binding_rejects_hash_symlink_and_hardlink(self):
        for mode in ("hash", "symlink", "hardlink"):
            binding = self.fresh("bad-" + mode); source = Path(binding["sources"]["quiet_run"]["path"])
            if mode == "hash": binding["sources"]["quiet_run"]["sha256"] = "0" * 64
            elif mode == "symlink":
                original = source.with_suffix(".real"); source.rename(original); source.symlink_to(original)
            else:
                os.link(source, source.with_suffix(".hard"))
            with self.assertRaises(helper.HelperError): helper.validate_binding(binding)

    def test_binding_rejects_root_symlink_and_descriptor_self_hash(self):
        target = self.fresh("root-target")
        link = self.root / "root-link"; link.symlink_to(Path(target["root"]), target_is_directory=True)
        linked = copy.deepcopy(target); linked["root"] = str(link)
        with self.assertRaisesRegex(helper.HelperError, "binding_root_symlink"):
            helper.validate_binding(linked)
        wrong = self.fresh("wrong-policy"); source = Path(wrong["sources"]["quiet_run"]["path"])
        source.write_text("reviewed-looking but wrong"); source.chmod(0o600)
        wrong["sources"]["quiet_run"]["sha256"] = sha(source)
        with self.assertRaisesRegex(helper.HelperError, "source_hash_mismatch"):
            helper.validate_binding(wrong)

    def test_quiet_run_observes_one_source_and_one_retrieval(self):
        inputs = {"reason": "stale-index"}
        raw = helper.run(self.request("I03", "cli_quiet_retrieve", "raw", inputs), self.binding)
        improved = helper.run(self.request("I03", "cli_quiet_retrieve", "improved", inputs), self.fresh("quiet-improved"))
        self.assertFalse(raw["pair_stop"]); self.assertFalse(improved["pair_stop"])
        self.assertEqual(improved["result"]["payload"]["facts"], {"child_exit": 7,
            "diagnostic_present": True, "source_runs": 1, "retrieval_runs": 1})
        self.assertGreater(len(raw["result"]["payload"]["context"]), len(improved["result"]["payload"]["context"]))
        self.assertEqual(improved["evidence"]["operation_count"], 2)
        artifact = improved["evidence"]["artifacts"]["quiet_full_log"]
        self.assertEqual((artifact["source_runs"], artifact["retrieval_runs"], artifact["reruns"]), (1, 1, 0))
        self.assertEqual(64, len(artifact["sha256"])); self.assertGreater(artifact["bytes"], 16384)

    def test_handover_runs_real_core_and_invalidates_gate(self):
        state = {"schema_version": 1, "objective": "ship alpha", "next_acceptance": "unit passes",
                 "plan": {"path": "logical", "anchor": "improvement-plan", "version": "v13", "sha256": "0" * 64},
                 "dependencies": ["synthetic-docs"], "unanswered_questions": [],
                 "required_gates": [{"name": "unit", "status": "passed", "approval_ref": None,
                                      "evidence_refs": ["unit-suite"]}],
                 "evidence": [{"name": "unit-suite", "status": "passed", "command": "unit",
                                "result": "passed", "fingerprints": {"diff": "old", "dependencies": "same",
                                "execution": "same", "plan": "same", "failure": "same"}}],
                 "next_action": "verify evidence"}
        result = helper.run(self.request("I04", "long_explore", inputs={"state": state}), self.binding)
        facts = result["result"]["payload"]["facts"]
        self.assertFalse(result["pair_stop"])
        self.assertEqual((facts["init_runs"], facts["save_runs"], facts["load_runs"]), (1, 1, 1))
        self.assertEqual(facts["gate_status"], "needs_revalidation")
        self.assertNotIn(str(self.root), result["result"]["payload"]["context"])
        self.assertIn("logical", result["result"]["payload"]["context"])
        for source in self.binding["sources"].values():
            self.assertNotIn(source["path"], result["result"]["payload"]["context"])

    def test_handover_model_result_is_reproducible_across_roots(self):
        request = helper.make_request({"candidate": "I04", "variant": "candidate", "fixture": "long_explore"}, {})
        first = helper.run(request, self.binding)
        second = helper.run(request, self.fresh("same-i04"))
        self.assertEqual(first["result"], second["result"])
        self.assertNotIn(str(self.root), first["result"]["payload"]["context"])
        self.assertIn("canonical_artifact_sha256", first["evidence"]["artifacts"]["handover_private"])

    def test_handover_compacts_full_baseline_without_losing_required_facts(self):
        raw_request = helper.make_request({"candidate": "I04", "variant": "baseline", "fixture": "long_explore"}, {})
        improved_request = copy.deepcopy(raw_request); improved_request["strategy"] = "improved"
        raw = helper.run(raw_request, self.binding)
        improved = helper.run(improved_request, self.fresh("compact-i04"))
        raw_context = raw["result"]["payload"]["context"]
        compact_context = improved["result"]["payload"]["context"]
        self.assertLessEqual(len(compact_context), int(len(raw_context) * 0.9))
        for heading in ("## Task Log (05_log.md)", "## Plan (30_plan.md)",
                        "## Recent Conversation (last 30 entries)", "## Recovery Instructions"):
            self.assertIn(heading, raw_context)
        self.assertEqual([row["name"] for row in raw["evidence"]["operations"]],
                         ["baseline-handover-save", "baseline-handover-inject"])
        self.assertTrue(raw_context.startswith("=== SESSION HANDOVER (auto-injected after compaction) ==="))
        self.assertTrue(raw_context.endswith("=== END HANDOVER ===\n"))
        self.assertEqual(raw["result"]["payload"]["facts"]["baseline_save_runs"], 1)
        self.assertEqual(raw["result"]["payload"]["facts"]["baseline_inject_runs"], 1)
        compact = json.loads(compact_context)
        self.assertEqual(set(compact), {"schema_version", "objective", "next_acceptance", "plan", "dependencies",
                                        "unanswered_questions", "required_gate", "evidence", "next_action"})
        self.assertEqual(compact["required_gate"]["status"], "needs_revalidation")
        raw_semantics = helper._i04_semantics(helper._i04_expected_state(raw_request, helper.validate_binding(self.binding)),
                                              "passed")
        self.assertIn(helper.canonical(raw_semantics).decode(), raw_context)
        self.assertEqual({**raw_semantics, "required_gate": {**raw_semantics["required_gate"],
                         "status": "needs_revalidation"}}, compact)
        self.assertNotIn(str(self.root), compact_context)

    def test_handover_rejects_each_required_fact_class(self):
        base = {"schema_version": 1, "objective": "ship alpha", "next_acceptance": "unit passes",
                "plan": {"path": "logical", "anchor": "improvement-plan", "version": "v13", "sha256": "0" * 64},
                "dependencies": ["synthetic-docs"], "unanswered_questions": [],
                "required_gates": [{"name": "unit", "status": "passed", "approval_ref": None,
                                     "evidence_refs": ["unit-suite"]}],
                "evidence": [{"name": "unit-suite", "status": "passed", "command": "unit", "result": "passed",
                              "fingerprints": {"diff": "old", "dependencies": "same", "execution": "same",
                                               "plan": "same", "failure": "same"}}],
                "next_action": "verify evidence"}
        mutations = [("identity", lambda x: x["plan"].update(anchor="other")),
                     ("approval", lambda x: x["required_gates"][0].update(approval_ref="fake")),
                     ("verification", lambda x: x["evidence"][0].update(result="failed")),
                     ("dependencies", lambda x: x.update(dependencies=[])),
                     ("questions", lambda x: x.update(unanswered_questions=["unknown"])),
                     ("metadata", lambda x: x.update(schema_version=2))]
        for index, (label, mutate) in enumerate(mutations):
            state = copy.deepcopy(base); mutate(state)
            with self.subTest(label=label):
                result = helper.run(self.request("I04", "long_explore", inputs={"state": state}), self.fresh(f"i04-{index}"))
                self.assertTrue(result["pair_stop"])

    def test_failure_observer_counts_resets_without_false_stop(self):
        result = helper.run(self.request("I05", "cli_failure_reset", inputs={"failure_code": "tsc:component"}), self.binding)
        self.assertFalse(result["pair_stop"])
        self.assertEqual(result["result"]["payload"]["facts"], {"failure_events": 7, "notifications": 1,
            "success_resets": 1, "edit_resets": 1, "false_notifications": 0, "forced_stops": 0})
        self.assertEqual(result["evidence"]["operation_count"], 9)

    def test_failure_raw_counters_come_from_nine_child_records(self):
        result = helper.run(self.request("I05", "cli_failure_reset", "raw",
                                        {"failure_code": "tsc:component"}), self.binding)
        self.assertFalse(result["pair_stop"]); facts = result["result"]["payload"]["facts"]
        self.assertEqual((2, 1, 0, 0), (facts["notifications"], facts["false_notifications"],
                                       facts["success_resets"], facts["edit_resets"]))
        self.assertEqual(9, result["evidence"]["operation_count"])
        self.assertEqual(9, len(result["evidence"]["operations"]))

    @requires_typescript
    def test_typescript_shim_proves_two_runs_to_one_and_reuses_diagnostic(self):
        inputs = {"source": "const value: = ;\n"}
        raw = helper.run(self.request("I05", "repo_tsc_once", "raw", inputs), self.binding)
        improved = helper.run(self.request("I05", "repo_tsc_once", "improved", inputs), self.fresh("tsc-improved"))
        self.assertEqual(raw["result"]["payload"]["facts"]["tsc_runs"], 2)
        facts = improved["result"]["payload"]["facts"]
        self.assertEqual(facts["tsc_runs"], 1); self.assertTrue(facts["diagnostic_reused"])
        self.assertFalse(raw["result"]["payload"]["facts"]["diagnostic_reused"])
        self.assertEqual(facts["diagnostic_sha256"], raw["result"]["payload"]["facts"]["diagnostic_sha256"])
        evidence = improved["evidence"]["artifacts"]["typescript"]
        self.assertEqual(evidence["node_sha256"], helper.DEPENDENCY_POLICY["node"])
        self.assertEqual(evidence["tsc_sha256"], helper.DEPENDENCY_POLICY["tsc_js"])
        self.assertEqual(evidence["slots"], ["1"]); self.assertTrue(evidence["markers_complete"])
        self.assertEqual((evidence["start_count"], evidence["complete_count"]), (1, 1))
        self.assertEqual(len(evidence["actual_exit_codes"]), 1)
        self.assertEqual(evidence["raw_diagnostic_sha256"], [facts["diagnostic_sha256"]])

    @requires_typescript
    def test_process_counts_use_unique_observed_pids_only(self):
        inputs = {"source": "const value: = ;\n"}
        raw = helper.run(self.request("I05", "repo_tsc_once", "raw", inputs), self.binding)
        improved = helper.run(self.request("I05", "repo_tsc_once", "improved", inputs), self.fresh("pid-improved"))
        raw_counts = raw["evidence"]["metrics"]["processes"]
        improved_counts = improved["evidence"]["metrics"]["processes"]
        self.assertEqual((raw_counts["direct_observed"], raw_counts["mechanism_children_verified"],
                          raw_counts["total_verified"]), (2, 2, 4))
        self.assertEqual((improved_counts["direct_observed"], improved_counts["mechanism_children_verified"],
                          improved_counts["total_verified"]), (1, 2, 3))
        self.assertFalse(raw_counts["unverified_children_possible"])

    @requires_typescript
    def test_tsc_marker_binds_run_task_nonce_and_rejects_tamper(self):
        helper.run(self.request("I05", "repo_tsc_once", inputs={"source": "const value: = ;\n"}), self.binding)
        marker = self.root / "work/shim-markers/1.complete.json"
        value = json.loads(marker.read_text()); self.assertEqual(value["run_id"], "run-1")
        self.assertEqual(value["task_id"], "repo_tsc_once"); value["task_id"] = "other"
        marker.write_text(json.dumps(value)); marker.chmod(0o600)
        with self.assertRaisesRegex(helper.HelperError, "tsc_completion_invalid"):
            helper._shim_records(helper.validate_binding(self.binding), ("1",))

    @requires_typescript
    def test_tsc_marker_set_rejects_extra_file(self):
        helper.run(self.request("I05", "repo_tsc_once", inputs={"source": "const value: = ;\n"}), self.binding)
        extra = self.root / "work/shim-markers/extra"; extra.write_bytes(b""); extra.chmod(0o600)
        with self.assertRaisesRegex(helper.HelperError, "tsc_marker_set_invalid"):
            helper._shim_records(helper.validate_binding(self.binding), ("1",))

    @requires_typescript
    def test_tsc_completion_exit_must_join_parent_operation(self):
        result = helper.run(self.request("I05", "repo_tsc_once", "raw",
                                        {"source": "const value: = ;\n"}), self.binding)
        marker = self.root / "work/shim-markers/2.complete.json"
        value = json.loads(marker.read_text()); value["exit_code"] = 0 if value["exit_code"] else 1
        marker.write_text(json.dumps(value)); marker.chmod(0o600)
        clean = helper.validate_binding(self.binding)
        with self.assertRaisesRegex(helper.HelperError, "tsc_parent_exit_mismatch"):
            helper._calculate(self.request("I05", "repo_tsc_once", "raw",
                              {"source": "const value: = ;\n"}), clean,
                              result["result"]["payload"], result["evidence"]["operations"])

    def test_neutral_context_is_strategy_independent(self):
        raw = helper.run(self.request("I03", "repo_add", "raw"), self.binding)
        improved = helper.run(self.request("I03", "repo_add", "improved"), self.fresh("neutral"))
        self.assertEqual(raw["result"], improved["result"])
        self.assertEqual(raw["evidence"]["operation_count"], 0)

    def test_all_non_target_candidate_fixture_pairs_are_neutral_and_identical(self):
        fixtures = ("repo_add", "repo_normalize", "repo_tsc_once", "cli_quiet_retrieve",
                    "cli_failure_reset", "long_explore", "long_compact", "long_resume")
        for candidate in sorted(helper.FIXTURE_TARGETS):
            for fixture in fixtures:
                if fixture in helper.FIXTURE_TARGETS[candidate]:
                    continue
                with self.subTest(candidate=candidate, fixture=fixture):
                    row = {"candidate": candidate, "fixture": fixture, "variant": "baseline"}
                    raw_request = helper.make_request(row, {})
                    candidate_request = helper.make_request({**row, "variant": "candidate"}, {})
                    self.assertEqual(raw_request["inputs"], {})
                    self.assertEqual(candidate_request["inputs"], {})
                    raw = helper.run(raw_request, self.fresh(f"neutral-{candidate}-{fixture}-raw"))
                    improved = helper.run(candidate_request,
                                          self.fresh(f"neutral-{candidate}-{fixture}-improved"))
                    self.assertEqual(raw["result"], improved["result"])
                    self.assertEqual(raw["result"]["status"], "neutral")
                    self.assertEqual((raw["evidence"]["operation_count"],
                                      improved["evidence"]["operation_count"]), (0, 0))
                    self.assertFalse(raw["pair_stop"])
                    self.assertFalse(improved["pair_stop"])

    def test_operation_manifest_rejects_unknown_argv_before_launch(self):
        clean = helper.validate_binding(self.binding)
        allowed = [helper._op(clean, "true", ["/usr/bin/true"])]
        executor = helper.Executor(clean, allowed, time.monotonic() + 20)
        other = helper._op(clean, "false", ["/usr/bin/false"], allowed=(1,)); executor.allowed[0] = other
        with self.assertRaisesRegex(helper.HelperError, "operation_manifest_mismatch"):
            executor.run()
        self.assertEqual(list((self.root / "raw").iterdir()), [])

    def test_false_counter_claim_is_rejected_from_raw_ledger(self):
        original = helper._i03
        def false_claim(request, binding):
            payload, records, references = original(request, binding)
            payload["facts"]["source_runs"] = 999
            return payload, records, references
        with mock.patch.object(helper, "_i03", side_effect=false_claim):
            result = helper.run(self.request("I03", "cli_quiet_retrieve", "raw", {"reason": "stale-index"}), self.binding)
        self.assertTrue(result["pair_stop"])
        self.assertEqual(result["evidence"]["failure_reason"], "counter_claim_mismatch")

    def test_normal_exit_reaps_background_process_group(self):
        clean = helper.validate_binding(self.binding); pidfile = clean["work_dir"] / "child.pid"
        operation = helper._op(clean, "background", ["/bin/sh", "-c", f"sleep 30 & echo $! > {pidfile}"])
        result = helper.Executor(clean, [operation], time.monotonic() + 10).run()
        child = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError): os.kill(child, 0)
        self.assertEqual(result["record"]["direct_process_count"], 1)
        self.assertIn("cpu_user_seconds", result["record"])
        self.assertEqual(result["record"]["argv_sha256"], helper.digest(operation["argv"]))

    def test_operation_ledger_contains_complete_contract_and_actual_limits(self):
        clean = helper.validate_binding(self.binding)
        operation = helper._op(clean, "true", ["/usr/bin/true"])
        record = helper.Executor(clean, [operation], time.monotonic() + 10).run()["record"]
        contract = record["operation_contract"]
        self.assertEqual(operation["normalized_argv"], record["normalized_argv"])
        self.assertEqual([0], contract["allowed_exit"]); self.assertEqual(20, contract["timeout_seconds"])
        self.assertTrue(contract["readable"])
        self.assertTrue({"cpu_soft", "cpu_hard", "nofile", "nproc", "fsize"} <= set(contract["limits"]))
        self.assertEqual(record["launch_argv_sha256"], helper.digest(record["launch_argv"]))
        self.assertEqual(record["normalized_launch_argv_sha256"], helper.digest(record["normalized_launch_argv"]))
        self.assertEqual(64, len(record["sandbox_profile_sha256"]))
        self.assertNotIn(str(self.root), json.dumps(record["normalized_launch_argv"]))

    def test_sandbox_denies_home_open_and_write_without_reading_live_content(self):
        write_probe = Path.home() / f"harness-helper-write-probe-{self.binding['nonce']}"
        self.assertFalse(write_probe.exists())
        clean = helper.validate_binding(self.binding)
        probe = clean["work_dir"] / "deny-home.py"
        probe.write_text("import os\ntry:os.open(os.environ['HOME'],os.O_RDONLY)\nexcept PermissionError:raise SystemExit(0)\nraise SystemExit(9)\n"); probe.chmod(0o600)
        commands = [helper._op(clean, "open-home", [clean["sources"]["python"], probe]),
                    helper._op(clean, "write-home", ["/usr/bin/touch", write_probe], allowed=(1,)),
                    helper._op(clean, "write-work", ["/usr/bin/touch", clean["work_dir"] / "ok"])]
        try:
            executor = helper.Executor(clean, commands, time.monotonic() + 30)
            for _ in commands: executor.run()
        finally:
            write_probe.unlink(missing_ok=True)
        self.assertTrue((clean["work_dir"] / "ok").exists())

    def test_sandbox_profile_denies_network_and_private_tmp_by_default(self):
        profile = helper._profile(self.root / "work", tuple(), Path.home())
        self.assertIn("(deny network*)", profile)
        self.assertIn('(subpath "/private/tmp")', profile)
        self.assertIn(f'(subpath "{Path.home()}")', profile)

    def test_sandbox_mechanically_denies_local_socket(self):
        clean = helper.validate_binding(self.binding); probe = clean["work_dir"] / "network.py"
        probe.write_text("import socket\ns=socket.socket()\ntry:s.bind(('127.0.0.1',0))\nexcept PermissionError:raise SystemExit(0)\nraise SystemExit(9)\n")
        probe.chmod(0o600); operation = helper._op(clean, "network-probe", [clean["sources"]["python"], probe])
        result = helper.Executor(clean, [operation], time.monotonic() + 10).run()
        self.assertEqual(0, result["record"]["exit_code"])

    def test_environment_is_exact_and_drops_parent_credentials(self):
        with mock.patch.dict(os.environ, {"PATH": "/bad", "ANTHROPIC_API_KEY": "secret"}):
            env = helper._env(helper.validate_binding(self.binding))
        self.assertEqual(os.environ["HOME"], env["HOME"])
        self.assertEqual("/usr/bin:/bin:/usr/sbin:/sbin", env["PATH"])
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_operation_timeout_is_terminal_and_recorded(self):
        clean = helper.validate_binding(self.binding)
        operation = helper._op(clean, "sleep", ["/bin/sleep", "2"], timeout=.2)
        limits = copy.deepcopy(helper.LIMITS); limits["term_grace"] = .05
        with mock.patch.dict(helper.LIMITS, limits, clear=True):
            executor = helper.Executor(clean, [operation], time.monotonic() + 1)
            with self.assertRaises(helper.HelperError) as caught: executor.run()
        self.assertEqual("operation_failed", caught.exception.reason)
        self.assertEqual("timeout", caught.exception.records[0]["stop_reason"])

    def test_binding_requires_every_override_and_rejects_root_as_home(self):
        missing = copy.deepcopy(self.binding); missing.pop("raw_dir")
        with self.assertRaisesRegex(helper.HelperError, "binding_schema_invalid"):
            helper.validate_binding(missing)
        nested = copy.deepcopy(self.binding); nested["home_sha256"] = "0" * 64
        with self.assertRaisesRegex(helper.HelperError, "home_identity_invalid"):
            helper.validate_binding(nested)

    def test_output_claim_is_retry_zero(self):
        request = self.request("I03", "repo_add")
        first = helper.run(request, self.binding)
        self.assertFalse(first["pair_stop"])
        with self.assertRaisesRegex(helper.HelperError, "output_claim_failed"):
            helper.run(request, self.binding)

    def test_generated_limits_reject_too_many_files(self):
        for index in range(helper.LIMITS["files"] + 1):
            (self.root / "work" / f"f{index}").write_bytes(b"")
        with self.assertRaisesRegex(helper.HelperError, "generated"):
            helper._scan(self.root / "work")

    def test_terminal_scan_includes_claim_and_final_and_metrics(self):
        result = helper.run(self.request("I03", "repo_add"), self.binding)
        self.assertGreaterEqual(result["evidence"]["generated"]["files"], 2)
        self.assertEqual({"cpu_user_seconds", "cpu_system_seconds", "processes", "input_bytes",
                          "output_bytes", "raw_bytes", "process_groups_drained"}, set(result["evidence"]["metrics"]))
        self.assertEqual(result["evidence"]["metrics"]["processes"]["total_verified"], 0)

    def test_terminal_scan_failure_writes_matching_final_truth(self):
        with mock.patch.object(helper, "_scan", side_effect=helper.HelperError("generated_total_limit")):
            result = helper.run(self.request("I03", "repo_add"), self.binding)
        final = json.loads((self.root / "ledger/run-1.final.json").read_text())
        self.assertEqual("pre_model_failed", final["status"])
        self.assertEqual(result["result"]["content_hash"], final["result_hash"])
        self.assertEqual(result["evidence"]["result_hash"], final["result_hash"])

    def test_source_hash_failure_consumes_attempt_and_closes_final(self):
        source = self.root / "exports/quiet_run"; source.write_text("changed"); source.chmod(0o600)
        result = helper.run(self.request("I03", "cli_quiet_retrieve", inputs={"reason": "stale-index"}), self.binding)
        self.assertTrue(result["pair_stop"]); self.assertEqual("source_hash_mismatch", result["evidence"]["failure_reason"])
        final = json.loads((self.root / "ledger/run-1.final.json").read_text())
        self.assertEqual("pre_model_failed", final["status"])

    def test_unexpected_failure_is_terminal_and_not_model_visible(self):
        with mock.patch.object(helper, "_calculate", side_effect=RuntimeError("boom")):
            result = helper.run(self.request("I03", "repo_add"), self.binding)
        self.assertTrue(result["pair_stop"]); self.assertEqual("unexpected_helper_exception", result["evidence"]["failure_reason"])
        self.assertFalse(result["evidence"]["model_received_helper_result"])

    def test_failure_result_stops_pair_and_has_no_model_claim(self):
        result = helper.run(self.request("I03", "cli_quiet_retrieve", inputs={"reason": "other"}), self.binding)
        self.assertTrue(result["pair_stop"]); self.assertEqual(result["result"]["status"], "failed")
        self.assertFalse(result["evidence"]["model_received_helper_result"])
        final = json.loads((self.root / "ledger/run-1.final.json").read_text())
        self.assertEqual(final["status"], "pre_model_failed")

    def test_result_hides_strategy_and_self_reported_counters(self):
        result = helper.run(self.request("I03", "repo_add", "improved"), self.binding)["result"]
        self.assertEqual(set(result), {"owner", "schema", "candidate", "fixture", "status",
                                      "mechanism", "payload", "references", "content_hash"})
        self.assertNotIn("strategy", json.dumps(result)); self.assertEqual(result["content_hash"], helper.digest({k: v for k, v in result.items() if k != "content_hash"}))

    def test_reset_snapshot_tamper_is_rejected(self):
        request = self.request("I05", "cli_failure_reset", inputs={"failure_code": "tsc:component"})
        result = helper.run(request, self.binding)
        path = self.root / "work/reset-snapshots.json"; snapshots = json.loads(path.read_text())
        snapshots[0]["states"][0]["count"] = 99; path.write_text(json.dumps(snapshots)); path.chmod(0o600)
        with self.assertRaisesRegex(helper.HelperError, "failure_snapshot_invalid"):
            helper._calculate(request, helper.validate_binding(self.binding), result["result"]["payload"],
                              result["evidence"]["operations"])

    def test_launch_error_is_terminal_operation_record(self):
        clean = helper.validate_binding(self.binding)
        executor = helper.Executor(clean, [helper._op(clean, "launch", ["/usr/bin/true"])], time.monotonic() + 10)
        with mock.patch.object(helper.subprocess, "Popen", side_effect=OSError("synthetic")):
            with self.assertRaises(helper.HelperError) as caught: executor.run()
        self.assertEqual("operation_launch_failed", caught.exception.reason)
        self.assertEqual("launch_error", caught.exception.records[0]["stop_reason"])
        self.assertIsNone(caught.exception.records[0]["pid"])

    def test_subprocess_error_is_terminal_operation_record(self):
        clean = helper.validate_binding(self.binding)
        executor = helper.Executor(clean, [helper._op(clean, "launch", ["/usr/bin/true"])], time.monotonic() + 10)
        with mock.patch.object(helper.subprocess, "Popen", side_effect=subprocess.SubprocessError("synthetic")):
            with self.assertRaises(helper.HelperError) as caught: executor.run()
        record = caught.exception.records[0]
        self.assertEqual((record["stop_reason"], record["launch_error_type"]),
                         ("launch_error", "SubprocessError"))

    def test_baseline_conformance_has_repository_and_blob_provenance(self):
        self.assertTrue(helper.BASELINE_PROVENANCE["codex_commit"].startswith("51ee53e"))
        self.assertTrue(helper.BASELINE_PROVENANCE["claude_commit"].startswith("7152ca3"))
        self.assertEqual(helper.BASELINE_POLICY, helper.BASELINE_PROVENANCE["control_hashes"])
        roots = {"codex": REPO_ROOT, "claude": CLAUDE_ROOT}
        commits = {"codex": helper.BASELINE_PROVENANCE["codex_commit"],
                   "claude": helper.BASELINE_PROVENANCE["claude_commit"]}
        for fixture in helper.BASELINE_GOLDEN.values():
            for source in fixture["sources"]:
                repo, commit, path = roots[source["repo"]], commits[source["repo"]], source["path"]
                tree = subprocess.check_output(["/usr/bin/git", "-C", str(repo), "ls-tree", commit, "--", path], text=True)
                self.assertEqual(tree.split()[2], source["blob"])
                content = subprocess.check_output(["/usr/bin/git", "-C", str(repo), "show", f"{commit}:{path}"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), source["sha256"])
                if source["path"] == "hooks/stop-save-handover.sh":
                    self.assertEqual(content, helper.BASELINE_CONTROLS["stop_save"])
                if source["repo"] == "claude" and source["path"] == "hooks/session-start-inject.sh":
                    self.assertEqual(content, helper.BASELINE_CONTROLS["session_inject"])

    def test_baseline_behavior_tamper_is_rejected(self):
        request = self.request("I03", "cli_quiet_retrieve", "raw", {"reason": "stale-index"})
        with self.assertRaisesRegex(helper.HelperError, "baseline_conformance_mismatch"):
            helper._baseline_checked(request, {"child_exit": 7, "diagnostic_present": True,
                                               "source_runs": 2, "retrieval_runs": 0})


if __name__ == "__main__":
    unittest.main()
