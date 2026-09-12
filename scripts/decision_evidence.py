"""Read-only validation for task-local decision evidence."""
from __future__ import annotations

import hashlib
import json
import re
import stat
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

MAX_BYTES = 128 * 1024
MAX_EVIDENCE = 32
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,122}\.md\Z", re.I)
SECRET_RE = re.compile(r"(?:^|[-_.])(secret|credential|password|token|auth|session|cookie|private(?:[-_]?key)?|api[-_]?key)(?:[-_.]|$)|^\.env", re.I)
CLAIM_STATUS = {"supported", "unknown", "refuted"}
COUNTER_STATUS = {"not-checked", "none-found", "addressed", "unresolved"}
EVIDENCE_KIND = {"repository", "primary-source", "customer-observation", "experiment", "synthetic"}
MARKET_APPLICABILITY = {"required", "not-applicable"}


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"invalid_json_constant:{value}")


def _read_bounded(path: Path, label: str) -> bytes:
    if path.is_symlink():
        raise ValueError(f"unsafe_symlink:{label}")
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError(f"missing_or_unreadable:{label}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"not_regular_file:{label}")
    if info.st_size > MAX_BYTES:
        raise ValueError(f"oversized:{label}")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"missing_or_unreadable:{label}") from exc
    if len(raw) > MAX_BYTES:
        raise ValueError(f"oversized:{label}")
    return raw


def _decode(raw: bytes, label: str) -> str:
    if b"\x00" in raw:
        raise ValueError(f"nul_byte:{label}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"non_utf8:{label}") from exc


def _shape(value: Any, label: str, fields: set[str], errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"invalid_type:{label}:object")
        return None
    missing, unknown = fields - value.keys(), value.keys() - fields
    errors.extend(f"missing_field:{label}.{field}" for field in sorted(missing))
    errors.extend(f"unknown_field:{label}.{field}" for field in sorted(unknown))
    return value


def _text(value: Any, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        errors.append(f"invalid_text:{label}")
        return None
    return value.strip()


def _enum(value: Any, label: str, allowed: set[str], errors: list[str]) -> str | None:
    if not isinstance(value, str) or value not in allowed:
        errors.append(f"invalid_value:{label}")
        return None
    return value


def _strings(value: Any, label: str, errors: list[str], *, nonempty: bool = False) -> list[str] | None:
    if not isinstance(value, list) or (nonempty and not value) or any(not isinstance(item, str) or not item.strip() or "\x00" in item for item in value):
        errors.append(f"invalid_string_list:{label}")
        return None
    result = [item.strip() for item in value]
    if len(result) != len(set(result)):
        errors.append(f"duplicate_reference:{label}")
    return result


def _identifier(value: Any, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        errors.append(f"invalid_id:{label}")
        return None
    return value


def _day(value: Any, label: str, errors: list[str]) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        errors.append(f"invalid_date:{label}")
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        errors.append(f"invalid_date:{label}")
        return None
    if parsed.isoformat() != value:
        errors.append(f"invalid_date:{label}")
        return None
    return parsed


def _safe_evidence_path(value: Any, label: str, errors: list[str]) -> str | None:
    text = _text(value, label, errors)
    if text is None:
        return None
    posix = PurePosixPath(text)
    if text != posix.as_posix() or "\\" in text or posix.is_absolute() or len(posix.parts) != 2 or posix.parts[0] != "decision-sources" or not FILENAME_RE.fullmatch(posix.name) or SECRET_RE.search(posix.name):
        errors.append(f"unsafe_evidence_path:{label}")
        return None
    return posix.as_posix()


def _validate_evidence(task: Path, entries: Any, today: date, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(entries, list):
        errors.append("invalid_type:evidence:list")
        return {}
    if len(entries) > MAX_EVIDENCE:
        errors.append("too_many_evidence")
    by_id: dict[str, dict[str, Any]] = {}
    fields = {"id", "kind", "path", "sha256", "observedAt", "validUntil", "source"}
    for index, value in enumerate(entries[: MAX_EVIDENCE + 1]):
        label = f"evidence[{index}]"
        item = _shape(value, label, fields, errors)
        if item is None:
            continue
        evidence_id = _identifier(item.get("id"), f"{label}.id", errors)
        _enum(item.get("kind"), f"{label}.kind", EVIDENCE_KIND, errors)
        relative = _safe_evidence_path(item.get("path"), f"{label}.path", errors)
        expected_hash = item.get("sha256")
        if not isinstance(expected_hash, str) or not HASH_RE.fullmatch(expected_hash):
            errors.append(f"invalid_sha256:{label}.sha256")
            expected_hash = None
        observed = _day(item.get("observedAt"), f"{label}.observedAt", errors)
        valid_until = _day(item.get("validUntil"), f"{label}.validUntil", errors)
        _text(item.get("source"), f"{label}.source", errors)
        if evidence_id:
            if evidence_id in by_id:
                errors.append(f"duplicate_evidence_id:{evidence_id}")
            else:
                by_id[evidence_id] = item
        if observed and observed > today:
            errors.append(f"future_observation:{evidence_id or label}")
        if observed and valid_until and valid_until < observed:
            errors.append(f"invalid_validity_range:{evidence_id or label}")
        if valid_until and valid_until < today:
            errors.append(f"expired_evidence:{evidence_id or label}")
        if relative:
            source_dir = task / "decision-sources"
            if source_dir.is_symlink():
                errors.append(f"unsafe_symlink:{relative}")
                continue
            try:
                raw = _read_bounded(task / relative, relative)
                if not _decode(raw, relative).strip():
                    errors.append(f"empty_evidence:{relative}")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if expected_hash and _digest(raw) != expected_hash:
                errors.append(f"evidence_hash_mismatch:{evidence_id or label}")
    return by_id


def _unknown_refs(values: Iterable[str], known: set[str], label: str, errors: list[str]) -> None:
    errors.extend(f"unknown_reference:{label}:{value}" for value in values if value not in known)


def _validate_claims(entries: Any, acceptance: set[str], evidence: dict[str, dict[str, Any]], errors: list[str], warnings: list[str]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    if not isinstance(entries, list) or not entries:
        errors.append("invalid_type:claims:nonempty_list")
        return {}, set()
    by_id: dict[str, dict[str, Any]] = {}
    covered: set[str] = set()
    critical_count = 0
    fields = {"id", "statement", "why", "acceptanceIds", "critical", "status", "evidenceIds", "falsification", "counterevidence"}
    counter_fields = {"status", "evidenceIds", "rationale"}
    for index, value in enumerate(entries):
        label = f"claims[{index}]"
        claim = _shape(value, label, fields, errors)
        if claim is None:
            continue
        claim_id = _identifier(claim.get("id"), f"{label}.id", errors)
        if claim_id:
            if claim_id in by_id:
                errors.append(f"duplicate_claim_id:{claim_id}")
            else:
                by_id[claim_id] = claim
        _text(claim.get("statement"), f"{label}.statement", errors)
        _text(claim.get("why"), f"{label}.why", errors)
        _text(claim.get("falsification"), f"{label}.falsification", errors)
        acceptance_ids = _strings(claim.get("acceptanceIds"), f"{label}.acceptanceIds", errors, nonempty=True) or []
        _unknown_refs(acceptance_ids, acceptance, f"{label}.acceptanceIds", errors)
        covered.update(item for item in acceptance_ids if item in acceptance)
        critical = claim.get("critical")
        if type(critical) is not bool:
            errors.append(f"invalid_type:{label}.critical:boolean")
            critical = False
        critical_count += int(critical)
        status_value = _enum(claim.get("status"), f"{label}.status", CLAIM_STATUS, errors)
        evidence_ids = _strings(claim.get("evidenceIds"), f"{label}.evidenceIds", errors) or []
        _unknown_refs(evidence_ids, set(evidence), f"{label}.evidenceIds", errors)
        if status_value == "supported" and not any(ref in evidence and evidence[ref].get("kind") != "synthetic" for ref in evidence_ids):
            errors.append(f"supported_claim_requires_real_evidence:{claim_id or label}")
        if status_value in {"unknown", "refuted"}:
            target = errors if critical else warnings
            target.append(f"claim_{status_value}:{claim_id or label}")
        counter = _shape(claim.get("counterevidence"), f"{label}.counterevidence", counter_fields, errors)
        if counter is not None:
            counter_status = _enum(counter.get("status"), f"{label}.counterevidence.status", COUNTER_STATUS, errors)
            counter_ids = _strings(counter.get("evidenceIds"), f"{label}.counterevidence.evidenceIds", errors) or []
            _unknown_refs(counter_ids, set(evidence), f"{label}.counterevidence.evidenceIds", errors)
            _text(counter.get("rationale"), f"{label}.counterevidence.rationale", errors)
            if counter_status in {"not-checked", "unresolved"}:
                target = errors if critical else warnings
                target.append(f"unhandled_counterevidence:{claim_id or label}")
    if critical_count == 0:
        errors.append("critical_claim_required")
    errors.extend(f"acceptance_not_covered:{item}" for item in sorted(acceptance - covered))
    return by_id, covered


def _validate_market(value: Any, claims: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]], errors: list[str]) -> None:
    market = _shape(value, "market", {"applicability", "rationale", "claimIds", "alternatives"}, errors)
    if market is None:
        return
    applicability = _enum(market.get("applicability"), "market.applicability", MARKET_APPLICABILITY, errors)
    _text(market.get("rationale"), "market.rationale", errors)
    claim_ids = _strings(market.get("claimIds"), "market.claimIds", errors, nonempty=applicability == "required") or []
    alternatives = _strings(market.get("alternatives"), "market.alternatives", errors, nonempty=applicability == "required") or []
    _unknown_refs(claim_ids, set(claims), "market.claimIds", errors)
    if applicability == "not-applicable" and (claim_ids or alternatives):
        errors.append("market_not_applicable_must_not_list_claims_or_alternatives")
    if applicability == "required":
        demand_kinds = {"customer-observation", "experiment"}
        for claim_id in claim_ids:
            claim = claims.get(claim_id)
            refs = claim.get("evidenceIds", []) if claim else []
            if claim and claim.get("critical") is not True:
                errors.append(f"market_claim_must_be_critical:{claim_id}")
            if not any(ref in evidence and evidence[ref].get("kind") in demand_kinds for ref in refs):
                errors.append(f"market_claim_requires_demand_evidence:{claim_id}")


def evaluate_decision_evidence(task_dir: str | Path, acceptance_ids: Iterable[str], request_sha256: str, *, today: date | None = None) -> dict[str, Any]:
    """Return structural readiness for independent review, never approval."""
    errors: list[str] = []
    warnings: list[str] = []
    record: dict[str, Any] | None = None
    artifact_hash: str | None = None
    runtime_day = today if today is not None else datetime.now(timezone.utc).date()
    try:
        task_input = Path(task_dir)
        if task_input.is_symlink() or not task_input.is_dir():
            raise ValueError("unsafe_or_missing_task_dir")
        task = task_input.resolve(strict=True)
        requested = list(acceptance_ids)
        if not requested or any(not isinstance(item, str) or not ID_RE.fullmatch(item) for item in requested) or len(requested) != len(set(requested)):
            errors.append("invalid_acceptance_ids")
            acceptance = set()
        else:
            acceptance = set(requested)
        if not isinstance(request_sha256, str) or not HASH_RE.fullmatch(request_sha256):
            errors.append("invalid_request_sha256")
        raw = _read_bounded(task / "decision-evidence.json", "decision-evidence.json")
        artifact_hash = _digest(raw)
        text = _decode(raw, "decision-evidence.json")
        try:
            value = json.loads(text, object_pairs_hook=_unique, parse_constant=_invalid_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid_json:{exc}")
            value = None
        root = _shape(value, "record", {"schemaVersion", "requestSha256", "claims", "evidence", "market"}, errors)
        if root is not None:
            record = root
            if type(root.get("schemaVersion")) is not int or root.get("schemaVersion") != 1:
                errors.append("invalid_schema_version")
            if root.get("requestSha256") != request_sha256:
                errors.append("request_sha256_mismatch")
            evidence = _validate_evidence(task, root.get("evidence"), runtime_day, errors)
            claims, _ = _validate_claims(root.get("claims"), acceptance, evidence, errors, warnings)
            _validate_market(root.get("market"), claims, evidence, errors)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    blockers = list(dict.fromkeys(errors))
    return {
        "readyForReview": not blockers,
        "blockers": blockers,
        "warnings": list(dict.fromkeys(warnings)),
        "decisionEvidenceSha256": artifact_hash,
        "record": record,
    }
