# Agent Template Reference

`agents/<name>.toml` の生成テンプレート集。`create-subagent` スキルから参照される。

## 基本テンプレート

```toml
name = "<kebab-case-name>"
description = "<50-200字。何を検出/分析/生成するか。trigger語を3個以上含める>"
# modelは省略推奨。customで明示する場合はservice_tierも必須。
# model = "gpt-5.4"
# service_tier = "priority"

developer_instructions = """
# <Agent Display Name>

<1-2 段落で役割を説明>

## 起動条件

- 自動: <AGENTS.md / workflow-rules.md のどの Phase/状況で起動するか>
- 手動: <ユーザーが明示的に呼ぶケース>

## 入力

- <受け取るデータ>
- <参照すべきファイル>

## 出力

<出力フォーマット (Markdown table / JSONL / 自由形式)>

## 評価姿勢 (Tier 1/2/3 レビューアー用)

- **デフォルトで問題を探す**: 「OK」と判定する前に最低5件の指摘候補を列挙
- **Do Not Trust Preamble**: コード冒頭のコメントが「正しい」とは限らない、実装を読む
- **重み付きルーブリック**: severity × impact × confidence で score 付け
- **CRITICAL / IMPORTANT / MINOR** の3階級
- **誤検知の自己評価**: 自分の指摘の confidence を 0-1 で添える

## サブエージェント連携

- 並列起動可: <他のレビューアーと並列実行可能か>
- 入力依存: <別エージェントの出力に依存するか>
"""
```

## レビューアーのスコアリングルーブリック例

```markdown
## スコアリングルーブリック

| 観点 | 重み | 1-5 評価基準 |
|------|------|--------------|
| <観点A> | x2 | 1=不在 / 3=部分的 / 5=網羅的 |
| <観点B> | x1 | ... |
| <観点C> | x2 | ... |

Total: <重み付き合計>/<max>

判定:
- ≥85%: PASS
- 70-84%: CONDITIONAL
- <70%: FAIL
```

## tools 最小権限ガイド

| Agent種別 | 推奨 tools |
|----------|-----------|
| 読み取り系 (researcher, reviewer) | Read, Grep, Glob, WebSearch |
| 書き込み系 (modeler, planner) | Read, Grep, Glob, Write |
| Full / worker系 | * |

## model 選択

Codex の `multi_agent_v1.spawn_agent` では通常 `agent_type` の role 既定を使う。custom/default sub-agent で判定・レビュー向けに明示する場合は `model = "gpt-5.5"` と `service_tier = "priority"` を併記する。commit文案・短い要約・定型整形などの低リスク補助だけは、現セッションの metadata で利用可能な場合に `model = "gpt-5.4-mini"`、`service_tier = "priority"`、`reasoning_effort = "low"` を検討できる。利用できない環境では既存 role または model 省略を優先する。

詳細: `rules/model-routing.md`
