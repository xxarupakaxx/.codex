#!/usr/bin/env python3
"""二つの HTML の変更点を、要素の単位で列挙する。

既存の HTML を直した後に、変えた箇所を依頼と突き合わせるための一覧である。
変えすぎかどうかは判定しない。差分があっても終了コード 0 で終わる。

限界: 対応づけは要素の並びの比較による。同じ内容の要素が大量に並ぶ入力では、対応がずれて
追加と削除が多く出ることがある。要素が数万あると数十秒かかる。
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

PREFIX = "[html-change]"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
HEADINGS = {"h1", "h2", "h3", "h4"}
LONG_ATTRIBUTES = {"d", "points", "srcset", "transform", "viewbox"}  # 座標の列などは名前だけ出す
TEXT_CHARS, VALUE_CHARS, MAX_LINES, PER_KIND = 60, 40, 200, 8
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
KINDS = ("追加", "削除", "文言の変更", "属性だけの変更", "文言と属性の変更")


class Flattener(HTMLParser):
    """要素を文書の順に並べる。各要素は [位置, タグ, 属性, 直下の文字] である。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[list] = []
        self.css: list[str] = []
        self._stack: list[tuple] = []  # (タグ, entries の添字, 自身か祖先の id)
        self._heading = ""

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        nearest = attributes.get("id") or (self._stack[-1][2] if self._stack else "")
        parts = ["#" + nearest if nearest else "", f"「{self._heading}」" if self._heading else ""]
        self.entries.append([" ".join(part for part in parts if part) or "（冒頭）", tag, attributes, ""])
        if tag not in VOID:
            self._stack.append((tag, len(self.entries) - 1, nearest))

    def handle_endtag(self, tag):
        for depth in range(len(self._stack) - 1, -1, -1):
            if self._stack[depth][0] != tag:
                continue
            if tag in HEADINGS:
                inside = " ".join(entry[3] for entry in self.entries[self._stack[depth][1] :])
                self._heading = " ".join(inside.split())[:VALUE_CHARS]
            del self._stack[depth:]
            return

    def handle_data(self, data):
        if not self._stack:
            return
        tag, index, _ = self._stack[-1]
        if tag == "style":
            self.css.append(data)
        else:
            self.entries[index][3] += data


def flatten(text: str):
    parser = Flattener()
    parser.feed(text)
    parser.close()
    for entry in parser.entries:
        entry[3] = " ".join(entry[3].split())
    return parser.entries, css_rules("\n".join(parser.css))


def css_rules(css: str) -> dict:
    rules: dict[str, list[str]] = {}
    for selector, body in CSS_RULE.findall(CSS_COMMENT.sub("", css)):
        rules.setdefault(" ".join(selector.split()), []).append(" ".join(body.split()))
    return rules


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def around(old: str, new: str, limit: int = VALUE_CHARS) -> str:
    """最初に違う位置の前後を切り出して「旧 → 新」にする。長い値の後ろの違いも見えるようにする。"""
    first = next((index for index, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    begin = 0 if max(len(old), len(new)) <= limit else max(0, first - limit // 4)

    def cut(text: str) -> str:
        return ("…" if begin else "") + text[begin : begin + limit] + ("…" if len(text) > begin + limit else "")

    return f"{cut(old)} → {cut(new)}"


def label(entry) -> str:
    _, tag, attributes, _ = entry
    identifier = "#" + attributes["id"] if attributes.get("id") else ""
    first_class = "." + attributes["class"].split()[0] if attributes.get("class", "").strip() else ""
    return f"<{tag}{identifier}{first_class}>"


def attribute_changes(old: dict, new: dict) -> str:
    parts = []
    for name in sorted(set(old) | set(new)):
        if old.get(name) == new.get(name):
            continue
        if name in LONG_ATTRIBUTES:
            parts.append(name)
        else:
            parts.append(f"{name}: {around(old.get(name, '（なし）'), new.get(name, '（なし）'))}")
    return "; ".join(parts)


def paired(old, new):
    """同じタグどうしの対を、文言と属性のどちらが変わったかで分ける。変わっていなければ None。"""
    text_changed, attributes_changed = old[3] != new[3], old[2] != new[2]
    if not text_changed and not attributes_changed:
        return None
    words = f"「{around(old[3], new[3])}」" if text_changed else ""
    attributes = attribute_changes(old[2], new[2]) if attributes_changed else ""
    kind = KINDS[4] if text_changed and attributes_changed else KINDS[2] if text_changed else KINDS[3]
    return new[0], kind, f"{label(new)} {' / '.join(part for part in (words, attributes) if part)}"


def element_changes(before: list, after: list) -> list:
    """(位置, 種類, 説明) を文書の順に返す。"""

    def key(entry):
        return entry[1], tuple(sorted(entry[2].items())), entry[3]

    changes = []
    whole = difflib.SequenceMatcher(None, [key(e) for e in before], [key(e) for e in after], autojunk=False)
    for operation, i1, i2, j1, j2 in whole.get_opcodes():
        if operation == "equal":
            continue
        old_block, new_block = before[i1:i2], after[j1:j2]
        by_tag = difflib.SequenceMatcher(None, [e[1] for e in old_block], [e[1] for e in new_block], autojunk=False)
        for sub, a1, a2, b1, b2 in by_tag.get_opcodes():
            if sub == "equal":
                changes += filter(None, (paired(old, new) for old, new in zip(old_block[a1:a2], new_block[b1:b2])))
                continue
            changes += [(e[0], KINDS[1], f"{label(e)} {clip(e[3], TEXT_CHARS)}".rstrip()) for e in old_block[a1:a2]]
            changes += [(e[0], KINDS[0], f"{label(e)} {clip(e[3], TEXT_CHARS)}".rstrip()) for e in new_block[b1:b2]]
    return changes


def group_lines(items: list, show_all: bool) -> list:
    """同じ種類の行が続いても少ない種類の変更が隠れないよう、まとまりごと、種類ごとに行数を絞る。"""
    shown, seen = [], {}
    for kind, text in items:
        seen[kind] = seen.get(kind, 0) + 1
        if show_all or seen[kind] <= PER_KIND:
            shown.append(f"- {kind} {text}")
    return shown + [f"- {kind} … ほか {count - PER_KIND} 件" for kind, count in seen.items() if not show_all and count > PER_KIND]


def render(changes: list, old_css: dict, new_css: dict, show_all: bool = False) -> str:
    css = [("追加", s) for s in new_css if s not in old_css] + [("削除", s) for s in old_css if s not in new_css]
    css += [("変更", f"{s} {{ {around('; '.join(old_css[s]), '; '.join(new_css[s]))} }}") for s in new_css if s in old_css and old_css[s] != new_css[s]]
    if not changes and not css:
        return f"{PREFIX} 変更なし\n"
    counts = "、".join(f"{kind} {sum(1 for change in changes if change[1] == kind)}" for kind in KINDS)
    css_counts = "、".join(f"{kind} {sum(1 for item in css if item[0] == kind)}" for kind in ("追加", "削除", "変更"))
    # CSS は行数が少ないので先に出す。要素の一覧が長くても隠れない。
    groups: dict[str, list[tuple]] = {"CSS の規則": [(kind, clip(selector, TEXT_CHARS * 2)) for kind, selector in css]} if css else {}
    for anchor, kind, text in changes:
        groups.setdefault(anchor, []).append((kind, text))
    lines = [line for anchor, items in groups.items() for line in ("", f"## {anchor}", *group_lines(items, show_all))]
    if not show_all and len(lines) > MAX_LINES:
        hidden = sum(1 for line in lines[MAX_LINES:] if line.startswith("- "))
        lines = lines[:MAX_LINES] + [f"… ほか {hidden} 行。--all を付けると全件を出す。"]
    footer = "各行が依頼のどの文に対応するかを確かめる。対応しない行は元へ戻すか、変えた理由を本人に伝える。"
    return "\n".join([f"{PREFIX} 要素: {counts} ／ CSS の規則: {css_counts}", *lines, "", footer]) + "\n"


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    parser.add_argument("before", type=Path, help="直す前の HTML")
    parser.add_argument("after", type=Path, help="直した後の HTML")
    parser.add_argument("--all", action="store_true", help="行数を絞らずに全件を出す")
    args = parser.parse_args(argv)
    try:
        (before, old_css), (after, new_css) = (flatten(path.read_text(encoding="utf-8", errors="replace")) for path in (args.before, args.after))
    except OSError as error:
        raise SystemExit(f"html-change-list: 読めない（{error}）")
    sys.stdout.write(render(element_changes(before, after), old_css, new_css, args.all))
    return 0


if __name__ == "__main__":
    sys.exit(main())
