---
name: team-run
description: "team-run は goal と Team Journal で長い作業を保ち、必要な場合だけ sub-agent に委任して合格基準まで loop engineering で回す。明示起動しても複数 agent を必須にしない。"
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
goalを作る → 合格基準を先に定義 → [lead実行または必要な委任→検証] を合格まで回す → update_goalで完了/ブロックを記録
```

価値は「回すこと」ではなく、合格基準（検証器）の固さ、独立レビュー、止め方にある。

## team-run の芯

`goal` は Done を固定する背骨だが、team-run の完了証明ではない。長い作業では以下を分けて扱う:

- Goal: 目的・Done・停止条件。
- Sprint Contract: 機械判定できる合格基準。
- Team Journal: 周回をまたぐ現在地・決定・失敗原因。
- Review Heat: 変更リスクに応じた checker / judge の選択。

チーム構成、レビュー熱量、終了判定の詳細は `context/team-run.md` を読む。Phase 順序やレビュー戦略の SSoT は引き続き `context/workflow-rules.md`。

## Codex 前提（CRITICAL）

- `config.toml` の default model は `gpt-5.5`、`service_tier = "priority"`。
- `features.goals = true` を有効化し、長い team-run は `create_goal` / `update_goal` を使う。
- Superpowers plugin が使える環境では、関連スキルをゲートとして使う。
- plugin / skill / agent role の選択は `context/agent-team-routing.md` を参照し、Phase順序やmodel方針は重複定義しない。
- `multi_agent_v1.spawn_agent` は role 既定の model/service_tier を優先する。
- custom/default sub-agent に model を明示する場合は `rules/model-routing.md` の許可モデル集合に従い、必ず `service_tier = "priority"` をセットする。
- `gpt-5.4-mini` は、現セッションの `spawn_agent` metadata で利用可能な場合に限り、commit文案、短い要約、定型整形など、低リスクで lead が即検査できる default/custom 作業に使える。利用できない環境では role 既定または model 省略へ戻す。
- Codex で無効な model 名は prompts/examples に書かない。
- 同時 sub-agent は4件目安。完了済み agent は `multi_agent_v1.close_agent` で閉じる。
- sub-agent は lead の会話履歴を持たない。状態は Team Journal に逃がす。

## Cost/Budget Gate

team-run は高価なので、起動前に次を順に確認する。

委任判断の SSoT は `context/agent-team-routing.md` の Delegation Gate とする。`team-run` が明示されても Gate を満たす作業がなければ、single-lead mode で Goal、Team Journal、検証ループだけを運用する。

1. **L0 local で足りるか**: `rg`、`git diff`、既存スクリプト、`multi_tool_use.parallel` で独立読み取りを処理できるなら sub-agent を起動しない。
2. **L1 mini で足りるか**: commit文案、短いログ要約、定型整形、重複検出だけなら、現セッションの metadata で利用可能な場合に限り、必要時のみ `default` + `model="gpt-5.4-mini"` + `service_tier="priority"` + `reasoning_effort="low"` を使う。利用不可なら role 既定または model 省略へ戻す。
3. **L2 role 既定が必要か**: 専門 role で表現できる調査・レビューは role 既定を使う。
4. **L3 heavy が必要か**: GO/NO-GO、セキュリティ、重要設計、複雑実装は heavy role に任せる。mini に落とさない。

mini で一度でも不確実性、矛盾、複数ファイル判断、ユーザー影響が出たら、その round は止めて role 既定へ昇格する。`service_tier` を落とすことをコスト最適化として扱わない。

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

`rules/model-routing.md` を model / service_tier / agent_type 対応の SSoT とする。plugin / skill / agent role の選択は `context/agent-team-routing.md` を参照する。ここでは team-run 内の役割ラベルだけを示す。

| team-run label | 役割 |
|----------------|------|
| planner | タスク分解、依存関係、合格基準案 |
| plan-reviewer | YAGNI、依存矛盾、実現可能性レビュー |
| explorer | 検索ファーストのコード調査 |
| maker | disjoint write scope 内の実装 |
| checker | 成果物ベースの独立レビュー |
| final judge | GO/NO-GO、採否判定 |

## コンテキスト保護（CRITICAL）

全 sub-agent への指示に必ず含める:

```text
- lead への最終報告は 1-3 行の compact サマリーのみ
- 詳細は変更ファイル、検証コマンド、レビュー観点の箇条書きに分ける
- コードブロック・巨大 diff・長いログは最終報告に含めない
- JSON を返す場合も 200 字程度に抑える
- ユーザーが逐語で読むべき成果物（計画・重要 findings・生成文書）は、ファイルに書き、その path を最終報告に含める
- 他 agent / user の変更を revert しない
```

lead は、sub-agent から path 付きで届いた user-facing 成果物（ユーザーが逐語で読むべき計画・重要 findings・生成文書）を自分で読み、要約せず原文をユーザーへの報告に含める。

### Context Slimming

sub-agent へ渡す文脈は、全文ではなく次の薄い束にする。

- objective: 今回の subtask で完了すべきこと。
- scope: 読む/書く対象パス、触ってよい境界、触らない境界。
- acceptance: 機械検証または reviewer 観点。
- prior failure: 直近の失敗原因。症状だけを書かない。
- output: 期待する短い報告形式。

Team Journal と 05_log.md が正本なので、同じ背景説明を毎回貼り直さない。

## フロー

このフローは `context/workflow-rules.md` の Phase 0-5.5 上で動く **team-run 固有の orchestration overlay**。Phase の正式順序・必須ゲート・05_log.md 更新ルールは常に `context/workflow-rules.md` を優先する。以下は各Phase内で追加する team-run 手順であり、global workflow の代替ではない。

### Overlay A: global Phase 0 内 — PJ設定読込

`context/workflow-rules.md` の Phase 0 を先に満たす。つまり、メモリディレクトリと05_log.mdを作成し、過去知見検索（原則 `learnings-researcher`）を実行して記録する。

そのうえで PJ `AGENTS.md` の一般制約を確認する。次にグローバルの `context/agent-team-routing.md` を baseline として読み、`context/team-run.md` を team-run policy として読む。PJ の `.codex/context/agent-team-routing.md` があれば routing override として重ねる。最後に PJ の `.codex/context/team-run.md` があれば team composition / review policy override として重ねる。両方ある場合、`.codex/context/team-run.md` は `/team-run` 固有事項にだけ適用し、一般 routing は `.codex/context/agent-team-routing.md` を優先する。

### Overlay B: global Phase 1-2 内 — 起動・計画

1. **goal 作成**: 長い作業なら `create_goal` で objective を固定する。既存 goal がある場合はその目的と矛盾しないか確認する。
2. **global Phase 1 調査**: `context/workflow-rules.md` に従い、外部情報参照（deepwiki / WebSearch / Context7 の最低1つ）と既存コード確認、GO/NO-GO検証を05_log.mdに記録する。
3. **Budget route 選択**: `rules/model-routing.md` の Cost Ladder で L0 local / L1 mini / L2 role / L3 heavy を選ぶ。選択理由を Team Journal に記録する。
4. **Plugin route 選択**: `context/agent-team-routing.md` に従い、Superpowers / Product Design / Data Analytics / Sites / Slack / GitHub などの router skill を必要に応じて読む。
5. **Superpowers 確認**: 該当する Superpowers skill を読む。曖昧な設計なら brainstorming、明確な実装なら writing-plans / dispatching-parallel-agents を使う。
6. **global Phase 2 計画**: `context/workflow-rules.md` に従い、30_plan.md を作成し、3ファイル以上の変更なら `deepening-plan` を実行してからサブエージェント計画検証へ進む。
7. **合格基準定義**: 機械判定を背骨にする。test / typecheck / lint / build / 実行確認で嘘をつけない形にする。
8. **Team Journal 初期化**: `${MEMORY_DIR}/memory/YYMMDD_<task_name>/team-journal.md` に合格基準 / Budget / leader 状態 / plugin route / model route を書く。
9. **Live Roadmap 起動（任意だが推奨）**: Codex app の横で進捗を見たい場合、`scripts/generate-roadmap-view.py ${MEMORY_DIR}/memory/YYMMDD_<task_name> --serve --watch` を起動し、URLをTeam Journalへ記録する。既定port `0` を使い、複数セッションはメモリディレクトリを分けて衝突を避ける。
10. **Review Heat 仮決定**: `context/team-run.md` の Heat ladder で checker / judge の初期セットを決め、Team Journal に記録する。
11. **planner の要否判定**: lead が依存関係と合格基準を直接作れず、独立した計画文脈に利益がある場合だけ起動する。

```text
multi_agent_v1.spawn_agent(
  agent_type: "implementation-planner",
  message: "タスクを最大10件に分解し、blockedBy、plugin route、合格基準、リスク、推奨agent_typeを compact JSON で返す。Codexで無効なmodel名は使わない。"
)
```

12. **plan-reviewer の要否判定**: 高リスク、policy 自己改変、機械検証不能のいずれかに該当する場合だけ、最も関連する reviewer 1名を起動する。

```text
multi_agent_v1.spawn_agent(
  agent_type: "arch-reviewer",
  message: "計画を YAGNI・過剰分解・依存矛盾・実現可能性・検証可能性でレビューし、approve/needs-revision と CRITICAL/IMPORTANT/MINOR を返す。"
)
```

13. **人間ゲート**: 仕様変更・外部副作用・破壊的操作・広範囲変更はユーザー承認を取る。既にユーザーが実行を明示し、変更がローカル設定/ドキュメントに閉じる場合は、計画をログに残して進めてよい。

### Overlay C: global Phase 3 内 — 実装ループ

1. **割り当て**: 依存のないタスクだけ並列化する。write scope が重なるタスクは並列化しない。
2. **explorer**: local search で不足し、独立した探索文脈に利益がある場合だけ `explorer` / `architecture-explorer` に渡す。
3. **implementer**: 並列利益があり、write scope を分離できる場合だけ `implementer` / `worker` に渡す。ファイル数だけを起動理由にしない。
4. **mini helper**: commit文案、短い要約、定型整形だけは、metadata で利用可能な場合に default/custom + `gpt-5.4-mini` を検討する。利用不可なら role 既定または model 省略へ戻す。実装、設計、最終レビューには使わない。
5. **共有**: 各 sub-agent の結果を Team Journal に要約し、失敗は症状ではなく原因で Attribution に残す。
6. **Budget/Stop**: 差し戻しは最大3回、連続失敗2回で escalate。これを超える場合は `update_goal(status="blocked")` の対象。

### Overlay D: global Phase 4 内 — レビュー

実装完了後、maker の自己申告だけでは完了扱いにしない。fresh な検証を先に行い、Delegation Gate が独立検証を要求する場合だけ checker を起動する。

`context/team-run.md` の Review Heat ladder と `context/workflow-rules.md` のレビューアー選択ガイドに従い、変更リスクに対応する最小の checker を選ぶ。観点が独立し、追加検出の価値がコストを上回る場合だけ reviewer を追加する。

- CRITICAL は必ず修正する。
- IMPORTANT は原則修正する。見送る場合は理由を Team Journal に残す。
- test の緩和、skip、削除、検証コマンドの形骸化は不合格。
- 重要判断やリスクが高い変更では `adversarial-review` / `auditor-reviewer` を追加する。
- Superpowers の `requesting-code-review` が適用できる場合は使う。

### Overlay E: global Phase 4 内 — 検証

2段階で検証する。

1. 各タスクが個別に合格基準を満たすか。
2. 統合後に全体の test / typecheck / lint / build / 実行確認が通るか。

完了を主張する前に `superpowers:verification-before-completion` を使い、fresh な検証コマンドの出力を確認する。

### Overlay F: global Phase 5 内 — 終了

1. `update_goal(status="complete")` または、同じブロッカーが3回続いた場合のみ `blocked`。
2. 完了済み sub-agent を `multi_agent_v1.close_agent` で閉じる。
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
- Live Roadmap: URL or path
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
- `context/team-run.md` — team-run のチーム構成・レビュー熱量・終了判定
- `skills/autonomous-loops/SKILL.md` — Budget/Stop とループ戦略
- `skills/compounding-knowledge/SKILL.md` — 完了後の知見保存
- `context/loop-engineering.md` — 実行モデル
- `commands/pr-watch.md` — PR作成後のCI/レビュー継続監視
