---
name: team-run
description: "team-run を起動すると Codex の goal / Superpowers / multi_agent_v1 を使い、leader が適材適所で専門 sub-agent に割り当て、合格基準を満たすまで loop engineering で回す。共有メモリ(Team Journal)で周をまたいだ失敗原因を持ち越す。並列の幅が要る高価値タスク限定。"
---

# /team-run — Codex Agent Team を loop engineering で回す

**メインセッション（あなた）= team-lead。全 sub-agent はメインセッションが直接 spawn する。**

Codex では `goal` で長い作業の目的を固定し、Superpowers で計画/検証/レビューのゲートを強化し、`multi_agent_v1.spawn_agent` で必要な専門 sub-agent を起動する。

## 使う前に — 本当にチームが要るか

マルチは高コスト。まず単一セッション + 良い文脈を基準にし、並列の幅が本当に要る時だけ team-run。

| 状況 | 使うもの |
|------|---------|
| 逐次依存・同一ファイル・密結合・低価値 | 単一セッション |
| 独立したローカル調査・ファイル読み取り | `multi_tool_use.parallel` |
| 独立した調査/実装/レビューを並列化したい | `multi_agent_v1.spawn_agent` |
| 複数ターンで目的・失敗原因・レビューを持ち越す高価値タスク | `/team-run` |

## loop engineering の形

```text
goalを作る → 合格基準を先に定義 → [割り当て→並行実行→検証] を合格まで回す → update_goalで完了/ブロックを記録
```

価値は「回すこと」ではなく、合格基準（検証器）の固さ、独立レビュー、止め方にある。

## Codex 前提（CRITICAL）

- `config.toml` の default model は `gpt-5.5`、`service_tier = "priority"`。
- `features.goals = true` を有効化し、長い team-run は `create_goal` / `update_goal` を使う。
- Superpowers plugin が使える環境では、関連スキルをゲートとして使う。
- plugin / skill / agent role の選択は `context/agent-team-routing.md` を参照し、Phase順序やmodel方針は重複定義しない。
- `multi_agent_v1.spawn_agent` は role 既定の model/service_tier を優先する。
- custom/default sub-agent に model を明示する場合は `model = "gpt-5.5"` または `model = "gpt-5.4"` と `service_tier = "priority"` を必ずセットする。
- Codex で無効な model 名は prompts/examples に書かない。
- 同時 sub-agent は4件目安。完了済み agent は `close_agent` で閉じる。
- sub-agent は lead の会話履歴を持たない。状態は Team Journal に逃がす。

## Superpowers の使い所

| 場面 | Superpowers skill |
|------|-------------------|
| 要求が曖昧・設計余地が大きい | `superpowers:brainstorming` |
| 実装計画を固める | `superpowers:writing-plans` |
| 独立タスクを並列委任する | `superpowers:dispatching-parallel-agents` / `superpowers:subagent-driven-development` |
| バグ診断 | `superpowers:systematic-debugging` |
| 実装完了前 | `superpowers:verification-before-completion` |
| merge/PR 前 | `superpowers:requesting-code-review` / `superpowers:finishing-a-development-branch` |

Codex 側ではスキル本文を読んでから、その指示を現在の tool 名に対応させる。

## Codex 実行プリミティブ

| 必要なこと | Codex で使うもの |
|----------|------------------|
| 長い作業の目的固定 | `create_goal` / `update_goal` |
| sub-agent 起動 | `multi_agent_v1.spawn_agent` |
| sub-agent 結果待ち | `multi_agent_v1.wait_agent` |
| 完了済み agent の整理 | `multi_agent_v1.close_agent` |
| 進捗・失敗原因の共有 | Team Journal と計画チェックリスト |
| 独立したローカルfan-out | `multi_tool_use.parallel` |
| プロセス規律 | Superpowers skills を読んで Codex tool に対応させる |

## Agent Role Routing

`rules/model-routing.md` を model / service_tier の SSoT とする。plugin / skill / agent role の選択は `context/agent-team-routing.md` を参照する。team-run でよく使う role は以下。

| teammate相当 | Codex agent_type | 役割 |
|--------------|------------------|------|
| planner | `implementation-planner` | タスク分解、依存関係、合格基準案 |
| plan-reviewer | `arch-reviewer` / `technical-evaluator` | YAGNI、依存矛盾、実現可能性レビュー |
| explorer | `explorer` / `architecture-explorer` / `dependency-mapper` | 検索ファーストのコード調査 |
| implementer | `implementer` / `worker` | disjoint write scope 内の実装 |
| reviewer | `arch-reviewer` / `security-reviewer` / `code-quality-reviewer` / `test-reviewer` | 独立レビュー |
| final judge | `go-nogo-advisor` / `auditor-reviewer` | GO/NO-GO、採否判定 |

## コンテキスト保護（CRITICAL）

全 sub-agent への指示に必ず含める:

```text
- lead への最終報告は 1-3 行の compact サマリーのみ
- 詳細は変更ファイル、検証コマンド、レビュー観点の箇条書きに分ける
- コードブロック・巨大 diff・長いログは最終報告に含めない
- JSON を返す場合も 200 字程度に抑える
- 他 agent / user の変更を revert しない
```

## フロー

このフローは `context/workflow-rules.md` の Phase 0-5.5 上で動く **team-run 固有の orchestration overlay**。Phase の正式順序・必須ゲート・05_log.md 更新ルールは常に `context/workflow-rules.md` を優先する。以下は各Phase内で追加する team-run 手順であり、global workflow の代替ではない。

### Phase 0: PJ設定読込

`context/workflow-rules.md` の Phase 0 を先に満たす。つまり、メモリディレクトリと05_log.mdを作成し、過去知見検索（原則 `learnings-researcher`）を実行して記録する。

そのうえで PJ `AGENTS.md` の一般制約を確認する。次にグローバルの `context/agent-team-routing.md` を baseline として読み、PJ の `.codex/context/agent-team-routing.md` があれば routing override として重ねる。最後に PJ の `.codex/context/team-run.md` があれば team composition / review policy override として重ねる。両方ある場合、`.codex/context/team-run.md` は `/team-run` 固有事項にだけ適用し、一般 routing は `.codex/context/agent-team-routing.md` を優先する。

### Phase 1: 起動・計画

1. **goal 作成**: 長い作業なら `create_goal` で objective を固定する。既存 goal がある場合はその目的と矛盾しないか確認する。
2. **global Phase 1 調査**: `context/workflow-rules.md` に従い、外部情報参照（deepwiki / WebSearch / Context7 の最低1つ）と既存コード確認、GO/NO-GO検証を05_log.mdに記録する。
3. **Plugin route 選択**: `context/agent-team-routing.md` に従い、Superpowers / Product Design / Data Analytics / Sites / Slack / GitHub などの router skill を必要に応じて読む。
4. **Superpowers 確認**: 該当する Superpowers skill を読む。曖昧な設計なら brainstorming、明確な実装なら writing-plans / dispatching-parallel-agents を使う。
5. **global Phase 2 計画**: `context/workflow-rules.md` に従い、30_plan.md を作成し、3ファイル以上の変更なら `deepening-plan` を実行してからサブエージェント計画検証へ進む。
6. **合格基準定義**: 機械判定を背骨にする。test / typecheck / lint / build / 実行確認で嘘をつけない形にする。
7. **Team Journal 初期化**: `.local/memory/<task>/team-journal.md` に合格基準 / Budget / leader 状態 / plugin route を書く。
8. **planner 起動**:

```text
spawn_agent(
  agent_type: "implementation-planner",
  message: "タスクを最大10件に分解し、blockedBy、plugin route、合格基準、リスク、推奨agent_typeを compact JSON で返す。Codexで無効なmodel名は使わない。"
)
```

9. **plan-reviewer 起動**:

```text
spawn_agent(
  agent_type: "arch-reviewer",
  message: "計画を YAGNI・過剰分解・依存矛盾・実現可能性・検証可能性でレビューし、approve/needs-revision と CRITICAL/IMPORTANT/MINOR を返す。"
)
```

10. **人間ゲート**: 仕様変更・外部副作用・破壊的操作・広範囲変更はユーザー承認を取る。既にユーザーが実行を明示し、変更がローカル設定/ドキュメントに閉じる場合は、計画をログに残して進めてよい。

### Phase 2: 実装ループ

1. **割り当て**: 依存のないタスクだけ並列化する。write scope が重なるタスクは並列化しない。
2. **explorer**: 調査タスクは `explorer` / `architecture-explorer` に渡す。検索ファーストで、必要箇所だけ読む。
3. **implementer**: 実装タスクは `implementer` / `worker` に渡す。3+ファイルや複雑実装は必ず write scope と境界を明示する。
4. **共有**: 各 sub-agent の結果を Team Journal に要約し、失敗は症状ではなく原因で Attribution に残す。
5. **Budget/Stop**: 差し戻しは最大3回、連続失敗2回で escalate。これを超える場合は `update_goal(status="blocked")` の対象。

### Phase 3: レビュー

実装完了後、maker の自己申告だけでは完了扱いにしない。成果物だけを見て checker が通す。

推奨レビュー:

```text
spawn_agent(agent_type: "arch-reviewer", message: "変更差分をレビュー。CRITICAL/IMPORTANT/MINORで返す。")
spawn_agent(agent_type: "security-reviewer", message: "変更差分をレビュー。CRITICAL/IMPORTANT/MINORで返す。")
spawn_agent(agent_type: "code-quality-reviewer", message: "変更差分をレビュー。CRITICAL/IMPORTANT/MINORで返す。")
```

- CRITICAL は必ず修正する。
- IMPORTANT は原則修正する。見送る場合は理由を Team Journal に残す。
- test の緩和、skip、削除、検証コマンドの形骸化は不合格。
- 重要判断やリスクが高い変更では `adversarial-review` / `auditor-reviewer` を追加する。
- Superpowers の `requesting-code-review` が適用できる場合は使う。

### Phase 4: 検証

2段階で検証する。

1. 各タスクが個別に合格基準を満たすか。
2. 統合後に全体の test / typecheck / lint / build / 実行確認が通るか。

完了を主張する前に `superpowers:verification-before-completion` を使い、fresh な検証コマンドの出力を確認する。

### Phase 5: 終了

1. `update_goal(status="complete")` または、同じブロッカーが3回続いた場合のみ `blocked`。
2. 完了済み sub-agent を `close_agent` で閉じる。
3. Orchestration Report を出す。

```markdown
## Orchestration Report
- Status: SHIP | NEEDS_WORK | BLOCKED
- Goal: ...
- Task Status: done / in_progress / blocked / pending
- Changed Files: [...]
- Verification: [...]
- Review Findings: [...]
- Blockers: [...]
```

4. 価値ある知見・失敗パターンは `compounding-knowledge` で保存する。

## Team Journal テンプレート

```markdown
# Team Journal: <task-name>
> 使い方: turn 開始前に定位置と直近 Attribution を読む。turn 終了時に Trace へ append する。

## 定位置（leader 単独が毎周更新）
- Goal: ...
- 合格基準: （機械判定: ... / 判断ベース: ...）
- Budget 残: sub-agent _/4 ・差し戻し _/3 ・連続失敗 _
- 現在の周: N / 直近の失敗（原因）: ...

## 決定ログ Decision Log
| 時刻 | agent | 決定 | 理由 |

## 軌跡 Trace
### [agent-name]
- やったこと / 成果物 file:line / 申し送り / ブロッカー

## 失敗・差し戻し Attribution
| agent | task | 失敗内容 | 原因 | ラウンド |
```

## 参照

- `rules/model-routing.md` — Codex role/model/service_tier の SSoT
- `context/agent-team-routing.md` — plugin / skill / agent role 選択の SSoT
- `skills/autonomous-loops/SKILL.md` — Budget/Stop とループ戦略
- `skills/compounding-knowledge/SKILL.md` — 完了後の知見保存
- `context/loop-engineering.md` — 実行モデル
- `commands/pr-watch.md` — PR作成後のCI/レビュー継続監視
