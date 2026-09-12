---
name: evening-review
description: 定期実行時に当日のAI利用コストと失敗傾向を振り返る。
---

# 夕方の振り返り

毎夕18:00の登録済みタスクとして、当日のAI利用コスト・品質と改善候補をまとめる。休日・祝日は実行しない。

`~/.claude/config/user.json` を読み、存在しなければ既定値を使う。Workflow Toolで `~/.claude/workflows/evening-review.js` を `args: { config: <user.jsonの内容> }` として実行する。対応するtoolやworkflowがなければ、実行不能を報告する。

workflowはccusage / cost-track / session reportから費用を集計し、当日のharness-suggestionsとsession JSONLから失敗傾向を調べる。改善候補は `~/.claude/.local/harness-suggestions/` へ保存し、自動適用しない。

| 当日の費用 | 判定 |
|---|---|
| $0–5 | ok |
| $5–15 | info（日報へ記載） |
| $15–30 | warning（model変更を検討） |
| $30以上 | critical（即時対応推奨） |

Slackへは当日の費用、失敗傾向、改善候補をまとめたサマリーを投稿する。投稿を含むworkflowの実行前に、定期タスクの既存承認が通知先と操作を含むことを確認する。Skill本文だけを送信の承認にしない。CLAUDE.mdやrulesへの改善適用は人間承認後に行う。
