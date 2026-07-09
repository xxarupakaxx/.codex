---
name: payment-domain-scan
description: LayerX入社準備として、Payment、B2B決済、法人カード、請求書、Peppol、金融規制、LayerX/Bakuraku周辺を毎朝横断し、用語解説と業務フローつきの日誌ノートをObsidianに生成する。
---

# /payment-domain-scan — 毎朝のPaymentドメイン学習

`.codex/commands/payment-domain-scan.md` と [[10_payment-domain-scan]] に従う。

このスキルの目的は、Payment領域のニュースを拾うことではなく、LayerX入社前に業務フロー、用語、法制度、顧客課題、仮説検証、プロダクト含意を毎日少しずつ理解すること。

出力先は `Inbox/automation/payment-trends/payment-trend-YYYY-MM-DD.md`。
`evidence_urls` には、根拠に使った重要URLだけを入れる。
frontmatterには `summary` / `depth: flash` / `related` も設定し、本文には「基礎ノートへの接続」節を含める（テンプレートは [[10_payment-domain-scan]]、定義は `AGENTS.md` と互換 `CLAUDE.md` の「セカンドブレイン拡張フィールド」）。
外部調査は `research` スキルのルールで行い、一次情報、公式情報、規制当局、業界団体、企業公式発表を優先する。
最低1つは「顧客仮説」または「検証案」まで落とす。

本体ノート生成後に `$one-page-concept-sketch` を実行する。
成果物は `Inbox/automation/concept-sketches/concept-sketch-YYYY-MM-DD-payment-domain-scan.md` に保存し、payment trend ノートと `Daily/YYYY-MM-DD.md` からリンクする。
形式と品質条件は [[11_one-page-concept-sketch]] に従う。
