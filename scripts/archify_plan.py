#!/usr/bin/env python3
"""Produce the Archify workflow overview for a canonical Roadmap Plan.

The Markdown parser remains the single source of Task semantics.  This module
only projects that parser's result into a small workflow IR and owns the
bounded, local SVG/cache bridge used by both viewers.
"""

from __future__ import annotations

import contextlib
import base64
import errno
import hashlib
import heapq
import importlib.util
import json
import math
import os
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
PLAN_CONTRACT = ROOT / "scripts" / "roadmap_plan_contract.py"
CONFIG_PATH = ROOT / "config" / "archify-source.json"
CONTAINER_CONFIG_PATH = ROOT / "config" / "archify-container.json"
SECCOMP_PATH = ROOT / "config" / "archify-seccomp.json"
RENDERER_PATH = ROOT / "scripts" / "archify_render.mjs"
CONTAINER_ENTRYPOINT_PATH = ROOT / "scripts" / "archify_container.mjs"
CACHE_ROOT = ROOT / ".local" / "archify-plan-assets"
EXPECTED_CONFIG_SHA256 = "8f3b1e38ff92ed0a589169686322123d676837fb9ce0716a27ebf28087e04810"
EXPECTED_REVISION = "5de7275fe87a66a19d52a4d9b0b3a4f2a5a90115"
EXPECTED_NODE_EXECUTABLE = "/usr/bin/node"
EXPECTED_CHROME_EXECUTABLE = "/ms-playwright/chromium-1228/chrome-linux/chrome"
EXPECTED_MANIFEST_SHA256 = "0549797b20e76a6908bd7328fe482fe168b81f40e5135a9aed44c67e543b03e5"
EXPECTED_SECCOMP_SHA256 = "05e4588202a0950e17465aff9831b04f6e196dcd5b31941515a6db4d0a3ee45d"
EXPECTED_DOCKER_EXECUTABLE = "/opt/homebrew/bin/docker"
EXPECTED_DOCKER_REALPATH = "/opt/homebrew/Cellar/docker/29.0.1/bin/docker"
EXPECTED_DOCKER_SHA256 = "7feea539042afd5712216041af4f54580816226b298c6f749ee133ff428a1ba7"
EXPECTED_DOCKER_CONTEXT = "colima"
EXPECTED_DOCKER_ENDPOINT = "unix:///Users/yoshiki/.colima/default/docker.sock"
EXPECTED_NODE_SHA256 = "4adeeca28663521e926659041cf26dbe5bded9d104316373c364a8b65ed17f03"
EXPECTED_NODE_VERSION = "v24.17.0"
EXPECTED_CHROME_SHA256 = "c1aa0fb5b6c60eb093df69d9e40dd50ab2039d3ccba8836ef21880340a77af64"
EXPECTED_CHROME_VERSION = "149.0.7827.0"
EXPECTED_BASE_IMAGE = "mcr.microsoft.com/playwright@sha256:824f1a789072e648c62541c2cfa4479c4061a290d5c27766d67dc1dcbc19b321"
EXPECTED_CONTAINER_BACKEND = "docker-colima-v1"
EXPECTED_CONTAINER_POLICY = "archify-plan-container-v1"
EXPECTED_CONTAINER_PROTOCOL = "archify-container-v1"
EXPECTED_CONTAINER_DESCRIPTOR_SHA256 = "657ba8433b8dfb824f3107077c369d4cf26cb78de11ff72af6fcb50cda370f42"

ADAPTER_VERSION = "archify-plan-producer-container-v1"
RAW_PLAN_LIMIT = 1024 * 1024
TASK_LIMIT = 128
EDGE_LIMIT = 256
TITLE_LIMIT = 512
SVG_LIMIT = 4 * 1024 * 1024
SVG_ELEMENT_LIMIT = 20_000
SVG_DEPTH_LIMIT = 64
HTML_LIMIT = 8 * 1024 * 1024
STREAM_LIMIT = 512 * 1024
RENDER_DEADLINE = 60.0
CONTAINER_INPUT_LIMIT = 1024 * 1024
CONTAINER_STDOUT_LIMIT = HTML_LIMIT
CONTAINER_STDERR_LIMIT = STREAM_LIMIT
CONTAINER_FSIZE_LIMIT = 32 * 1024 * 1024
CONTAINER_CLEANUP_RESERVE = 5.0
DOCKER_CALL_OUTPUT_LIMIT = 256 * 1024
NODE_HEIGHT = 52
ROW_PITCH = 64
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_XML_RE = re.compile(r"(?is)<!\s*(?:doctype|entity)|<\?(?!xml(?:\s|\?))")
FORBIDDEN_ELEMENT_NAMES = {"script", "foreignobject"}
URL_RE = re.compile(
    r"(?i)(?:javascript\s*:|data\s*:|file\s*:|blob\s*:|about\s*:|https?\s*:|ftp\s*:|//)"
)
CSS_URL_RE = re.compile(r"(?i)\burl\s*\(")
CSS_URL_FUNCTION_RE = re.compile(r"(?i)\burl\s*\(\s*[^()]*\)")
CSS_IMPORT_RE = re.compile(r"(?i)(?:^|[;{\s])@import\b")
CSS_ESCAPE_RE = re.compile(r"\\(?:[0-9a-f]{1,6}\s?|.)", re.IGNORECASE)
SAFE_FRAGMENT_URL_RE = re.compile(r"(?i)^url\(\s*#[A-Za-z_][A-Za-z0-9_.:-]*\s*\)$")
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
SANDBOX_POLICY_ID = "archify-plan-sandbox-v2"
SANDBOX_MARKER = "ARCHIFY_REVIEW_SANDBOX"
SANDBOX_PROFILE_HASH_MARKER = "ARCHIFY_REVIEW_SANDBOX_PROFILE_SHA256"
SVG_ALLOWED_ELEMENTS = {
    "svg",
    "title",
    "desc",
    "defs",
    "marker",
    "pattern",
    "path",
    "rect",
    "text",
    "line",
    "g",
    "polygon",
    "ellipse",
    "circle",
    "style",
}
SVG_SMIL_ATTRIBUTES = {
    "attributename",
    "attributetype",
    "begin",
    "by",
    "calcmode",
    "dur",
    "end",
    "from",
    "keypoints",
    "keysplines",
    "keytimes",
    "repeatcount",
    "repeatdur",
    "restart",
    "to",
    "values",
}
EXPECTED_PLAYWRIGHT_VERSION = "1.61.1"
EXPECTED_PLAYWRIGHT_LOCK_SHA256 = "f39a5523505682275900e15483f080e04537917107686743f047edfe5b8a3ba3"
EXPECTED_PLAYWRIGHT_PACKAGE_SHA256 = "6b840268612656f0639fb7d68782e8353bdf11518589d30ddf66f283c2670ed5"
EXPECTED_PLAYWRIGHT_CORE_SHA256 = "759e376f995bf39edd4810d699b99469bab1d7428b6fbc78d41912f367df7ba9"

_PLAN_CONTRACT_MODULE: object | None = None
_CACHE_THREAD_LOCK = threading.RLock()
SOURCE_FILE_COUNT = 190


class _ProducerError(ValueError):
    """A user-visible producer failure with a stable payload status."""

    def __init__(self, message: str, *, status: str = "error") -> None:
        super().__init__(message)
        self.status = status


class _RendererBlocked(_ProducerError):
    def __init__(self, message: str, *, revision: str = "unknown") -> None:
        super().__init__(message, status="blocked")
        self.revision = revision


class _RendererFailure(_ProducerError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status="error")


def _canonical_json(value: Any) -> str:
    """Serialize hash inputs without Unicode or whitespace rewriting."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _ProducerError("canonical JSONを生成できません。", status="invalid") from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _ProducerError("stdin JSONに重複keyがあります。", status="invalid")
        result[key] = value
    return result


def _manifest_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise _ProducerError("固定source manifestを検証できません。", status="blocked") from error
    return _sha256_bytes(encoded)


def _adapter_source_sha256() -> str:
    try:
        return _sha256_bytes(Path(__file__).resolve().read_bytes())
    except OSError:
        return ""


ADAPTER_SOURCE_SHA256 = _adapter_source_sha256()


def _load_plan_contract_module() -> object:
    """Load only the fixed canonical parser, independent of ``sys.path``."""
    global _PLAN_CONTRACT_MODULE
    if _PLAN_CONTRACT_MODULE is not None:
        return _PLAN_CONTRACT_MODULE
    if PLAN_CONTRACT.is_symlink() or not PLAN_CONTRACT.is_file():
        raise _ProducerError("計画の検証機能を利用できません。", status="blocked")
    spec = importlib.util.spec_from_file_location("roadmap_plan_contract", PLAN_CONTRACT)
    if spec is None or spec.loader is None:
        raise _ProducerError("計画の検証機能を利用できません。", status="blocked")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("roadmap_plan_contract", module)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        sys.modules.pop("roadmap_plan_contract", None)
        raise _ProducerError("計画の検証機能を利用できません。", status="blocked") from error
    _PLAN_CONTRACT_MODULE = module
    return module


def _parse_model(plan_text: str, plan_model: dict[str, Any] | None) -> dict[str, Any]:
    if plan_model is not None:
        if not isinstance(plan_model, dict):
            raise _ProducerError("plan_modelはobjectで指定してください。", status="invalid")
        return plan_model
    try:
        module = _load_plan_contract_module()
        model = module.parse_plan_contract(plan_text)  # type: ignore[attr-defined]
    except _ProducerError:
        raise
    except Exception as error:
        raise _ProducerError("計画の構造を確認できません。", status="invalid") from error
    if not isinstance(model, dict):
        raise _ProducerError("計画の構造を確認できません。", status="invalid")
    return model


def _task_id(number: str) -> str:
    return "task-" + number.encode("utf-8").hex()


def _topological_ranks(numbers: list[str], edges: list[dict[str, str]]) -> dict[str, int]:
    index = {number: position for position, number in enumerate(numbers)}
    adjacency: dict[str, list[str]] = {number: [] for number in numbers}
    indegree = {number: 0 for number in numbers}
    for edge in edges:
        source = edge["from"]
        target = edge["to"]
        adjacency[source].append(target)
        indegree[target] += 1
    available = [index[number] for number in numbers if indegree[number] == 0]
    heapq.heapify(available)
    ranks = {number: 0 for number in numbers}
    visited = 0
    while available:
        source_index = heapq.heappop(available)
        source = numbers[source_index]
        visited += 1
        for target in adjacency[source]:
            ranks[target] = max(ranks[target], ranks[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(available, index[target])
    if visited != len(numbers):
        raise _ProducerError("明示された依存関係にcycleがあります。", status="invalid")
    return ranks


def _text_units(value: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WFA" else 1 for char in value)


def _node_width(title: str) -> int:
    return max(92, math.ceil(_text_units(title) * 6.8 + 6))


def _prepare_projection(plan_text: str, plan_model: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan_text, str):
        raise _ProducerError("計画本文は文字列で指定してください。", status="invalid")
    try:
        raw_bytes = plan_text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _ProducerError("計画本文をUTF-8へ変換できません。", status="invalid") from error
    plan_hash = _sha256_bytes(raw_bytes)
    if len(raw_bytes) > RAW_PLAN_LIMIT:
        raise _ProducerError("計画本文が1 MiBの上限を超えています。", status="invalid")
    model = _parse_model(plan_text, plan_model)
    tasks_value = model.get("tasks")
    if not isinstance(tasks_value, list):
        raise _ProducerError("計画modelのtasksが配列ではありません。", status="invalid")
    if len(tasks_value) > TASK_LIMIT:
        raise _ProducerError("Task数が128件の上限を超えています。", status="invalid")
    tasks: list[dict[str, str]] = []
    numbers: list[str] = []
    seen_numbers: set[str] = set()
    for task in tasks_value:
        if not isinstance(task, dict):
            raise _ProducerError("canonical Plan taskがobjectではありません。", status="invalid")
        number = task.get("number")
        title = task.get("title")
        if not isinstance(number, str) or not NUMBER_RE.fullmatch(number):
            raise _ProducerError("Task番号がcanonical形式ではありません。", status="invalid")
        if number in seen_numbers:
            raise _ProducerError(f"重複Task番号です: {number}", status="invalid")
        if not isinstance(title, str) or not title:
            raise _ProducerError(f"Task {number} のtitleが空です。", status="invalid")
        if len(title) > TITLE_LIMIT:
            raise _ProducerError(f"Task {number} のtitleが512文字を超えています。", status="invalid")
        seen_numbers.add(number)
        numbers.append(number)
        tasks.append({"number": number, "title": title})

    edges_value = model.get("edges", [])
    if not isinstance(edges_value, list):
        raise _ProducerError("計画modelのedgesが配列ではありません。", status="invalid")
    if len(edges_value) > EDGE_LIMIT:
        raise _ProducerError("依存edge数が256本の上限を超えています。", status="invalid")
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    known_numbers = set(numbers)
    for edge in edges_value:
        if not isinstance(edge, dict):
            raise _ProducerError("canonical Plan edgeがobjectではありません。", status="invalid")
        source = edge.get("from")
        target = edge.get("to")
        if not isinstance(source, str) or not isinstance(target, str):
            raise _ProducerError("依存edgeのfrom/toが文字列ではありません。", status="invalid")
        if source not in known_numbers or target not in known_numbers:
            raise _ProducerError("依存edgeが存在しないTaskを参照しています。", status="invalid")
        pair = (source, target)
        if pair in seen_edges:
            raise _ProducerError(f"重複edgeです: {source} → {target}", status="invalid")
        if source == target:
            raise _ProducerError(f"自己依存edgeです: {source}", status="invalid")
        seen_edges.add(pair)
        edges.append({"from": source, "to": target})

    _topological_ranks(numbers, edges)
    overview_model = {"tasks": tasks, "edges": edges}
    return {
        "rawBytes": raw_bytes,
        "planSha256": plan_hash,
        "overviewModel": overview_model,
        "overviewModelSha256": _sha256_json(overview_model),
        "edgeSha256": _sha256_json(edges),
        "taskIds": numbers,
        "parserVersion": model.get("parserVersion") if isinstance(model.get("parserVersion"), str) else "",
        "ranks": _topological_ranks(numbers, edges),
    }


def project_plan(plan_text: str, plan_model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the hash-bound, semantic-only overview projection."""
    return _prepare_projection(plan_text, plan_model)


def _workflow_spec(projection: dict[str, Any]) -> dict[str, Any]:
    tasks = projection["overviewModel"]["tasks"]
    edges = projection["overviewModel"]["edges"]
    numbers = projection["taskIds"]
    ranks: dict[str, int] = projection["ranks"]
    lanes: list[dict[str, str]] = []
    node_layout: dict[str, tuple[str, int, float]] = {}
    if not edges:
        lane_id = "plan-independent"
        lanes.append({"id": lane_id, "label": "依存関係なし（表示用）"})
        rows = max(1, math.ceil(len(tasks) / 6))
        for index, number in enumerate(numbers):
            row = index // 6
            node_layout[number] = (lane_id, index % 6, (row - (rows - 1) / 2) * ROW_PITCH)
    else:
        maximum_rank = max(ranks.values(), default=0)
        band_count = maximum_rank // 6 + 1
        for band in range(band_count):
            start = band * 6
            end = min(start + 5, maximum_rank)
            lanes.append({"id": f"plan-band-{band}", "label": f"表示帯 {start}–{end}（深度折返し）"})
        grouped: dict[tuple[int, int], list[str]] = {}
        for number in numbers:
            rank = ranks[number]
            grouped.setdefault((rank // 6, rank % 6), []).append(number)
        for (band, col), group in grouped.items():
            rows = len(group)
            for row, number in enumerate(group):
                node_layout[number] = (
                    f"plan-band-{band}",
                    col,
                    (row - (rows - 1) / 2) * ROW_PITCH,
                )

    nodes: list[dict[str, Any]] = []
    for task in tasks:
        number = task["number"]
        lane, col, y_offset = node_layout[number]
        node: dict[str, Any] = {
            "id": _task_id(number),
            "lane": lane,
            "col": col,
            "type": "external",
            "label": task["title"],
            "width": _node_width(task["title"]),
        }
        if y_offset:
            node["yOffset"] = y_offset
        nodes.append(node)

    spec_edges: list[dict[str, str]] = []
    for edge in edges:
        source = edge["from"]
        target = edge["to"]
        source_lane = node_layout[source][0]
        target_lane = node_layout[target][0]
        spec_edge: dict[str, str] = {
            "id": f"edge-{source.encode('utf-8').hex()}-{target.encode('utf-8').hex()}",
            "from": _task_id(source),
            "to": _task_id(target),
            "route": "drop" if source_lane != target_lane else "auto",
        }
        if source_lane != target_lane:
            spec_edge["fromSide"] = "bottom"
            spec_edge["toSide"] = "top"
        spec_edges.append(spec_edge)

    spec: dict[str, Any] = {
        "schema_version": 2,
        "diagram_type": "workflow",
        "meta": {
            "title": "計画の依存関係",
            "animation": "none",
            "quality_profile": "standard",
            "legend": {"mode": "hidden"},
        },
        "lanes": lanes,
        "nodes": nodes,
        "edges": spec_edges,
    }
    _validate_workflow_spec(spec)
    if len(_canonical_json(spec).encode("utf-8")) > HTML_LIMIT:
        raise _ProducerError("Archify workflow入力が8 MiBの上限を超えています。", status="invalid")
    return spec


def build_workflow_spec(plan_text: str, plan_model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the Archify schema-v2 workflow IR without invoking Node."""
    projection = _prepare_projection(plan_text, plan_model)
    if not projection["taskIds"]:
        raise _ProducerError("計画にTaskがないためworkflow nodeを作れません。", status="empty")
    return _workflow_spec(projection)


def _validate_workflow_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != 2 or spec.get("diagram_type") != "workflow":
        raise _ProducerError("生成したworkflow specのschemaが不正です。", status="error")
    meta = spec.get("meta")
    if not isinstance(meta, dict) or meta.get("animation") != "none" or meta.get("legend") != {"mode": "hidden"}:
        raise _ProducerError("workflow specの安全なmeta設定が不正です。", status="error")
    lanes = spec.get("lanes")
    nodes = spec.get("nodes")
    edges = spec.get("edges")
    if not isinstance(lanes, list) or not lanes or not isinstance(nodes, list) or not nodes or not isinstance(edges, list):
        raise _ProducerError("workflow specの必須配列が不正です。", status="error")
    lane_ids = {lane.get("id") for lane in lanes if isinstance(lane, dict)}
    if len(lane_ids) != len(lanes) or any(not isinstance(value, str) or not ID_RE.fullmatch(value) for value in lane_ids):
        raise _ProducerError("workflow specのlane IDが不正です。", status="error")
    node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise _ProducerError("workflow spec nodeが不正です。", status="error")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not ID_RE.fullmatch(node_id) or node_id in node_ids:
            raise _ProducerError("workflow spec node IDが不正です。", status="error")
        if node.get("lane") not in lane_ids or node.get("type") != "external":
            raise _ProducerError("workflow spec nodeのlane/typeが不正です。", status="error")
        if not isinstance(node.get("col"), int) or not 0 <= node["col"] <= 5:
            raise _ProducerError("workflow spec nodeのcolが不正です。", status="error")
        if not isinstance(node.get("label"), str) or not node["label"]:
            raise _ProducerError("workflow spec node labelが空です。", status="error")
        for key in ("width", "yOffset"):
            if key in node and (not isinstance(node[key], (int, float)) or not math.isfinite(node[key])):
                raise _ProducerError("workflow spec nodeの座標が不正です。", status="error")
        node_ids.add(node_id)
    edge_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("from") not in node_ids or edge.get("to") not in node_ids:
            raise _ProducerError("workflow spec edge endpointが不正です。", status="error")
        pair = (edge["from"], edge["to"])
        if pair in edge_pairs:
            raise _ProducerError("workflow specに重複edgeがあります。", status="error")
        edge_pairs.add(pair)


def _read_fixed_file(path: Path, expected_hash: str, *, maximum: int, label: str) -> bytes:
    """Read a pinned regular file without following a replacement link."""
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise OSError("not a regular file")
        if info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > maximum:
            raise OSError("unsafe file metadata")
        data = path.read_bytes()
    except OSError as error:
        raise _RendererBlocked(f"{label}を検証できません。") from error
    if len(data) > maximum or _sha256_bytes(data) != expected_hash:
        raise _RendererBlocked(f"{label}の固定hashが一致しません。")
    return data


def _read_descriptor() -> dict[str, Any]:
    if not EXPECTED_CONTAINER_DESCRIPTOR_SHA256 or not SHA256_RE.fullmatch(EXPECTED_CONTAINER_DESCRIPTOR_SHA256):
        raise _RendererBlocked("container descriptorの固定hashが未確定です。")
    data = _read_fixed_file(
        CONTAINER_CONFIG_PATH,
        EXPECTED_CONTAINER_DESCRIPTOR_SHA256,
        maximum=128 * 1024,
        label="container descriptor",
    )
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_json_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _RendererBlocked("container descriptorを読み込めません。") from error
    if not isinstance(value, dict):
        raise _RendererBlocked("container descriptorの形式が不正です。")
    return value


def _verify_container_descriptor(descriptor: dict[str, Any], revision: str) -> None:
    required = {
        "schemaVersion", "backend", "policyId", "image", "baseImage",
        "sourceManifestSha256", "sourceConfigSha256", "bridgeSha256",
        "entrypointSha256", "seccompSha256", "dockerExecutable",
        "dockerRealpath", "dockerSha256", "nodeExecutable", "nodeSha256",
        "nodeVersion", "chromeExecutable", "chromeSha256", "chromeVersion",
    }
    if not required.issubset(descriptor):
        raise _RendererBlocked("container descriptorの必須pinが不足しています。", revision=revision)
    if descriptor.get("schemaVersion") != 1 or descriptor.get("backend") != EXPECTED_CONTAINER_BACKEND:
        raise _RendererBlocked("container descriptorのschemaが不正です。", revision=revision)
    if descriptor.get("policyId") != EXPECTED_CONTAINER_POLICY or descriptor.get("baseImage") != EXPECTED_BASE_IMAGE:
        raise _RendererBlocked("container descriptorのpolicy/imageが不正です。", revision=revision)
    image = descriptor.get("image")
    if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image) or image == "sha256:" + "0" * 64:
        raise _RendererBlocked("container imageの固定IDが不正です。", revision=revision)
    for key in ("sourceManifestSha256", "sourceConfigSha256", "bridgeSha256", "entrypointSha256", "seccompSha256", "dockerSha256", "nodeSha256", "chromeSha256"):
        value = descriptor.get(key)
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise _RendererBlocked("container descriptorのhash pinが不正です。", revision=revision)
    if (
        descriptor["sourceManifestSha256"] != EXPECTED_MANIFEST_SHA256
        or descriptor["sourceConfigSha256"] != EXPECTED_CONFIG_SHA256
        or descriptor["seccompSha256"] != EXPECTED_SECCOMP_SHA256
        or descriptor["dockerExecutable"] != EXPECTED_DOCKER_EXECUTABLE
        or descriptor["dockerRealpath"] != EXPECTED_DOCKER_REALPATH
        or descriptor["dockerSha256"] != EXPECTED_DOCKER_SHA256
        or descriptor["nodeExecutable"] != EXPECTED_NODE_EXECUTABLE
        or descriptor["nodeSha256"] != EXPECTED_NODE_SHA256
        or descriptor["nodeVersion"] != EXPECTED_NODE_VERSION
        or descriptor["chromeExecutable"] != EXPECTED_CHROME_EXECUTABLE
        or descriptor["chromeSha256"] != EXPECTED_CHROME_SHA256
        or descriptor["chromeVersion"] != EXPECTED_CHROME_VERSION
    ):
        raise _RendererBlocked("container descriptorの固定pinが一致しません。", revision=revision)
    for key in ("dockerExecutable", "dockerRealpath", "nodeExecutable", "chromeExecutable"):
        if not isinstance(descriptor[key], str) or "\x00" in descriptor[key]:
            raise _RendererBlocked("container descriptorのpathが不正です。", revision=revision)


def _verify_docker_executable(descriptor: dict[str, Any], revision: str) -> None:
    path = Path(EXPECTED_DOCKER_EXECUTABLE)
    try:
        target = path.resolve(strict=True)
        info = target.lstat()
        digest = _sha256_bytes(target.read_bytes())
    except OSError as error:
        raise _RendererBlocked("固定Dockerを実行できません。", revision=revision) from error
    if (
        target != Path(EXPECTED_DOCKER_REALPATH)
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or digest != descriptor["dockerSha256"]
        or not os.access(target, os.X_OK)
    ):
        raise _RendererBlocked("固定Dockerを実行できません。", revision=revision)


def _load_config() -> tuple[str, dict[str, Any]]:
    """Load and cross-pin the source config, descriptor, and local policy file."""
    revision = "unknown"
    try:
        source_bytes = _read_fixed_file(CONFIG_PATH, EXPECTED_CONFIG_SHA256, maximum=256 * 1024, label="Archify固定設定")
        source = json.loads(source_bytes.decode("utf-8"), object_pairs_hook=_unique_json_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _RendererBlocked("Archify固定設定を読み込めません。", revision=revision) from error
    if not isinstance(source, dict):
        raise _RendererBlocked("Archify固定設定の形式が不正です。", revision=revision)
    revision_value = source.get("revision")
    revision = revision_value if isinstance(revision_value, str) else "unknown"
    if revision != EXPECTED_REVISION or not re.fullmatch(r"[A-Za-z0-9._-]+", revision):
        raise _RendererBlocked("Archify固定revisionが不正です。", revision="unknown")
    files = source.get("files")
    if not isinstance(files, list) or len(files) != SOURCE_FILE_COUNT or _manifest_sha256(files) != EXPECTED_MANIFEST_SHA256:
        raise _RendererBlocked("固定source manifestが一致しません。", revision=revision)
    if source.get("nodeExecutable") != EXPECTED_NODE_EXECUTABLE or source.get("chromeExecutable") != EXPECTED_CHROME_EXECUTABLE:
        raise _RendererBlocked("Archify固定runtime pinが不正です。", revision=revision)

    descriptor = _read_descriptor()
    _verify_container_descriptor(descriptor, revision)
    _read_fixed_file(SECCOMP_PATH, EXPECTED_SECCOMP_SHA256, maximum=256 * 1024, label="container seccomp")
    _read_fixed_file(RENDERER_PATH, descriptor["bridgeSha256"], maximum=2 * 1024 * 1024, label="Archify renderer bridge")
    _read_fixed_file(CONTAINER_ENTRYPOINT_PATH, descriptor["entrypointSha256"], maximum=256 * 1024, label="container entrypoint")
    _verify_docker_executable(descriptor, revision)
    return revision, descriptor


def _stop_host_process(process: subprocess.Popen[bytes]) -> None:
    """Stop only the fixed Docker client process group; container cleanup is separate."""
    if process.poll() is not None:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=0)
        return
    for sig, method in ((signal.SIGTERM, process.terminate), (signal.SIGKILL, process.kill)):
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(process.pid, sig)
        with contextlib.suppress(OSError, ProcessLookupError):
            method()
        try:
            process.wait(timeout=0.5)
            if process.poll() is not None:
                return
        except (OSError, subprocess.TimeoutExpired):
            continue


def _bounded_process(
    command: list[str],
    input_bytes: bytes,
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    stdout_limit: int = STREAM_LIMIT,
    stderr_limit: int = STREAM_LIMIT,
) -> tuple[int, bytes, bytes]:
    """Run a host helper with bounded pipes and one monotonic deadline."""
    if timeout <= 0:
        raise _RendererFailure("container操作の期限を超えました。")
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _RendererBlocked("固定Docker processを起動できません。") from error
    if process.stdin is None or process.stdout is None or process.stderr is None:
        _stop_host_process(process)
        raise _RendererFailure("containerのpipeを確保できません。")
    selector = selectors.DefaultSelector()
    output: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    streams = ((process.stdin, "stdin"), (process.stdout, "stdout"), (process.stderr, "stderr"))
    input_offset = 0
    started = time.monotonic()
    try:
        for stream, _name in streams:
            os.set_blocking(stream.fileno(), False)
        if input_bytes:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise _RendererFailure("container操作が60秒の期限を超えました。")
            for key, mask in selector.select(min(remaining, 0.1)):
                stream = key.fileobj
                kind = key.data
                if kind == "stdin" and mask & selectors.EVENT_WRITE:
                    if input_offset < len(input_bytes):
                        try:
                            input_offset += os.write(stream.fileno(), input_bytes[input_offset:])
                        except BlockingIOError:
                            continue
                    if input_offset >= len(input_bytes):
                        selector.unregister(stream)
                        stream.close()
                    continue
                if kind not in {"stdout", "stderr"} or not mask & selectors.EVENT_READ:
                    continue
                try:
                    chunk = os.read(stream.fileno(), 65_536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                output[kind].extend(chunk)
                limit = stdout_limit if kind == "stdout" else stderr_limit
                if len(output[kind]) > limit:
                    raise _RendererFailure("container processの出力上限を超えました。")
        return_code = process.wait(timeout=max(0.0, timeout - (time.monotonic() - started)))
        return return_code, bytes(output["stdout"]), bytes(output["stderr"])
    except _ProducerError:
        raise
    except (OSError, subprocess.TimeoutExpired) as error:
        raise _RendererFailure("container processとの通信に失敗しました。") from error
    finally:
        if process.poll() is None:
            _stop_host_process(process)
        selector.close()
        for stream, _name in streams:
            with contextlib.suppress(Exception):
                stream.close()


def _docker_environment() -> dict[str, str]:
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, ImportError):
        raise _RendererBlocked("固定Dockerの実行環境を準備できません。")
    # This environment is for the host Docker client only. Nothing here is
    # forwarded with --env into the container.
    return {
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
        "HOME": home,
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }


def _docker_command(*args: str) -> list[str]:
    if any("\x00" in arg for arg in args):
        raise _RendererFailure("container commandが不正です。")
    return [EXPECTED_DOCKER_EXECUTABLE, "--context", EXPECTED_DOCKER_CONTEXT, *args]


def _docker_call(
    args: list[str], *, deadline: float, input_bytes: bytes = b"", stdout_limit: int = DOCKER_CALL_OUTPUT_LIMIT,
    check: bool = True,
) -> tuple[int, bytes, bytes]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _RendererFailure("container操作が60秒の期限を超えました。")
    result = _bounded_process(
        _docker_command(*args),
        input_bytes,
        cwd=ROOT,
        env=_docker_environment(),
        timeout=remaining,
        stdout_limit=stdout_limit,
        stderr_limit=CONTAINER_STDERR_LIMIT,
    )
    if check and result[0] != 0:
        raise _RendererFailure("container操作に失敗しました。")
    return result


def _decode_json_object(raw: bytes, *, maximum: int, label: str) -> dict[str, Any]:
    if len(raw) > maximum:
        raise _RendererFailure(f"{label}が上限を超えました。")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise _RendererFailure(f"{label}を検証できません。") from error
    if not isinstance(value, dict):
        raise _RendererFailure(f"{label}の形式が不正です。")
    return value


def _verify_context(*, deadline: float) -> None:
    _code, stdout, _stderr = _docker_call(
        ["context", "inspect", "--format={{json .Endpoints.docker.Host}}", EXPECTED_DOCKER_CONTEXT],
        deadline=deadline,
        stdout_limit=4096,
    )
    try:
        endpoint = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _RendererBlocked("Docker context endpointを検証できません。") from error
    if endpoint != EXPECTED_DOCKER_ENDPOINT:
        raise _RendererBlocked("Docker context endpointが固定値と一致しません。")


def _verify_image(*, image: str, deadline: float) -> None:
    _code, stdout, _stderr = _docker_call(
        ["image", "inspect", "--format={{json .}}", image], deadline=deadline
    )
    info = _decode_json_object(stdout, maximum=DOCKER_CALL_OUTPUT_LIMIT, label="container image inspect")
    if info.get("Id") != image:
        raise _RendererBlocked("derived image IDが一致しません。")


def _container_name() -> str:
    token = f"{os.getpid():x}-{time.monotonic_ns() & 0xFFFFFFF:x}-{threading.get_ident() & 0xFFFF:x}"
    return f"archify-plan-{token}"[:63]


CONTAINER_LABEL_KEY = "io.codex.archify.producer"


def _container_create_command(descriptor: dict[str, Any], name: str, label: str) -> list[str]:
    image = descriptor["image"]
    seccomp = str(SECCOMP_PATH)
    return _docker_command(
        "create", "--pull", "never", "--init", "--interactive", "--name", name,
        "--label", f"{CONTAINER_LABEL_KEY}={label}",
        "--user", "1000:1000", "--network", "none", "--ipc", "private",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
        "--security-opt", "apparmor=docker-default", "--security-opt", f"seccomp={seccomp}",
        "--cpus", "1", "--memory", "1g", "--memory-swap", "1g", "--pids-limit", "128",
        "--shm-size", "64m", "--ulimit", "cpu=60:61", "--ulimit",
        f"fsize={CONTAINER_FSIZE_LIMIT}:{CONTAINER_FSIZE_LIMIT}",
        "--ulimit", "nofile=512:512", "--ulimit", "core=0:0",
        "--tmpfs", "/tmp/run:rw,noexec,nosuid,nodev,size=32m,nr_inodes=128,uid=1000,gid=1000,mode=700",
        "--tmpfs", "/tmp/browser:rw,noexec,nosuid,nodev,size=64m,nr_inodes=4096,uid=1000,gid=1000,mode=700",
        "--workdir", "/tmp/run", "--env", "HOME=/tmp/browser", "--env", "TMPDIR=/tmp/browser",
        "--env", "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright",
        "--env", "LANG=C", "--env", "LC_ALL=C", "--env", "TZ=UTC",
        "--env", f"{SANDBOX_MARKER}={EXPECTED_CONTAINER_POLICY}",
        "--env", f"{SANDBOX_PROFILE_HASH_MARKER}={descriptor['seccompSha256']}",
        "--env", f"ARCHIFY_CONTAINER_IMAGE={image}",
        "--entrypoint", EXPECTED_NODE_EXECUTABLE, image, "/app/scripts/archify_container.mjs",
    )


def _inspect_map(value: Any, key: str) -> dict[str, Any]:
    result = value.get(key) if isinstance(value, dict) else None
    if not isinstance(result, dict):
        raise _RendererBlocked(f"container inspectの{key}が不正です。")
    return result


def _parse_tmpfs_value(value: Any) -> tuple[set[str], dict[str, str]]:
    if not isinstance(value, str) or not value:
        raise _RendererBlocked("container inspectのtmpfs tokenが不正です。")
    flags: set[str] = set()
    values: dict[str, str] = {}
    for token in value.split(","):
        if not token or token != token.strip() or any(char.isspace() for char in token):
            raise _RendererBlocked("container inspectのtmpfs tokenが不正です。")
        if "=" in token:
            key, item = token.split("=", 1)
            if not key or not item or key in values or key in flags:
                raise _RendererBlocked("container inspectのtmpfs key/valueが不正です。")
            values[key] = item
        elif token in flags:
            raise _RendererBlocked("container inspectのtmpfs flagが不正です。")
        else:
            flags.add(token)
    return flags, values


def _tmpfs_size_bytes(value: str) -> int:
    try:
        if re.fullmatch(r"[0-9]+m", value):
            return int(value[:-1]) * 1024 * 1024
        if re.fullmatch(r"[0-9]+", value):
            return int(value)
    except (ValueError, OverflowError) as error:
        raise _RendererBlocked("container inspectのtmpfs sizeが不正です。") from error
    raise _RendererBlocked("container inspectのtmpfs sizeが不正です。")


def _verify_container_inspect(info: dict[str, Any], descriptor: dict[str, Any], name: str) -> str:
    if (
        info.get("Name") != f"/{name}"
        or not isinstance(info.get("Id"), str)
        or not re.fullmatch(r"[0-9a-f]{12,64}", info["Id"])
        or info.get("AppArmorProfile") != "docker-default"
    ):
        raise _RendererBlocked("container inspectのidentityが不正です。")
    config = _inspect_map(info, "Config")
    if config.get("Image") not in {descriptor["image"], descriptor["image"][7:]}:
        raise _RendererBlocked("container inspectのimageが一致しません。")
    if config.get("User") != "1000:1000" or config.get("WorkingDir") != "/tmp/run" or config.get("OpenStdin") is not True or config.get("Tty") is not False or config.get("Entrypoint") != [EXPECTED_NODE_EXECUTABLE] or config.get("Cmd") != ["/app/scripts/archify_container.mjs"]:
        raise _RendererBlocked("container inspectのentrypointが不正です。")
    env_values: dict[str, str] = {}
    for item in config.get("Env", []):
        if not isinstance(item, str) or "=" not in item:
            raise _RendererBlocked("container inspectのenvが不正です。")
        key, value = item.split("=", 1)
        if key in env_values:
            raise _RendererBlocked("container inspectのenvに重複があります。")
        env_values[key] = value
    expected_env = {
        "HOME": "/tmp/browser", "TMPDIR": "/tmp/browser", "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
        SANDBOX_MARKER: EXPECTED_CONTAINER_POLICY,
        SANDBOX_PROFILE_HASH_MARKER: descriptor["seccompSha256"],
        "ARCHIFY_CONTAINER_IMAGE": descriptor["image"],
    }
    if any(env_values.get(key) != value for key, value in expected_env.items()):
        raise _RendererBlocked("container inspectの固定envが一致しません。")
    if any(key in env_values for key in ("NODE_OPTIONS", "NODE_PATH", "LD_PRELOAD", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")):
        raise _RendererBlocked("container inspectに禁止envがあります。")

    host = _inspect_map(info, "HostConfig")
    if (
        host.get("NetworkMode") != "none" or host.get("IpcMode") != "private" or host.get("PidMode") not in ("", "private")
        or host.get("ReadonlyRootfs") is not True or host.get("Privileged") is True
        or host.get("CapAdd") not in (None, []) or host.get("CapDrop") not in (["ALL"], ["all"])
        or host.get("Memory") != 1024 * 1024 * 1024 or host.get("MemorySwap") != 1024 * 1024 * 1024
        or host.get("NanoCpus") != 1_000_000_000 or host.get("PidsLimit") != 128
        or host.get("ShmSize") != 64 * 1024 * 1024
        or host.get("Binds") not in (None, [])
        or host.get("Devices") not in (None, [])
        or host.get("DeviceRequests") not in (None, [])
    ):
        raise _RendererBlocked("container inspectの隔離/資源条件が一致しません。")
    security = host.get("SecurityOpt")
    if not isinstance(security, list) or not any(value in {"no-new-privileges=true", "no-new-privileges:true"} for value in security) or "apparmor=docker-default" not in security:
        raise _RendererBlocked("container inspectのsecurity profileが一致しません。")
    seccomp_values = [value[len("seccomp="):] for value in security if isinstance(value, str) and value.startswith("seccomp=")]
    if len(seccomp_values) != 1:
        raise _RendererBlocked("container inspectのseccomp profileが不足しています。")
    try:
        expected_seccomp = json.loads(SECCOMP_PATH.read_text(encoding="utf-8"))
        actual_seccomp = json.loads(seccomp_values[0])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _RendererBlocked("container inspectのseccomp profileを検証できません。") from error
    if actual_seccomp != expected_seccomp:
        raise _RendererBlocked("container inspectのseccomp profileが固定値と一致しません。")
    limits = {item.get("Name"): (item.get("Soft"), item.get("Hard")) for item in host.get("Ulimits", []) if isinstance(item, dict)}
    if any(limits.get(key) != pair for key, pair in {"cpu": (60, 61), "fsize": (CONTAINER_FSIZE_LIMIT, CONTAINER_FSIZE_LIMIT), "nofile": (512, 512), "core": (0, 0)}.items()):
        raise _RendererBlocked("container inspectのulimitが一致しません。")
    tmpfs = host.get("Tmpfs")
    required_tmpfs = {
        "/tmp/run": (32 * 1024 * 1024, "128"),
        "/tmp/browser": (64 * 1024 * 1024, "4096"),
    }
    if not isinstance(tmpfs, dict) or set(tmpfs) != set(required_tmpfs):
        raise _RendererBlocked("container inspectのtmpfsが不足しています。")
    for path, (size_bytes, inode_value) in required_tmpfs.items():
        flags, values = _parse_tmpfs_value(tmpfs[path])
        if flags != {"rw", "noexec", "nosuid", "nodev"} or set(values) != {"size", "nr_inodes", "uid", "gid", "mode"}:
            raise _RendererBlocked("container inspectのtmpfs tokenが一致しません。")
        if (
            _tmpfs_size_bytes(values["size"]) != size_bytes
            or values["nr_inodes"] != inode_value
            or values["uid"] != "1000"
            or values["gid"] != "1000"
            or values["mode"] not in {"700", "0700"}
        ):
            raise _RendererBlocked("container inspectのtmpfs条件が一致しません。")
    mounts = info.get("Mounts")
    if not isinstance(mounts, list):
        raise _RendererBlocked("container inspectのmount情報が不正です。")
    allowed_mounts = {"/tmp/run", "/tmp/browser"}
    if any(not isinstance(mount, dict) or mount.get("Type") != "tmpfs" or mount.get("Destination") not in allowed_mounts for mount in mounts):
        raise _RendererBlocked("container inspectにhost mountがあります。")
    if {mount.get("Destination") for mount in mounts if isinstance(mount, dict)} - allowed_mounts:
        raise _RendererBlocked("container inspectのtmpfs destinationが不正です。")
    state = info.get("State")
    if isinstance(state, dict) and state.get("Running") is True:
        raise _RendererBlocked("container inspectがstart前にrunningです。")
    return info["Id"]


def _cleanup_container(name: str, container_id: str | None, label: str, *, deadline: float) -> None:
    """Remove by both known identity and unique label, then prove absence."""
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,62}", name) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,62}", label):
        raise _RendererFailure("container cleanup identityが不正です。")
    if container_id is not None and not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        raise _RendererFailure("container cleanup IDが不正です。")
    errors: list[_ProducerError] = []

    def call(args: list[str]) -> tuple[int, bytes, bytes] | None:
        try:
            result = _docker_call(args, deadline=deadline, stdout_limit=4096, check=False)
        except _ProducerError as error:
            errors.append(error)
            return None
        if result[0] == 0:
            return result
        if args and args[0] == "rm":
            try:
                message = result[2].decode("utf-8").strip().casefold()
            except UnicodeDecodeError:
                message = ""
            target = args[-1].casefold()
            if message.endswith(f"no such container: {target}") or message.endswith(f"no such object: {target}"):
                return result
        errors.append(_RendererFailure("container cleanup操作に失敗しました。"))
        return result

    def query(filter_value: str) -> list[str] | None:
        result = call(["ps", "-aq", "--filter", filter_value])
        if result is None or result[0] != 0:
            return None
        try:
            tokens = result[1].decode("ascii").split()
        except UnicodeDecodeError:
            errors.append(_RendererFailure("container cleanupのIDを検証できません。"))
            return []
        if any(not re.fullmatch(r"[0-9a-f]{12,64}", item) for item in tokens):
            errors.append(_RendererFailure("container cleanupのIDを検証できません。"))
        return [item for item in tokens if re.fullmatch(r"[0-9a-f]{12,64}", item)]

    targets = [value for value in (name, container_id) if isinstance(value, str)]
    for target in targets:
        call(["rm", "--force", target])
    label_filter = f"label={CONTAINER_LABEL_KEY}={label}"
    for _attempt in range(8):
        ids = query(label_filter)
        if ids is None:
            break
        for item in ids:
            call(["rm", "--force", item])
        if ids:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))
    residual = query(label_filter)
    if residual:
        errors.append(_RendererFailure("container cleanupを確認できません。"))
    for target, option in ((name, f"name=^{name}$"), (container_id, f"id={container_id}")):
        if not target:
            continue
        identity = query(option)
        if identity:
            errors.append(_RendererFailure("container identityの残存を確認しました。"))
    if errors:
        raise _RendererFailure("containerの停止を確認できません。") from errors[0]


def _decode_container_envelope(stdout: bytes, descriptor: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    envelope = _decode_json_object(stdout, maximum=CONTAINER_STDOUT_LIMIT, label="container envelope")
    if envelope.get("schemaVersion") != 1 or envelope.get("protocol") != EXPECTED_CONTAINER_PROTOCOL or envelope.get("ok") is not True:
        raise _RendererFailure("container envelopeのschemaが不正です。")
    receipt = envelope.get("receipt")
    raw = envelope.get("rawSvg")
    if not isinstance(receipt, dict) or not isinstance(raw, dict) or set(raw) != {"encoding", "bytes", "sha256", "data"}:
        raise _RendererFailure("container envelopeの成果物が不正です。")
    if raw.get("encoding") != "base64" or not isinstance(raw.get("bytes"), int) or not 1 <= raw["bytes"] <= SVG_LIMIT:
        raise _RendererFailure("container envelopeのSVGサイズが不正です。")
    encoded = raw.get("data")
    if not isinstance(encoded, str) or len(encoded) > ((SVG_LIMIT + 2) // 3) * 4:
        raise _RendererFailure("container envelopeのbase64が不正です。")
    try:
        raw_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise _RendererFailure("container envelopeのbase64を検証できません。") from error
    if base64.b64encode(raw_bytes).decode("ascii") != encoded or len(raw_bytes) != raw["bytes"] or raw.get("sha256") != _sha256_bytes(raw_bytes):
        raise _RendererFailure("container envelopeのSVG hashが一致しません。")
    _validate_bridge_receipt(
        receipt,
        revision=receipt.get("revision") if isinstance(receipt.get("revision"), str) else None,
        profile_hash=descriptor["seccompSha256"],
        renderer_config=descriptor,
    )
    return receipt, raw_bytes


def _invoke_renderer(
    spec_path: Path,
    run_dir: Path,
    renderer_config: dict[str, Any] | Path,
    *,
    timeout: float = RENDER_DEADLINE,
    revision: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    if not isinstance(renderer_config, dict):
        raise _RendererBlocked("container descriptorが必要です。", revision=revision or "unknown")
    if not _secure_mode(run_dir, 0o700) or not _secure_mode(spec_path, 0o600):
        raise _RendererFailure("Archify rendererの一時領域が安全ではありません。")
    try:
        if spec_path.resolve().parent != run_dir.resolve():
            raise _RendererFailure("Archify workflow入力が専用run directory外にあります。")
        spec_bytes = spec_path.read_bytes()
    except OSError as error:
        raise _RendererFailure("Archify workflow入力を読み込めません。") from error
    if len(spec_bytes) > CONTAINER_INPUT_LIMIT:
        raise _ProducerError("Archify workflow入力が1 MiBの上限を超えています。", status="invalid")
    end = time.monotonic() + timeout
    if end - time.monotonic() <= CONTAINER_CLEANUP_RESERVE:
        raise _RendererFailure("container cleanup用の期限を確保できません。")
    name = _container_name()
    label = name
    container_id: str | None = None
    primary_error: BaseException | None = None
    try:
        work_deadline = end - CONTAINER_CLEANUP_RESERVE
        _verify_context(deadline=work_deadline)
        _verify_image(image=renderer_config["image"], deadline=work_deadline)
        _code, created, _stderr = _docker_call(
            _container_create_command(renderer_config, name, label)[3:],
            deadline=work_deadline,
            stdout_limit=4096,
        )
        token = created.decode("ascii", "ignore").strip()
        if not re.fullmatch(r"[0-9a-f]{12,64}", token):
            raise _RendererFailure("container createのIDが不正です。")
        container_id = token
        _code, inspected, _stderr = _docker_call(
            ["inspect", "--format={{json .}}", container_id], deadline=work_deadline
        )
        info = _decode_json_object(inspected, maximum=DOCKER_CALL_OUTPUT_LIMIT, label="container inspect")
        container_id = _verify_container_inspect(info, renderer_config, name)
        start_limit = end - time.monotonic()
        if start_limit <= CONTAINER_CLEANUP_RESERVE:
            raise _RendererFailure("container start用の期限を確保できません。")
        return_code, stdout, _stderr = _bounded_process(
            _docker_command("start", "--attach", "--interactive", container_id),
            spec_bytes,
            cwd=ROOT,
            env=_docker_environment(),
            timeout=max(0.0, end - CONTAINER_CLEANUP_RESERVE - time.monotonic()),
            stdout_limit=CONTAINER_STDOUT_LIMIT,
            stderr_limit=CONTAINER_STDERR_LIMIT,
        )
        if return_code != 0:
            raise _RendererFailure("Archify renderer containerが失敗しました。")
        receipt, raw_bytes = _decode_container_envelope(stdout, renderer_config)
        if revision is not None and receipt.get("revision") != revision:
            raise _RendererFailure("renderer receiptのrevisionが一致しません。")
        return receipt, raw_bytes
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            _cleanup_container(name, container_id, label, deadline=end)
        except _ProducerError as cleanup_error:
            if primary_error is None:
                raise
            raise _RendererFailure("containerの停止を確認できません。") from cleanup_error


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _namespace(tag: str) -> str | None:
    return tag[1 : tag.find("}")] if tag.startswith("{") and "}" in tag else None


def _validate_css_value(value: str) -> None:
    if CSS_ESCAPE_RE.search(value):
        raise _RendererFailure("SVG CSS escapeを拒否しました。")
    functions = list(CSS_URL_FUNCTION_RE.finditer(value))
    for match in functions:
        if not SAFE_FRAGMENT_URL_RE.fullmatch(match.group(0)):
            raise _RendererFailure("SVG CSS外部参照を拒否しました。")
    if CSS_URL_RE.search(CSS_URL_FUNCTION_RE.sub("", value)):
        raise _RendererFailure("SVG CSS外部参照を拒否しました。")
    if CSS_IMPORT_RE.search(value):
        raise _RendererFailure("SVG CSS importを拒否しました。")


def _validate_svg(raw_bytes: bytes) -> tuple[str, str]:
    if len(raw_bytes) > SVG_LIMIT:
        raise _RendererFailure("SVGが4 MiBの上限を超えました。")
    try:
        text = raw_bytes.decode("utf-8")
        if FORBIDDEN_XML_RE.search(text):
            raise _RendererFailure("SVGのDTD/entity/processing instructionを拒否しました。")
        root = ET.fromstring(text)
    except (UnicodeDecodeError, ET.ParseError) as error:
        raise _RendererFailure("SVG XMLを安全に解析できません。") from error
    if root.tag != f"{{{SVG_NAMESPACE}}}svg" or not re.search(r"<svg(?:\s|>)", text, re.IGNORECASE):
        raise _RendererFailure("SVG rootが不正です。")
    stack: list[tuple[ET.Element, int]] = [(root, 0)]
    index = 0
    while stack:
        element, depth = stack.pop()
        index += 1
        if index > SVG_ELEMENT_LIMIT:
            raise _RendererFailure("SVG element数が上限を超えました。")
        if depth > SVG_DEPTH_LIMIT:
            raise _RendererFailure("SVGの入れ子深度が上限を超えました。")
        if not isinstance(element.tag, str):
            raise _RendererFailure("SVG element名が不正です。")
        if _namespace(element.tag) != SVG_NAMESPACE:
            raise _RendererFailure("SVG element namespaceを拒否しました。")
        name = _local_name(element.tag)
        if name not in SVG_ALLOWED_ELEMENTS:
            raise _RendererFailure(f"SVG element {name}を拒否しました。")
        if name == "svg" and depth != 0:
            raise _RendererFailure("SVG nested rootを拒否しました。")
        for raw_name, value in element.attrib.items():
            attr_name = _local_name(raw_name)
            namespace = _namespace(raw_name)
            if namespace is not None and namespace not in {XML_NAMESPACE, XLINK_NAMESPACE}:
                raise _RendererFailure("SVG attribute namespaceを拒否しました。")
            if attr_name.startswith("on"):
                raise _RendererFailure("SVG event handlerを拒否しました。")
            if attr_name in SVG_SMIL_ATTRIBUTES:
                raise _RendererFailure("SVG SMIL animation attributeを拒否しました。")
            if attr_name == "style":
                _validate_css_value(value)
            if raw_name in {"href", "src", "action", "resource", "xlink:href"} or attr_name in {"href", "src", "action", "resource"}:
                if not value.startswith("#"):
                    raise _RendererFailure("SVG外部URLを拒否しました。")
            if CSS_URL_RE.search(value):
                _validate_css_value(value)
            if URL_RE.search(value) and not value.startswith("#"):
                allowed_namespace = value in {SVG_NAMESPACE, XLINK_NAMESPACE, XML_NAMESPACE}
                if not allowed_namespace:
                    raise _RendererFailure("SVG外部URLを拒否しました。")
        if name == "style":
            style_text = "".join(element.itertext())
            _validate_css_value(style_text)
            if URL_RE.search(style_text):
                raise _RendererFailure("SVG stylesheet URLを拒否しました。")
        stack.extend((child, depth + 1) for child in reversed(list(element)))
    return text, _svg_geometry_digest(root)


def _svg_geometry_digest(root: ET.Element) -> str:
    records: list[tuple[str, list[tuple[str, str]], str | None]] = []
    def visit(element: ET.Element, is_root: bool = False) -> None:
        name = _local_name(element.tag)
        if name in {"title", "desc"}:
            return
        attrs: list[tuple[str, str]] = []
        for key, value in sorted(element.attrib.items()):
            local = _local_name(key)
            if is_root and (local in {"theme", "data-theme", "lang", "role"} or local.startswith("aria-")):
                continue
            attrs.append((key, value))
        text = "".join(element.itertext()) if name == "style" else element.text
        records.append((name, attrs, text))
        for child in list(element):
            visit(child)
    visit(root, True)
    return _sha256_json(records)


def _finalize_svg(raw_text: str, spec: dict[str, Any], raw_digest: str) -> tuple[bytes, str]:
    root_match = re.search(r"<svg(?:\s|>)[^>]*>", raw_text, re.IGNORECASE | re.DOTALL)
    self_closing = re.search(r"<svg(?:\s|>)[^>]*/>", raw_text, re.IGNORECASE | re.DOTALL)
    if not root_match and not self_closing:
        raise _RendererFailure("SVG rootタグを更新できません。")
    match = self_closing or root_match
    assert match is not None
    title = str(spec["meta"]["title"])
    description = "Taskと明示された依存関係を示す計画overview"
    try:
        root = ET.fromstring(raw_text)
    except ET.ParseError as error:
        raise _RendererFailure("SVG XMLを再検証できません。") from error
    metadata: dict[str, list[ET.Element]] = {"title": [], "desc": []}
    for child in list(root):
        name = _local_name(child.tag)
        if name in metadata:
            metadata[name].append(child)
    if any(len(children) > 1 for children in metadata.values()):
        raise _RendererFailure("SVG root metadataが重複しています。")
    for name, value in (("title", title), ("desc", description)):
        children = metadata[name]
        if children:
            if list(children[0]):
                raise _RendererFailure("SVG root metadataを確認できません。")
            children[0].text = value
        else:
            element = ET.Element(f"{{{SVG_NAMESPACE}}}{name}")
            element.text = value
            root.insert(0, element)
    for name, value in (("data-theme", "light"), ("lang", "ja"), ("role", "img")):
        root.set(name, value)
    root.set(f"{{{XML_NAMESPACE}}}lang", "ja")
    ET.register_namespace("", SVG_NAMESPACE)
    if self_closing:
        suffix = raw_text[match.end() :]
    else:
        closing = list(re.finditer(r"</svg\s*>", raw_text[match.end() :], re.IGNORECASE))
        if not closing:
            raise _RendererFailure("SVG root閉じタグを確認できません。")
        suffix = raw_text[match.end() + closing[-1].end() :]
    final_text = raw_text[: match.start()] + ET.tostring(root, encoding="unicode") + suffix
    try:
        final_root = ET.fromstring(final_text)
    except ET.ParseError as error:
        raise _RendererFailure("metadata付与後のSVG XMLが不正です。") from error
    final_digest = _svg_geometry_digest(final_root)
    if final_digest != raw_digest:
        raise _RendererFailure("SVG geometry digestがmetadata付与前後で変化しました。")
    final_bytes = final_text.encode("utf-8")
    if len(final_bytes) > SVG_LIMIT:
        raise _RendererFailure("metadata付与後のSVGが4 MiBの上限を超えました。")
    return final_bytes, final_digest


def _require_final_svg_metadata(svg_bytes: bytes) -> None:
    try:
        root = ET.fromstring(svg_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ET.ParseError) as error:
        raise _RendererFailure("最終SVG metadataを検証できません。") from error
    if root.tag != f"{{{SVG_NAMESPACE}}}svg":
        raise _RendererFailure("最終SVG root namespaceが不正です。")
    if (
        root.get("data-theme") != "light"
        or root.get("lang") != "ja"
        or root.get(f"{{{XML_NAMESPACE}}}lang") != "ja"
        or root.get("role") != "img"
        or not {"title", "desc"}.issubset({_local_name(child.tag) for child in list(root)})
    ):
        raise _RendererFailure("最終SVG root metadataが不足しています。")


def sanitize_svg(raw_bytes: bytes, spec: dict[str, Any] | None = None) -> tuple[bytes, str]:
    """Validate and metadata-normalize official SVG bytes without redrawing."""
    raw_text, digest = _validate_svg(raw_bytes)
    effective_spec = spec or {"meta": {"title": "計画の依存関係"}}
    return _finalize_svg(raw_text, effective_spec, digest)


def _validate_bridge_receipt(
    receipt: dict[str, Any], *, revision: str | None, profile_hash: str | None,
    renderer_config: dict[str, Any] | None = None,
) -> None:
    """Require the fixed container bridge receipt before accepting SVG bytes."""
    required = {
        "schemaVersion",
        "ok",
        "status",
        "command",
        "diagramType",
        "revision",
        "source",
        "renderer",
        "html",
        "browser",
        "rawSvg",
        "runtime",
    }
    if not required.issubset(receipt) or receipt.get("schemaVersion") != 1 or receipt.get("ok") is not True:
        raise _RendererFailure("renderer receiptの必須schemaが不足しています。")
    if receipt.get("status") != "verified" or receipt.get("command") != "archify-render" or receipt.get("diagramType") != "workflow":
        raise _RendererFailure("renderer receiptのstatus/commandが不正です。")
    if revision is not None and receipt.get("revision") != revision:
        raise _RendererFailure("renderer receiptのrevisionが一致しません。")

    runtime = receipt.get("runtime")
    runtime_keys = {
        "backend", "image", "baseImage", "bridgeSha256", "entrypointSha256",
        "nodeSha256", "nodeVersion", "chromeSha256", "chromeVersion",
    }
    if not isinstance(runtime, dict) or not runtime_keys.issubset(runtime):
        raise _RendererFailure("renderer receiptのcontainer runtime証跡が不足しています。")
    if (
        runtime.get("backend") != EXPECTED_CONTAINER_BACKEND
        or runtime.get("baseImage") != EXPECTED_BASE_IMAGE
        or not isinstance(runtime.get("image"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", runtime["image"])
        or not SHA256_RE.fullmatch(str(runtime.get("bridgeSha256", "")))
        or not SHA256_RE.fullmatch(str(runtime.get("entrypointSha256", "")))
        or runtime.get("nodeSha256") != EXPECTED_NODE_SHA256
        or runtime.get("nodeVersion") != EXPECTED_NODE_VERSION
        or runtime.get("chromeSha256") != EXPECTED_CHROME_SHA256
        or runtime.get("chromeVersion") != EXPECTED_CHROME_VERSION
    ):
        raise _RendererFailure("renderer receiptのcontainer runtime証跡が不正です。")
    if renderer_config is not None:
        for key in runtime_keys:
            if runtime.get(key) != renderer_config.get(key):
                raise _RendererFailure("renderer receiptのcontainer runtime pinが一致しません。")

    source = receipt.get("source")
    if (
        not isinstance(source, dict)
        or source.get("revision") != receipt.get("revision")
        or source.get("fileCount") != SOURCE_FILE_COUNT
        or source.get("manifestSha256") != EXPECTED_MANIFEST_SHA256
    ):
        raise _RendererFailure("renderer receiptのsource証跡が不正です。")

    renderer = receipt.get("renderer")
    artifact = renderer.get("artifact") if isinstance(renderer, dict) else None
    if (
        not isinstance(renderer, dict)
        or renderer.get("command") != "deliver"
        or renderer.get("quality") != "standard"
        or not isinstance(artifact, dict)
        or not SHA256_RE.fullmatch(str(artifact.get("sha256", "")))
        or not isinstance(artifact.get("bytes"), int)
        or not 1 <= artifact["bytes"] <= HTML_LIMIT
    ):
        raise _RendererFailure("renderer receiptのdelivery証跡が不正です。")

    html_receipt = receipt.get("html")
    if (
        not isinstance(html_receipt, dict)
        or not SHA256_RE.fullmatch(str(html_receipt.get("rawSha256", "")))
        or not SHA256_RE.fullmatch(str(html_receipt.get("sanitizedSha256", "")))
        or not isinstance(html_receipt.get("rawBytes"), int)
        or not isinstance(html_receipt.get("sanitizedBytes"), int)
        or not 1 <= html_receipt["rawBytes"] <= HTML_LIMIT
        or not 1 <= html_receipt["sanitizedBytes"] <= HTML_LIMIT
    ):
        raise _RendererFailure("renderer receiptのHTML証跡が不正です。")

    browser = receipt.get("browser")
    if (
        not isinstance(browser, dict)
        or browser.get("theme") != "light"
        or browser.get("sandboxPolicy") != EXPECTED_CONTAINER_POLICY
        or not isinstance(browser.get("sandboxProfileSha256"), str)
        or not SHA256_RE.fullmatch(browser["sandboxProfileSha256"])
        or (profile_hash is not None and browser["sandboxProfileSha256"] != profile_hash)
        or browser.get("chromeExecutable") != EXPECTED_CHROME_EXECUTABLE
        or browser.get("chromiumSandbox") is not True
        or browser.get("pipe") is not True
        or browser.get("freshContext") is not True
        or not SHA256_RE.fullmatch(str(browser.get("sha256", "")))
        or not isinstance(browser.get("bytes"), int)
        or not 1 <= browser["bytes"] <= SVG_LIMIT
    ):
        raise _RendererFailure("renderer receiptのbrowser証跡が不正です。")
    playwright = browser.get("playwright")
    if (
        not isinstance(playwright, dict)
        or playwright.get("version") != EXPECTED_PLAYWRIGHT_VERSION
        or playwright.get("packageSha256") != EXPECTED_PLAYWRIGHT_PACKAGE_SHA256
        or playwright.get("coreSha256") != EXPECTED_PLAYWRIGHT_CORE_SHA256
        or playwright.get("lockSha256") != EXPECTED_PLAYWRIGHT_LOCK_SHA256
    ):
        raise _RendererFailure("renderer receiptのPlaywright証跡が不正です。")

    raw_receipt = receipt.get("rawSvg")
    if (
        not isinstance(raw_receipt, dict)
        or raw_receipt.get("path") != "raw.svg"
        or raw_receipt.get("sha256") != browser.get("sha256")
        or raw_receipt.get("bytes") != browser.get("bytes")
    ):
        raise _RendererFailure("renderer receiptのraw SVG証跡が不正です。")


def _validate_renderer_receipt(
    receipt: dict[str, Any],
    projection: dict[str, Any],
    spec: dict[str, Any],
    raw_bytes: bytes,
    *,
    revision: str | None = None,
) -> None:
    if receipt.get("status") not in {None, "verified"} or receipt.get("diagramType") not in {None, "workflow"}:
        raise _RendererFailure("renderer receiptのstatus/diagram typeが不正です。")
    if "schemaVersion" in receipt and receipt["schemaVersion"] != 1:
        raise _RendererFailure("renderer receiptのschemaが不正です。")
    if revision is not None and "revision" in receipt and receipt["revision"] != revision:
        raise _RendererFailure("renderer receiptのrevisionが一致しません。")
    expected_nodes = [node["id"] for node in spec["nodes"]]
    expected_edges = {(edge["from"], edge["to"]) for edge in spec["edges"]}
    for key in ("nodeCount", "nodesCount"):
        if key in receipt and receipt[key] != len(expected_nodes):
            raise _RendererFailure("renderer receiptのnode数が一致しません。")
    for key in ("edgeCount", "edgesCount"):
        if key in receipt and receipt[key] != len(expected_edges):
            raise _RendererFailure("renderer receiptのedge数が一致しません。")
    for key in ("nodeIds", "nodes"):
        if key not in receipt:
            continue
        values = receipt[key]
        if isinstance(values, list) and values and isinstance(values[0], dict):
            values = [item.get("id") for item in values]
        if not isinstance(values, list) or set(values) != set(expected_nodes) or len(values) != len(expected_nodes):
            raise _RendererFailure("renderer receiptのnode identityが一致しません。")
    for key in ("edgePairs", "edges"):
        if key not in receipt:
            continue
        values = receipt[key]
        if isinstance(values, list) and values and isinstance(values[0], dict):
            values = [(item.get("from"), item.get("to")) for item in values]
        if not isinstance(values, list):
            raise _RendererFailure("renderer receiptのedge identityが不正です。")
        if set(tuple(pair) for pair in values) != expected_edges or len(values) != len(expected_edges):
            raise _RendererFailure("renderer receiptのedge identityが一致しません。")
    for key, expected in (
        ("planSha256", projection["planSha256"]),
        ("overviewModelSha256", projection["overviewModelSha256"]),
        ("edgeSha256", projection["edgeSha256"]),
    ):
        if key in receipt and receipt[key] != expected:
            raise _RendererFailure(f"renderer receiptの{key}が一致しません。")
    if "rawSvgSha256" in receipt and receipt["rawSvgSha256"] != _sha256_bytes(raw_bytes):
        raise _RendererFailure("renderer receiptのraw SVG hashが一致しません。")
    source = receipt.get("source")
    if source is not None:
        if not isinstance(source, dict):
            raise _RendererFailure("renderer receiptのsourceが不正です。")
        if revision is not None and source.get("revision") != revision:
            raise _RendererFailure("renderer receiptのsource revisionが一致しません。")
        if "fileCount" in source and source["fileCount"] != SOURCE_FILE_COUNT:
            raise _RendererFailure("renderer receiptのsource file数が一致しません。")
        if "manifestSha256" in source and not SHA256_RE.fullmatch(str(source["manifestSha256"])):
            raise _RendererFailure("renderer receiptのsource hashが不正です。")
    raw_receipt = receipt.get("rawSvg")
    if raw_receipt is not None:
        if not isinstance(raw_receipt, dict):
            raise _RendererFailure("renderer receiptのraw SVG情報が不正です。")
        if raw_receipt.get("path") not in {None, "raw.svg"}:
            raise _RendererFailure("renderer receiptのraw SVG pathが不正です。")
        if raw_receipt.get("sha256") != _sha256_bytes(raw_bytes) or raw_receipt.get("bytes") != len(raw_bytes):
            raise _RendererFailure("renderer receiptのraw SVG情報が一致しません。")
    browser = receipt.get("browser")
    if browser is not None:
        if not isinstance(browser, dict):
            raise _RendererFailure("renderer receiptのbrowser情報が不正です。")
        if browser.get("theme") not in {None, "light"}:
            raise _RendererFailure("renderer receiptのthemeが不正です。")
        if "sha256" in browser and browser["sha256"] != _sha256_bytes(raw_bytes):
            raise _RendererFailure("renderer receiptのbrowser SVG hashが一致しません。")
        if "bytes" in browser and browser["bytes"] != len(raw_bytes):
            raise _RendererFailure("renderer receiptのbrowser SVG bytesが一致しません。")


def _source_payload(projection: dict[str, Any]) -> dict[str, Any]:
    source: dict[str, Any] = {
        "planSha256": projection["planSha256"],
        "overviewModelSha256": projection["overviewModelSha256"],
        "edgeSha256": projection["edgeSha256"],
        "taskIds": list(projection["taskIds"]),
    }
    if projection.get("parserVersion"):
        source["parserVersion"] = projection["parserVersion"]
    return source


def _base_payload(projection: dict[str, Any], revision: str, status: str, message: str) -> dict[str, Any]:
    return {
        "provider": "archify",
        "revision": revision,
        "adapterVersion": ADAPTER_VERSION,
        "adapterSourceSha256": ADAPTER_SOURCE_SHA256,
        "status": status,
        "message": message,
        "source": _source_payload(projection),
        "overviewModel": projection["overviewModel"],
    }


def _asset_id(revision: str, plan_hash: str) -> str:
    return f"archify-{revision}-{ADAPTER_VERSION}-{plan_hash}"


def _cache_paths(revision: str, plan_hash: str) -> tuple[Path, Path, Path]:
    directory = CACHE_ROOT / revision / ADAPTER_VERSION / plan_hash
    return directory, directory / "bundle.json", directory / "overview.svg"


def _secure_mode(path: Path, expected: int) -> bool:
    try:
        info = path.lstat()
        return (
            stat.S_IMODE(info.st_mode) == expected
            and not stat.S_ISLNK(info.st_mode)
            and info.st_uid == os.getuid()
            and (not stat.S_ISREG(info.st_mode) or info.st_nlink == 1)
        )
    except OSError:
        return False


@contextlib.contextmanager
def _cache_lock(timeout: float = RENDER_DEADLINE) -> Iterator[None]:
    started = time.monotonic()
    if not _CACHE_THREAD_LOCK.acquire(timeout=max(0.0, timeout)):
        raise _RendererFailure("Archify cache lockの期限を超えました。")
    fd: int | None = None
    fcntl: Any = None
    try:
        try:
            parent_info = CACHE_ROOT.parent.lstat()
        except OSError as error:
            raise _RendererBlocked("Archify cacheの祖先directoryを検査できません。") from error
        if (
            stat.S_ISLNK(parent_info.st_mode)
            or not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.getuid()
        ):
            raise _RendererBlocked("Archify cacheの祖先directoryが安全ではありません。")
        try:
            root_info = CACHE_ROOT.lstat()
        except FileNotFoundError:
            CACHE_ROOT.mkdir(parents=True, mode=0o700)
            root_info = CACHE_ROOT.lstat()
        if (
            stat.S_ISLNK(root_info.st_mode)
            or not stat.S_ISDIR(root_info.st_mode)
            or root_info.st_uid != os.getuid()
        ):
            raise _RendererBlocked("Archify cache rootが安全ではありません。")
        os.chmod(CACHE_ROOT, 0o700)
        lock_path = CACHE_ROOT / ".lock"
        fd = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        lock_info = os.fstat(fd)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1 or lock_info.st_uid != os.getuid():
            raise _RendererBlocked("Archify cache lockが安全ではありません。")
        os.chmod(lock_path, 0o600)
        try:
            import fcntl
        except ImportError:
            fcntl = None  # type: ignore[assignment]
        if fcntl is None:
            raise _RendererBlocked("Archify cache lockを利用できません。")
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise _RendererFailure("Archify cache lockを取得できません。") from error
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise _RendererFailure("Archify cache lockの期限を超えました。")
                time.sleep(min(0.05, remaining))
        yield
    finally:
        if fd is not None:
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(fd)
        _CACHE_THREAD_LOCK.release()


def _cache_hit(
    projection: dict[str, Any], revision: str, renderer_config: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    directory, bundle_path, svg_path = _cache_paths(revision, projection["planSha256"])
    if not directory.is_dir() or directory.is_symlink() or not bundle_path.is_file() or not svg_path.is_file():
        return None
    try:
        cache_parent_mode = stat.S_IMODE(CACHE_ROOT.parent.lstat().st_mode)
    except OSError:
        return None
    if not _secure_mode(CACHE_ROOT.parent, cache_parent_mode) or not all(
        _secure_mode(path, 0o700)
        for path in (CACHE_ROOT, directory.parent.parent, directory.parent, directory)
    ) or not _secure_mode(bundle_path, 0o600) or not _secure_mode(svg_path, 0o600):
        return None
    try:
        if bundle_path.stat().st_size > HTML_LIMIT or svg_path.stat().st_size > SVG_LIMIT:
            return None
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        svg_bytes = svg_path.read_bytes()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(bundle, dict):
        return None
    if (
        bundle.get("provider") != "archify"
        or bundle.get("status") != "verified"
        or bundle.get("revision") != revision
        or bundle.get("adapterVersion") != ADAPTER_VERSION
        or bundle.get("adapterSourceSha256") != ADAPTER_SOURCE_SHA256
        or bundle.get("overviewModel") != projection["overviewModel"]
        or bundle.get("assetId") != _asset_id(revision, projection["planSha256"])
    ):
        return None
    if bundle.get("source") != _source_payload(projection):
        return None
    overview = bundle.get("overview")
    if not isinstance(overview, dict) or overview.get("diagramType") != "workflow" or overview.get("theme") != "light":
        return None
    try:
        if overview.get("svg") != svg_bytes.decode("utf-8"):
            return None
    except UnicodeDecodeError:
        return None
    if overview.get("svgSha256") != _sha256_bytes(svg_bytes) or not SHA256_RE.fullmatch(str(overview.get("rawSvgSha256", ""))):
        return None
    raw_value = bundle.get("_rawSvg")
    renderer_receipt = bundle.get("_rendererReceipt")
    if not isinstance(raw_value, str) or not isinstance(renderer_receipt, dict):
        return None
    try:
        raw_bytes = raw_value.encode("utf-8")
        _raw_text, raw_geometry_digest = _validate_svg(raw_bytes)
        _text, geometry_digest = _validate_svg(svg_bytes)
        _require_final_svg_metadata(svg_bytes)
        _validate_renderer_receipt(
            renderer_receipt,
            projection,
            _workflow_spec(projection),
            raw_bytes,
            revision=revision,
        )
        descriptor = renderer_config if isinstance(renderer_config, dict) else None
        _validate_bridge_receipt(
            renderer_receipt,
            revision=revision,
            profile_hash=descriptor.get("seccompSha256") if descriptor else None,
            renderer_config=descriptor,
        )
    except _ProducerError:
        return None
    if overview.get("rawSvgSha256") != _sha256_bytes(raw_bytes) or raw_geometry_digest != geometry_digest:
        return None
    if overview.get("geometryDigest") != geometry_digest:
        return None
    result = dict(bundle)
    result.pop("_rawSvg", None)
    result.pop("_rendererReceipt", None)
    return result


def _write_bytes(path: Path, data: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def _ensure_private_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o700)
        return
    except OSError as error:
        raise _RendererFailure("Archify cache directoryを検査できません。") from error
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
        raise _RendererFailure("Archify cache directoryが安全ではありません。")
    os.chmod(path, 0o700)


def _publish_cache(
    payload: dict[str, Any],
    svg_bytes: bytes,
    revision: str,
    plan_hash: str,
    *,
    raw_bytes: bytes | None = None,
    renderer_receipt: dict[str, Any] | None = None,
) -> None:
    directory, bundle_path, svg_path = _cache_paths(revision, plan_hash)
    parent = directory.parent
    _ensure_private_directory(CACHE_ROOT)
    revision_dir = CACHE_ROOT / revision
    _ensure_private_directory(revision_dir)
    _ensure_private_directory(parent)
    if directory.exists() and directory.is_symlink():
        raise _RendererFailure("Archify cache directoryがsymlinkです。")
    bundle = dict(payload)
    if raw_bytes is not None and renderer_receipt is not None:
        try:
            bundle["_rawSvg"] = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _RendererFailure("raw.svgをcacheへ保存できません。") from error
        bundle["_rendererReceipt"] = renderer_receipt
    bundle_bytes = (_canonical_json(bundle) + "\n").encode("utf-8")
    if len(bundle_bytes) > HTML_LIMIT:
        raise _RendererFailure("Archify cache bundleが8 MiBの上限を超えました。")
    temp_dir = Path(tempfile.mkdtemp(prefix=".archify-publish-", dir=str(parent)))
    os.chmod(temp_dir, 0o700)
    temp_bundle = temp_dir / "bundle.json"
    temp_svg = temp_dir / "overview.svg"
    try:
        _write_bytes(temp_bundle, bundle_bytes)
        _write_bytes(temp_svg, svg_bytes)
        directory.mkdir(parents=False, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        os.replace(temp_bundle, bundle_path)
        os.replace(temp_svg, svg_path)
    except (OSError, _ProducerError) as error:
        raise _RendererFailure("Archify cacheのatomic publishに失敗しました。") from error
    finally:
        with contextlib.suppress(OSError):
            temp_bundle.unlink()
        with contextlib.suppress(OSError):
            temp_svg.unlink()
        with contextlib.suppress(OSError):
            temp_dir.rmdir()


def _cleanup_staging_directory(temp_root: Path) -> None:
    errors: list[OSError] = []
    try:
        paths = sorted(temp_root.rglob("*"), reverse=True)
    except OSError as error:
        paths = []
        errors.append(error)
    for path in paths:
        try:
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                path.rmdir()
            elif stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                path.unlink()
            else:
                errors.append(OSError("unexpected staging entry"))
        except FileNotFoundError:
            continue
        except OSError as error:
            errors.append(error)
    try:
        temp_root.rmdir()
    except FileNotFoundError:
        pass
    except OSError as error:
        errors.append(error)
    if errors:
        raise _RendererFailure("Archify一時領域の後片付けを確認できません。") from errors[0]


def _render_payload(
    projection: dict[str, Any], revision: str, renderer_config: dict[str, Any] | Path,
    *, deadline: float = RENDER_DEADLINE
) -> tuple[dict[str, Any], bytes, bytes, dict[str, Any]]:
    spec = _workflow_spec(projection)
    temp_root = Path(tempfile.mkdtemp(prefix="archify-plan-"))
    os.chmod(temp_root, 0o700)
    run_dir = temp_root / "run"
    run_dir.mkdir(mode=0o700)
    spec_path = run_dir / "spec.json"
    try:
        spec_bytes = (_canonical_json(spec) + "\n").encode("utf-8")
        if len(spec_bytes) > RAW_PLAN_LIMIT:
            raise _ProducerError("Archify workflow入力が1 MiBの上限を超えています。", status="invalid")
        _write_bytes(spec_path, spec_bytes)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _RendererFailure("Archify rendererが60秒の期限を超えました。")
        receipt, raw_bytes = _invoke_renderer(
            spec_path, run_dir, renderer_config, timeout=remaining, revision=revision
        )
        _validate_renderer_receipt(receipt, projection, spec, raw_bytes, revision=revision)
        raw_text, raw_digest = _validate_svg(raw_bytes)
        final_bytes, geometry_digest = _finalize_svg(raw_text, spec, raw_digest)
        _require_final_svg_metadata(final_bytes)
        payload = _base_payload(projection, revision, "verified", "Archify overviewを生成しました。")
        payload["assetId"] = _asset_id(revision, projection["planSha256"])
        payload["overview"] = {
            "svg": final_bytes.decode("utf-8"),
            "svgSha256": _sha256_bytes(final_bytes),
            "rawSvgSha256": _sha256_bytes(raw_bytes),
            "geometryDigest": geometry_digest,
            "diagramType": "workflow",
            "theme": "light",
        }
        return payload, final_bytes, raw_bytes, receipt
    finally:
        _cleanup_staging_directory(temp_root)


def _invalid_payload(plan_text: Any, message: str) -> dict[str, Any]:
    try:
        raw = plan_text.encode("utf-8") if isinstance(plan_text, str) else b""
        plan_hash = _sha256_bytes(raw)
    except UnicodeEncodeError:
        plan_hash = ""
    projection = {
        "rawBytes": b"",
        "planSha256": plan_hash,
        "overviewModel": {"tasks": [], "edges": []},
        "overviewModelSha256": _sha256_json({"tasks": [], "edges": []}),
        "edgeSha256": _sha256_json([]),
        "taskIds": [],
        "parserVersion": "",
    }
    return _base_payload(projection, "unknown", "invalid", message)


def archify_for_plan(plan_text: str, plan_model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a verified Archify payload, or an explicit non-success status."""
    try:
        projection = _prepare_projection(plan_text, plan_model)
    except _ProducerError as error:
        return _invalid_payload(plan_text, str(error))
    if not projection["taskIds"]:
        return _base_payload(projection, EXPECTED_REVISION, "empty", "計画にTaskがありません。")
    try:
        revision, renderer_config = _load_config()
    except _RendererBlocked as error:
        return _base_payload(projection, error.revision, "blocked", str(error))
    try:
        deadline = time.monotonic() + RENDER_DEADLINE
        with _cache_lock(max(0.0, deadline - time.monotonic())):
            cached = _cache_hit(projection, revision, renderer_config)
            if cached is not None:
                return cached
            payload, svg_bytes, raw_bytes, renderer_receipt = _render_payload(
                projection, revision, renderer_config, deadline=deadline
            )
            _publish_cache(
                payload,
                svg_bytes,
                revision,
                projection["planSha256"],
                raw_bytes=raw_bytes,
                renderer_receipt=renderer_receipt,
            )
            return payload
    except _RendererBlocked as error:
        return _base_payload(projection, revision, "blocked", str(error))
    except _ProducerError as error:
        return _base_payload(projection, revision, error.status, str(error))
    except (OSError, RuntimeError) as error:
        return _base_payload(projection, revision, "error", "Archify生成に失敗しました。")


def _read_bounded_stdin(limit: int = HTML_LIMIT) -> bytes:
    data = bytearray()
    while len(data) <= limit:
        chunk = os.read(0, min(65_536, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise _ProducerError("stdin JSONが8 MiBの上限を超えています。", status="invalid")
    return bytes(data)


def _cli() -> int:
    try:
        request_bytes = _read_bounded_stdin()
        request = json.loads(request_bytes.decode("utf-8"), object_pairs_hook=_unique_json_pairs)
    except _ProducerError as error:
        print(json.dumps(_invalid_payload("", str(error)), ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, MemoryError):
        print(json.dumps(_invalid_payload("", "stdin JSONを読み込めません。"), ensure_ascii=False, separators=(",", ":")))
        return 0
    if not isinstance(request, dict) or not isinstance(request.get("content"), str) or set(request) != {"content"}:
        print(json.dumps(_invalid_payload("", "stdin JSONはcontentだけを持つobjectにしてください。"), ensure_ascii=False, separators=(",", ":")))
        return 0
    payload = archify_for_plan(request["content"])
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
