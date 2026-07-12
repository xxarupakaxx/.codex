# Team Run Policy

`/team-run` のチーム構成・レビュー熱量・終了判定を定義する。

このファイルは `context/workflow-rules.md` の Phase 0-5.5 を置き換えない。Phase 順序、05_log.md、Sprint Contract、レビュー戦略の詳細は `context/workflow-rules.md` が SSoT。ここでは team-run 固有の「誰をいつ呼ぶか」「何を疑うか」「どこで止めるか」だけを扱う。

## Harmony Contract

`goal` と `goal-setter` は目的と Done を固定する背骨だが、それだけでは team-run は閉じない。team-run では次の4点を必ず揃える。

| 要素 | 役割 | 主な保存先 |
|------|------|------------|
| Goal | 目的、Done、停止条件を固定する | `create_goal` / active goal |
| Sprint Contract | 機械判定できる合格基準を定義する | `checkpoint.md` |
| Team Journal | 周回をまたぐ状態、決定、失敗原因を共有する | `${MEMORY_DIR}/memory/YYMMDD_<task_name>/team-journal.md` |
| Review Heat | 変更のリスクに応じて checker / judge を選ぶ | このファイル + `workflow-rules.md` |
| Live Roadmap | 現在地を横で見るための補助ビュー | `${MEMORY_DIR}/memory/YYMMDD_<task_name>/roadmap.html` |

Goal は「完了の定義」であり、レビュー体制ではない。Team Journal は「現在地」であり、合格証明ではない。Review Heat は「疑い方」であり、実装計画ではない。Live Roadmap は見える化であり、正本ログではない。この分離を崩さない。

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

## Review Heat Ladder

| Heat | 使う場面 | 必須 checker | 追加条件 |
|------|----------|--------------|----------|
| 0 Self | typo、単一ドキュメント、外部影響なし | lead self-check | fresh な validation だけで足りる場合 |
| 1 Focused | 1-3ファイル、設定/ドキュメント中心、低リスク | `docs-reviewer` または `rule-validator` の該当1名 + 関連1名 | `CRITICAL=0`、IMPORTANT は理由付き処理。AGENTS/context/skills/commands 変更は下の Reviewer Pack を優先 |
| 2 Standard | 4-9ファイル、複数責務、通常の実装 | `arch-reviewer`, `security-reviewer`, `code-quality-reviewer`, 関連 reviewer | `workflow-rules.md` の規模別ラウンドを適用 |
| 3 Hot | 10+ファイル、認証/課金/DB/外部API/データ損失リスク | Heat 2 + `test-reviewer` + `go-nogo-advisor` | unresolved IMPORTANT があれば出荷不可または明示承認 |
| 4 Adversarial | 重要判断、セキュリティ、契約変更、ESCALATE | `adversarial-review` 経由の `red-reviewer` / `blue-reviewer` / `auditor-reviewer` | Auditor 判定を最終判断に使う |

Heat は変更規模だけでなくリスクで上げる。設定ファイルのみでも、model routing、権限、外部書き込み、レビューゲートを変える場合は Heat 1 以上にする。

## Reviewer Pack Selection

`workflow-rules.md` のレビューアー選択ガイドを一般規則の正とし、team-run では次の pack を最初の候補にする。Heat ladder の checker は最低ラインであり、この表がより具体的な場合は表を優先する。

| 変更領域 | 最初に選ぶ reviewer |
|----------|---------------------|
| AGENTS.md / context / skills / commands | `rule-validator`, `docs-reviewer`, `arch-reviewer` |
| model / service_tier / agent routing | `cost-aware-llm` で方針確認後、`technical-evaluator`, `rule-validator`, `cost-monitor` |
| security / auth / data access | `security-reviewer`, `api-contract-reviewer`, `data-flow-tracer` |
| tests / validation harness | `test-reviewer`, `code-quality-reviewer` |
| UI / browser behavior | `ui-ux-reviewer`, `a11y-reviewer`, Playwright smoke |
| CI / deploy / env vars | `devops-reviewer`, `security-reviewer` |

PRD や受入条件がある場合は `prd-reviewer` を足す。性能が主目的または性能劣化リスクがある場合は `perf-reviewer` を足す。

`gpt-5.4-mini` は reviewer の代替ではなく、commit文案、短い要約、定型整形、重複検出などの前段補助に限る。Review Heat を下げる理由として mini を使わない。

## Stop And Escalate

次のいずれかに該当したら、lead は続行ではなく停止・相談・blocked 判定を検討する。

- 同一 CRITICAL が3ラウンド残る。
- validation が同じ理由で3回失敗する。
- reviewer 間で出荷可否が割れ、lead が根拠を持って裁けない。
- 外部書き込み、破壊的操作、認証/課金/個人情報、production 影響に踏み込む。
- Goal、Sprint Contract、Review Heat のどれかを変更しないと Done に届かない。

## Exit Gate

team-run を完了扱いにするには、少なくとも次を満たす。

- Goal の Done が現在の成果物で満たされている。
- Sprint Contract または代替の検証結果が fresh に確認されている。
- CRITICAL が0件。
- IMPORTANT は修正済み、または残す理由とリスクを Team Journal に記録済み。
- Team Journal に最終状態、検証、レビュー結果、残存リスクが記録されている。
- Live Roadmap を使っていた場合、最終 `roadmap.html` / `roadmap-snapshot.json` が同じメモリディレクトリ内に残っている。
- 完了済み sub-agent を `multi_agent_v1.close_agent` している。
