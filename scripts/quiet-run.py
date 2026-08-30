"""Run a finite command, keeping complete local logs and bounded diagnostics."""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def excerpt(path: Path, success: bool) -> str:
    limit, lines = (4096, 7) if success else (16384, 80)
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - limit))
        raw = stream.read(limit)
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = "\n".join(text.splitlines()[-lines:])
    text = "".join(c for c in text if c.isprintable() or c in "\n\t")
    return text.encode("utf-8")[-limit:].decode("utf-8", errors="ignore")


def run(command: list[str], descriptor: int) -> int:
    child = None
    cancelled = 0
    deadline = 0.0

    def send(signum: int) -> None:
        if child is not None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    def cancel(signum: int, _frame: object) -> None:
        nonlocal cancelled, deadline
        if not cancelled:
            cancelled, deadline = signum, time.monotonic() + 1.0
            send(signum)

    previous = {s: signal.signal(s, cancel) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with os.fdopen(descriptor, "wb") as output:
            try:
                child = subprocess.Popen(
                    command,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as error:
                output.write(
                    f"quiet-run: cannot start command ({error.strerror})\n".encode()
                )
                return 127 if isinstance(error, FileNotFoundError) else 126
            if cancelled:
                send(cancelled)
            while True:
                status = child.poll()
                if cancelled:
                    if time.monotonic() >= deadline:
                        # The leader may have exited while grandchildren ignore the signal.
                        send(signal.SIGKILL)
                        child.wait()
                        return 128 + cancelled
                elif status is not None:
                    return 128 - status if status < 0 else status
                time.sleep(0.05)
    finally:
        if child is not None and child.poll() is None:
            send(signal.SIGKILL)
            child.wait()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-dir", type=Path, default=Path.home() / ".codex/.local/test-logs"
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide -- followed by a finite, noninteractive command")
    try:
        args.log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, filename = tempfile.mkstemp(
            prefix="quiet-", suffix=".log", dir=args.log_dir
        )
    except OSError as error:
        print(f"quiet-run: cannot create log ({error.strerror})", file=sys.stderr)
        return 125
    log = Path(filename).resolve()
    started = time.monotonic()
    print("[quiet-run] START", flush=True)
    print(f"[quiet-run] log: {str(log)!r}", flush=True)
    status = run(command, descriptor)
    print(
        f"[quiet-run] {'PASS' if status == 0 else 'FAIL'} exit={status} elapsed={time.monotonic() - started:.2f}s"
    )
    tail = excerpt(log, status == 0)
    if tail:
        print(tail)
    return status


if __name__ == "__main__":
    sys.exit(main())
