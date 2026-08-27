from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-html-surfaces.py"


class VerifyHtmlSurfacesCliTest(unittest.TestCase):
    def test_cli_reports_machine_readable_contract_result(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        issues = json.loads(completed.stdout)
        self.assertIsInstance(issues, list)
        self.assertEqual(
            [item for item in issues if item["severity"] == "error"],
            [],
        )

    def test_cli_text_mode_summarizes_pass_and_warnings(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("html surface contract: PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
