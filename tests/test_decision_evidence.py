from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decision_evidence import MAX_BYTES, evaluate_decision_evidence


def plan_html() -> str:
    fields = "".join(f'<section data-field="{name}"><p>{name} value</p></section>' for name in ("intent", "assumptions", "approach", "success-scenarios"))
    task_fields = "".join(f'<section data-field="{name}"><p>{name} value</p></section>' for name in ("purpose", "targets", "outputs", "verification", "decision-boundaries", "stop-conditions", "negative-paths"))
    return f'''<main data-plan-schema="2"><section data-field="execution-contract-version"><p>2</p></section><h1>Fixture</h1>{fields}
<section data-task-id="1"><h2>Check evidence</h2>{task_fields}<section data-field="implementation"><ol><li>check</li></ol></section>
<section data-field="acceptance"><ul><li data-acceptance-id="A1">one</li><li data-acceptance-id="A2">two</li></ul></section></section></main>'''


class DecisionEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = Path(self.temp.name) / "task"
        (self.task / "decision-sources").mkdir(parents=True)
        self.source = self.task / "decision-sources" / "observation.md"
        self.source.write_text("Observed repository behavior.\n", encoding="utf-8")
        self.request = b"Original request\n"
        (self.task / "00_request.md").write_bytes(self.request)
        self.request_hash = hashlib.sha256(self.request).hexdigest()
        self.record = {
            "schemaVersion": 1,
            "requestSha256": self.request_hash,
            "claims": [{
                "id": "H1", "statement": "The change catches missing evidence", "why": "It prevents rework",
                "acceptanceIds": ["A1", "A2"], "critical": True, "status": "supported", "evidenceIds": ["E1"],
                "falsification": "A missing record proceeds", "counterevidence": {"status": "none-found", "evidenceIds": [], "rationale": "Checked the current execution path"},
            }],
            "evidence": [{
                "id": "E1", "kind": "repository", "path": "decision-sources/observation.md",
                "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(), "observedAt": "2026-09-10",
                "validUntil": "2026-09-12", "source": "repo:scripts/current.py",
            }],
            "market": {"applicability": "not-applicable", "rationale": "Internal validation change", "claimIds": [], "alternatives": []},
        }
        self.write_record()

    def write_record(self, raw: bytes | None = None) -> None:
        payload = raw if raw is not None else json.dumps(self.record, ensure_ascii=False).encode()
        (self.task / "decision-evidence.json").write_bytes(payload)

    def evaluate(self) -> dict:
        return evaluate_decision_evidence(self.task, ["A1", "A2"], self.request_hash, today=date(2026, 9, 12))

    def assert_blocked(self, marker: str) -> None:
        result = self.evaluate()
        self.assertFalse(result["readyForReview"], result)
        self.assertTrue(any(marker in item for item in result["blockers"]), result)

    def test_valid_record_is_ready_and_returns_only_record_structure(self) -> None:
        result = self.evaluate()
        self.assertTrue(result["readyForReview"], result)
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["decisionEvidenceSha256"], hashlib.sha256((self.task / "decision-evidence.json").read_bytes()).hexdigest())
        self.assertEqual(result["record"], self.record)
        self.assertNotIn("Observed repository behavior", json.dumps(result))

    def test_critical_state_and_unhandled_counterevidence_block(self) -> None:
        for status in ("unknown", "refuted"):
            with self.subTest(status=status):
                self.record["claims"][0]["status"] = status
                self.write_record()
                self.assert_blocked(f"claim_{status}:H1")
        self.record["claims"][0]["status"] = "supported"
        for status in ("not-checked", "unresolved"):
            with self.subTest(counter=status):
                self.record["claims"][0]["counterevidence"]["status"] = status
                self.write_record()
                self.assert_blocked("unhandled_counterevidence:H1")

    def test_noncritical_unknown_and_refuted_warn_without_blocking(self) -> None:
        self.record["claims"].append({
            "id": "H2", "statement": "Optional premise", "why": "May improve usability", "acceptanceIds": ["A1"],
            "critical": False, "status": "unknown", "evidenceIds": [], "falsification": "No improvement",
            "counterevidence": {"status": "none-found", "evidenceIds": [], "rationale": "Small optional check"},
        })
        for status in ("unknown", "refuted"):
            with self.subTest(status=status):
                self.record["claims"][1]["status"] = status
                self.write_record()
                result = self.evaluate()
                self.assertTrue(result["readyForReview"], result)
                self.assertIn(f"claim_{status}:H2", result["warnings"])
        self.record["claims"][1]["status"] = "unknown"
        for status in ("not-checked", "unresolved"):
            with self.subTest(counter=status):
                self.record["claims"][1]["counterevidence"]["status"] = status
                self.write_record()
                result = self.evaluate()
                self.assertTrue(result["readyForReview"], result)
                self.assertIn("unhandled_counterevidence:H2", result["warnings"])

    def test_supported_claim_needs_non_synthetic_evidence(self) -> None:
        self.record["evidence"][0]["kind"] = "synthetic"
        self.write_record()
        self.assert_blocked("supported_claim_requires_real_evidence:H1")

    def test_dates_and_hash_fail_closed(self) -> None:
        cases = (
            ("observedAt", "2026-09-13", "future_observation"),
            ("observedAt", "2026-02-30", "invalid_date"),
            ("validUntil", "2026-09-11", "expired_evidence"),
            ("validUntil", "2026-09-09", "invalid_validity_range"),
            ("sha256", "0" * 64, "evidence_hash_mismatch"),
        )
        for field, value, marker in cases:
            with self.subTest(field=field, value=value):
                original = self.record["evidence"][0][field]
                self.record["evidence"][0][field] = value
                self.write_record()
                self.assert_blocked(marker)
                self.record["evidence"][0][field] = original

    def test_acceptance_and_reference_integrity(self) -> None:
        mutations = (
            (lambda r: r["claims"][0].__setitem__("acceptanceIds", ["A1"]), "acceptance_not_covered:A2"),
            (lambda r: r["claims"][0].__setitem__("acceptanceIds", ["A1", "NOPE"]), "unknown_reference"),
            (lambda r: r["claims"][0].__setitem__("evidenceIds", ["NOPE"]), "unknown_reference"),
            (lambda r: r["claims"].append(deepcopy(r["claims"][0])), "duplicate_claim_id:H1"),
            (lambda r: r["evidence"].append(deepcopy(r["evidence"][0])), "duplicate_evidence_id:E1"),
        )
        for mutate, marker in mutations:
            with self.subTest(marker=marker):
                original = deepcopy(self.record)
                mutate(self.record)
                self.write_record()
                self.assert_blocked(marker)
                self.record = original

    def test_market_requires_alternatives_and_demand_evidence(self) -> None:
        self.record["market"] = {"applicability": "required", "rationale": "Product decision", "claimIds": ["H1"], "alternatives": ["manual process"]}
        self.write_record()
        self.assert_blocked("market_claim_requires_demand_evidence:H1")
        self.record["evidence"][0]["kind"] = "customer-observation"
        self.write_record()
        self.assertTrue(self.evaluate()["readyForReview"])
        self.record["claims"][0]["critical"] = False
        self.write_record()
        self.assert_blocked("market_claim_must_be_critical:H1")
        self.record["claims"][0]["critical"] = True
        self.record["market"]["alternatives"] = []
        self.write_record()
        self.assert_blocked("invalid_string_list:market.alternatives")

    def test_unsafe_paths_are_rejected(self) -> None:
        paths = ("../observation.md", "/tmp/observation.md", "decision-sources/nested/x.md", "decision-sources/./x.md", "decision-sources//x.md", "decision-sources/private-notes.md", "decision-sources/auth-token.md", "decision-sources/foo:bar.md", "decision-sources/foo\nbar.md", "decision-sources\\x.md", "decision-sources/x.txt")
        for value in paths:
            with self.subTest(path=value):
                self.record["evidence"][0]["path"] = value
                self.write_record()
                self.assert_blocked("unsafe_evidence_path")
        self.record["evidence"][0]["path"] = "decision-sources/observation.md"
        self.source.unlink()
        self.source.symlink_to(self.task / "00_request.md")
        self.write_record()
        self.assert_blocked("unsafe_symlink")

    def test_binary_nul_oversized_and_too_many_evidence_are_rejected(self) -> None:
        for raw, marker in ((b"", "empty_evidence"), (b"\xff", "non_utf8"), (b"has\x00nul", "nul_byte"), (b"x" * (MAX_BYTES + 1), "oversized")):
            with self.subTest(marker=marker):
                self.source.write_bytes(raw)
                self.write_record()
                self.assert_blocked(marker)
        self.source.write_text("Observed repository behavior.\n")
        self.record["evidence"] = [dict(self.record["evidence"][0], id=f"E{i}") for i in range(33)]
        self.write_record()
        self.assert_blocked("too_many_evidence")

    def test_duplicate_keys_wrong_types_and_artifact_boundaries(self) -> None:
        raw = json.dumps(self.record).replace('"schemaVersion": 1', '"schemaVersion": 1, "schemaVersion": 1').encode()
        self.write_record(raw)
        self.assert_blocked("duplicate_json_key:schemaVersion")
        self.write_record(b'{"schemaVersion":NaN}')
        self.assert_blocked("invalid_json_constant:NaN")
        for raw, marker in ((b"\xff", "non_utf8"), (b'{"x":"\x00"}', "nul_byte"), (b"x" * (MAX_BYTES + 1), "oversized")):
            with self.subTest(marker=marker):
                self.write_record(raw)
                self.assert_blocked(marker)
        self.record["schemaVersion"] = True
        self.write_record()
        self.assert_blocked("invalid_schema_version")
        artifact = self.task / "decision-evidence.json"
        artifact.unlink()
        artifact.symlink_to(self.task / "00_request.md")
        self.assert_blocked("unsafe_symlink:decision-evidence.json")

    def test_nested_wrong_types_are_blocked_without_tracebacks(self) -> None:
        for mutate, marker in (
            (lambda r: r.__setitem__("evidence", {}), "invalid_type:evidence:list"),
            (lambda r: r.__setitem__("claims", {}), "invalid_type:claims:nonempty_list"),
            (lambda r: r["claims"][0].__setitem__("critical", 1), "invalid_type:claims[0].critical:boolean"),
            (lambda r: r["claims"][0].__setitem__("acceptanceIds", "A1"), "invalid_string_list:claims[0].acceptanceIds"),
            (lambda r: r.__setitem__("market", []), "invalid_type:market:object"),
        ):
            with self.subTest(marker=marker):
                original = deepcopy(self.record)
                mutate(self.record)
                self.write_record()
                self.assert_blocked(marker)
                self.record = original

    def test_request_hash_critical_claim_and_exact_shape_are_required(self) -> None:
        for mutate, marker in (
            (lambda r: r.__setitem__("requestSha256", "0" * 64), "request_sha256_mismatch"),
            (lambda r: r["claims"][0].__setitem__("critical", False), "critical_claim_required"),
            (lambda r: r.__setitem__("extra", True), "unknown_field:record.extra"),
        ):
            with self.subTest(marker=marker):
                original = deepcopy(self.record)
                mutate(self.record)
                self.write_record()
                self.assert_blocked(marker)
                self.record = original

    def test_cli_template_normal_failure_and_input_error_exit_codes(self) -> None:
        (self.task / "30_plan.html").write_text(plan_html(), encoding="utf-8")
        runtime_day = datetime.now(timezone.utc).date().isoformat()
        self.record["evidence"][0].update(observedAt=runtime_day, validUntil=runtime_day)
        self.write_record()
        command = [sys.executable, str(ROOT / "scripts" / "decision-preflight.py"), str(self.task)]
        success = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(set(json.loads(success.stdout)), {"readyForReview", "blockers", "warnings", "decisionEvidenceSha256", "record"})
        before = set(self.task.iterdir())
        template = subprocess.run(command + ["--template"], capture_output=True, text=True)
        self.assertEqual(template.returncode, 0, template.stderr)
        self.assertEqual(json.loads(template.stdout)["claims"][0]["status"], "unknown")
        self.assertEqual(before, set(self.task.iterdir()))
        bypass = subprocess.run(command + ["--today", "2099-01-01"], capture_output=True, text=True)
        self.assertEqual(bypass.returncode, 2)
        self.assertNotIn("Traceback", bypass.stderr)
        self.record["claims"][0]["status"] = "unknown"
        self.write_record()
        blocked = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        bad = subprocess.run([*command[:-1], str(self.task / "missing")], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertNotIn("Traceback", bad.stderr)
        self.assertEqual(json.loads(bad.stderr)["status"], "error")


if __name__ == "__main__":
    unittest.main()
