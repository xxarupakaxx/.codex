from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-durable-workflow-evidence.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_durable_workflow_evidence", SCRIPT
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_evidence() -> dict[str, object]:
    return {
        "schema_version": 1,
        "max_cardinality": 5000,
        "boundaries": [
            {
                "name": "activity input",
                "serialized_bytes": 128000,
                "limit_bytes": 2000000,
                "source": "test:max-load",
            }
        ],
        "history": {
            "max_events": 1800,
            "limit_events": 50000,
            "source": "test:history-budget",
        },
        "rate_limits": [
            {
                "name": "Notion update",
                "rate_limit_scope": "integration HTTP request",
                "max_requests": 675,
                "request_interval_ms": 1000,
                "retry_policy": "bounded exponential backoff",
                "source": "test:notion-rate",
            }
        ],
        "terminal_states": {
            "completed": "test:completed",
            "failed": "test:failed",
            "canceled": "test:canceled",
            "terminated": "test:terminated",
        },
        "polling": {
            "applicable": True,
            "stop_states": ["completed", "failed", "canceled", "terminated"],
            "source": "test:polling-stops",
        },
        "replay": {
            "status": "pass",
            "command": "test max-load fixture",
            "source": "test:incident-replay",
        },
    }


class ValidateDurableWorkflowEvidenceTest(unittest.TestCase):
    def test_accepts_measured_max_load_and_all_terminal_states(self) -> None:
        self.assertEqual(MODULE.validate_evidence(valid_evidence()), [])

    def test_replays_payload_limit_and_stale_polling_incident(self) -> None:
        evidence = valid_evidence()
        evidence["boundaries"][0]["serialized_bytes"] = 4200000
        del evidence["terminal_states"]["terminated"]
        evidence["polling"]["stop_states"] = ["completed"]

        errors = MODULE.validate_evidence(evidence)

        self.assertTrue(any("exceeds limit" in error for error in errors))
        self.assertIn(
            "terminal_states.terminated must reference convergence evidence", errors
        )
        self.assertTrue(
            any(
                "missing terminal states: failed, canceled, terminated" in error
                for error in errors
            )
        )

    def test_requires_reason_when_polling_is_not_applicable(self) -> None:
        evidence = valid_evidence()
        evidence["polling"] = {"applicable": False}

        errors = MODULE.validate_evidence(evidence)

        self.assertIn(
            "polling.reason must explain why polling is not applicable", errors
        )


if __name__ == "__main__":
    unittest.main()
