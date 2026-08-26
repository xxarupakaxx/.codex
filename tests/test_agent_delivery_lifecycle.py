from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from agent_delivery_lifecycle import (  # noqa: E402
    delivery_draft_content_hash,
    next_action,
    route_delivery_draft,
    route_work_packet,
    validate_artifact,
    validate_delivery_draft_pair,
)


ZERO_FACTORS = {
    "ambiguity": 0,
    "blast_radius": 0,
    "dependency_coupling": 0,
    "verification_difficulty": 0,
    "failure_risk": 0,
    "context_volume": 0,
}
ALL_MODELS = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]


class RoutingTest(unittest.TestCase):
    def test_nontrivial_delivery_draft_routes_to_luna_without_tools(self) -> None:
        decision = route_delivery_draft(
            requires_summary=True,
            available_models=ALL_MODELS,
        )

        self.assertEqual(
            (decision.status, decision.handler, decision.model, decision.reasoning_effort),
            ("READY", "FAST_WORKER", "gpt-5.6-luna", "max"),
        )
        self.assertEqual(decision.allowed_tools, ())

    def test_unavailable_luna_returns_delivery_draft_to_lead(self) -> None:
        decision = route_delivery_draft(
            requires_summary=True,
            available_models=["gpt-5.6-terra"],
        )

        self.assertEqual((decision.status, decision.handler, decision.model), ("LEAD_REQUIRED", "LEAD", None))

    def test_deterministic_local_uses_no_model(self) -> None:
        decision = route_work_packet(ZERO_FACTORS, deterministic_local=True)
        self.assertEqual((decision.route_id, decision.capability_class), ("fast-track", "Local"))
        self.assertIsNone(decision.model)

    def test_low_risk_work_routes_to_luna(self) -> None:
        factors = {**ZERO_FACTORS, "ambiguity": 1, "verification_difficulty": 1}
        decision = route_work_packet(factors, available_models=ALL_MODELS)
        self.assertEqual((decision.route_id, decision.capability_class), ("fast-track", "Fast"))
        self.assertEqual((decision.model, decision.reasoning_effort), ("gpt-5.6-luna", "max"))

    def test_medium_work_routes_to_terra(self) -> None:
        factors = {**ZERO_FACTORS, "ambiguity": 2, "blast_radius": 2, "context_volume": 2}
        decision = route_work_packet(factors, available_models=ALL_MODELS)
        self.assertEqual((decision.route_id, decision.capability_class), ("prd-flow", "Standard"))
        self.assertEqual(decision.model, "gpt-5.6-terra")

    def test_large_work_routes_to_multi_packet_sol(self) -> None:
        factors = {axis: 2 for axis in ZERO_FACTORS}
        decision = route_work_packet(factors, work_packet_count=2, available_models=ALL_MODELS)
        self.assertEqual((decision.route_id, decision.capability_class), ("multi-packet-flow", "Heavy"))
        self.assertEqual(decision.model, "gpt-5.6-sol")

    def test_safety_trigger_forces_judgment(self) -> None:
        decision = route_work_packet(
            ZERO_FACTORS, safety_triggers=["external_write"], available_models=ALL_MODELS
        )
        self.assertEqual(decision.capability_class, "Judgment")
        self.assertEqual((decision.model, decision.reasoning_effort), ("gpt-5.6-sol", "max"))

    def test_unavailable_required_model_fails_closed(self) -> None:
        decision = route_work_packet(
            ZERO_FACTORS,
            safety_triggers=["billing_change"],
            available_models=["gpt-5.6-luna"],
        )
        self.assertEqual(decision.status, "ROUTING_BLOCKED")
        self.assertIsNone(decision.model)

    def test_unknown_axis_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            route_work_packet({**ZERO_FACTORS, "file_count": 2})

    def test_nonlocal_route_requires_runtime_roster(self) -> None:
        decision = route_work_packet({**ZERO_FACTORS, "ambiguity": 1})
        self.assertEqual(decision.status, "ROUTING_BLOCKED")
        self.assertIn("model_roster_missing", decision.reasons)

    def test_score_boundaries_are_stable(self) -> None:
        score_four = {**ZERO_FACTORS, "ambiguity": 1, "blast_radius": 1, "dependency_coupling": 1, "verification_difficulty": 1}
        score_five = {**score_four, "context_volume": 1}
        score_ten = {**ZERO_FACTORS, "blast_radius": 2, "dependency_coupling": 2, "verification_difficulty": 2, "context_volume": 2, "failure_risk": 2}
        score_eleven = {**score_ten, "ambiguity": 1}
        self.assertEqual(route_work_packet(score_four, available_models=ALL_MODELS).capability_class, "Fast")
        self.assertEqual(route_work_packet(score_five, available_models=ALL_MODELS).capability_class, "Standard")
        self.assertEqual(route_work_packet(score_ten, available_models=ALL_MODELS).capability_class, "Heavy")
        self.assertEqual(route_work_packet(score_eleven, available_models=ALL_MODELS).route_id, "prd-flow")
        self.assertEqual(
            route_work_packet(score_eleven, work_packet_count=2, available_models=ALL_MODELS).route_id,
            "multi-packet-flow",
        )

    def test_judgment_boundaries_and_invalid_inputs(self) -> None:
        for axis in ("ambiguity", "failure_risk"):
            decision = route_work_packet({**ZERO_FACTORS, axis: 3}, available_models=ALL_MODELS)
            self.assertEqual(decision.capability_class, "Judgment")
        with self.assertRaises(ValueError):
            route_work_packet(ZERO_FACTORS, work_packet_count=0)
        with self.assertRaises(ValueError):
            route_work_packet(ZERO_FACTORS, safety_triggers=["unknown"])


class ArtifactContractTest(unittest.TestCase):
    def test_delivery_draft_input_requires_bound_source_fields(self) -> None:
        errors = validate_artifact("delivery_draft_input", {"draft_id": "draft-1"})

        self.assertIn("missing required field: source_hash", errors)

    def test_delivery_draft_rejects_unknown_kind(self) -> None:
        payload = {
            "draft_id": "draft-1", "draft_kind": "push", "source_hash": "abc",
            "changed_paths": [], "evidence_bundle_id": "eb-1", "acceptance_ids": [],
            "test_ids": [], "residual_risk_ids": [], "template_sections": [],
            "policy_source": "AGENTS.md",
        }

        self.assertIn(
            "draft_kind must be commit or pull_request",
            validate_artifact("delivery_draft_input", payload),
        )

    def test_delivery_draft_output_rejects_unknown_status(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": ["A1"], "test_ids": ["T1"], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "APPROVED", "claim_references": ["A1", "T1"],
            "content": {"type": "feat", "subject": "配送契約を追加", "body": ""},
        }

        self.assertIn(
            "status must be DRAFT_READY or DRAFT_BLOCKED",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )

    def test_delivery_draft_rejects_claims_outside_bound_evidence(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": ["A1"], "test_ids": ["T1"],
            "residual_risk_ids": ["R1"], "template_sections": [],
            "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": ["A1", "T-fabricated"],
            "content": {"type": "feat", "subject": "配送契約を追加", "body": ""},
        }

        self.assertIn(
            "claim_references contain unbound evidence: T-fabricated",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )

    def test_delivery_draft_rejects_source_hash_drift(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "before",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "after",
            "status": "DRAFT_READY", "claim_references": [],
            "content": {"type": "fix", "subject": "差分を修正", "body": ""},
        }

        self.assertIn(
            "source_hash does not match draft input",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="before"),
        )

    def test_commit_draft_rejects_subject_over_seventy_characters(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": [], "evidence_bundle_id": "eb-1", "acceptance_ids": [],
            "test_ids": [], "residual_risk_ids": [], "template_sections": [],
            "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": [],
            "content": {"type": "feat", "subject": "あ" * 71, "body": ""},
        }

        self.assertIn(
            "commit subject must be 70 characters or fewer",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )

    def test_commit_draft_requires_japanese_subject(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": ["app.py"],
            "content": {"type": "feat", "subject": "add delivery adapter", "body": ""},
        }

        self.assertIn(
            "commit subject must include Japanese text",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )

    def test_pr_draft_requires_canonical_and_template_sections(self) -> None:
        draft_input = {
            "draft_id": "draft-2", "draft_kind": "pull_request", "source_hash": "abc",
            "changed_paths": [], "evidence_bundle_id": "eb-1", "acceptance_ids": [],
            "test_ids": [], "residual_risk_ids": [], "template_sections": ["security"],
            "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-2", "draft_kind": "pull_request", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": [],
            "content": {"title": "配送契約を追加", "sections": {"summary": "概要"}},
        }

        errors = validate_delivery_draft_pair(
            draft_input, output, expected_source_hash="abc"
        )

        self.assertIn("PR sections are missing: impact, out_of_scope, residual_risks, security, tests, trade_off, why", errors)

    def test_delivery_draft_cannot_request_tools_or_approval(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": [], "evidence_bundle_id": "eb-1", "acceptance_ids": [],
            "test_ids": [], "residual_risk_ids": [], "template_sections": [],
            "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": [], "tools": ["git"],
            "approval_state": "approved",
            "content": {"type": "feat", "subject": "配送契約を追加", "body": ""},
        }

        self.assertIn(
            "delivery draft contains privileged fields: approval_state, tools",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )

    def test_delivery_draft_rejects_nested_privileged_fields(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": ["app.py"],
            "content": {
                "type": "feat", "subject": "配送契約を追加", "body": "",
                "commands": ["git push"],
            },
        }

        self.assertIn(
            "delivery draft contains privileged fields: content.commands",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )

    def test_delivery_draft_rejects_non_string_claim_reference(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": [{"id": "app.py"}],
            "content": {"type": "feat", "subject": "配送契約を追加", "body": ""},
        }

        self.assertIn(
            "claim_references items must be strings",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )

    def test_delivery_draft_rejects_untrusted_source_hash(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "worker-hash",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "worker-hash",
            "status": "DRAFT_READY", "claim_references": ["app.py"],
            "content": {"type": "feat", "subject": "配送契約を追加", "body": ""},
        }

        self.assertIn(
            "source_hash does not match trusted snapshot",
            validate_delivery_draft_pair(
                draft_input, output, expected_source_hash="trusted-snapshot-hash"
            ),
        )

    def test_ready_draft_requires_claim_references(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": [],
            "content": {"type": "feat", "subject": "配送契約を追加", "body": ""},
        }

        self.assertIn(
            "claim_references are required for DRAFT_READY",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )

    def test_delivery_draft_rejects_unknown_content_fields_and_multiline_title(self) -> None:
        draft_input = {
            "draft_id": "draft-2", "draft_kind": "pull_request", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        sections = {name: "確認済み" for name in (
            "summary", "why", "trade_off", "out_of_scope", "impact", "tests",
            "residual_risks",
        )}
        output = {
            "draft_id": "draft-2", "draft_kind": "pull_request", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": ["app.py"],
            "content": {"title": "安全な題名\n--body", "sections": sections, "extra": "x"},
        }

        errors = validate_delivery_draft_pair(
            draft_input, output, expected_source_hash="abc"
        )

        self.assertIn("PR title must be a single line without control characters", errors)
        self.assertIn("PR content contains unknown fields: extra", errors)

    def test_delivery_draft_rejects_unknown_top_level_and_reserved_aliases(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": ["app.py"],
            "tool": "git", "whatever": "x",
            "content": {"type": "feat", "subject": "配送契約を追加", "body": ""},
        }

        errors = validate_delivery_draft_pair(
            draft_input, output, expected_source_hash="abc"
        )

        self.assertIn("delivery draft contains privileged fields: tool", errors)
        self.assertIn("delivery draft contains unknown fields: tool, whatever", errors)

    def test_ready_draft_requires_content_hash_bound_semantic_review(self) -> None:
        draft_input = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "changed_paths": ["app.py"], "evidence_bundle_id": "eb-1",
            "acceptance_ids": [], "test_ids": [], "residual_risk_ids": [],
            "template_sections": [], "policy_source": "AGENTS.md",
        }
        output = {
            "draft_id": "draft-1", "draft_kind": "commit", "source_hash": "abc",
            "status": "DRAFT_READY", "claim_references": ["app.py"],
            "content": {
                "type": "feat", "subject": "配送契約を追加",
                "body": "未検証のテストが通った",
            },
        }

        self.assertIn(
            "verified claim evidence is required for DRAFT_READY",
            validate_delivery_draft_pair(draft_input, output, expected_source_hash="abc"),
        )
        evidence = {
            "status": "pass",
            "source_hash": "abc",
            "content_hash": delivery_draft_content_hash(output),
            "claim_references": ["app.py"],
        }
        self.assertEqual(
            validate_delivery_draft_pair(
                draft_input,
                output,
                expected_source_hash="abc",
                verified_claim_evidence=evidence,
            ),
            [],
        )

    def test_approved_prd_requires_independent_pass(self) -> None:
        payload = {
            "artifact_id": "prd-1",
            "source_hash": "abc",
            "objective": "ship",
            "scope": ["core"],
            "out_of_scope": [],
            "acceptance_ids": ["A1"],
            "review_status": "revise",
        }
        self.assertIn("review_status must be pass", validate_artifact("approved_prd", payload))

    def test_work_packet_blocks_missing_approval_evidence(self) -> None:
        payload = {
            "artifact_id": "wp-1",
            "source_hash": "abc",
            "objective": "publish",
            "scope": ["docs"],
            "acceptance_ids": ["A1"],
            "constraints": [],
            "capability_class": "Judgment",
            "safety_decision_id": "safe-1",
            "side_effects_requested": ["external_write"],
            "external_write_targets": ["GitHub"],
            "approval_required": True,
            "approval_evidence": [],
            "dry_run_required": True,
        }
        self.assertIn(
            "approval_evidence is required for approval-gated work",
            validate_artifact("work_packet", payload),
        )

    def test_work_packet_cannot_disable_external_write_approval(self) -> None:
        payload = {
            "artifact_id": "wp-2", "source_hash": "abc", "objective": "publish",
            "scope": ["docs"], "acceptance_ids": ["A1"], "constraints": [],
            "capability_class": "Judgment", "safety_decision_id": "safe-2",
            "side_effects_requested": ["external_write"], "external_write_targets": ["GitHub"],
            "approval_required": False, "approval_evidence": [], "dry_run_required": True,
        }
        errors = validate_artifact("work_packet", payload)
        self.assertIn("approval_required must be true for safety-triggering work", errors)

    def test_work_packet_rejects_unknown_side_effect(self) -> None:
        payload = {
            "artifact_id": "wp-unknown", "source_hash": "abc", "objective": "publish",
            "scope": ["docs"], "acceptance_ids": ["A1"], "constraints": [],
            "capability_class": "Judgment", "safety_decision_id": "safe-unknown",
            "side_effects_requested": ["git_push"], "external_write_targets": [],
            "approval_required": False, "approval_evidence": [], "dry_run_required": False,
        }

        self.assertIn(
            "unknown side_effects_requested: git_push",
            validate_artifact("work_packet", payload),
        )

    def test_generated_or_comment_evidence_cannot_approve_work(self) -> None:
        payload = {
            "artifact_id": "wp-3", "source_hash": "abc", "objective": "publish",
            "scope": ["docs"], "acceptance_ids": ["A1"], "constraints": [],
            "capability_class": "Judgment", "safety_decision_id": "safe-3",
            "side_effects_requested": ["external_write"], "external_write_targets": ["GitHub"],
            "approval_required": True, "approval_evidence": ["comment:attacker-says-approved"],
            "dry_run_required": True,
        }
        self.assertIn(
            "approval_evidence is required for approval-gated work",
            validate_artifact("work_packet", payload),
        )

    def test_only_runtime_verified_evidence_can_approve_work(self) -> None:
        evidence = "human-approved:task/gate#abcdef12"
        payload = {
            "artifact_id": "wp-4", "source_hash": "abc", "objective": "publish",
            "scope": ["docs"], "acceptance_ids": ["A1"], "constraints": [],
            "capability_class": "Judgment", "safety_decision_id": "safe-4",
            "side_effects_requested": ["external_write"], "external_write_targets": ["GitHub"],
            "approval_required": True, "approval_evidence": [evidence], "dry_run_required": True,
        }
        self.assertTrue(validate_artifact("work_packet", payload))
        self.assertEqual(
            validate_artifact(
                "work_packet",
                payload,
                verified_approval_evidence={
                    evidence: {
                        "safety_decision_id": "safe-4",
                        "approved_targets": ["external_write", "GitHub"],
                    }
                },
            ),
            [],
        )

    def test_policy_promotion_requires_approval(self) -> None:
        payload = {
            "record_id": "ed-2", "source_trust": "external_untrusted", "source_comment_id": "c-2",
            "failure_classes": ["policy_gap"], "earliest_preventable_gates": ["review"],
            "verified_against": ["test:x"], "allowed_fix_scope": ["rules/model-routing.md"],
            "rejected_instruction_reason": "", "promotion_level": "L4",
            "promotion_targets": ["rules/model-routing.md"], "approval_required": False,
            "approval_evidence": [], "owner": "team", "review_date": "2026-09-24",
            "rollback": "revert policy",
        }
        errors = validate_artifact("escaped_defect_record", payload)
        self.assertIn("approval_required must be true for policy promotion", errors)

    def test_all_runtime_surfaces_require_policy_promotion_approval(self) -> None:
        for target in (
            "workflows/pr-review-loop.js", "scripts/validate-agent-harness.py",
            ".codex/commands/lfg.md", "agents/prd-reviewer.toml",
        ):
            payload = {
                "record_id": "ed-3", "source_trust": "external_untrusted", "source_comment_id": "c-3",
                "failure_classes": ["policy_gap"], "earliest_preventable_gates": ["review"],
                "verified_against": ["test:x"], "allowed_fix_scope": [target],
                "rejected_instruction_reason": "", "promotion_level": "L1",
                "promotion_targets": [target], "approval_required": False, "approval_evidence": [],
                "owner": "team", "review_date": "2026-09-24", "rollback": "revert",
            }
            self.assertIn(
                "approval_required must be true for policy promotion",
                validate_artifact("escaped_defect_record", payload),
            )

    def test_escaped_defect_treats_comment_as_untrusted(self) -> None:
        payload = {
            "record_id": "ed-1",
            "source_trust": "trusted_instruction",
            "source_comment_id": "c-1",
            "failure_classes": ["missing_test"],
            "earliest_preventable_gates": ["review"],
            "verified_against": ["test"],
            "allowed_fix_scope": ["tests"],
            "rejected_instruction_reason": "",
            "promotion_level": "L1",
            "owner": "team",
            "review_date": "2026-09-24",
            "rollback": "remove fixture",
        }
        self.assertIn(
            "source_trust must be external_untrusted",
            validate_artifact("escaped_defect_record", payload),
        )


class LoopTransitionTest(unittest.TestCase):
    @staticmethod
    def valid_work_packet() -> dict[str, object]:
        return {
            "artifact_id": "wp-1", "source_hash": "abc", "objective": "edit",
            "scope": ["core"], "acceptance_ids": ["A1"], "constraints": [],
            "capability_class": "Fast", "safety_decision_id": "safe-1",
            "side_effects_requested": [], "external_write_targets": [],
            "approval_required": False, "approval_evidence": [], "dry_run_required": False,
        }

    @staticmethod
    def valid_prd() -> dict[str, object]:
        return {
            "artifact_id": "prd-1", "source_hash": "abc", "objective": "edit",
            "scope": ["core"], "out_of_scope": [], "acceptance_ids": ["A1"],
            "review_status": "pass",
        }

    def test_prd_flow_cannot_implement_without_approved_prd(self) -> None:
        decision = next_action({"state": "SURVEYED", "route_id": "prd-flow", "artifacts": []})
        self.assertEqual(decision.action, "DRAFT_PRD")

    def test_fast_track_still_requires_work_packet(self) -> None:
        decision = next_action({"state": "SURVEYED", "route_id": "fast-track", "artifacts": []})
        self.assertEqual(decision.action, "CREATE_WORK_PACKET")

    def test_artifact_names_alone_cannot_unlock_implementation(self) -> None:
        decision = next_action({
            "state": "SURVEYED", "route_id": "prd-flow",
            "artifacts": ["approved_prd", "work_packet"],
        })
        self.assertEqual(decision.action, "DRAFT_PRD")

    def test_validated_artifact_payloads_unlock_implementation(self) -> None:
        decision = next_action({
            "state": "SURVEYED", "route_id": "prd-flow",
            "artifact_payloads": {
                "approved_prd": self.valid_prd(), "work_packet": self.valid_work_packet(),
            },
        })
        self.assertEqual(decision.action, "IMPLEMENT")

    def test_safety_change_waits_for_human(self) -> None:
        decision = next_action({"state": "SURVEYED", "safety_trigger": True, "approval_state": "pending"})
        self.assertEqual(decision.status, "WAITING_HUMAN")

    def test_safety_trigger_array_and_external_targets_wait_for_evidence(self) -> None:
        for extra in (
            {"safety_triggers": ["external_write"]},
            {"external_write_targets": ["GitHub"]},
        ):
            decision = next_action({"state": "SURVEYED", "approval_state": "approved", **extra})
            self.assertEqual(decision.status, "WAITING_HUMAN")

    def test_unknown_requested_side_effect_fails_closed(self) -> None:
        decision = next_action(
            {
                "state": "SURVEYED",
                "approval_state": "approved",
                "side_effects_requested": ["git_push"],
            }
        )

        self.assertEqual(decision.status, "WAITING_HUMAN")

    def test_runtime_verified_evidence_unlocks_safety_transition(self) -> None:
        evidence = "user-validation:task/gate#abcdef12"
        decision = next_action(
            {
                "state": "SURVEYED", "route_id": "fast-track",
                "safety_triggers": ["external_write"], "approval_state": "approved",
                "approval_evidence": [evidence],
                "safety_decision_id": "safe-1",
                "artifact_payloads": {"work_packet": self.valid_work_packet()},
            },
            verified_approval_evidence={
                evidence: {
                    "safety_decision_id": "safe-1",
                    "approved_targets": ["external_write"],
                }
            },
        )
        self.assertEqual(decision.action, "IMPLEMENT")

    def test_review_findings_loop_back_to_fix(self) -> None:
        decision = next_action({"state": "REVIEWED", "high_findings": 2})
        self.assertEqual(decision.action, "FIX")

    def test_retry_limit_stops_loop(self) -> None:
        decision = next_action({"state": "REVIEWED", "retry_count": 3, "max_retries": 3})
        self.assertEqual(decision.status, "WAITING_HUMAN")

    def test_escaped_defect_enters_learning_loop(self) -> None:
        decision = next_action({"state": "DELIVERED", "escaped_defects": ["ed-1"]})
        self.assertEqual(decision.action, "RECORD_ESCAPED_DEFECT")

    def test_failed_replay_does_not_auto_promote(self) -> None:
        decision = next_action({"state": "REPLAYED", "replay_passed": False})
        self.assertEqual(decision.status, "WAITING_HUMAN")

    def test_policy_replay_waits_for_separate_promotion_approval(self) -> None:
        decision = next_action({
            "state": "REPLAYED", "replay_passed": True, "promotion_level": "L4",
            "promotion_targets": ["rules/model-routing.md"], "approval_state": "pending",
            "approval_evidence": [],
        })
        self.assertEqual(decision.status, "WAITING_HUMAN")


if __name__ == "__main__":
    unittest.main()
