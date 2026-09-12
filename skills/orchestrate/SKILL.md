---
name: orchestrate
description: ユーザーが `/orchestrate` を明示したとき、workflow種別に合う専門agentを依存順に実行し、構造化handoffで次へ渡す。feature、bugfix、refactor、security、customの逐次chainが必要なときに使い、単一文脈の局所作業には使わない。
---

# エージェントオーケストレーション

各agentの成果物を次のagentの入力にする逐次chain。開始前に変更範囲、依存、合格基準、外部writeの承認、コード変更ならComplexity Budgetを確定する。現在のsessionが提供するcollaboration capabilityを使い、固定API名・固定roster・legacy modelを仮定しない。

```text
/orchestrate <workflow-type> "<タスク説明>"
/orchestrate custom "agent1,agent2,agent3" "<タスク説明>"
```

## 標準chain

| type | chain |
| --- | --- |
| `feature` | `requirement-parser` → `prd-reviewer` → Approved PRD gate → `implementation-planner` → Work Packet → implementation → Evidence Bundle → `test-reviewer` + risk-based review |
| `bugfix` | `data-flow-tracer` → fix implementation → `test-reviewer` |
| `refactor` | `architecture-explorer` → `arch-reviewer` → implementation → `code-quality-reviewer` |
| `security` | `security-reviewer` → fix implementation → `security-reviewer` recheck |
| `custom` | ユーザー指定順（依存を満たす場合のみ） |

featureはPRD reviewerの `pass` まで実装へ進めない。Work Packetのmodel/service tierは `rules/model-routing.md` のsix-axis routerで解決し、必要なrouteがなければ `ROUTING_BLOCKED` として停止する。

## 実行と分岐

1. PJの `AGENTS.md`、`context/workflow-rules.md`、`context/agent-team-routing.md`を読み、必要な正本だけを各agentへ渡す。
2. 最初のagentを起動し、入力とowned pathsを限定する。
3. 成果物、findings、変更file、検証、open questions、次のacceptanceをhandoffへ記録する。code変更では担当要素のtarget・actual・varianceも記録する。
4. 次のagentへhandoffを渡し、依存が満たされるまで開始しない。独立したreviewだけは同じ段階で並列化できる。
5. reviewerが不合格にしたら、原因を記録して該当agentへ戻す。外部write、仕様変更、破壊的操作、広範囲変更、commit/pushは承認gateを通す。
6. 全chainの検証とholistic checkが通るまで完了扱いにしない。ブロッカーはchainを止め、残課題と必要な判断を報告する。

## Handoff形式

```markdown
## HANDOFF: <前のagent> → <次のagent>

### Context
<今回確認した範囲>
### Findings
<根拠付きの発見、決定、未確認>
### Files Modified
<絶対またはrepo相対path>
### Verification
<コマンドと結果>
### Open Questions
<次のagentまたはユーザーの判断>
### Recommendations
<次のagentが行うこと>
### Complexity Budget
- Target: <production / test / config・migration>
- Actual: <同じ区分>
- Variance / reason: <within target / justified variance / scope drift>
```

## 機構の使い分け

| 機構 | 用途 |
| --- | --- |
| `multi_tool_use.parallel` / session collaboration | 独立した短命の調査・レビュー・A/B・fan-out |
| `/team-run` | Goal、Team Journal、Review Heatを持つ複数roundの協働 |
| `/orchestrate` | 順序が重要なagent chain |
| `/lfg` | Phase 0〜5.5を一つのタスクとして通す |
| `blueprint` | 多session・多PRの設計図 |

同じ問いをchainとteam-runで二重実行しない。詳細な実行モデルは `context/loop-engineering.md`、routeは `context/agent-team-routing.md`、phaseと承認は `context/workflow-rules.md` を正本とする。

## 最終報告

```markdown
# ORCHESTRATION REPORT
- Workflow: <種別>
- Task: <説明>
- Agents: <chain>
- Summary: <短い要約>
- Files Changed: [...]
- Verification: [...]
- Complexity Budget: <target / actual / variance / reason またはN/A>
- Recommendation: SHIP | NEEDS_WORK | BLOCKED
```

05_log.mdへ各handoffとブロッカーを記録する。chainを完了しただけでSHIPとせず、検証結果と未解決の判断を分けて報告する。
