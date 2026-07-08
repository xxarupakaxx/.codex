---
description: 直近1週間のDaily・digest・trend・payment-trend・新規knowledgeを横断し、今週の学びとメタデータ監査とMOC接続提案を1枚の週次レビューノートに統合する（Routineのエントリポイント）
---

# /weekly-learning-review — 週次の学び統合

毎朝の自動収集（daily-curator、ai-trend-scan、payment-domain-scan）が溜めた情報を、週に一度「学び」として固める上位レビュー。**まず `CLAUDE.md` を読み、絶対ルール（リネーム禁止・削除禁止・既存は追記のみ・新規はInbox配下・wikilinkはファイル名ベース）とセカンドブレイン拡張フィールドの定義を守ること。**

手順の本体は `.codex/skills/weekly-learning-review/SKILL.md` に従う。地の文は `japanese-tech-writing` の規範で書く。

要点:

- 出力先は `Inbox/automation/weekly-review/weekly-review-YYYY-Www.md`（ISO週単位・冪等。週の途中で複数回実行しても同じノートへ追記）。
- 収集は検索ファーストで、`Daily/`、`Inbox/automation/{digest,trends,payment-trends}/`、当週の新規 `Inbox/knowledge/` を横断する。`Claude-note/` は読み取りのみ。
- 本文は「今週の学び」「LayerX入社準備の進捗」「今週の数字」「メタデータ監査」「MOCへの接続」「来週のフォーカス」で構成する。
- メタデータ監査では、当週の新規ノートの `summary` / `related` / `depth` 欠落と、全期間の孤立ノート（リンク0）を数える。
- MOCへの接続は、無人実行なら提案に留め、対話中なら承認のうえ該当ノート末尾へ追記する。
- 保存前に YAML・`[[wikilink]]` の実在・Templater記法の残りを自己検証する（[[04_verifier]] の観点）。

スケジュール設定は [[SCHEDULES]] の「7. /weekly-learning-review」を参照（金曜18:00、Vault内横断のためconnector不要）。
