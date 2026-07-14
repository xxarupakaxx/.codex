# Team Run Policy

`/team-run` のチーム構成・レビュー熱量・終了判定を定義する。

このファイルは `context/workflow-rules.md` の Phase 0-5.5 を置き換えない。Phase 順序、05_log.md、Sprint Contract、Outcome Trace、レビュー戦略の詳細は `context/workflow-rules.md` が SSoT。Goal readiness の詳細は `skills/goal-setter/SKILL.md` が SSoT。ここでは team-run 固有の「誰をいつ呼ぶか」「何を疑うか」「どこで止めるか」だけを扱う。

## Harmony Contract

`goal` と `goal-setter` は目的と Done を固定する背骨だが、それだけでは team-run は閉じない。team-run では次の6要素を区別し、先頭5要素を必ず揃える。Live Roadmapは任意の補助表示である。

| 要素 | 役割 | 主な保存先 |
|------|------|------------|
| Goal | Goal Quality Gate を通った目的と Done を固定する | `create_goal` / active goal |
| Sprint Contract / 代替検証 | 機械判定できる合格基準を定義する。自明なタスクで正式なContractを省略する場合は代替検証を明示する | `checkpoint.md` / Team Journal |
| Outcome Trace | Goal outcome から acceptance と evidence までの未対応をなくす | `checkpoint.md` / Team Journal |
| Team Journal | 周回をまたぐ状態、決定、失敗原因を共有する | `${MEMORY_DIR}/memory/YYMMDD_<task_name>/team-journal.md` |
| Review Heat | 変更のリスクに応じて checker / judge を選ぶ | このファイル + `workflow-rules.md` |
| Live Roadmap（任意） | 現在地を横で見るための補助ビュー | `${MEMORY_DIR}/memory/YYMMDD_<task_name>/roadmap.html` |

Goal は「価値と完了の定義」であり、Sprint Contractまたは明示した代替検証は「成果物の合格基準」である。Outcome Trace は両者の対応であり、どちらの代替でもない。Team Journal は「現在地」であり、合格証明ではない。Review Heat は「疑い方」であり、実装計画ではない。Live Roadmap は見える化であり、正本ログではない。この分離を崩さない。

Team Journal には Goal Gate の状態、選択した lane と省略理由、未対応 Goal outcome 数、holistic check の状態を置く。判定項目と trace schema はここへ複製せず、各 SSoT を参照する。

## Team Roles

| 役割 | 推奨 agent_type | 責務 |
|------|-----------------|------|
| lead | メインセッション | goal、計画、統合判断、最終責任 |
| planner | `implementation-planner` / `technical-evaluator` | 分解、依存、合格基準、リスク |
| explorer | `explorer` / `architecture-explorer` / `dependency-mapper` | 必要箇所の調査、既存パターン確認 |
| maker | `implementer` / `worker` | disjoint write scope 内の実装 |
| checker | `arch-reviewer` / `security-reviewer` / `code-quality-reviewer` / `test-reviewer` など | 成果物ベースの独立レビュー |
| judge | `go-nogo-advisor` / `auditor-reviewer` | GO/NO-GO、残存リスク、出荷判定 |
| recorder | lead | Team Journal、05_log.md、issues/ への記録 |

maker と checker を同一 agent にしない。maker の自己申告は完了条件ではなく、checker が成果物と検証結果を見て通す。

Role 表は固定 roster ではない。
lead は local-first の後、`context/agent-team-routing.md` の Delegation Gate を通る役割だけを追加する。
Goal、Team Journal、Review Heat が有用でも、同一文脈を無理に分割しない。
高リスク変更では、最小の独立 checker または人間 gate を残す。

lead だけが役割の作成、task の割当、write scope の変更を決める。worker は役割の追加、再割当、外部書き込みを自分で始めず、必要性と対象を lead へ返す。

外部 artifact を create / update する前に、lead は既存 artifact を検索して対象を確定する。Team Journal には target、operation、結果 URL（または「既存を更新」）を記録し、同じ issue、comment、PR、tracker item を重複作成しない。

## Review Heat Ladder

| Heat | 使う場面 | 最低限 |
|------|----------|----------|
| 0 Self | typo、単一文書、外部影響なし | fresh な lead self-check |
| 1 Focused | 設定、文書、workflow policy | 必要な `docs-reviewer`、`rule-validator`、または human gate |
| 2 Standard | 複数責務の実装 | 変更に対応する最小の independent checker |
| 3 Hot | 権限、外部書き込み、不可逆操作、重要設計 | independent review と必要な human gate |
| 4 Adversarial | security、契約、ESCALATE | `adversarial-review` または auditor を含む判断 |

Heat は変更規模やファイル数だけで決めない。設定ファイルのみでも、model routing、権限、外部書き込み、レビューゲートを変える場合は Heat 1 以上にする。

## Reviewer Pack Selection

`workflow-rules.md` のレビューアー選択ガイドを一般規則の正とし、team-run では次の候補から必要な観点だけを選ぶ。Heat は固定人数や固定 pack を要求しない。lead はまず direct validation を行い、その結果だけでは不足し、Delegation Gate を通る独立検証に価値がある場合だけ checker を追加する。

| 変更領域 | 最初に選ぶ reviewer |
|----------|---------------------|
| AGENTS.md / context / skills / commands | `rule-validator`、`docs-reviewer`、`arch-reviewer` |
| model / service_tier / agent routing | `cost-aware-llm`、`technical-evaluator`、`rule-validator`、`cost-monitor` |
| security / auth / data access | `security-reviewer`、`api-contract-reviewer`、`data-flow-tracer` |
| tests / validation harness | `test-reviewer`、`code-quality-reviewer` |
| UI / browser behavior | `ui-ux-reviewer`、`a11y-reviewer`、Playwright smoke |
| CI / deploy / env vars | `devops-reviewer`、`security-reviewer` |

PRD や受入条件がある場合は `prd-reviewer` を足す。性能が主目的または性能劣化リスクがある場合は `perf-reviewer` を足す。

`gpt-5.4-mini` は reviewer の代替ではなく、commit文案、短い要約、定型整形、重複検出などの前段補助に限る。Review Heat を下げる理由として mini を使わない。

## Stop And Escalate

次のいずれかに該当したら、lead は続行ではなく停止・相談・blocked 判定を検討する。

- 同一 CRITICAL が3ラウンド残る。
- validation が同じ理由で3回失敗する。
- reviewer 間で出荷可否が割れ、lead が根拠を持って裁けない。
- 外部書き込み、破壊的操作、認証/課金/個人情報、production 影響に踏み込む。
- Goal、承認済み Phase 2 artifact、Sprint Contract、Review Heat のどれかを material に変更しないと Done に届かない。

## Exit Gate

team-run を完了扱いにするには、少なくとも次を満たす。

- Goal の Done が現在の成果物で満たされている。
- 最新のGoalがGoal Quality GateをPASSしている。
- Sprint Contract または代替の検証結果が fresh に確認されている。
- 未対応 Goal outcome が0で、統合成果物の holistic check がPASSしている。
- CRITICAL が0件。
- IMPORTANT は修正済み、または残す理由とリスクを Team Journal に記録済み。
- Team Journal に最終状態、検証、レビュー結果、残存リスクが記録されている。
- Live Roadmap を使っていた場合、最終 `roadmap.html` / `roadmap-snapshot.json` が同じメモリディレクトリ内に残っている。
- session が cleanup API を提供する場合は、完了済み sub-agent を整理している。提供しない場合は Team Journal に終了状態を残してよい。
