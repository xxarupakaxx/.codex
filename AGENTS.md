# 共通ルール

このファイルは user-scope Codex の短い入口である。全 Agent が毎回守る不変条件と正本への導線だけを置き、手順、履歴、例外、形式の詳細はリンク先へ置く。

## 基本方針

- 日本語で応答する。
- 同等の観測性と安全性がある場合は、MCP サーバーより CLI ツールを先に検討する。
- Project `AGENTS.md` と、対象ファイルに最も近い `AGENTS.md` の追加制約を適用する。
- ユーザーの実行依頼は、調査や計画だけを求められた場合を除き、依頼範囲の完了条件まで進める。途中報告だけで終了しない。
- 軽微で低リスクな曖昧さは合理的な仮定で進める。結果を大きく変える選択、外部公開、不可逆操作、権限・課金・認証変更だけ確認する。
- 新しく生成する図はSVGを正本とし、Mermaidを生成しない。MarkdownはSVGファイルを参照し、HTML内の図は自己完結したinline SVGで描画する。既存のMermaid成果物は、明示的な移行依頼がない限り一括変換しない。

## 実装と検証

- 実装前に仮定、不明点、複数解釈、重要な trade-off を明示する。永続的な仕様判断は既存実装、test、文書、またはユーザー確認を根拠にする。
- 要求を満たす最小の実装を選び、依頼外の機能、抽象化、設定、将来対応を足さない。
- 対象に必要な行だけを変更し、無関係な整形、refactor、削除を行わない。
- 成功条件を検証可能にし、再現、test、差分確認、task-level workflow check を含めて完了を判定する。
- 再現 test は観測済みの失敗と既存契約だけを固定し、未確認の出力形式やerror型を新しい期待値にしない。
- Markdown を変更したら全文を再読し、矛盾、重複、rule漏れを同じturnで解消する。

## 指示と知識の配置

- sessionをまたぐ情報はMemoryだけに置かず、git管理された正本へ反映する。
- 現在の仕様はdocs、検証可能な期待はtest、局所例外は隣接comment、判断理由はADR、反復手順はSkill、未完了作業はissue、履歴はGit logに置く。
- `AGENTS.md`には全Agentが毎回守る不変条件と正本への入口だけを置く。完了済みTODOや手順の複製を残さない。
- 例外には理由、適用範囲、解除条件を付け、条件が満たされたら削除する。
- 一過性の下書きや受け渡しはworktreeの`.local/context/`に置き、`.context/`、`/tmp`、`/private`を標準置き場にしない。task workflowの記録は`${MEMORY_DIR:-.local}/memory/`に置く。複数行や構造化内容は実ファイルで渡し、inline展開とhere-docを避け、pipeは単一commandがstdinを即時に一度だけ読む処理に限る。

## Script とerror

- 長時間実行や外部通信を伴うscriptは、開始、反復、retry、完了、失敗をsecretなしで記録する。
- 主経路の失敗を暗黙fallbackで隠さない。代替経路は目的、発動条件、観測log、再実行時の挙動を明示する。
- errorを一致なし、context不一致、path不存在、conflict、dirty state、検証failureなど意味で分類し、原因を確認してから続行する。

## 委譲とSkill

- 独立した作業幅、隔離された専門知識、独立検証に価値がある場合だけrole-appropriateなsub-agent / runnerへ委譲する。
- 委譲時はobjective、背景、scope、制約、許可する副作用、成果物、検証方法を明示し、親が既存実装、設定、文書、testへ戻って検証する。
- 委譲先へsecret、secret reference、認証済みsession情報を渡さない。
- 詳細手順はrepoの正規docs / Skillを優先し、新しいSkill、runner、wrapperを作る前に既存部品を確認する。
- 現在の作業で生成した成果物の整形、校正、品質確認では `skills/sanitizing-artifacts/SKILL.md` を読む。
- 日本語のドキュメントをまとめる、書き出す、または推敲するときは `skills/natural-japanese/SKILL.md` を読み、その設計、執筆、検査の規則に従う。

## Workflow gate

- すべてのtaskを`context/workflow-rules.md`のPhase 0から順に実行し、各Phaseの内容を`05_log.md`へ作業中に記録する。Fast Trackも同正本の条件に従う。
- Phase / Stepを持つ作業は、遷移前に所定artifactを保存する。配置とfrontmatterは`context/memory-file-formats.md`に従う。
- code変更はTask WorkspaceのCodemap gateを編集前後に通す。複数Phaseでは同Workspaceをlive表示し、案内前に実際に開く。詳細は`context/codemap.md`と`skills/viewing-plans/SKILL.md`に従う。
- `/clear`後やcontextが空の場合は`${MEMORY_DIR:-.local}/handovers/`のsession一致handoverを優先し、互換の`HANDOVER.md`と対応taskの`05_log.md`から状態を復元する。
- freshな直接検証を先に行い、変更リスクに合う最小の独立checkerを選ぶ。CRITICALは必ず、正しさに関わるIMPORTANT / MINORは原則修正する。
- code変更では計画時target、実装時actual、レビュー時varianceを記録する。必要な安全性、可読性、testを行数合わせで削らない。

## 正本map

| 関心 | 正本 |
|---|---|
| Phase 0-5.5、Fast Track、review、Goal / acceptance、Roadmap | `context/workflow-rules.md` |
| plugin / Skill / agent routing、委譲、外部write | `context/agent-team-routing.md` |
| artifact / memory形式、session復元 | `context/memory-file-formats.md` |
| Task Workspace、Codemap preflight、live Roadmap | `context/codemap.md` と `skills/viewing-plans/SKILL.md` |
| team-run composition / exit gate | `context/team-run.md` と `skills/team-run/SKILL.md` |
| model / service tier | `rules/model-routing.md` |
| code complexity budget | `rules/complexity-budget.md` |
| ADR判定 | `rules/adr-criteria.md` |
| secret管理の詳細（対象path） | `rules/security.md` |
| Git / PR | `rules/common-git-workflow.md` と `rules/code-review-philosophy.md` |

## 完了境界

- project固有の品質check、必須review、commit / push policyを満たす。
- 完了報告には変更、検証、review、残課題を含め、設定済みと実行済み、構文成功とuser outcome達成を区別する。
- code変更の完了報告では、Complexity Budgetを「変更量」として日本語で示す。計画内なら「変更量：想定内」と簡潔に書き、計画超過時だけ計画値、実績、差分、理由を説明する。code変更がないtaskでは記載しない。
- GitHub CLIを使う場合は`gh auth status`でprincipalを確認する。既定accountは`xxarupakaxx`とし、切替が必要なら自動で行わない。
