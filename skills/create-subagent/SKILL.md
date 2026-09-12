---
name: create-subagent
description: 自然言語の要件から `agents/<name>.toml` のsub-agent雛形を作る。reviewer、explorer、generatorの追加依頼で、起動条件・最小権限tools・model route・出力形式・評価基準を定義するときに使う。
allowed-tools: Read, Write, Glob, Grep, AskUserQuestion
---

# Create Subagent

自然言語の役割要件を、既存のagent定義と衝突しないTOMLへ変換するメタスキル。`agents/<name>.toml` 以外は書かず、既存ファイルを上書きするときはAskUserQuestionで確認する。

## 要件の確定

`/create-subagent <要件>` または同等の依頼を受けたら、役割（review / exploration / generation / evaluation）、自動または手動の起動条件、入力、出力（issue file / inline / structured JSON）、write scope、外部情報の要否を整理する。不明点でagentの境界や副作用が変わる場合だけ確認する。既存 `agents/` はGlobで調べて重複を避ける。

## Tierとmodel route

modelとservice tierは `rules/model-routing.md` のcurrent runtime resolutionを正本にし、通常は両方をTOMLから省略して親session/role既定を継承する。

| Tier | 例 | 方針 |
| --- | --- | --- |
| 1 | 標準のarchitecture/performance review | role既定を継承 |
| 2 | quality/test/observability/a11y review | 必要なときだけ追加 |
| 3 | security、PRD、複雑な判断 | heavy roleを選ぶ |
| Explorer | file検索、pattern調査 | 既存explorer roleを優先 |
| Fast helper | commit文案、短い要約、定型整形 | toolなしでleadが即検査できる場合だけ |

Fast helperで不確実性、矛盾、複数ファイル判断、ユーザー影響が出たらleadへ戻す。固定のlegacy model slugや `service_tier` をこのSkillへ複製しない。

## nameとdescription

- nameは小文字、数字、hyphenを使う64文字以下の識別名（例 `api-contract-reviewer`）。
- descriptionは第三者の文で1024文字以内にし、「何を」「いつ」「どのtrigger語で」呼ぶかを含める。XMLタグ、1人称、責務外の一般論を入れない。

## TOMLの生成

`references/agent-template.md` を読み、必要な項目だけを埋める。

```toml
name = "<kebab-case-name>"
description = "<役割・起動条件・trigger語>"
# model / service_tier は rules/model-routing.md に沿って必要な場合だけ指定

developer_instructions = """
# <Agent Display Name>

<役割と完了条件>

## 起動条件
- 自動: <workflow/phase/状況>
- 手動: <明示呼び出し>

## 入力
- <データと参照path>

## 出力
- <形式、保存先、短い最終報告>

## 境界
- <owned paths、触らないpath、外部writeの承認>
"""
```

reviewer系には次をdeveloper instructionsへ含める。

- コード冒頭のコメントを信頼せず実装で検証する `Do Not Trust Preamble`。
- evidence、見逃しコスト、誤検知のconfidence（0〜1）を明記する。
- CRITICAL / IMPORTANT / MINORの優先度と、観点・重み・1/3/5基準のルーブリックを定義する。
- 他agentとの並列可否、入力依存、issue fileまたはinlineの出力形式を定義する。

探索系は `Read, Grep, Glob`、レビュー系は必要に応じて `Read, Grep, Glob, WebSearch, Write`、生成・編集系は `Read, Write, Edit` を最小単位で選ぶ。Bashを漫然と付与しない。外部情報が必要なときだけ `WebSearch` / `WebFetch` を含め、credentialsや秘密をagent promptへ渡さない。

## 配置と報告

生成先は `agents/<name>.toml`。起動には現在のsessionのcollaboration capabilityを使い、固定API名を仮定しない。必要なら既存roleの起動例だけを報告する。

作成後に次を確認する。

- nameが既存agentと衝突しない。
- descriptionが役割・trigger・実行時期を識別できる。
- model route、service tier、toolsが最小権限である。
- reviewerならDo Not Trust Preamble、ルーブリック、3階級、出力形式がある。
- writerのowned paths、外部write、承認、秘密境界が明記されている。

既存と重複する責務、曖昧なtrigger、不要なmodel固定、toolの取りすぎ、レビュー系の主観採点だけは不合格とする。関連する正本は `rules/model-routing.md`、`context/agent-team-routing.md`、`create-skill`、`create-hook`、`create-mcp-server`。
