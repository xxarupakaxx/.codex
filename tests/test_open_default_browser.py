from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "open-default-browser.py"
SPEC = importlib.util.spec_from_file_location("open_default_browser", SCRIPT)
assert SPEC and SPEC.loader
browser = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(browser)


class OpenDefaultBrowserTest(unittest.TestCase):
    def test_macos_opens_file_in_existing_arc_without_new_instance(self) -> None:
        with (
            mock.patch.object(browser.sys, "platform", "darwin"),
            mock.patch.object(browser.subprocess, "run") as run,
            mock.patch.object(Path, "resolve", return_value=Path("/tmp/dashboard.html")),
        ):
            self.assertTrue(browser.open_default_browser("/tmp/dashboard.html"))

        run.assert_called_once_with(
            ["/usr/bin/open", "-a", "Arc", "file:///tmp/dashboard.html"],
            check=True,
        )

    def test_arc_launch_failure_does_not_fall_back_to_another_browser(self) -> None:
        with (
            mock.patch.object(browser.sys, "platform", "darwin"),
            mock.patch.object(
                browser.subprocess, "run",
                side_effect=subprocess.CalledProcessError(1, ["open", "-a", "Arc"]),
            ),
            mock.patch.object(browser.webbrowser, "open") as fallback,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                browser.open_default_browser("https://example.com/dashboard")
        fallback.assert_not_called()

    def test_non_macos_uses_platform_default_browser(self) -> None:
        with (
            mock.patch.object(browser.sys, "platform", "linux"),
            mock.patch.object(browser.webbrowser, "open", return_value=True) as opener,
        ):
            self.assertTrue(browser.open_default_browser("https://example.com/dashboard"))
        opener.assert_called_once_with("https://example.com/dashboard")

    def test_missing_local_file_fails_before_browser_launch(self) -> None:
        with self.assertRaises(FileNotFoundError):
            browser.normalize_target("/tmp/definitely-missing-dashboard.html")


if __name__ == "__main__":
    unittest.main()
