# Model Routing Rules

Claude Code から Agent Tool でサブエージェントを起動する際のモデル選択ルール。

## 基本方針

通常は `model` を省略し、親セッションのモデルを継承させる。明示的なモデル指定は特定の用途のみ。

## Dispatch Table（Source of Truth）

| 用途 | 呼び出し方法 | モデル |
|------|-------------|--------|
| 探索・監視（explore/pr-watch等） | `Agent(model: "gpt-5.5")` | gpt-5.5 |
| 軽量ワーカー・実装 | `Agent(model: "gpt-5.5")` | gpt-5.5 |
| 判定・設計判断・計画・レビュー | `Agent(model: "gpt-5.5")` | gpt-5.5 |
| 重い実装（3+ファイル） | `Agent(subagent_type: "codex:codex-rescue")` | gpt-5.x（Codex側で管理） |
| 専門レビュー | `Agent(subagent_type: "arch-reviewer")` 等 | gpt-5.5推奨（明示指定） |
| 過去知見検索 | `Agent(subagent_type: "learnings-researcher")` | 継承 |
| Workflowパイプライン | `Workflow({script: ...})` 内の `agent()` | 継承（`model` オプションで上書き可） |

## 判断フロー

```
Agent起動時:
  重い実装？ → codex:codex-rescue
  計画・判定・高品質レビュー？ → model: "gpt-5.5"
  実装（中程度）？ → model: "gpt-5.5"
  探索・監視・軽量タスク？ → model: "gpt-5.5"
  それ以外 → model省略（継承）
```

## team-run のモデル割り当て

| teammate | subagent_type | model |
|----------|--------------|-------|
| planner  | Plan | **gpt-5.5** |
| explorer | Explore | **gpt-5.5** |
| implementer | implementer | **gpt-5.5** |
| reviewer | arch-reviewer 等 | **gpt-5.5** |

## Workflow内のmodel指定

Workflow Tool の `agent()` 関数では `model` オプションで上書き可能:
- `agent('...', { model: "gpt-5.5" })` — 判定・レビュー用
- `agent('...', { model: "gpt-5.5" })` — 軽量タスク用
- `agent('...')` — model省略で親セッション継承

## 注意

- 迷ったら model を省略する
- Adversarial Review（Red/Blue/Auditor）のモデル割り当ては `adversarial-review` スキルの定義に従う
- Tier 1-3レビューアーは各 `agents/*.md` の定義で品質を担保する
