"""Roadmap Task Hub backend."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import subprocess
from typing import Callable, TextIO


@dataclass(frozen=True)
class CodexThread:
    id: str
    title: str
    cwd: str
    status: str
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class ProviderSnapshot:
    threads: tuple[CodexThread, ...]
    connected: bool
    synced_at: str
    error: str | None = None


class ProviderError(RuntimeError):
    """Raised when the Codex app-server protocol cannot be completed."""


class CodexAppServerProvider:
    def __init__(self, process_factory: Callable[[], object] | None = None):
        self._process_factory = process_factory or self._start_process

    @staticmethod
    def _start_process() -> subprocess.Popen[str]:
        return subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    @staticmethod
    def _send(stream: TextIO, message: dict[str, object]) -> None:
        stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        stream.flush()

    @staticmethod
    def _read_response(stream: TextIO, request_id: int) -> dict[str, object]:
        while True:
            line = stream.readline()
            if not line:
                raise ProviderError(
                    f"codex app-server closed before response {request_id}"
                )
            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                raise ProviderError(f"invalid JSON from codex app-server: {error}") from error
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                if isinstance(error, dict):
                    detail = error.get("message", json.dumps(error, ensure_ascii=False))
                else:
                    detail = str(error)
                raise ProviderError(f"codex app-server request failed: {detail}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ProviderError(
                    f"codex app-server response {request_id} has no result object"
                )
            return result

    def list_threads(self) -> ProviderSnapshot:
        process = self._process_factory()
        stdin = getattr(process, "stdin", None)
        stdout = getattr(process, "stdout", None)
        if stdin is None or stdout is None:
            raise ProviderError("codex app-server process has no stdio streams")

        try:
            self._send(
                stdin,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "roadmap-task-hub",
                            "version": "0.1.0",
                        }
                    },
                },
            )
            self._read_response(stdout, 1)
            self._send(
                stdin,
                {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            )

            threads: list[CodexThread] = []
            cursor: str | None = None
            request_id = 2
            while True:
                params: dict[str, object] = {
                    "limit": 100,
                    "sortKey": "updated_at",
                }
                if cursor:
                    params["cursor"] = cursor
                self._send(
                    stdin,
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "thread/list",
                        "params": params,
                    },
                )
                result = self._read_response(stdout, request_id)
                data = result.get("data", [])
                if not isinstance(data, list):
                    raise ProviderError("thread/list result data is not a list")
                threads.extend(self._to_thread(item) for item in data)
                cursor_value = result.get("nextCursor")
                cursor = cursor_value if isinstance(cursor_value, str) else None
                if not cursor:
                    break
                request_id += 1

            return ProviderSnapshot(
                threads=tuple(threads),
                connected=True,
                synced_at=_now_iso(),
            )
        finally:
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                terminate()

    @staticmethod
    def _to_thread(item: object) -> CodexThread:
        if not isinstance(item, dict):
            raise ProviderError("thread/list returned a non-object thread")
        thread_id = str(item.get("id", ""))
        name = item.get("name")
        preview = item.get("preview")
        title = (
            name.strip()
            if isinstance(name, str) and name.strip()
            else preview[:80]
            if isinstance(preview, str) and preview
            else thread_id
        )
        status_value = item.get("status")
        status = (
            str(status_value.get("type", ""))
            if isinstance(status_value, dict)
            else str(status_value or "")
        )
        return CodexThread(
            id=thread_id,
            title=title,
            cwd=str(item.get("cwd", "")),
            status=status,
            created_at=int(item.get("createdAt", 0)),
            updated_at=int(item.get("updatedAt", 0)),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_provider_snapshot(provider: CodexAppServerProvider) -> ProviderSnapshot:
    try:
        return provider.list_threads()
    except Exception as error:
        return ProviderSnapshot(
            threads=(), connected=False, synced_at=_now_iso(), error=str(error)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-provider", action="store_true")
    args = parser.parse_args()
    if not args.probe_provider:
        parser.error("one of --probe-provider is required")

    snapshot = safe_provider_snapshot(CodexAppServerProvider())
    payload = {
        "connected": snapshot.connected,
        "syncedAt": snapshot.synced_at,
        "error": snapshot.error,
        "threads": [
            {
                "id": thread.id,
                "title": thread.title,
                "cwd": thread.cwd,
                "status": thread.status,
                "updatedAt": thread.updated_at,
            }
            for thread in snapshot.threads
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if snapshot.connected else 1


if __name__ == "__main__":
    raise SystemExit(main())
