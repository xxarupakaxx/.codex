# Model Routing Rules

Codex で sub-agent を起動する際のモデル/role選択ルール。

## 基本方針

- まず `multi_agent_v1.spawn_agent` の `agent_type` を選ぶ。
- role に model/service_tier が設定されている場合は role 既定を使う。
- `default` / custom sub-agent で model を明示する場合は、`service_tier = "priority"` も必ず明示する。
- Claude-only model aliases or slugs are not valid in Codex examples or prompts.（例外: 外部相談ブリッジ `scripts/consult-fable.sh` 内の `--model fable` は claude CLI への引数であり対象外。末尾の External Consult 節を参照）
- plugin / skill / agent role の選択は `context/agent-team-routing.md` を参照する。このファイルは model / service_tier 方針に集中する。

## Codex Model Pairs

| 用途 | model | service_tier |
|------|-------|--------------|
| Default / heavy judgment | `gpt-5.5` | `priority` |
| Routine specialist agents | `gpt-5.4` | `priority` |
| Simple custom/default helper work | `gpt-5.4-mini` | `priority` |
| Role-backed work | role既定または model 省略 | role既定または親セッション継承 |

`gpt-5.4-mini` は、現セッションの `multi_agent_v1.spawn_agent` metadata で利用可能な場合だけ使う。既存 role があるなら model override ではなく role 既定を優先する。custom/default sub-agent で model を明示する場合は、mini でも `service_tier = "priority"` を併記する。

## Service Tier Policy

この Vault の Codex 互換ルールでは、custom/default sub-agent で model を明示する場合に `service_tier = "priority"` を併記する。
これは互換性とレイテンシのためのローカル方針であり、OpenAI API 一般の最安構成を意味しない。
コスト最適化は service tier を下げることではなく、L0 local、文脈削減、Heat ladder、mini の限定投入で行う。
API レスポンスなどで実際に適用された service tier が取得できる場合は、requested tier ではなく actual tier をログや評価の根拠にする。

## Dispatch Table

| 用途 | Codex 呼び出し | モデル方針 |
|------|----------------|------------|
| 探索・監視（explore/pr-watch等） | `spawn_agent(agent_type: "explorer")` / local `rg` | role既定 |
| アーキテクチャ探索 | `architecture-explorer` / `dependency-mapper` / `data-flow-tracer` | role既定 (`gpt-5.4`, `priority`) |
| 軽量ワーカー・通常実装 | `worker` / `implementer` | role既定 |
| commit文案・短い要約・定型整形 | `default` with explicit model when delegation is useful | `gpt-5.4-mini`, `service_tier="priority"`, `reasoning_effort="low"` |
| 判定・設計判断・計画 | `implementation-planner` / `technical-evaluator` / `go-nogo-advisor` | role既定 |
| 重い実装（3+ファイル） | `implementer` または `worker` に disjoint write scope を明示 | role既定 (`gpt-5.5`, `priority`) |
| 専門レビュー | `arch-reviewer` / `security-reviewer` / `code-quality-reviewer` / `test-reviewer` 等 | role既定 |
| 過去知見検索 | `learnings-researcher` | role既定 (`gpt-5.4`, `priority`) |
| ローカル並列実行 | `multi_tool_use.parallel` | modelなし |
| plugin / skill ルーティング | `context/agent-team-routing.md` | modelなし |
| 戦略相談・taste判断（外部・on-demand） | shell: `scripts/consult-fable.sh`（`skills/consult-fable/SKILL.md` 参照） | Codex ladder外（Fable 5） |

## 判断フロー

```text
Sub-agent 起動時:
  既存 role で表現できる？ → agent_type を指定して role 既定を使う
  default/custom で、短い定型作業かつ失敗してもleadが即検査できる？ → gpt-5.4-mini + service_tier priority + low effort
  3+ファイルまたは複雑実装？ → implementer/worker に明確な write scope を渡す
  計画・判定・高品質レビュー？ → planner/evaluator/reviewer role を使う
  探索・監視・軽量調査？ → explorer 系 role または local rg
  それ以外 → default/custom。model を明示するなら service_tier も明示
```

## Cost Ladder

| Level | 使う場面 | 例 | 昇格条件 |
|-------|----------|----|----------|
| L0 local | shell/rg/diff で十分 | ファイル列挙、差分確認、format check | 判断・要約が必要 |
| L1 mini | default/custom の単純作業 | commit文案、短いlog要約、既知形式への整形、重複チェック | 不確実性、矛盾、複数ファイル判断、ユーザー影響 |
| L2 routine role | 専門 role がある通常作業 | explorer、docs-reviewer、arch-reviewer | CRITICAL/IMPORTANT、広い設計判断 |
| L3 heavy role | 失敗コストが高い判断 | technical-evaluator、security-reviewer、go-nogo-advisor、implementer | さらに独立審判が必要 |

### `gpt-5.4-mini` を使ってよい条件

- 入力が短く、成果物を lead がすぐ検査できる。
- 変更を書かない、または書く場合でも単一の低リスク text artifact に閉じる。
- 失敗時のコストが低く、再実行や lead 修正が容易。
- `service_tier = "priority"` と `reasoning_effort = "low"` を明示できる。
- 例: git-cz 日本語 commit message 候補、短い調査ログ要約、明確なテンプレートへの整形、重複 URL/見出しの検出。

### `gpt-5.4-mini` を使わない条件

- セキュリティ、認証、課金、データ削除、外部書き込み、GO/NO-GO 判定。
- 3ファイル以上の実装、未知コードの設計判断、レビューの最終判定。
- ユーザー要件が曖昧、ソース間に矛盾がある、引用や法務・医療・金融など高リスク根拠が必要。
- role 定義済み agent で表現できる作業。role 既定を override しない。

## team-run の割り当て

| teammate相当 | Codex agent_type | 役割 |
|--------------|------------------|------|
| planner | `implementation-planner` | タスク分解、依存関係、合格基準案 |
| plan-reviewer | `arch-reviewer` または `technical-evaluator` | YAGNI、依存矛盾、実現可能性レビュー |
| explorer | `explorer` / `architecture-explorer` / `dependency-mapper` | 検索ファーストのコードベース調査 |
| implementer | `implementer` / `worker` | disjoint write scope 内の実装 |
| reviewer | `arch-reviewer` / `security-reviewer` / `code-quality-reviewer` / `test-reviewer` | 独立レビュー |

## External Consult（外部相談段・Codex ladder の外）

Codex の model ladder の上に、外部モデルへの単発戦略相談がある。

- 経路: `consult-fable` スキル → `scripts/consult-fable.sh` → claude CLI（`claude -p --model fable`）。shell 実行であり `spawn_agent` では呼ばない。
- `fable` は claude CLI の引数であり、Codex の model 指定には書かない（冒頭の Claude-only aliases ルールは維持）。
- 昇格条件・1往復原則・セキュリティ境界の SSoT は `skills/consult-fable/SKILL.md`。
- hot path に入れない: 毎ターン・毎 workflow の常設段にしない。日次上限ガードあり。

## 注意

- `goal` が使える環境では、長い team-run の開始時に目的を作成し、完了/ブロック時に更新する。
- Superpowers が使える環境では、計画・TDD・検証・レビューの該当スキルを team-run のゲートとして使う。
- `spawn_agent` は同時に最大4件を目安にし、完了済み agent は `close_agent` で閉じる。
