#!/usr/bin/env python3
"""Author and verify the explicit implementation architecture in 30_plan.html.

The canonical parser's ``task.diagramData`` is the only source.  This module
does not derive a graph from Tasks; the fixed Archify adapter owns rendering,
cache locking, container policy, and SVG verification.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import html
import importlib.util
import json
import os
import re
import stat
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = ROOT / "scripts" / "roadmap_plan_contract.py"
ADAPTER_PATH = ROOT / "scripts" / "archify_plan.py"
ARCHITECTURE_ID = "implementation-architecture"
MAX_PLAN = 8 * 1024 * 1024
MAX_SPEC = 1024 * 1024
MAX_SVG = 4 * 1024 * 1024
MAX_TEXT = 512
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
SVG_PREFIX = "data:image/svg+xml;base64,"
VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
NODE_TYPES = frozenset({"frontend", "backend", "database", "cloud", "security", "messagebus", "external"})
EDGE_ENUMS = {
    "fromSide": {"left", "right", "top", "bottom"},
    "toSide": {"left", "right", "top", "bottom"},
    "route": {"auto", "straight", "drop", "outside-right", "return-left", "bottom-channel", "up-channel"},
}
_ADAPTER: object | None = None
_PARSER: object | None = None
class ArchitectureError(ValueError):
    def __init__(self, message: str, *, status: str = "invalid") -> None:
        super().__init__(message)
        self.status = status


def _load(path: Path, name: str) -> object:
    if path.is_symlink() or not path.is_file():
        raise ArchitectureError("固定された計画・Archify adapterを読み込めません。", status="blocked")
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError("module spec unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ArchitectureError("固定された計画・Archify adapterを読み込めません。", status="blocked") from exc
    return module


def _adapter() -> object:
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = _load(ADAPTER_PATH, "plan_architecture_archify_adapter")
    return _ADAPTER


def _parser() -> object:
    global _PARSER
    if _PARSER is None:
        _PARSER = _load(PARSER_PATH, "plan_architecture_plan_contract")
    return _PARSER


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ArchitectureError("architecture fragmentのJSONを正規化できません。") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise ArchitectureError(f"architecture {field}が不正です。")
    return value


def _id(value: Any, field: str) -> str:
    value = _text(value, field)
    if not ID_RE.fullmatch(value):
        raise ArchitectureError(f"architecture {field}のIDが不正です。")
    return value


def _integer(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ArchitectureError(f"architecture {field}の数値が不正です。")
    return value


def _fields(value: Any, allowed: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise ArchitectureError(f"architecture {field}が不正です。")
    return value


def _shape(block: Mapping[str, Any]) -> None:
    _fields(block, {"version", "kind", "id", "title", "lanes", "nodes", "edges"}, "fragment")
    if (block.get("version"), block.get("kind"), block.get("id")) != (1, "architecture", ARCHITECTURE_ID):
        raise ArchitectureError("architecture fragmentのversion/kind/idが不正です。")
    _text(block.get("title"), "title")
    nodes, edges = block.get("nodes"), block.get("edges")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 128 or not isinstance(edges, list) or len(edges) > 256:
        raise ArchitectureError("architecture nodes/edgesの件数が不正です。")
    lanes = block.get("lanes")
    if lanes is not None and (not isinstance(lanes, list) or not 1 <= len(lanes) <= 32):
        raise ArchitectureError("architecture lanesの件数が不正です。")


def _lanes(block: Mapping[str, Any], nodes: list[Mapping[str, Any]]) -> tuple[list[dict[str, str]], str]:
    result: list[dict[str, str]] = []
    ids: set[str] = set()
    for i, lane in enumerate(block.get("lanes") or []):
        lane = _fields(lane, {"id", "label"}, f"lanes[{i}]")
        lane_id, label = _id(lane.get("id"), f"lanes[{i}].id"), _text(lane.get("label"), f"lanes[{i}].label")
        if lane_id in ids:
            raise ArchitectureError("architecture lane IDが重複しています。")
        item: dict[str, str] = {"id": lane_id, "label": label}
        result.append(item)
        ids.add(lane_id)
    refs: list[str] = []
    for i, node in enumerate(nodes):
        if "lane" in node:
            lane = _id(node["lane"], f"nodes[{i}].lane")
            if lane not in refs:
                refs.append(lane)
    if not result:
        result = [{"id": lane, "label": lane} for lane in refs or ["implementation"]]
        ids = {lane["id"] for lane in result}
    if any(lane not in ids for lane in refs):
        raise ArchitectureError("architecture nodeが未定義laneを参照しています。")
    return result, result[0]["id"]


def build_architecture_spec(block: Mapping[str, Any]) -> dict[str, Any]:
    """Map one source fragment to the fixed Archify workflow IR."""
    if not isinstance(block, Mapping):
        raise ArchitectureError("architecture fragmentはobjectで指定してください。")
    _shape(block)
    raw_nodes, raw_edges = block["nodes"], block["edges"]
    assert isinstance(raw_nodes, list) and isinstance(raw_edges, list)
    if any(not isinstance(node, Mapping) for node in raw_nodes):
        raise ArchitectureError("architecture nodeがobjectではありません。")
    nodes_input = [node for node in raw_nodes if isinstance(node, Mapping)]
    lanes, default_lane = _lanes(block, nodes_input)
    lane_ids, node_ids = {lane["id"] for lane in lanes}, set()
    node_fields = {"id", "label", "responsibility", "contract", "lane", "col", "type", "sublabel", "tag"}
    nodes: list[dict[str, Any]] = []
    for i, raw in enumerate(nodes_input):
        _fields(raw, node_fields, f"nodes[{i}]")
        node_id, label = _id(raw.get("id"), f"nodes[{i}].id"), _text(raw.get("label"), f"nodes[{i}].label")
        if node_id in node_ids:
            raise ArchitectureError("architecture node IDが重複しています。")
        lane, col = _id(raw.get("lane", default_lane), f"nodes[{i}].lane"), _integer(raw.get("col", i % 6), f"nodes[{i}].col", minimum=0, maximum=5)
        if lane not in lane_ids or raw.get("type", "external") not in NODE_TYPES:
            raise ArchitectureError(f"architecture nodes[{i}]のlane/typeが不正です。")
        node: dict[str, Any] = {"id": node_id, "lane": lane, "col": col, "type": raw.get("type", "external"), "label": label}
        for key, alias in (("sublabel", "responsibility"), ("tag", "contract")):
            if key in raw and alias in raw:
                raise ArchitectureError(f"architecture nodes[{i}]に{key}と{alias}を併記できません。")
            source = key if key in raw else alias if alias in raw else None
            if source:
                node[key] = _text(raw[source], f"nodes[{i}].{source}")
        nodes.append(node)
        node_ids.add(node_id)

    edge_fields = {"id", "from", "to", "label", *EDGE_ENUMS}
    node_by_id, edge_ids, pairs = {node["id"]: node for node in nodes}, set(), set()
    edges: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_edges):
        _fields(raw, edge_fields, f"edges[{i}]")
        source, target = _id(raw.get("from"), f"edges[{i}].from"), _id(raw.get("to"), f"edges[{i}].to")
        if source not in node_ids or target not in node_ids or (source, target) in pairs:
            raise ArchitectureError("architecture edgeのendpointが不正または重複しています。")
        pairs.add((source, target))
        edge_id = _id(raw.get("id", f"edge-{source}-{target}-{i}"), f"edges[{i}].id")
        if edge_id in edge_ids:
            raise ArchitectureError("architecture edge IDが重複しています。")
        edge_ids.add(edge_id)
        edge: dict[str, Any] = {"id": edge_id, "from": source, "to": target}
        if "label" in raw:
            edge["label"] = _text(raw["label"], f"edges[{i}].label")
        for key, values in EDGE_ENUMS.items():
            if key in raw:
                if raw[key] not in values:
                    raise ArchitectureError(f"architecture edges[{i}].{key}が不正です。")
                edge[key] = raw[key]
        if "route" not in edge:
            left, right = node_by_id[source], node_by_id[target]
            edge.update({"route": "drop", "fromSide": "bottom", "toSide": "top"} if left["lane"] != right["lane"] else {"route": "return-left", "fromSide": "left", "toSide": "left"} if left["col"] > right["col"] else {"route": "auto"})
        edges.append(edge)
    spec = {"schema_version": 2, "diagram_type": "workflow", "meta": {"title": _text(block["title"], "title"), "animation": "none", "quality_profile": "standard", "legend": {"mode": "hidden"}}, "lanes": lanes, "nodes": nodes, "edges": edges}
    if len(_json(spec).encode("utf-8")) > MAX_SPEC:
        raise ArchitectureError("architecture specが1 MiBの上限を超えています。")
    return spec


def architecture_digest(block: Mapping[str, Any]) -> str:
    _shape(block)
    return _sha256(_json(block).encode("utf-8"))


def extract_architecture_block(plan_model: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Select a single architecture item from Task ``diagramData`` only."""
    if not isinstance(plan_model, Mapping) or not isinstance(plan_model.get("tasks"), list):
        raise ArchitectureError("Plan modelのtasksが配列ではありません。")
    matches: list[Mapping[str, Any]] = []
    for ti, task in enumerate(plan_model["tasks"]):
        if not isinstance(task, Mapping):
            raise ArchitectureError(f"Plan task[{ti}]がobjectではありません。")
        blocks = task.get("diagramData")
        if blocks is None:
            continue
        if not isinstance(blocks, list):
            raise ArchitectureError(f"Task {task.get('number', ti + 1)} のdiagramDataが配列ではありません。")
        for bi, block in enumerate(blocks):
            if not isinstance(block, Mapping):
                raise ArchitectureError(f"Task {task.get('number', ti + 1)} のdiagramData[{bi}]がobjectではありません。")
            if block.get("kind") == "architecture" or block.get("id") == ARCHITECTURE_ID:
                _shape(block)
                matches.append(block)
    if len(matches) > 1:
        raise ArchitectureError("implementation-architecture fragmentが複数あります。")
    return matches[0] if matches else None


def prepare_architecture(plan_model: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None, str | None]:
    block = extract_architecture_block(plan_model)
    return (None, None, None) if block is None else (block, build_architecture_spec(block), architecture_digest(block))


def _read_plan(task_dir: str | Path) -> tuple[Path, bytes, dict[str, Any]]:
    directory = Path(task_dir)
    if directory.is_symlink() or not directory.is_dir():
        raise ArchitectureError("task directoryが通常directoryではありません。", status="blocked")
    path = directory / "30_plan.html"
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PLAN:
            raise OSError("unsafe plan")
        raw = path.read_bytes()
    except OSError as exc:
        raise ArchitectureError("30_plan.htmlを読み込めません。", status="blocked") from exc
    if len(raw) > MAX_PLAN:
        raise ArchitectureError("30_plan.htmlがサイズ上限を超えています。")
    try:
        model = _parser().parse_html_plan_contract(raw, plan_source=str(path), progress_source=str(directory / "40_progress.md"))  # type: ignore[attr-defined]
    except Exception as exc:
        raise ArchitectureError("30_plan.htmlの構造を確認できません。") from exc
    if not isinstance(model, dict):
        raise ArchitectureError("30_plan.htmlの構造を確認できません。")
    return path, raw, model


class _FigureLocator(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source, self.figure, self.depth = source, None, 0
        self.lines = [0]
        self.lines.extend(i + 1 for i, char in enumerate(source) if char == "\n")

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.lines[min(line - 1, len(self.lines) - 1)] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name, start = tag.casefold(), self._offset()
        values = {key.casefold(): value or "" for key, value in attrs}
        if name == "figure" and values.get("id") == ARCHITECTURE_ID:
            if self.figure is not None:
                raise ArchitectureError("implementation-architecture figureが複数あります。")
            self.figure = (start + len(self.get_starttag_text() or ""), -1, -1)
            self.depth = 1
        elif self.depth and name not in VOID:
            self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name, start = tag.casefold(), self._offset()
        values = {key.casefold(): value or "" for key, value in attrs}
        if name == "figure" and values.get("id") == ARCHITECTURE_ID:
            if self.figure is not None:
                raise ArchitectureError("implementation-architecture figureが複数あります。")
            end = start + len(self.get_starttag_text() or "")
            self.figure = (end, end, end)
        # Other self-closing elements do not change the open-element depth.

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        name, start = tag.casefold(), self._offset()
        if name == "figure" and self.depth == 1 and self.figure is not None and self.figure[1] < 0:
            self.figure = (self.figure[0], start, self.source.find(">", start) + 1)
            self.depth = 0
        elif name not in VOID:
            self.depth = max(0, self.depth - 1)


def _figure_span(raw: bytes) -> tuple[int, int, int]:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchitectureError("30_plan.htmlがUTF-8ではありません。") from exc
    locator = _FigureLocator(source)
    try:
        locator.feed(source)
        locator.close()
    except ArchitectureError:
        raise
    except Exception as exc:
        raise ArchitectureError("implementation-architecture figureを解析できません。") from exc
    if locator.figure is None or locator.figure[1] < 0:
        raise ArchitectureError("implementation-architecture figureがありません。")
    return locator.figure


class _ImageSources(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.sources: list[str] = []

    def _capture(self, attrs: list[tuple[str, str | None]]) -> None:
        self.sources.append({key.casefold(): value or "" for key, value in attrs}.get("src", ""))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "img":
            self._capture(attrs)

    handle_startendtag = handle_starttag


def _embedded_svg(raw: bytes, span: tuple[int, int, int]) -> bytes:
    parser = _ImageSources()
    source = raw.decode("utf-8")
    try:
        parser.feed(source[span[0] : span[1]])
        parser.close()
    except Exception as exc:
        raise ArchitectureError("implementation-architecture figureの画像を解析できません。") from exc
    if len(parser.sources) != 1 or not parser.sources[0].startswith(SVG_PREFIX):
        raise ArchitectureError("implementation-architecture figureに検証済みSVG画像が1つ必要です。")
    encoded = parser.sources[0][len(SVG_PREFIX) :]
    try:
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as exc:
        raise ArchitectureError("implementation-architecture SVG dataが不正です。") from exc
    if not decoded or len(decoded) > MAX_SVG or base64.b64encode(decoded).decode("ascii") != encoded:
        raise ArchitectureError("implementation-architecture SVG dataが不正です。")
    try:
        _adapter()._validate_svg(decoded)  # type: ignore[attr-defined]
    except Exception as exc:
        raise ArchitectureError("implementation-architecture SVGの安全性を確認できません。", status="error") from exc
    return decoded


def _render_verified(spec: Mapping[str, Any], digest: str, *, cache_only: bool = False) -> tuple[bytes, dict[str, Any]]:
    try:
        adapter = _adapter()
        payload = adapter.archify_for_spec(dict(spec), digest, cache_only=cache_only)  # type: ignore[attr-defined]
    except Exception as exc:
        raise ArchitectureError("固定Archify rendererを利用できません。", status=getattr(exc, "status", "blocked")) from exc
    if not isinstance(payload, dict) or payload.get("status") != "verified":
        status = payload.get("status", "error") if isinstance(payload, dict) else "error"
        message = payload.get("message") if isinstance(payload, dict) else None
        raise ArchitectureError(message if isinstance(message, str) and 0 < len(message) <= MAX_TEXT else "Archify architectureの生成に失敗しました。", status=status)
    overview = payload.get("overview")
    if not isinstance(overview, dict) or overview.get("diagramType") != "workflow" or not isinstance(overview.get("svg"), str):
        raise ArchitectureError("Archify architectureのSVG証跡が不正です。", status="error")
    svg = overview["svg"].encode("utf-8")
    if not 1 <= len(svg) <= MAX_SVG or overview.get("svgSha256") != _sha256(svg):
        raise ArchitectureError("Archify architectureのSVG hashが一致しません。", status="error")
    try:
        adapter._validate_svg(svg)  # type: ignore[attr-defined]
        adapter._require_final_svg_metadata(svg)  # type: ignore[attr-defined]
    except Exception as exc:
        raise ArchitectureError("Archify architectureのSVG安全性を確認できません。", status="error") from exc
    return svg, {"revision": payload.get("revision", "unknown"), "digest": digest, "architectureSha256": digest, "svgSha256": _sha256(svg), "svgBytes": len(svg), "cache": True}


def _markup(title: str, svg: bytes) -> str:
    title = html.escape(title, quote=True)
    return f'\n    <figcaption>{title}</figcaption>\n    <img alt="{title}" src="{SVG_PREFIX}{base64.b64encode(svg).decode("ascii")}">\n  '


def _replace(path: Path, original: bytes, updated: bytes) -> None:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or path.read_bytes() != original:
            raise ArchitectureError("30_plan.htmlが生成中に変更されました。", status="error")
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.architecture-", dir=str(path.parent))
        temporary = Path(name)
        try:
            os.fchmod(fd, stat.S_IMODE(info.st_mode))
            with os.fdopen(fd, "wb") as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()
    except ArchitectureError:
        raise
    except OSError as exc:
        raise ArchitectureError("30_plan.htmlを原子的に更新できません。", status="error") from exc


def _result(block: Mapping[str, Any], spec: Mapping[str, Any], source_hash: str, metadata: Mapping[str, Any], changed: bool) -> dict[str, Any]:
    return {"status": "verified", "changed": changed, "id": ARCHITECTURE_ID, "title": block["title"], "nodes": len(spec["nodes"]), "edges": len(spec["edges"]), "sourceSha256": source_hash, **metadata}


def update_plan_architecture(task_dir: str | Path, *, check: bool = False) -> dict[str, Any]:
    """Embed the current fragment, or check without changing the plan file."""
    source_hash: str | None = None
    try:
        path, raw, model = _read_plan(task_dir)
        source_hash = _sha256(raw)
        block, spec, digest = prepare_architecture(model)
        if block is None or spec is None or digest is None:
            return {"status": "none", "message": "architecture fragmentがありません。", "sourceSha256": source_hash}
        span = _figure_span(raw)
        svg, metadata = _render_verified(spec, digest, cache_only=check)
        if check:
            if _embedded_svg(raw, span) != svg:
                raise ArchitectureError("implementation-architectureのSVGが現在のfragmentと一致しません。", status="error")
            return _result(block, spec, source_hash, metadata, False)
        source = raw.decode("utf-8")
        updated = (source[:span[0]] + _markup(str(block["title"]), svg) + source[span[1]:]).encode("utf-8")
        changed = updated != raw
        if changed:
            _replace(path, raw, updated)
        return _result(block, spec, source_hash, metadata, changed)
    except ArchitectureError as exc:
        result = {"status": exc.status, "message": str(exc), "id": ARCHITECTURE_ID}
        if source_hash is not None:
            result["sourceSha256"] = source_hash
        return result


def check_architecture(task_dir: str | Path) -> dict[str, Any]:
    return update_plan_architecture(task_dir, check=True)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed the explicit Archify implementation architecture in 30_plan.html.")
    parser.add_argument("task_dir")
    parser.add_argument("--check", action="store_true", help="Validate without writing 30_plan.html.")
    args = parser.parse_args(argv)
    result = update_plan_architecture(args.task_dir, check=args.check)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") in {"none", "verified"} else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
