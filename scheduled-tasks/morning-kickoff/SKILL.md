---
name: morning-kickoff
description: 登録済みの朝タスクでJira・予定・未完了事項・PRから日次計画を作る。
---

# 朝の日次計画

毎朝9:00の登録済みタスクで使う。休日・祝日や、カレンダーに終日「休み」等がある日は実行しない。

`~/.claude/config/user.json` を読み、不在なら既定値を使う。Workflow Toolで `~/.claude/workflows/morning-kickoff.js` を `args: { config: <user.jsonの内容> }` として実行する。toolやworkflowが利用できなければ、その失敗を報告する。

計画の材料は、自分の未完了Jira（`assignee = currentUser() AND statusCategory != Done`）、当日の予定、`~/.claude/.local/daily/` の前日の未完了事項、PRレビュー待ち。P0〜P2に整理し、作業時間は8時間から会議時間を引いた範囲に収める。P0が3件以上なら優先順位の確認を求める。

Slack投稿を含む実行前に、定期タスクの既存承認と通知先を照合する。承認範囲内で計画またはデータ取得失敗を通知し、送信不能を成功として扱わない。
