"""Read-only readiness checks for a reviewed plan; not an approval authority."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

try:
    from decision_evidence import evaluate_decision_evidence
except ModuleNotFoundError as exc:
    if exc.name != "decision_evidence":
        raise
    # Callers also load this module by absolute path outside the scripts directory.
    spec = importlib.util.spec_from_file_location("decision_evidence", Path(__file__).with_name("decision_evidence.py"))
    if spec is None or spec.loader is None:
        raise
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluate_decision_evidence = module.evaluate_decision_evidence

GLOBAL_FIELDS = ("intent", "assumptions", "approach", "success-scenarios")
TASK_FIELDS = ("decision-boundaries", "stop-conditions", "negative-paths")
PROGRESS_ATTRS = frozenset({"data-status", "data-done", "data-total", "data-complete",
    "data-progress-done", "data-progress-total", "data-global-complete"})
MAX_RECEIPT_BYTES = 128 * 1024
MAX_BRIEF_BYTES = 256 * 1024


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _design_node(node: dict, *, implementation: bool = False) -> dict:
    """Keep all plan content, excluding only native implementation progress."""
    attrs = node.get("attrs", {})
    implementation = implementation or attrs.get("data-field") == "implementation"
    ignored = PROGRESS_ATTRS | ({"checked"} if implementation and node.get("tag") == "input" and attrs.get("type", "checkbox") == "checkbox" else set())
    return {key: ([_design_node(child, implementation=implementation) for child in value] if key == "children"
                  else {k: v for k, v in value.items() if k not in ignored} if key == "attrs" else value)
            for key, value in node.items()}


def design_hash(model: dict) -> str:
    payload = {"document": [_design_node(node) for node in model.get("planDocument", {}).get("nodes", [])],
               "presentation": [{k: v for k, v in node.items() if k not in {"lineStart", "lineEnd"}} for node in model.get("planPresentation", [])],
               "fragments": [{key: task.get(key) for key in ("number", "uiPreviewBlocks", "diagramData")} for task in model.get("tasks", [])]}
    return _digest(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def _read_local(task_dir: Path, name: str) -> bytes:
    # Receipt paths are fixed names, never paths supplied by the receipt itself.
    path = task_dir / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError(f"missing, unsafe or oversized artifact: {name}")
    return path.read_bytes()


def _unique(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate receipt key: {key}")
        result[key] = value
    return result


def readiness(task_dir: Path, model: dict) -> dict:
    """Keep incomplete plans inspectable, but never report them executable."""
    errors = []
    contract = model.get("executionContract", {})
    if model.get("sourceKind") != "html":
        errors.append("legacy_plan_requires_execution_contract")
    version = model.get("executionContractVersion")
    if version not in {"1", "2"}:
        errors.append("execution_contract_version_required:1_or_2")
    for field in GLOBAL_FIELDS:
        if not contract.get(field, "").strip():
            errors.append(f"missing_plan_field:{field}")
    for task in model.get("tasks", []):
        for field in TASK_FIELDS:
            if not task.get("executionContract", {}).get(field, "").strip():
                errors.append(f"missing_task_field:{task['number']}:{field}")
        for field in ("implementation", "targets", "verification", "acceptanceIds"):
            if not task.get(field):
                errors.append(f"missing_task_field:{task['number']}:{field}")
    if not model.get("tasks") or model.get("diagnostics"):
        errors.append("plan_structure_invalid")
    fingerprints = {"planDesignSha256": design_hash(model)}
    try:
        request = _read_local(task_dir, "00_request.md")
        if b"\x00" in request:
            raise ValueError("invalid request source: NUL")
        if not request.decode("utf-8").strip():
            raise ValueError("empty request source")
        fingerprints["requestSha256"] = _digest(request)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    decision = None
    if version == "2":
        acceptance = [item for task in model.get("tasks", []) for item in task.get("acceptanceIds", [])]
        decision = evaluate_decision_evidence(task_dir, acceptance, fingerprints.get("requestSha256", ""))
        errors.extend(f"decision_evidence:{item}" for item in decision["blockers"])
        fingerprints["decisionEvidenceSha256"] = decision["decisionEvidenceSha256"]
    receipt_hash = None
    try:
        receipt_bytes = _read_local(task_dir, "plan-review.json")
        receipt_hash = _digest(receipt_bytes)
        receipt = json.loads(receipt_bytes, object_pairs_hook=_unique)
        if not isinstance(receipt, dict) or type(receipt.get("schemaVersion")) is not int or receipt.get("schemaVersion") != 1:
            raise ValueError("invalid review receipt schema")
        for key, value in fingerprints.items():
            if receipt.get(key) != value:
                errors.append(f"stale_review:{key}")
        author = receipt.get("authorId")
        if not isinstance(author, str) or not author.strip():
            errors.append("missing_plan_author")
        reviews = receipt.get("reviews")
        if not isinstance(reviews, dict):
            raise ValueError("missing reviews")
        for stage in ("intent", "plan"):
            review = reviews.get(stage)
            if not isinstance(review, dict):
                errors.append(f"missing_review:{stage}")
                continue
            if review.get("verdict") != "pass":
                errors.append(f"review_not_pass:{stage}")
            reviewer = review.get("reviewerId")
            if not isinstance(reviewer, str) or not reviewer.strip() or reviewer == author:
                errors.append(f"independent_reviewer_required:{stage}")
            for field in ("basis", "counterexample", "evidence"):
                if not isinstance(review.get(field), str) or not review[field].strip():
                    errors.append(f"missing_review_evidence:{stage}:{field}")
            try:
                evidence = _read_local(task_dir, f"{stage}-review.md")
                if not evidence.decode("utf-8").strip() or review.get("evidenceSha256") != _digest(evidence):
                    errors.append(f"review_evidence_mismatch:{stage}")
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
            if stage == "plan":
                intent_hash = _digest(json.dumps(reviews.get("intent"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
                if review.get("intentReviewSha256") != intent_hash:
                    errors.append("plan_review_not_bound_to_intent")
            if review.get("openFindings") != []:
                errors.append(f"unresolved_findings:{stage}")
    except (OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))
    return {"canImplement": not errors, "blockers": errors, **fingerprints,
            **({"decisionEvidence": decision} if decision is not None else {}),
            "reviewReceipt": str(task_dir / "plan-review.json"), "reviewReceiptSha256": receipt_hash,
            "limitations": "構造と記録の整合性検査。reviewer本人性・意味的正しさ・ユーザー承認の証明ではない。leadが実際の独立review出力を照合する。"}


def execution_brief(task_dir: Path, model: dict, task_id: str | None) -> dict:
    gate = readiness(task_dir, model)
    selected = next((task for task in model.get("tasks", []) if task.get("number") == task_id), None)
    if selected is None:
        gate["blockers"].append("no_selected_task")
    else:
        by_id = {task["number"]: task for task in model["tasks"]}
        for edge in model.get("edges", []):
            if edge.get("to") == task_id and (edge.get("from") not in by_id or by_id[edge["from"]].get("status") != "complete"):
                gate["blockers"].append(f"dependency_not_complete:{edge.get('from')}")
        if selected.get("status") in {"blocked", "complete"}:
            gate["blockers"].append(f"task_not_runnable:{selected.get('status')}")
    gate["canImplement"] = not gate["blockers"]
    result = {"gate": gate, "plan": model.get("executionContract", {}), "task": None}
    if gate["canImplement"]:
        result["request"] = _read_local(task_dir, "00_request.md").decode("utf-8")
        # No _compact, MAX_ITEMS, or lossy list-only extraction in executable output.
        result["task"] = {key: selected.get(key) for key in ("number", "title", "purpose", "body", "targets", "implementation", "outputs", "verification", "blockedBy", "blockedByTaskIds", "acceptance", "acceptanceIds", "sourceRefs", "requiredSources", "executionContract", "source")}
    if gate["canImplement"]:
        def find_task(nodes):
            for node in nodes:
                if node.get("attrs", {}).get("data-task-id") == selected.get("source", {}).get("taskIdAttribute"):
                    return node
                found = find_task(node.get("children", []))
                if found:
                    return found
            return None
        result["task"]["document"] = find_task(model.get("planDocument", {}).get("nodes", []))
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BRIEF_BYTES:
        gate["blockers"].append("execution_brief_too_large")
        gate["canImplement"] = False
        result = {"gate": gate, "task": None}
    return result
