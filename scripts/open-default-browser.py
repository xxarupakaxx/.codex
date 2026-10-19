#!/usr/bin/env python3
"""Open a URL or local file in Arc on macOS, or the platform browser elsewhere."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import webbrowser


MACOS_BROWSER_APP = "Arc"


def normalize_target(target: str) -> str:
    if "://" in target:
        return target
    return Path(target).expanduser().resolve(strict=True).as_uri()


def open_default_browser(target: str) -> bool:
    normalized = normalize_target(target)
    if sys.platform == "darwin":
        subprocess.run(
            ["/usr/bin/open", "-a", MACOS_BROWSER_APP, normalized], check=True
        )
        return True
    if os.name == "nt":
        os.startfile(normalized)  # type: ignore[attr-defined]
        return True
    return webbrowser.open(normalized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open a target in the existing Arc app on macOS."
    )
    parser.add_argument("target", help="URL or existing local file")
    args = parser.parse_args(argv)
    try:
        if not open_default_browser(args.target):
            raise RuntimeError("the platform browser opener rejected the target")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"failed to open browser: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
