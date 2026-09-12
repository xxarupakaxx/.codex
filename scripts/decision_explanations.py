"""Pure, bounded Japanese explanations for decision evidence diagnostics."""
from __future__ import annotations

import re
from typing import Any

MAX_DIAGNOSTICS = 20
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

DETAILS = {
    "ready": (
        "構造、参照、期限の機械検査は通過しました。",
        "00_request.md、30_plan.html、decision-evidence.json、参照する decision-sources の資料",
        "元依頼のWHY、受入条件、前提、資料内容が一致するか独立reviewで確認してください。",
    ),
    "claim": (
        "前提の確認状態または支持根拠が、記録した重要度の条件を満たしていません。",
        "decision-evidence.json の claims と、その前提が参照する根拠ID",
        "実際の観測と反証を確認し、前提の状態と残る不確実性を記録し直してください。",
    ),
    "critical": (
        "重要前提として分類されたclaimが一つもありません。",
        "元依頼のWHY、受入条件、decision-evidence.json の claims にある critical と why",
        "外れたときに方針を見直す前提を元の困り事から特定し、その重要度と理由を確認してください。",
    ),
    "evidence": (
        "根拠資料の日付、内容、hash、または安全な読込条件に問題があります。",
        "decision-evidence.json の evidence と、対応する decision-sources 直下の資料",
        "元資料を読み直し、観測日・有効期限・保存内容が一致するか確認してください。通すためだけに日付やhashを変更しないでください。",
    ),
    "evidence-io": (
        "根拠資料の許可path、存在、または読込形式に問題があります。",
        "decision-evidence.json の evidence.path と対応する decision-sources 直下の資料",
        "許可されたMarkdown pathと実在を確かめ、通常ファイル、symlinkなし、UTF-8、NULなし、128 KiB以下の条件を確認してください。",
    ),
    "acceptance": (
        "受入条件、前提、根拠のID対応に不足または矛盾があります。",
        "30_plan.html の受入条件と decision-evidence.json のID参照",
        "計画の受入条件ごとに必要な前提と根拠を照合し、未知・重複・未対応のIDを直してください。",
    ),
    "market": (
        "市場判断に必要な重要前提、代替手段、または利用者の観測・実験が不足しています。",
        "decision-evidence.json の market、対象claim、customer-observationまたはexperimentの資料",
        "比較した代替手段と実際の観測を確認してください。製品資料だけで需要確認済みとは扱えません。",
    ),
    "market-critical": (
        "市場判断に使うclaimがcritical: trueとして分類されていません。",
        "元依頼の目的、market.claimIds、対象claimの critical と why",
        "採択が市場前提に依存するか判断し、依存する場合は重要度とその理由を記録してください。",
    ),
    "market-conflict": (
        "market.applicabilityがnot-applicableなのにclaimIdsまたはalternativesが記入されています。",
        "元依頼の目的と decision-evidence.json の market",
        "目的からapplicabilityを判断し直してください。requiredなら利用者の観測か実験を確認し、not-applicableなら無関係なclaimIdsとalternativesを整理してください。",
    ),
    "record": (
        "task直下の decision-evidence.json がないか、安全に読み取れません。",
        "task直下の decision-evidence.json と --template が示す未記入の形式",
        "記録がなければ--templateで形式を確認してください。存在する場合は通常ファイル、UTF-8、NULなし、128 KiB以下などの読込条件を確認してください。",
    ),
    "hash-format": (
        "根拠のsha256が64桁の小文字16進数ではありません。",
        "decision-evidence.json の evidence.sha256 と対応する decision-sources の資料",
        "保存した資料のbytesからSHA-256を再計算し、記録した値と一致するか確認してください。",
    ),
    "request": (
        "判断記録が現在の元依頼と結び付いていません。",
        "00_request.md と decision-evidence.json の requestSha256",
        "元依頼が変わっていないか確認し、変わっていれば判断根拠と独立reviewをやり直してください。",
    ),
    "structure": (
        "判断記録のJSON形式、必須項目、型、件数上限のいずれかが契約と一致しません。",
        "decision-evidence.json の構造と --template が示す未記入の形式",
        "資料本文を補う前に、未知field、重複key、型、必須項目を確認してください。",
    ),
    "unknown": (
        "説明modeで分類できない診断があります。診断自体は無視されていません。",
        "--explainを外した既定JSONの blockers と warnings",
        "既定JSONの診断codeを確認し、意味が不明ならvalidatorの契約を確認してください。",
    ),
}

PREFIX_CATEGORY = {
    "claim_unknown": "claim", "claim_refuted": "claim", "unhandled_counterevidence": "claim",
    "supported_claim_requires_real_evidence": "claim", "critical_claim_required": "critical",
    "future_observation": "evidence", "expired_evidence": "evidence", "invalid_validity_range": "evidence",
    "evidence_hash_mismatch": "evidence", "unsafe_evidence_path": "evidence-io", "unsafe_symlink": "evidence-io",
    "empty_evidence": "evidence-io", "non_utf8": "evidence-io", "nul_byte": "evidence-io", "oversized": "evidence-io",
    "missing_or_unreadable": "evidence-io", "not_regular_file": "evidence-io", "invalid_date": "evidence",
    "acceptance_not_covered": "acceptance", "unknown_reference": "acceptance", "duplicate_reference": "acceptance",
    "duplicate_claim_id": "acceptance", "duplicate_evidence_id": "acceptance", "invalid_id": "acceptance",
    "invalid_acceptance_ids": "acceptance", "market_claim_must_be_critical": "market-critical",
    "market_claim_requires_demand_evidence": "market", "market_not_applicable_must_not_list_claims_or_alternatives": "market-conflict",
    "request_sha256_mismatch": "request", "invalid_request_sha256": "request",
    "invalid_json": "structure", "invalid_json_constant": "structure", "duplicate_json_key": "structure",
    "invalid_type": "structure", "invalid_text": "structure", "invalid_value": "structure",
    "invalid_string_list": "structure", "invalid_sha256": "hash-format", "invalid_schema_version": "structure",
    "missing_field": "structure", "unknown_field": "structure", "too_many_evidence": "structure",
}
TARGET_PREFIXES = {
    "claim_unknown", "claim_refuted", "unhandled_counterevidence", "supported_claim_requires_real_evidence",
    "future_observation", "expired_evidence", "invalid_validity_range", "evidence_hash_mismatch",
    "acceptance_not_covered", "unknown_reference", "duplicate_claim_id", "duplicate_evidence_id",
    "market_claim_must_be_critical", "market_claim_requires_demand_evidence",
}
ROOT_RECORD_PREFIXES = {"missing_or_unreadable", "unsafe_symlink", "not_regular_file", "oversized", "non_utf8", "nul_byte"}
PREFIX_REASONS = {
    "claim_unknown": "前提の状態がunknownで、確認が終わっていません。",
    "claim_refuted": "前提の状態がrefutedで、観測結果が前提を支持していません。",
    "unhandled_counterevidence": "反証の調査が未実施または未解決です。",
    "supported_claim_requires_real_evidence": "supportedとした前提に実在する非syntheticの支持根拠がありません。",
    "future_observation": "観測日observedAtがUTCの実行日より未来です。",
    "expired_evidence": "根拠のvalidUntilがUTCの実行日より前で、期限切れです。",
    "invalid_validity_range": "根拠のvalidUntilがobservedAtより前です。",
    "evidence_hash_mismatch": "保存した根拠資料のbytesと記録したsha256が一致しません。",
    "market_claim_requires_demand_evidence": "市場判断の前提にcustomer-observationまたはexperimentの根拠がありません。",
}


def _diagnostic(value: Any) -> tuple[str, str, str]:
    if not isinstance(value, str):
        return "unknown", "", DETAILS["unknown"][0]
    prefix, _, tail = value.partition(":")
    category = PREFIX_CATEGORY.get(prefix, "unknown")
    if tail == "decision-evidence.json" and prefix in ROOT_RECORD_PREFIXES:
        category = "record"
    candidate = tail.rsplit(":", 1)[-1] if tail else ""
    target = candidate if prefix in TARGET_PREFIXES and SAFE_ID_RE.fullmatch(candidate) else ""
    return category, target, PREFIX_REASONS.get(prefix, DETAILS[category][0])


def _items(value: Any, severity: str, remaining: int) -> tuple[list[tuple[str, str, str, str]], int]:
    if not isinstance(value, list):
        return [(severity, "unknown", "", DETAILS["unknown"][0])], 0
    shown = [(severity, *_diagnostic(item)) for item in value[:remaining]]
    return shown, max(0, len(value) - remaining)


def explain_decision_result(result: Any) -> str:
    """Explain an existing result without exposing its record or changing its verdict."""
    if not isinstance(result, dict) or type(result.get("readyForReview")) is not bool:
        return explain_input_error()
    blockers = result.get("blockers")
    warnings = result.get("warnings")
    if not isinstance(blockers, list) or not isinstance(warnings, list):
        return explain_input_error()
    if result["readyForReview"] == bool(blockers):
        return explain_input_error()
    blocker_items, omitted = _items(blockers, "停止理由", MAX_DIAGNOSTICS)
    warning_items, warning_omitted = _items(warnings, "警告（停止理由ではありません）", MAX_DIAGNOSTICS - len(blocker_items))
    items = blocker_items + warning_items
    ready = result["readyForReview"]
    lines = ["検査結果: " + ("独立reviewへ進める状態" if ready else "停止")]
    if ready:
        lines.extend(["理由:", "- 構造、参照、期限の機械検査は通過しました。これは実装承認や需要確認を意味しません。"])
    current = ""
    for severity, category, target, reason in items:
        if severity != current:
            lines.append(severity + ":")
            current = severity
        lines.append(f"- {target}: {reason}" if target else f"- {reason}")
    for severity, count in (("停止理由", omitted), ("警告（停止理由ではありません）", warning_omitted)):
        if count:
            if severity != current:
                lines.append(severity + ":")
                current = severity
            lines.append(f"- {severity}はほか {count} 件を省略しました。--explainを外した既定JSONで全診断を確認してください。")
    categories = list(dict.fromkeys(category for _, category, _, _ in items))
    if ready:
        categories.insert(0, "ready")
    elif not categories:
        categories = ["unknown"]
    lines.append("確認する記録:")
    lines.extend(f"- {DETAILS[category][1]}" for category in categories)
    lines.append("次の確認:")
    lines.extend(f"- {DETAILS[category][2]}" for category in categories)
    if ready:
        lines.append("- makerとは別のcheckerが元依頼、前提、資料内容を確認してから計画を審査してください。")
    return "\n".join(lines)


def explain_input_error() -> str:
    return "\n".join((
        "検査結果: 入力を確認してください",
        "理由:", "- task、計画、または00_request.mdを安全に読み取れませんでした。",
        "確認する記録:", "- 指定したtask directory、30_plan.html、00_request.md",
        "次の確認:", "- pathとファイル形式を確認してから、同じコマンドを再実行してください。",
    ))


def explain_argument_error() -> str:
    return "\n".join((
        "検査結果: 引数を確認してください",
        "理由:", "- 必須のTASKがないか、引数のoption、個数、組合せが正しくありません。",
        "確認する指定:", "- TASK、--explain、--template",
        "次の確認:", "- TASK directoryを一つ指定し、--explainと--templateは値を付けず、必要な一方だけを指定してください。使い方は--helpで確認できます。",
    ))
