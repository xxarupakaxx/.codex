---
name: project-sync
description: PJドキュメント同期。PJ AGENTS.md/CLAUDE.mdの更新や整理で、AGENTS.mdを正本、CLAUDE.mdをimport入口としてuser-level方針へ整合させる。
allowed-tools: Read, Write, Bash, Glob, Grep
---

# PJドキュメント同期

## トリガー条件

- PJ `AGENTS.md` または `CLAUDE.md` の更新を依頼された場合
- ドキュメント構造の整理を依頼された場合
- user-level `AGENTS.md` に合わせるよう依頼された場合

## 所有境界

| 対象 | 配置場所 | 用途 |
|---|---|---|
| 人間向け | `README.md`, `docs/` | プロジェクト説明、API仕様、設計文書 |
| Agent入口 | `AGENTS.md` | PJ固有の現在形の不変条件と正本への導線 |
| Claude互換入口 | `CLAUDE.md` | `@AGENTS.md` importのみ |
| 詳細契約 | `.codex/context/`, `docs/`, Skill | workflow override、背景、反復手順 |

## 実行手順

### 1. 現状把握

```bash
cat AGENTS.md 2>/dev/null || echo "AGENTS.md not found"
cat CLAUDE.md 2>/dev/null || echo "CLAUDE.md not found"
wc -l AGENTS.md 2>/dev/null
find .codex/context docs -maxdepth 2 -type f 2>/dev/null
```

user-level `~/.codex/AGENTS.md` と、その正本 map が指す `context/`、`rules/`、`skills/` も必要な範囲だけ確認する。

### 2. 差分分析

- `AGENTS.md` が短い入口になっているか
- `MEMORY_DIR`、`BASE_BRANCH`、品質チェックが PJ `AGENTS.md` にあるか
- 詳細手順、履歴、完了済みTODO、理由説明が適切な正本へ分離されているか
- `CLAUDE.md` が `@AGENTS.md` だけか
- 例外に理由、範囲、解除条件があるか
- 既存ruleとの矛盾、重複、dead linkがないか

### 3. 更新提案

変更前に、対象、変更概要、理由、削除・移動の有無、検証方法を提示する。削除、rename、外部writeは別の user gate を維持する。

新規PJは `templates/project/AGENTS.md` と `templates/project/CLAUDE.md` を基準にする。

### 4. 承認後の実行

1. `AGENTS.md` を現在形の不変条件と正本導線へ更新する。
2. `CLAUDE.md` を `@AGENTS.md` import のみにする。
3. 承認された範囲だけ詳細文書を移動・統合する。
4. 編集したMarkdown全体を読み直し、矛盾、重複、rule漏れを修正する。

### 5. 検証

```bash
wc -l AGENTS.md
test "$(tr -d '\r\n' < CLAUDE.md)" = '@AGENTS.md'
git diff --check
git diff --name-status
```

用語や導線を置換した場合は、旧語彙を `rg` で横断検索し、意図した互換説明以外の残存がないことを確認する。projectに専用validatorがある場合は必ず実行する。

## 完了条件

- [ ] `AGENTS.md` が短い入口で、PJ変数・品質チェック・固有不変条件を持つ
- [ ] `CLAUDE.md` が `@AGENTS.md` importのみ
- [ ] 詳細手順と判断理由が適切な正本へ分離されている
- [ ] 削除・rename・外部writeが承認範囲内
- [ ] Markdown全体、参照、diff、project validatorがPASS
