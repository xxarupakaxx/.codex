# 改善記録

常駐contextへ反省文を積み重ねず、再現できる失敗と検査を残す。採用済みの現在仕様はコード・テスト・運用文書に置く。この記録は判断の根拠と、次に測ることを保持する。

## L001: 未検証の計画を完了表示へ進めない

- 状態: ローカル採用。固定した正常例・負例とClaude実taskで検証済み。実運用の効果を確認したadopted段階を意味しない。
- 観測: 2026-08-31、未完了Taskしかなく証拠束もないfixtureが、Phase 5 dry-runでcompleted生成コマンドを返した。
- 原因仮説: 生成物と計画の整合検査はあるが、完了の前提を検査していない。
- 最小変更: 既存syncのPhase 5直前に、既存Evidence Bundleを使うvalidatorを接続する。
- 対象: roadmap / explicit-roadmap。log-only、旧計画の閲覧、Phase 2–4は対象外。
- 正常例: 全項目、acceptance、実ファイルと証跡hashが一致する計画。
- 負例: 未完了を100%進捗で隠す、証跡欠落、ID不一致、古いcode、危険なpath、到達段階不足。
- 採用条件: 負例を拒否、正常例と既存Phase 2–4を維持、独立reviewで重大な未修正指摘なし。
- 検証結果: 完了validator23件、同期40件、context helper12件がPASS。Claude実taskで未完了Phase 5を拒否し、証跡照合後の更新を確認。独立再レビューで未修正の重大指摘なし。
- 回帰検査: `python3 -m unittest tests.test_task_completion tests.test_sync_roadmap tests.test_task_context`。source/evidence改変と、生成失敗・非UTF-8出力時の旧成果物保持を含む。
- 戻す条件: 正当なtaskを再現可能に誤拒否し、その原因を契約の修正で解消できない場合。無検証のcompletedへ戻す代わりにPhase 5の表示更新を停止する。
- 未測定: 実運用での見逃し率、誤拒否率、tokenと費用、復元成功率。
- 次回確認: モデル更新時、または実taskでの失敗・誤拒否が報告されたとき。同じfixtureを実行し、追加検査の必要性を再判断する。

## 次の候補を残す形式

識別子、観測した失敗、実在する証跡、原因仮説、最小変更、対象外、正常例、負例、比較結果、採否と理由、戻す条件、次回確認条件を短く記録する。根拠のない改善率や、自動的な権限拡張を含めない。
