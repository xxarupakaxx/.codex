---
name: team-run
description: ユーザーが `/team-run` またはTeam Runを明示したとき、goal・合格基準・Team Journalを共有し、独立した専門sub-agentを必要な範囲だけ並列化して検証まで回す。単一ファイル・密結合・低価値の作業には使わない。
---

# /team-run

メインセッションが team-lead となり、session-provided collaboration capability の sub-agent を使って、調査・実装・検証を独立に進める。価値は起動数ではなく、機械判定可能な合格基準、独立レビュー、失敗時の止め方に置く。

## 起動判断

| 状況 | 経路 |
| --- | --- |
| 逐次依存、同一ファイル、密結合、低価値 | leadが単独で実行 |
| 独立した読み取り | `multi_tool_use.parallel` |
| 独立した調査・実装・レビュー | sessionのcollaboration capability |
| 複数ターンで目的・失敗原因・レビューを持ち越す高価値作業 | `/team-run` |

起動前に L0 local（`rg`、既存スクリプト、並列読み取り）で足りるか確認する。専門性が必要ならL2 role、GO/NO-GO・セキュリティ・重要設計・複雑実装ならL3 heavyを使う。定型要約やcommit文案だけは、現在の `rules/model-routing.md` で解決できるFast classをL1として使える。Fast classで不確実性、矛盾、複数ファイル判断、ユーザー影響が出たらそのroundを止め、role既定へ戻す。model、service tier、roleは固定値を書かず、同ファイルの許可集合に従う。

## 5つの共有成果物

- **Goal**: 目的、Done、停止条件。長い作業は `create_goal` で固定し、完了または同じブロッカーが3回続いたときだけ `update_goal(status="complete"|"blocked")` を使う。
- **Sprint Contract**: 機械判定可能な受入条件。`checkpoint.md` に保存する。
- **Outcome Trace**: Goal outcome と acceptance/evidence の対応。未対応項目を残さない。
- **Team Journal**: 現在地、決定、失敗の原因、次の担当をround間で共有する。
- **Review Heat / Complexity Budget**: 変更リスクに応じたchecker/judgeと、コード変更のtarget・actual・varianceを記録する。

Goalは完了証明ではない。成果物と検証結果をOutcome Traceで結び、makerの自己申告だけで完了にしない。

## 開始時の読み込み

global `context/workflow-rules.md` のPhase 0を先に満たし、PJの `AGENTS.md`、`context/agent-team-routing.md`、`context/team-run.md` を現在の順序と境界の正本として読む。PJ側の同名contextは、globalの一般規則を壊さない範囲でroute/team-run固有の上書きとして扱う。

開始時に次をTeam Journalへ記録する。

- draft objective と Goal Quality Gate の状態
- lane、sub-agentを省略した理由、model route、budget route
- 合格基準、owned paths、外部副作用の承認状態
- Complexity Budget（コード変更時）と初期Review Heat

Goal Quality Gateは `skills/goal-setter/SKILL.md`、Phaseの正式な順序・必須ゲート・roadmap表示は `context/workflow-rules.md` に従う。ここで複製した規則より正本を優先する。

## ループ

1. **調査**: local-firstで既存コード・資料・履歴を調べ、必要な外部参照とGO/NO-GO根拠を記録する。必要なら検索専任を委譲する。
2. **計画**: Goal Gateを通過させ、`create_goal`、Sprint Contract、Outcome Trace、roadmap、Team Journalを整える。依存・acceptance・risk・write scopeを確定する。
3. **割り当て**: 依存のない仕事だけを並列化する。write scopeが重なる仕事を同時に渡さない。各sub-agentには目的、scope、acceptance、既知の失敗原因、短い出力形式を渡す。
4. **実行**: makerは明示したdisjoint write scopeだけを変更する。explorerは必要な箇所だけ読む。leadは結果をEvidence BundleとJournalへ要約し、失敗を症状でなく原因としてAttributionに残す。
5. **レビュー**: 変更リスクに応じて最小のchecker/judgeを選ぶ。CRITICALは修正、IMPORTANTを見送る場合は理由をJournalに残す。testのskip・緩和・削除、検証コマンドの形骸化を通さない。重要設計や高リスク変更だけadversarial/auditor reviewを追加する。
6. **検証**: 個別タスク、統合後のtest/typecheck/lint/buildまたは実行確認、holisticなGoal outcomeの順に確認する。失敗時は原因をJournalに記録し、write scopeと受入条件を保った小さい修正へ戻す。
7. **終了**: Outcome Traceに未対応がなく、freshな検証が通り、Exit Gateを満たしてから `update_goal(status="complete")`。同一ブロッカーが3回連続した場合だけ `blocked` とし、残課題を報告する。cleanup capabilityは提供される場合だけ使う。

Phase 0〜5.5の正式な作業、承認、レビュー、material changeの再計画は `context/workflow-rules.md` を優先する。コード変更では `rules/complexity-budget.md` のtarget・根拠・超過時の再計画条件を計画と報告へ含める。外部write、仕様変更、破壊的操作、広範囲変更は承認gateを通す。

## Capability adapter と役割

固定APIや固定rosterを仮定しない。capabilityがあればその現在の起動・待機・メッセージ手段を使い、なければleadが逐次実行する。`multi_agent_v1` は旧表記であり、利用可否を推測しない。全sub-agentをleadが直接管理し、同時数は依存とreview熱量に応じて最小限（目安4）にする。

| label | 担当 |
| --- | --- |
| planner | 分解、依存、合格基準案 |
| plan-reviewer | YAGNI、依存矛盾、実現可能性 |
| explorer | 検索ファーストのコード調査 |
| maker | disjoint scope内の実装 |
| checker | 成果物ベースの独立レビュー |
| final judge | GO/NO-GOと採否 |

必要なSuperpowers skillがある場合は、brainstorming（曖昧な設計）、writing-plans/dispatching-parallel-agents（計画と委譲）、systematic-debugging（診断）、verification-before-completion（完了前）、requesting-code-review/finishing-a-development-branch（merge前）を読み、現在のCodex toolへ対応させる。routeの選択は `context/agent-team-routing.md` に戻す。

## Sub-agentの文脈契約

指示には次を含める。

```text
objective: 今回完了すべき仕事
scope: 読む/書く対象、owned paths、触らない境界
acceptance: 機械検証またはreview観点
prior failure: 直近の失敗原因
output: 変更ファイル、検証、短い所見だけ
```

最終報告は1〜3行のcompact summaryにし、巨大diff・長いログ・base64・不要な全文を返さない。逐語で読むべき計画やfindingsはファイルへ書き、そのpathを返す。他agentやuserの変更をrevertしない。leadはpath付き成果物を自分で読み、必要な原文をユーザーへ引き継ぐ。

## Team Journalの最小形式

```markdown
# Team Journal: <task-name>

## 定位置
- Goal: ...
- Goal Gate: draft | PASS | NEEDS_CLARIFICATION
- Lane / 省略理由: ...
- Outcome Trace: 未対応 _ / holistic pending|PASS|FAIL
- 合格基準: 機械判定 ... / 判断ベース ...
- Complexity Budget: code|non-code / target ... / actual ... / variance ...
- Budget: sub-agent _/4 / 差し戻し _/3 / 連続失敗 _
- 現在のround / 直近の失敗原因: ...

## Decision Log
| 時刻 | agent | 決定 | 理由 |

## Trace
### <agent>
- 成果物 path:line / 検証 / 申し送り / blocker

## Attribution
| agent | task | 失敗内容 | 原因 | round |
```

## Orchestration Report

```markdown
## Orchestration Report
- Status: SHIP | NEEDS_WORK | BLOCKED
- Goal: ...
- Outcome Trace: unmatched _ / holistic PASS|FAIL
- Task Status: done / in_progress / blocked / pending
- Changed Files: [...]
- Verification: [...]
- Review Findings: [...]
- Complexity Budget: target / actual / variance / reason（コード変更なしはN/A）
- Blockers: [...]
- Live Roadmap: URL or path
```

関連正本: `context/team-run.md`（Heat、構成、Exit Gate）、`skills/goal-setter/SKILL.md`（Goal readiness）、`skills/autonomous-loops/SKILL.md`（loopのbudget/stop）、`skills/compounding-knowledge/SKILL.md`（知見保存）、`context/loop-engineering.md`（実行モデル）。
