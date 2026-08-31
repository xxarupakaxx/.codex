from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "task_completion.py"
SPEC = importlib.util.spec_from_file_location("task_completion_test_module", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TaskCompletionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.task = self.workspace / ".local" / "memory" / "fixture"
        self.task.mkdir(parents=True)
        self.source = self.workspace / "src.py"
        self.source.write_text("print('fixture')\n", encoding="utf-8")
        self.plan = (
            "# Plan\n\n"
            "## Task 1: fixture\n\n"
            "acceptance: AC1\n"
            "required_sources: task:30_plan.md, task:40_progress.md, "
            "task:checkpoint.md, workspace:src.py\n\n"
            "#### purpose\nfixture\n\n"
            "#### targets\n- src.py\n\n"
            "#### implementation\n- [x] implement fixture\n\n"
            "#### outputs\n- output\n\n"
            "#### verification\n- test fixture\n"
        )
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        (self.task / "40_progress.md").write_text("進捗: 100%\n", encoding="utf-8")
        (self.task / "checkpoint.md").write_text("- [x] AC1: fixture passes\n", encoding="utf-8")
        (self.task / "90_verification.md").write_text(
            "AC1 fixture verification passed\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def model(self) -> dict[str, object]:
        parser_path = SCRIPT.with_name("roadmap_plan_contract.py")
        parser_spec = importlib.util.spec_from_file_location("plan_parser_test_module", parser_path)
        assert parser_spec and parser_spec.loader
        parser = importlib.util.module_from_spec(parser_spec)
        parser_spec.loader.exec_module(parser)
        return parser.parse_plan_files(self.task / "30_plan.md", self.task / "40_progress.md")

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def bundle(self, **overrides: object) -> dict[str, object]:
        model = self.model()
        payload: dict[str, object] = {
            "artifact_id": "eb-fixture",
            "source_hash": model["sourceHash"],
            "acceptance_evidence": ["AC1|PASS|source:task:90_verification.md#L1"],
            "tests": ["fixture-test"],
            "findings": [],
            "residual_risks": [],
            "writes_performed": ["src.py"],
            "safety_decision_id": "safe-fixture",
            "policy_source": "AGENTS.md",
            "lineage": ["fixture"],
            "journey_evidence": ["fixture journey"],
            "negative_path_evidence": ["fixture negative path"],
            "completion_state": "implemented",
            "source_fingerprints": {
                "task:30_plan.md": self.sha(self.task / "30_plan.md"),
                "task:40_progress.md": self.sha(self.task / "40_progress.md"),
                "task:checkpoint.md": self.sha(self.task / "checkpoint.md"),
                "workspace:src.py": self.sha(self.source),
            },
            "evidence_fingerprints": {
                "task:90_verification.md": self.sha(self.task / "90_verification.md")
            },
        }
        payload.update(overrides)
        return payload

    def write_bundle(self, payload: dict[str, object]) -> None:
        (self.task / "evidence-bundle.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def validate(self, payload: dict[str, object] | None = None) -> dict[str, object]:
        if payload is not None:
            self.write_bundle(payload)
        return MODULE.validate_phase5_completion(self.task, self.workspace, self.model())

    def assert_reason(self, reason: str, payload: dict[str, object] | None = None) -> None:
        with self.assertRaises(MODULE.CompletionValidationError) as context:
            self.validate(payload)
        self.assertEqual(context.exception.reason, reason)

    def test_valid_bundle_requires_each_raw_step_and_passes(self) -> None:
        result = self.validate(self.bundle())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["planned_acceptance_ids"], ["AC1"])
        self.assertEqual(result["source_fingerprints_checked"], 4)

    def test_html_completion_uses_typed_acceptance_and_sources_without_progress(self) -> None:
        parser_path = SCRIPT.with_name("roadmap_plan_contract.py")
        parser_spec = importlib.util.spec_from_file_location("html_plan_parser_test_module", parser_path)
        assert parser_spec and parser_spec.loader
        parser = importlib.util.module_from_spec(parser_spec)
        parser_spec.loader.exec_module(parser)
        html = (
            "<main id=\"plan-document\" data-plan-schema=\"2\"><h1>HTML</h1>"
            "<section data-task-id=\"1\"><h2>Task 1: HTML</h2>"
            "<section data-field=\"purpose\"><p>Purpose</p></section>"
            "<section data-field=\"targets\"><p>src.py</p></section>"
            "<section data-field=\"implementation\"><ul><li data-complete=\"true\">Step</li></ul></section>"
            "<section data-field=\"outputs\"><p>Output</p></section>"
            "<section data-field=\"verification\"><p>Verification</p></section>"
            "<ul data-field=\"acceptance\"><li data-acceptance-id=\"H1\">H1</li></ul>"
            "<ul data-field=\"required-sources\"><li data-source-ref=\"task:30_plan.html\"></li>"
            "<li data-source-ref=\"task:checkpoint.md\"></li><li data-source-ref=\"workspace:src.py\"></li></ul>"
            "</section></main>"
        )
        html_path = self.task / "30_plan.html"
        html_path.write_text(html, encoding="utf-8")
        (self.task / "30_plan.md").write_text("stale MD sibling", encoding="utf-8")
        (self.task / "checkpoint.md").write_text("- H1: passes\n", encoding="utf-8")
        model = parser.resolve_plan_source(self.task)
        payload = self.bundle(
            source_hash=model["sourceHash"],
            acceptance_evidence=["H1|PASS|source:task:90_verification.md#L1"],
            source_fingerprints={
                "task:30_plan.html": self.sha(html_path),
                "task:checkpoint.md": self.sha(self.task / "checkpoint.md"),
                "workspace:src.py": self.sha(self.source),
            },
        )
        result = self.validate_phase5_html(payload, model)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["planned_acceptance_ids"], ["H1"])
        self.assertEqual(result["source_fingerprints_checked"], 3)

    def validate_phase5_html(self, payload: dict[str, object], model: dict[str, object]) -> dict[str, object]:
        self.write_bundle(payload)
        return MODULE.validate_phase5_completion(self.task, self.workspace, model)

    def test_progress_override_cannot_complete_unchecked_raw_step(self) -> None:
        self.plan = self.plan.replace("- [x] implement fixture", "- [ ] implement fixture")
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        self.assert_reason("completion_plan_steps_incomplete", self.bundle())

    def test_missing_bundle_fails_closed(self) -> None:
        self.assert_reason("completion_evidence_missing")

    def test_task_and_checkpoint_ids_are_exact(self) -> None:
        self.plan = self.plan.replace("acceptance: AC1", "acceptance: AC01")
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        self.assert_reason("completion_acceptance_mismatch", self.bundle())

    def test_unknown_or_missing_evidence_id_fails(self) -> None:
        self.assert_reason(
            "completion_acceptance_mismatch",
            self.bundle(acceptance_evidence=["AC2|PASS|source:task:90_verification.md#L1"]),
        )

    def test_source_fingerprint_drift_fails(self) -> None:
        payload = self.bundle()
        self.source.write_text("changed\n", encoding="utf-8")
        self.assert_reason("completion_source_stale", payload)

    def test_source_manifest_must_match_plan_declaration(self) -> None:
        payload = self.bundle()
        source_fingerprints = dict(payload["source_fingerprints"])
        source_fingerprints["workspace:extra.py"] = "0" * 64
        payload["source_fingerprints"] = source_fingerprints
        self.assert_reason("completion_source_set_mismatch", payload)

    def test_unsafe_source_and_evidence_paths_are_rejected(self) -> None:
        self.plan = self.plan.replace("workspace:src.py", "workspace:../secret.txt")
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        self.assert_reason("completion_source_path_invalid", self.bundle())

    def test_source_manifest_rejects_self_reference(self) -> None:
        self.plan = self.plan.replace("workspace:src.py", "task:evidence-bundle.json")
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        payload = self.bundle()
        payload["source_fingerprints"] = {
            "task:30_plan.md": payload["source_fingerprints"]["task:30_plan.md"],
            "task:40_progress.md": payload["source_fingerprints"]["task:40_progress.md"],
            "task:checkpoint.md": payload["source_fingerprints"]["task:checkpoint.md"],
            "task:evidence-bundle.json": "0" * 64,
        }
        self.assert_reason("completion_self_reference_rejected", payload)

    def test_evidence_reference_rejects_path_traversal(self) -> None:
        self.assert_reason(
            "completion_source_path_invalid",
            self.bundle(acceptance_evidence=["AC1|PASS|source:task:../secret.md#L1"]),
        )

    def test_source_manifest_rejects_secret_path(self) -> None:
        secret = self.workspace / "secrets.txt"
        secret.write_text("private\n", encoding="utf-8")
        self.plan = self.plan.replace("workspace:src.py", "workspace:secrets.txt")
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        payload = self.bundle()
        payload["source_fingerprints"] = {
            "task:30_plan.md": payload["source_fingerprints"]["task:30_plan.md"],
            "task:40_progress.md": payload["source_fingerprints"]["task:40_progress.md"],
            "task:checkpoint.md": payload["source_fingerprints"]["task:checkpoint.md"],
            "workspace:secrets.txt": self.sha(secret),
        }
        self.assert_reason("completion_secret_path_rejected", payload)

    def test_source_manifest_rejects_uppercase_secret_suffix(self) -> None:
        self.plan = self.plan.replace("workspace:src.py", "workspace:artifact.PEM")
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        self.assert_reason("completion_secret_path_rejected", self.bundle())

    def test_source_manifest_rejects_symlink_escape(self) -> None:
        outside = self.workspace / "outside.py"
        outside.write_text("outside\n", encoding="utf-8")
        link = self.workspace / "link.py"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symlink unavailable: {exc}")
        self.plan = self.plan.replace("workspace:src.py", "workspace:link.py")
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        payload = self.bundle()
        payload["source_fingerprints"] = {
            "task:30_plan.md": payload["source_fingerprints"]["task:30_plan.md"],
            "task:40_progress.md": payload["source_fingerprints"]["task:40_progress.md"],
            "task:checkpoint.md": payload["source_fingerprints"]["task:checkpoint.md"],
            "workspace:link.py": self.sha(outside),
        }
        self.assert_reason("completion_source_symlink_rejected", payload)

    def test_evidence_reference_requires_current_fingerprint(self) -> None:
        payload = self.bundle(
            evidence_fingerprints={"task:90_verification.md": "0" * 64}
        )
        self.assert_reason("completion_evidence_stale", payload)

    def test_unresolved_findings_block_completion(self) -> None:
        self.assert_reason("completion_findings_unresolved", self.bundle(findings=["F1"]))

    def test_high_state_without_packet_is_not_inferred(self) -> None:
        self.assert_reason("completion_evidence_invalid", self.bundle(completion_state="effective"))

    def test_same_acceptance_id_can_be_planned_by_multiple_tasks(self) -> None:
        self.plan += (
            "\n## Task 2: follow-up\n\n"
            "acceptance: AC1\n\n"
            "#### purpose\nfollow-up\n\n"
            "#### targets\n- src.py\n\n"
            "#### implementation\n- [x] follow-up\n\n"
            "#### outputs\n- output\n\n"
            "#### verification\n- test follow-up\n"
        )
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        result = self.validate(self.bundle())
        self.assertEqual(result["planned_acceptance_ids"], ["AC1"])

    def test_same_evidence_file_can_prove_multiple_acceptance_ids(self) -> None:
        self.plan = self.plan.replace("acceptance: AC1", "acceptance: AC1, AC2")
        (self.task / "30_plan.md").write_text(self.plan, encoding="utf-8")
        (self.task / "checkpoint.md").write_text(
            "- [x] AC1: first\n- [x] AC2: second\n", encoding="utf-8"
        )
        payload = self.bundle(
            acceptance_evidence=[
                "AC1|PASS|source:task:90_verification.md#L1",
                "AC2|PASS|source:task:90_verification.md#L1",
            ]
        )
        result = self.validate(payload)
        self.assertEqual(result["evidence_fingerprints_checked"], 1)

    def test_checkpoint_acceptance_ids_use_the_plan_id_grammar(self) -> None:
        self.assertEqual(
            MODULE.extract_checkpoint_acceptance_ids("- [x] P1: passes\n"),
            ["P1"],
        )

    def test_plan_diagnostics_block_phase5(self) -> None:
        payload = self.bundle()
        self.write_bundle(payload)
        model = self.model()
        model["diagnostics"] = [{"code": "missing_required_section"}]
        with self.assertRaises(MODULE.CompletionValidationError) as context:
            MODULE.validate_phase5_completion(self.task, self.workspace, model)
        self.assertEqual(context.exception.reason, "completion_plan_diagnostics_present")

    def test_packet_owned_paths_bound_writes_and_target(self) -> None:
        packet = {
            "artifact_id": "wp-fixture", "source_hash": self.model()["sourceHash"],
            "objective": "fixture", "scope": ["src.py"], "out_of_scope": ["docs"],
            "owned_paths": ["src.py"], "acceptance_ids": ["AC1"], "constraints": [],
            "capability_class": "Fast", "safety_decision_id": "safe-fixture",
            "side_effects_requested": [], "external_write_targets": [],
            "approval_required": False, "approval_evidence": [], "dry_run_required": False,
            "baseline": ["fixture"], "reality_contract": ["fixture"],
            "verification": ["fixture"], "dependencies": ["none"],
            "handoff_requirements": ["fixture"], "reviewer_focus": ["fixture"],
            "journey_scenarios": ["fixture"], "negative_paths": ["fixture"],
            "completion_target": "implemented",
        }
        (self.task / "work-packet.json").write_text(
            json.dumps(packet), encoding="utf-8"
        )
        result = self.validate(self.bundle())
        self.assertEqual(result["completion_target"], "implemented")
        self.assert_reason(
            "completion_write_scope_invalid",
            self.bundle(writes_performed=["other.py"]),
        )

    def test_no_workspace_writes_sentinel_is_accepted(self) -> None:
        result = self.validate(
            self.bundle(writes_performed=[MODULE.NO_WORKSPACE_WRITES])
        )
        self.assertEqual(result["completion_target"], "implemented")

    def test_no_workspace_writes_sentinel_rejects_mixed_or_free_text(self) -> None:
        for writes in (
            [MODULE.NO_WORKSPACE_WRITES, "src.py"],
            ["N/A: no workspace write"],
        ):
            with self.subTest(writes=writes):
                self.assert_reason(
                    "completion_write_scope_invalid",
                    self.bundle(writes_performed=writes),
                )


if __name__ == "__main__":
    unittest.main()
