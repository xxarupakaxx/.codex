# Model Routing Rules

Codex で sub-agent を起動する際のモデル/role選択ルール。

## 基本方針

- まず `multi_agent_v1.spawn_agent` の `agent_type` を選ぶ。
- role に model/service_tier が設定されている場合は role 既定を使う。
- `default` / custom sub-agent で model を明示する場合は、`service_tier = "priority"` も必ず明示する。
- Claude-only model aliases or slugs are not valid in Codex examples or prompts.
- plugin / skill / agent role の選択は `context/agent-team-routing.md` を参照する。このファイルは model / service_tier 方針に集中する。

## Codex Model Pairs

| 用途 | model | service_tier |
|------|-------|--------------|
| Default / heavy judgment | `gpt-5.5` | `priority` |
| Routine specialist agents | `gpt-5.4` | `priority` |
| Cost-sensitive simple work | role既定または model 省略 | role既定または親セッション継承 |

## Dispatch Table

| 用途 | Codex 呼び出し | モデル方針 |
|------|----------------|------------|
| 探索・監視（explore/pr-watch等） | `spawn_agent(agent_type: "explorer")` / local `rg` | role既定 |
| アーキテクチャ探索 | `architecture-explorer` / `dependency-mapper` / `data-flow-tracer` | role既定 (`gpt-5.4`, `priority`) |
| 軽量ワーカー・通常実装 | `worker` / `implementer` | role既定 |
| 判定・設計判断・計画 | `implementation-planner` / `technical-evaluator` / `go-nogo-advisor` | role既定 |
| 重い実装（3+ファイル） | `implementer` または `worker` に disjoint write scope を明示 | role既定 (`gpt-5.5`, `priority`) |
| 専門レビュー | `arch-reviewer` / `security-reviewer` / `code-quality-reviewer` / `test-reviewer` 等 | role既定 |
| 過去知見検索 | `learnings-researcher` | role既定 (`gpt-5.4`, `priority`) |
| ローカル並列実行 | `multi_tool_use.parallel` | modelなし |
| plugin / skill ルーティング | `context/agent-team-routing.md` | modelなし |

## 判断フロー

```text
Sub-agent 起動時:
  既存 role で表現できる？ → agent_type を指定して role 既定を使う
  3+ファイルまたは複雑実装？ → implementer/worker に明確な write scope を渡す
  計画・判定・高品質レビュー？ → planner/evaluator/reviewer role を使う
  探索・監視・軽量調査？ → explorer 系 role または local rg
  それ以外 → default/custom。model を明示するなら service_tier も明示
```

## team-run の割り当て

| teammate相当 | Codex agent_type | 役割 |
|--------------|------------------|------|
| planner | `implementation-planner` | タスク分解、依存関係、合格基準案 |
| plan-reviewer | `arch-reviewer` または `technical-evaluator` | YAGNI、依存矛盾、実現可能性レビュー |
| explorer | `explorer` / `architecture-explorer` / `dependency-mapper` | 検索ファーストのコードベース調査 |
| implementer | `implementer` / `worker` | disjoint write scope 内の実装 |
| reviewer | `arch-reviewer` / `security-reviewer` / `code-quality-reviewer` / `test-reviewer` | 独立レビュー |

## 注意

- `goal` が使える環境では、長い team-run の開始時に目的を作成し、完了/ブロック時に更新する。
- Superpowers が使える環境では、計画・TDD・検証・レビューの該当スキルを team-run のゲートとして使う。
- `spawn_agent` は同時に最大4件を目安にし、完了済み agent は `close_agent` で閉じる。
