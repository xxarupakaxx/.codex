from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from draft_delivery_message import (  # noqa: E402
    DISABLED_FEATURES,
    MODEL,
    build_command,
    draft_delivery_message,
)


class DraftDeliveryMessageTest(unittest.TestCase):
    @staticmethod
    def safe_feature_inventory() -> str:
        return "\n".join(
            f"{feature} stable true" for feature in DISABLED_FEATURES
        )

    @staticmethod
    def draft_input() -> dict[str, object]:
        return {
            "draft_id": "draft-1",
            "draft_kind": "commit",
            "source_hash": "a" * 64,
            "changed_paths": ["app.py"],
            "evidence_bundle_id": "eb-1",
            "acceptance_ids": ["A1"],
            "test_ids": ["T1"],
            "residual_risk_ids": [],
            "template_sections": [],
            "policy_source": "AGENTS.md",
            "worker_patch": "safe bounded patch",
        }

    @staticmethod
    def valid_output() -> dict[str, object]:
        return {
            "draft_id": "draft-1",
            "draft_kind": "commit",
            "source_hash": "a" * 64,
            "status": "DRAFT_READY",
            "claim_references": ["app.py", "A1", "T1"],
            "content": {"type": "feat", "subject": "配送契約を追加", "body": ""},
        }

    def test_command_is_ephemeral_read_only_luna_max_with_tool_features_disabled(self) -> None:
        command = build_command(Path("schema.json"), Path("output.json"), Path("isolated"))

        self.assertIn(MODEL, command)
        self.assertIn('model_reasoning_effort="max"', command)
        self.assertIn('service_tier="priority"', command)
        for marker in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "read-only"):
            self.assertIn(marker, command)
        disabled = {
            command[index + 1]
            for index, value in enumerate(command[:-1])
            if value == "--disable"
        }
        self.assertEqual(disabled, set(DISABLED_FEATURES))

    def test_validated_worker_output_is_returned(self) -> None:
        expected = self.valid_output()

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text(json.dumps(expected), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        output, errors = draft_delivery_message(
            self.draft_input(), expected_source_hash="a" * 64,
            feature_inventory=self.safe_feature_inventory(), runner=runner
        )

        self.assertEqual(output, expected)
        self.assertEqual(errors, [])

    def test_privileged_worker_output_is_rejected(self) -> None:
        invalid = self.valid_output()
        invalid["content"] = {
            "type": "feat",
            "subject": "配送契約を追加",
            "body": "",
            "commands": ["git push"],
        }

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text(json.dumps(invalid), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        output, errors = draft_delivery_message(
            self.draft_input(), expected_source_hash="a" * 64,
            feature_inventory=self.safe_feature_inventory(), runner=runner
        )

        self.assertIsNone(output)
        self.assertIn("delivery draft contains privileged fields: content.commands", errors)

    def test_worker_failure_does_not_fallback(self) -> None:
        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 9, "", "unavailable")

        output, errors = draft_delivery_message(
            self.draft_input(), expected_source_hash="a" * 64,
            feature_inventory=self.safe_feature_inventory(), runner=runner
        )

        self.assertIsNone(output)
        self.assertEqual(errors, ["isolated Luna worker failed with exit 9"])

    def test_adapter_rechecks_worker_patch_for_secrets_before_dispatch(self) -> None:
        draft_input = self.draft_input()
        draft_input["worker_patch"] = (
            "+OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456"
        )
        called = False

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            nonlocal called
            called = True
            return subprocess.CompletedProcess(command, 0, "", "")

        output, errors = draft_delivery_message(
            draft_input, expected_source_hash="a" * 64,
            feature_inventory=self.safe_feature_inventory(), runner=runner
        )

        self.assertFalse(called)
        self.assertIsNone(output)
        self.assertIn("input: worker_patch contains secret-like content", errors)

    def test_adapter_requires_hash_from_trusted_snapshot(self) -> None:
        called = False

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            nonlocal called
            called = True
            return subprocess.CompletedProcess(command, 0, "", "")

        output, errors = draft_delivery_message(
            self.draft_input(), expected_source_hash="trusted",
            feature_inventory=self.safe_feature_inventory(), runner=runner
        )

        self.assertFalse(called)
        self.assertIsNone(output)
        self.assertEqual(errors, ["input: source_hash does not match trusted snapshot"])

    def test_unknown_enabled_tool_feature_fails_closed(self) -> None:
        called = False

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            nonlocal called
            called = True
            return subprocess.CompletedProcess(command, 0, "", "")

        inventory = self.safe_feature_inventory() + "\nfuture_workspace_tool stable true\n"
        output, errors = draft_delivery_message(
            self.draft_input(),
            expected_source_hash="a" * 64,
            feature_inventory=inventory,
            runner=runner,
        )

        self.assertFalse(called)
        self.assertIsNone(output)
        self.assertEqual(
            errors,
            ["input: enabled tool feature is not denied: future_workspace_tool"],
        )


if __name__ == "__main__":
    unittest.main()
