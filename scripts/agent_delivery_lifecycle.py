#!/usr/bin/env python3
"""Deterministic contracts for the agent delivery lifecycle and its bounded loop."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


AXES = (
    "ambiguity",
    "blast_radius",
    "dependency_coupling",
    "verification_difficulty",
    "failure_risk",
    "context_volume",
)
MODEL_ROSTER = {
    "Fast": ("gpt-5.6-luna", "max"),
    "Standard": ("gpt-5.6-terra", "high"),
    "Heavy": ("gpt-5.6-sol", "high"),
    "Judgment": ("gpt-5.6-sol", "max"),
}
SAFETY_TRIGGERS = {
    "external_write",
    "permission_change",
    "billing_change",
    "authentication_change",
    "destructive_action",
    "runtime_policy_change",
    "go_nogo_decision",
}
ARTIFACT_REQUIRED_FIELDS = {
    "approved_prd": (
        "artifact_id",
        "source_hash",
        "objective",
        "scope",
        "out_of_scope",
        "acceptance_ids",
        "review_status",
    ),
    "work_packet": (
        "artifact_id",
        "source_hash",
        "objective",
        "scope",
        "acceptance_ids",
        "constraints",
        "capability_class",
        "safety_decision_id",
        "side_effects_requested",
        "external_write_targets",
        "approval_required",
        "approval_evidence",
        "dry_run_required",
    ),
    "evidence_bundle": (
        "artifact_id",
        "source_hash",
        "acceptance_evidence",
        "tests",
        "findings",
        "residual_risks",
        "writes_performed",
        "safety_decision_id",
        "policy_source",
    ),
    "escaped_defect_record": (
        "record_id",
        "source_trust",
        "source_comment_id",
        "failure_classes",
        "earliest_preventable_gates",
        "verified_against",
        "allowed_fix_scope",
        "rejected_instruction_reason",
        "promotion_level",
        "promotion_targets",
        "approval_required",
        "approval_evidence",
        "owner",
        "review_date",
        "rollback",
        "safety_decision_id",
    ),
}
LIST_FIELDS = {
    "scope",
    "out_of_scope",
    "acceptance_ids",
    "constraints",
    "side_effects_requested",
    "external_write_targets",
    "approval_evidence",
    "acceptance_evidence",
    "tests",
    "findings",
    "residual_risks",
    "writes_performed",
    "failure_classes",
    "earliest_preventable_gates",
    "verified_against",
    "allowed_fix_scope",
    "promotion_targets",
}

POLICY_PROMOTION_PREFIXES = (
    "AGENTS.md", "agents/", "commands/", "context/", "hooks/", "ci/", "prompts/",
    "rules/", "scheduled-tasks/", "scripts/", "skills/", "workflows/",
)
APPROVAL_EVIDENCE = re.compile(
    r"^(?:human-approved|user-validation):[A-Za-z0-9._/-]+#[a-f0-9]{8,64}$"
)


@dataclass(frozen=True)
class RoutingDecision:
    status: str
    route_id: str
    capability_class: str
    model: str | None
    reasoning_effort: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TransitionDecision:
    status: str
    action: str
    reason: str


def _axis_values(factors: Mapping[str, Any]) -> dict[str, int]:
    unknown = sorted(set(factors) - set(AXES))
    if unknown:
        raise ValueError(f"unknown routing axes: {', '.join(unknown)}")
    values: dict[str, int] = {}
    for axis in AXES:
        value = factors.get(axis, 0)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
            raise ValueError(f"{axis} must be an integer from 0 to 3")
        values[axis] = value
    return values


def route_work_packet(
    factors: Mapping[str, Any],
    *,
    safety_triggers: Sequence[str] = (),
    deterministic_local: bool = False,
    work_packet_count: int = 1,
    available_models: Sequence[str] | None = None,
) -> RoutingDecision:
    values = _axis_values(factors)
    invalid_triggers = sorted(set(safety_triggers) - SAFETY_TRIGGERS)
    if invalid_triggers:
        raise ValueError(f"unknown safety triggers: {', '.join(invalid_triggers)}")
    if work_packet_count < 1:
        raise ValueError("work_packet_count must be positive")

    score = sum(values.values())
    peak = max(values.values())
    if safety_triggers:
        capability = "Judgment"
        reasons = ("safety_trigger", *sorted(set(safety_triggers)))
    elif values["ambiguity"] == 3 or values["failure_risk"] == 3:
        capability = "Judgment"
        reasons = ("forced_judgment",)
    elif deterministic_local and score == 0:
        capability = "Local"
        reasons = ("deterministic_local",)
    elif score <= 4 and peak <= 1:
        capability = "Fast"
        reasons = ("low_complexity",)
    elif score <= 9:
        capability = "Standard"
        reasons = ("bounded_complexity",)
    else:
        capability = "Heavy"
        reasons = ("high_complexity",)

    if work_packet_count > 1:
        route_id = "multi-packet-flow"
    elif capability in {"Local", "Fast"} and not safety_triggers:
        route_id = "fast-track"
    else:
        route_id = "prd-flow"

    if capability == "Local":
        return RoutingDecision("READY", route_id, capability, None, None, reasons)

    model, effort = MODEL_ROSTER[capability]
    if available_models is None:
        return RoutingDecision(
            "ROUTING_BLOCKED",
            route_id,
            capability,
            None,
            None,
            (*reasons, "model_roster_missing"),
        )
    if model not in available_models:
        return RoutingDecision(
            "ROUTING_BLOCKED",
            route_id,
            capability,
            None,
            None,
            (*reasons, f"model_unavailable:{model}"),
        )
    return RoutingDecision("READY", route_id, capability, model, effort, reasons)


def validate_artifact(
    kind: str,
    payload: Mapping[str, Any],
    *,
    verified_approval_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    required = ARTIFACT_REQUIRED_FIELDS.get(kind)
    if required is None:
        return [f"unknown artifact kind: {kind}"]
    errors = [f"missing required field: {field}" for field in required if field not in payload]
    for field in LIST_FIELDS.intersection(payload):
        if not isinstance(payload[field], list):
            errors.append(f"{field} must be a list")
    if kind == "approved_prd" and payload.get("review_status") != "pass":
        errors.append("review_status must be pass")
    if kind == "escaped_defect_record":
        if payload.get("source_trust") != "external_untrusted":
            errors.append("source_trust must be external_untrusted")
        if payload.get("promotion_level") not in {"L0", "L1", "L2", "L3", "L4"}:
            errors.append("promotion_level must be L0 through L4")
        targets = payload.get("promotion_targets", [])
        policy_promotion = payload.get("promotion_level") in {"L3", "L4"} or (
            isinstance(targets, list) and any(_is_policy_target(target) for target in targets)
        )
        if policy_promotion and payload.get("approval_required") is not True:
            errors.append("approval_required must be true for policy promotion")
        if policy_promotion and not _verified_approval_evidence(
            payload.get("approval_evidence"),
            verified_approval_evidence,
            safety_decision_id=payload.get("safety_decision_id"),
            targets=targets if isinstance(targets, list) else [],
        ):
            errors.append("approval_evidence is required for policy promotion")
    if kind == "work_packet":
        side_effects = payload.get("side_effects_requested", [])
        external_targets = payload.get("external_write_targets", [])
        side_effects = side_effects if isinstance(side_effects, list) else []
        external_targets = external_targets if isinstance(external_targets, list) else []
        requires_approval = bool(external_targets) or any(
            trigger in SAFETY_TRIGGERS for trigger in side_effects if isinstance(side_effects, list)
        )
        if requires_approval and payload.get("approval_required") is not True:
            errors.append("approval_required must be true for safety-triggering work")
        if (payload.get("approval_required") or requires_approval) and not _verified_approval_evidence(
            payload.get("approval_evidence"),
            verified_approval_evidence,
            safety_decision_id=payload.get("safety_decision_id"),
            targets=[
                *external_targets,
                *(item for item in side_effects if item in SAFETY_TRIGGERS),
            ],
        ):
            errors.append("approval_evidence is required for approval-gated work")
    return errors


def _validated_artifact(
    snapshot: Mapping[str, Any],
    kind: str,
    verified_approval_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool:
    payloads = snapshot.get("artifact_payloads", {})
    if not isinstance(payloads, Mapping):
        return False
    payload = payloads.get(kind)
    return isinstance(payload, Mapping) and not validate_artifact(
        kind, payload, verified_approval_evidence=verified_approval_evidence
    )


def _valid_approval_evidence(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and APPROVAL_EVIDENCE.fullmatch(item) for item in value
    )


def _verified_approval_evidence(
    value: Any,
    verified: Mapping[str, Mapping[str, Any]] | None,
    *,
    safety_decision_id: Any,
    targets: Sequence[Any],
) -> bool:
    if not _valid_approval_evidence(value):
        return False
    if not isinstance(verified, Mapping) or not isinstance(safety_decision_id, str):
        return False
    required_targets = {item for item in targets if isinstance(item, str)}
    for evidence_id in value:
        record = verified.get(evidence_id)
        if not isinstance(record, Mapping):
            return False
        if record.get("safety_decision_id") != safety_decision_id:
            return False
        approved_targets = record.get("approved_targets")
        if not isinstance(approved_targets, list) or not required_targets.issubset(approved_targets):
            return False
    return True


def _is_policy_target(target: Any) -> bool:
    if not isinstance(target, str):
        return False
    normalized = target.removeprefix(".codex/")
    return normalized.startswith(POLICY_PROMOTION_PREFIXES)


def next_action(
    snapshot: Mapping[str, Any],
    *,
    verified_approval_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> TransitionDecision:
    state = str(snapshot.get("state", "RECEIVED"))
    route_id = str(snapshot.get("route_id", "prd-flow"))
    if snapshot.get("routing_status") == "ROUTING_BLOCKED":
        return TransitionDecision("ROUTING_BLOCKED", "STOP", "required model is unavailable")
    raw_triggers = snapshot.get("safety_triggers", [])
    safety_triggers = set(raw_triggers) if isinstance(raw_triggers, list) else set()
    raw_side_effects = snapshot.get("side_effects_requested", [])
    if isinstance(raw_side_effects, list):
        safety_triggers.update(item for item in raw_side_effects if item in SAFETY_TRIGGERS)
    external_targets = snapshot.get("external_write_targets", [])
    external_targets = external_targets if isinstance(external_targets, list) else []
    approval_gated = bool(snapshot.get("safety_trigger")) or bool(safety_triggers) or bool(external_targets)
    approval_targets = [*external_targets, *safety_triggers]
    if approval_gated and (
        snapshot.get("approval_state") != "approved"
        or not _verified_approval_evidence(
            snapshot.get("approval_evidence"),
            verified_approval_evidence,
            safety_decision_id=snapshot.get("safety_decision_id"),
            targets=approval_targets,
        )
    ):
        return TransitionDecision("WAITING_HUMAN", "STOP", "safety approval is required")
    if int(snapshot.get("retry_count", 0)) >= int(snapshot.get("max_retries", 3)):
        return TransitionDecision("WAITING_HUMAN", "STOP", "bounded retry limit reached")

    if state == "RECEIVED":
        return TransitionDecision("RUNNING", "SURVEY", "establish current facts")
    if state == "SURVEYED":
        if route_id != "fast-track" and not _validated_artifact(
            snapshot, "approved_prd", verified_approval_evidence
        ):
            payloads = snapshot.get("artifact_payloads", {})
            action = "REVIEW_PRD" if isinstance(payloads, Mapping) and "prd_draft" in payloads else "DRAFT_PRD"
            return TransitionDecision("RUNNING", action, "approved PRD is required")
        if not _validated_artifact(snapshot, "work_packet", verified_approval_evidence):
            return TransitionDecision("RUNNING", "CREATE_WORK_PACKET", "implementation contract is missing")
        return TransitionDecision("RUNNING", "IMPLEMENT", "implementation contract is ready")
    if state == "IMPLEMENTED":
        return TransitionDecision("RUNNING", "REVIEW", "independent review is required")
    if state == "REVIEWED":
        high = int(snapshot.get("high_findings", 0))
        if high:
            return TransitionDecision("RUNNING", "FIX", "critical or important findings remain")
        if not _validated_artifact(snapshot, "evidence_bundle", verified_approval_evidence):
            return TransitionDecision("RUNNING", "BUILD_EVIDENCE_BUNDLE", "delivery evidence is incomplete")
        return TransitionDecision("RUNNING", "DELIVER", "review and evidence gates passed")
    if state == "DELIVERED":
        if snapshot.get("escaped_defects"):
            return TransitionDecision("RUNNING", "RECORD_ESCAPED_DEFECT", "new review evidence must be classified")
        return TransitionDecision("COMPLETE", "STOP", "delivery loop converged")
    if state == "DEFECT_RECORDED":
        return TransitionDecision("RUNNING", "REPLAY", "verify the earliest preventable gate")
    if state == "REPLAYED":
        if snapshot.get("replay_passed"):
            targets = snapshot.get("promotion_targets", [])
            policy_promotion = snapshot.get("promotion_level") in {"L3", "L4"} or (
                isinstance(targets, list) and any(_is_policy_target(target) for target in targets)
            )
            if policy_promotion and (
                snapshot.get("approval_state") != "approved"
                or not _verified_approval_evidence(
                    snapshot.get("approval_evidence"),
                    verified_approval_evidence,
                    safety_decision_id=snapshot.get("safety_decision_id"),
                    targets=targets if isinstance(targets, list) else [],
                )
            ):
                return TransitionDecision(
                    "WAITING_HUMAN", "STOP", "policy promotion approval is required"
                )
            return TransitionDecision("COMPLETE", "STOP", "promoted guard prevents the defect")
        return TransitionDecision("WAITING_HUMAN", "STOP", "replay did not prevent the defect")
    if state == "COMPLETE":
        return TransitionDecision("COMPLETE", "STOP", "already complete")
    return TransitionDecision("INVALID_STATE", "STOP", f"unknown state: {state}")


def _load_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    route_parser = subparsers.add_parser("route")
    route_parser.add_argument("input")
    next_parser = subparsers.add_parser("next")
    next_parser.add_argument("input")
    artifact_parser = subparsers.add_parser("validate-artifact")
    artifact_parser.add_argument("kind", choices=sorted(ARTIFACT_REQUIRED_FIELDS))
    artifact_parser.add_argument("input")
    args = parser.parse_args()
    payload = _load_json(args.input)
    if not isinstance(payload, dict):
        print("FAIL: input must be a JSON object", file=sys.stderr)
        return 2
    if args.command == "route":
        if "factors" in payload:
            factors = payload["factors"]
            options = {key: value for key, value in payload.items() if key != "factors"}
        else:
            factors = payload
            options = {}
        if not isinstance(factors, dict):
            print("FAIL: factors must be a JSON object", file=sys.stderr)
            return 2
        decision = route_work_packet(factors, **options)
        print(json.dumps(asdict(decision), ensure_ascii=False, indent=2))
        return 0 if decision.status == "READY" else 3
    if args.command == "next":
        print(json.dumps(asdict(next_action(payload)), ensure_ascii=False, indent=2))
        return 0
    errors = validate_artifact(args.kind, payload)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: artifact contract is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
