from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decision_evidence import evaluate_decision_evidence
from decision_explanations import MAX_DIAGNOSTICS, explain_decision_result


def plan_html() -> str:
    fields = "".join(
        f'<section data-field="{name}"><p>{name} value</p></section>'
        for name in ("intent", "assumptions", "approach", "success-scenarios")
    )
    task_fields = "".join(
        f'<section data-field="{name}"><p>{name} value</p></section>'
        for name in (
            "purpose", "targets", "outputs", "verification", "decision-boundaries",
            "stop-conditions", "negative-paths",
        )
    )
    return f'''<main data-plan-schema="2"><section data-field="execution-contract-version"><p>2</p></section>
<h1>Fixture</h1>{fields}<section data-task-id="1"><h2>Check</h2>{task_fields}
<section data-field="implementation"><ol><li>check</li></ol></section>
<section data-field="acceptance"><ul><li data-acceptance-id="A1">one</li>
<li data-acceptance-id="A2">two</li></ul></section></section></main>'''


class DecisionExplanationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = Path(self.temp.name) / "task"
        (self.task / "decision-sources").mkdir(parents=True)
        (self.task / "30_plan.html").write_text(plan_html(), encoding="utf-8")
        self.request = b"Original request\n"
        (self.task / "00_request.md").write_bytes(self.request)
        self.source = self.task / "decision-sources" / "observation.md"
        self.source.write_text("Observed behavior. SECRET_RECORD_BODY\n", encoding="utf-8")
        today = datetime.now(timezone.utc).date().isoformat()
        self.record = {
            "schemaVersion": 1,
            "requestSha256": hashlib.sha256(self.request).hexdigest(),
            "claims": [{
                "id": "H1", "statement": "The check catches drift", "why": "Avoid rework",
                "acceptanceIds": ["A1", "A2"], "critical": True, "status": "supported",
                "evidenceIds": ["E1"], "falsification": "Drift proceeds",
                "counterevidence": {
                    "status": "none-found", "evidenceIds": [], "rationale": "Checked",
                },
            }],
            "evidence": [{
                "id": "E1", "kind": "repository", "path": "decision-sources/observation.md",
                "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                "observedAt": today, "validUntil": today, "source": "repo:current.py",
            }],
            "market": {
                "applicability": "not-applicable", "rationale": "Internal change",
                "claimIds": [], "alternatives": [],
            },
        }
        self.write_record()
        self.command = [sys.executable, str(ROOT / "scripts" / "decision-preflight.py"), str(self.task)]

    def write_record(self, raw: bytes | None = None) -> None:
        payload = raw if raw is not None else json.dumps(self.record, ensure_ascii=False).encode()
        (self.task / "decision-evidence.json").write_bytes(payload)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([*self.command, *args], capture_output=True, text=True)

    def test_ready_explanation_is_bounded_guidance_not_record_or_approval(self) -> None:
        result = evaluate_decision_evidence(
            self.task, ["A1", "A2"], self.record["requestSha256"]
        )
        original = deepcopy(result)
        text = explain_decision_result(result)
        self.assertIn("独立reviewへ進める状態", text)
        self.assertIn("実装承認や需要確認を意味しません", text)
        self.assertIn("別のchecker", text)
        self.assertIn("00_request.md、30_plan.html", text)
        self.assertNotIn("分類できない診断", text)
        self.assertNotIn("SECRET_RECORD_BODY", text)
        self.assertNotIn(self.record["claims"][0]["statement"], text)
        self.assertEqual(result, original)

    def test_blockers_and_warnings_remain_distinct(self) -> None:
        text = explain_decision_result({
            "readyForReview": False,
            "blockers": ["claim_unknown:H1"],
            "warnings": ["claim_refuted:H2"],
            "record": {"private": "DO_NOT_REPEAT"},
        })
        self.assertIn("停止理由:\n- H1:", text)
        self.assertIn("警告（停止理由ではありません）:\n- H2:", text)
        self.assertNotIn("DO_NOT_REPEAT", text)
        self.assertNotIn("承認", text)

    def test_known_diagnostic_families_map_to_records_and_actions(self) -> None:
        cases = (
            ("claim_unknown:H1", "unknownで", "不確実性", "claims"),
            ("claim_refuted:H1", "refutedで", "不確実性", "claims"),
            ("unhandled_counterevidence:H1", "未実施または未解決", "反証", "claims"),
            ("critical_claim_required", "重要前提として分類", "元の困り事", "critical"),
            ("future_observation:E1", "実行日より未来", "観測日", "decision-sources"),
            ("expired_evidence:E1", "期限切れ", "有効期限", "decision-sources"),
            ("invalid_validity_range:E1", "observedAtより前", "有効期限", "decision-sources"),
            ("evidence_hash_mismatch:E1", "sha256が一致しません", "保存内容", "decision-sources"),
            ("invalid_sha256:evidence[0].sha256", "64桁の小文字16進数", "再計算", "evidence.sha256"),
            ("market_claim_must_be_critical:H1", "critical: trueとして分類", "市場前提に依存するか", "market.claimIds"),
            ("market_claim_requires_demand_evidence:H1", "customer-observation", "代替手段", "market"),
            ("market_not_applicable_must_not_list_claims_or_alternatives", "not-applicableなのに", "applicabilityを判断し直", "元依頼"),
            ("missing_or_unreadable:decision-evidence.json", "decision-evidence.json がない", "--template", "task直下"),
            ("nul_byte:decision-evidence.json", "安全に読み取れません", "NULなし", "task直下"),
            ("non_utf8:decision-evidence.json", "安全に読み取れません", "UTF-8", "task直下"),
            ("unsafe_evidence_path:evidence[0].path", "許可path", "symlinkなし", "evidence.path"),
            ("missing_or_unreadable:decision-sources/obs.md", "読込形式", "実在", "evidence.path"),
            ("non_utf8:decision-sources/obs.md", "読込形式", "UTF-8", "evidence.path"),
            ("invalid_json:decision-evidence.json", "JSON形式", "未知field", "JSON形式"),
            ("request_sha256_mismatch", "元依頼と結び付いていません", "独立reviewをやり直", "00_request.md"),
        )
        for diagnostic, reason, action, record in cases:
            with self.subTest(diagnostic=diagnostic):
                text = explain_decision_result({
                    "readyForReview": False, "blockers": [diagnostic], "warnings": [],
                })
                self.assertIn(reason, text)
                self.assertIn(action, text)
                self.assertIn(record, text)

    def test_unknown_control_and_arbitrary_values_are_not_repeated(self) -> None:
        secret = "PRIVATE_VALUE_8ef73"
        text = explain_decision_result({
            "readyForReview": False,
            "blockers": [f"future_validator:{secret}\nINJECT", f"claim_unknown:H1\n{secret}", 7],
            "warnings": [],
            "record": {"statement": secret},
            "arbitraryKey": secret,
        })
        self.assertIn("分類できない診断", text)
        self.assertNotIn(secret, text)
        self.assertNotIn("INJECT", text)
        self.assertNotIn("arbitraryKey", text)
        malformed = explain_decision_result({
            "readyForReview": True, "blockers": [], "warnings": {"arbitrary": secret},
        })
        self.assertIn("入力を確認してください", malformed)
        self.assertNotIn(secret, malformed)
        inconsistent = explain_decision_result({
            "readyForReview": True, "blockers": [f"claim_unknown:{secret}"], "warnings": [],
        })
        self.assertIn("入力を確認してください", inconsistent)
        self.assertNotIn(secret, inconsistent)

    def test_large_diagnostic_set_is_truncated_with_full_json_direction(self) -> None:
        result = {
            "readyForReview": False,
            "blockers": [f"claim_unknown:H{i}" for i in range(MAX_DIAGNOSTICS + 13)],
            "warnings": [f"claim_refuted:W{i}" for i in range(5)],
        }
        text = explain_decision_result(result)
        self.assertIn("停止理由はほか 13 件を省略", text)
        self.assertIn("警告（停止理由ではありません）はほか 5 件を省略", text)
        self.assertIn("--explainを外した既定JSON", text)
        self.assertIn("H19", text)
        self.assertNotIn("H20:", text)
        self.assertLess(len(text), 4000)

    def test_cli_default_output_and_exit_codes_are_unchanged(self) -> None:
        expected = evaluate_decision_evidence(
            self.task, ["A1", "A2"], self.record["requestSha256"]
        )
        normal = self.run_cli()
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertEqual(normal.stdout, json.dumps(
            expected, ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n")
        self.record["claims"][0]["status"] = "unknown"
        self.write_record()
        blocked = self.run_cli()
        explained = self.run_cli("--explain")
        self.assertEqual(blocked.returncode, 1)
        self.assertEqual(explained.returncode, 1)
        self.assertIn("検査結果: 停止", explained.stdout)
        self.assertEqual(explained.stderr, "")

    def test_cli_explain_handles_warning_and_does_not_modify_inputs(self) -> None:
        self.record["claims"].append({
            "id": "H2", "statement": "Optional premise", "why": "May help",
            "acceptanceIds": ["A1"], "critical": False, "status": "unknown",
            "evidenceIds": [], "falsification": "No effect",
            "counterevidence": {
                "status": "not-checked", "evidenceIds": [], "rationale": "Pending",
            },
        })
        self.write_record()
        before = {path: path.read_bytes() for path in self.task.rglob("*") if path.is_file()}
        explained = self.run_cli("--explain")
        after = {path: path.read_bytes() for path in self.task.rglob("*") if path.is_file()}
        self.assertEqual(explained.returncode, 0, explained.stderr)
        self.assertIn("警告（停止理由ではありません）", explained.stdout)
        self.assertNotIn("SECRET_RECORD_BODY", explained.stdout)
        self.assertEqual(before, after)

    def test_cli_invalid_artifact_and_input_errors_are_safe(self) -> None:
        secret = "PRIVATE_INPUT_717c"
        self.write_record(f'{{"schemaVersion": 1, "x": "{secret}"'.encode())
        invalid = self.run_cli("--explain")
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("JSON形式", invalid.stdout)
        self.assertNotIn(secret, invalid.stdout + invalid.stderr)
        (self.task / "decision-evidence.json").unlink()
        absent = self.run_cli("--explain")
        self.assertEqual(absent.returncode, 1)
        self.assertIn("decision-evidence.json がない", absent.stdout)
        self.assertIn("--template", absent.stdout)
        missing = subprocess.run(
            [*self.command[:-1], str(self.task / secret), "--explain"],
            capture_output=True, text=True,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("入力を確認してください", missing.stderr)
        self.assertNotIn(secret, missing.stderr)
        exclusive = self.run_cli("--template", "--explain")
        self.assertEqual(exclusive.returncode, 2)
        self.assertIn("引数を確認してください", exclusive.stderr)
        self.assertIn("必要な一方だけを指定", exclusive.stderr)
        self.assertNotIn("Traceback", exclusive.stderr)
        unknown = self.run_cli("--explain", f"--{secret}")
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("引数を確認してください", unknown.stderr)
        self.assertNotIn(secret, unknown.stderr)
        abbreviated = self.run_cli("--expl", "--PRIVATE_CANARY")
        self.assertEqual(abbreviated.returncode, 2)
        self.assertIn("引数を確認してください", abbreviated.stderr)
        self.assertNotIn("PRIVATE_CANARY", abbreviated.stderr)
        assigned = self.run_cli("--explain=PRIVATE_CANARY")
        self.assertEqual(assigned.returncode, 2)
        self.assertIn("引数を確認してください", assigned.stderr)
        self.assertNotIn("PRIVATE_CANARY", assigned.stderr)
        missing_task = subprocess.run(
            [*self.command[:-1], "--explain"], capture_output=True, text=True,
        )
        self.assertEqual(missing_task.returncode, 2)
        self.assertIn("引数を確認してください", missing_task.stderr)
        self.assertIn("TASK directoryを一つ指定", missing_task.stderr)
        extra = self.run_cli("--explain", "PRIVATE_EXTRA")
        self.assertEqual(extra.returncode, 2)
        self.assertIn("引数を確認してください", extra.stderr)
        self.assertNotIn("PRIVATE_EXTRA", extra.stderr)


if __name__ == "__main__":
    unittest.main()
