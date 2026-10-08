#!/usr/bin/env python3
"""HTML 文書の「機械的な最低水準」のうち、機械で数えられる項目を調べる。

creating-html-documents で作る文書が対象である。既存の html_artifact_contract の検査
（strict-self-contained）に、文書向けの検査を足す。描画や意味の判断が要る項目
（強調した要素のラベル、はみ出し、SVG の文字の実寸、件数の一致、数値の根拠など）は調べない。
誤りがあれば終了コード 1、「要確認」だけなら 0 で終わる。
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import html_artifact_contract as contract  # noqa: E402

PREFIX = "[html-document]"
ERROR, CHECK = "誤り", "要確認"
DOCUMENT_OWNER = "creating-html-documents"
COUNTED_TAGS = ("table", "h1", "script")
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
CSS_ESCAPE = re.compile(r"\\([0-9a-fA-F]{1,6})\s?")
PSEUDO_ELEMENT = re.compile(r"::?(?:before|after)\b")
CONTENT_DECLARATION = re.compile(r"(?:^|[;\s])content\s*:([^;]*)")
CSS_STRING = re.compile(r"([\"'])(.*?)\1", re.S)
CONTENT_FUNCTION = re.compile(r"\b(counters?|attr)\(")
TEXT_ELEMENT_SELECTOR = re.compile(r"(?:^|[ >+~])text$")  # 修飾のない text 要素で終わるセレクタ
UNSCOPED_TEXT_SELECTOR = re.compile(r"^(?:(?:svg|g)[ >])*text$")  # どの図の text にも当たるセレクタ
FILL_DECLARATION = re.compile(r"(?:^|[;\s])fill\s*:")


class DocumentScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: dict[str, list[int]] = {name: [] for name in (*COUNTED_TAGS, "th_without_scope", "text_fill")}
        self.metas: dict[str, str] = {}
        self.css: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        line = self.getpos()[0]
        if tag in COUNTED_TAGS:
            self.lines[tag].append(line)
        elif tag == "th" and not attributes.get("scope"):
            self.lines["th_without_scope"].append(line)
        elif tag == "text" and "fill" in attributes:
            self.lines["text_fill"].append(line)
        elif tag == "meta" and attributes.get("name"):
            self.metas[attributes["name"].lower()] = (attributes.get("content") or "").strip()
        elif tag == "style":
            self._in_style = True

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.css.append(data)


def located(lines: list[int]) -> str:
    return f"{len(lines)} 個（最初は {lines[0]} 行目）"


def excepted(scanner: DocumentScanner, tag: str, advice: str) -> list[tuple]:
    """table と script は、理由を書いた meta があれば「要確認」に下げる。"""
    lines = scanner.lines[tag]
    if not lines:
        return []
    meta = f"{tag}-exception"
    reason = scanner.metas.get(meta)
    if reason:
        return [(lines[0], CHECK, tag, f"{tag} 要素が {located(lines)}ある。{meta} の理由: {reason}")]
    return [(lines[0], ERROR, tag, f'{tag} 要素が {located(lines)}ある。{advice}例外で使うときは <meta name="{meta}" content="理由"> を置く。')]


def foreign_kinds() -> dict:
    """他のスキルが持つ成果物の種類と、その持ち主。表や script を使う決まりのものがあるので調べない。"""
    routes = contract.load_manifest().get("routes", [])
    kinds = {route.get("artifactKind"): route.get("localOwner") for route in routes if isinstance(route, dict)}
    kinds = {kind: owner for kind, owner in kinds.items() if owner != DOCUMENT_OWNER}
    kinds["session-dashboard"] = "session-dashboard"
    return kinds


def decode_css_escapes(value: str) -> str:
    def decode(match):
        code = int(match.group(1), 16)
        return chr(code) if 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF else ""

    return CSS_ESCAPE.sub(decode, value)


def pseudo_findings(selector: str, body: str) -> list[tuple]:
    if not PSEUDO_ELEMENT.search(selector):
        return []
    declaration = CONTENT_DECLARATION.search(body)
    if not declaration:
        return []
    text = decode_css_escapes("".join(string.group(2) for string in CSS_STRING.finditer(declaration.group(1))))
    function = CONTENT_FUNCTION.search(CSS_STRING.sub("", declaration.group(1)))
    if any(char.isalnum() for char in text):
        return [(None, ERROR, "pseudo-content", f"{selector} の content に文字「{text[:20]}」がある。意味を持つラベルは実要素に置く。")]
    if function:
        message = f"{selector} の content が {function.group(1)}() で文字を出している。番号とラベルは実要素に置く決まりである。"
        return [(None, CHECK, "pseudo-content", message)]
    return []


def css_findings(css: str, text_fill: list[int]) -> list[tuple]:
    findings, everywhere, scoped = [], [], []
    for selectors, body in CSS_RULE.findall(CSS_COMMENT.sub("", css)):
        for selector in (re.sub(r"\s*>\s*", ">", " ".join(part.split())) for part in selectors.split(",")):
            findings += pseudo_findings(selector, body)
            if TEXT_ELEMENT_SELECTOR.search(selector) and FILL_DECLARATION.search(body):
                (everywhere if UNSCOPED_TEXT_SELECTOR.match(selector) else scoped).append(selector)
    if not text_fill:
        return findings
    if everywhere:
        message = f"SVG の text の fill 属性 {located(text_fill)}が、CSS の「{everywhere[0]}」の fill に上書きされる。色は CSS クラスで指定する。"
        return findings + [(text_fill[0], ERROR, "svg-text-fill", message)]
    message = f"SVG の text に fill 属性が {located(text_fill)}ある。色は CSS クラスで指定する決まりである。"
    if scoped:
        message += f"CSS の「{scoped[0]}」の範囲にある text では、fill 属性が上書きされる。"
    return findings + [(text_fill[0], CHECK, "svg-text-fill", message)]


def lint_text(text: str, path: str):
    """指摘の一覧を返す。他のスキルの成果物なら、対象外の説明を文字列で返す。"""
    scanner = DocumentScanner()
    scanner.feed(text)
    kind = scanner.metas.get("artifact-kind")
    owner = foreign_kinds().get(kind)
    if owner:
        return f"対象外（artifact-kind「{kind}」は {owner} の成果物）"
    issues = contract.validate_html_text(text, path=path)
    findings = [(item.line, ERROR, item.code, item.message) for item in issues if item.severity == "error"]
    findings += excepted(scanner, "table", "表は使わない。")
    if scanner.lines["table"] and scanner.lines["th_without_scope"]:
        findings.append((scanner.lines["th_without_scope"][0], ERROR, "th-scope", f"scope のない th が {located(scanner.lines['th_without_scope'])}ある。"))
    if len(scanner.lines["h1"]) != 1:
        findings.append((None, ERROR, "h1-count", f"h1 が {len(scanner.lines['h1'])} 個ある。一つにする。"))
    findings += excepted(scanner, "script", "")
    findings += css_findings("\n".join(scanner.css), scanner.lines["text_fill"])
    return findings


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    parser.add_argument("files", nargs="+", type=Path, help="調べる HTML ファイル")
    args = parser.parse_args(argv)
    failed = False
    for path in args.files:
        try:
            findings = lint_text(path.read_text(encoding="utf-8"), str(path))
        except (OSError, UnicodeDecodeError) as error:
            print(f"{PREFIX} {path}: 読めない（{error}）")
            failed = True
            continue
        if isinstance(findings, str):
            print(f"{PREFIX} {path}: {findings}")
            continue
        for line, severity, code, message in findings:
            print(f"{PREFIX} {path}:{line or 1} {severity} {code}: {message}")
        errors = sum(1 for finding in findings if finding[1] == ERROR)
        failed = failed or errors > 0
        print(f"{PREFIX} {path}: {ERROR} {errors} 件、{CHECK} {len(findings) - errors} 件。調べたのは機械で数えられる項目だけである。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
