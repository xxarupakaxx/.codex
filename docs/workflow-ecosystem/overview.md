# 計画を残し、検証して完了する

2026-08-31時点のローカル実装。Codex/Claudeの共通CLI、HTML表示、指定taskのbrief、未完了拒否、証跡照合後の完了更新を検証した。実運用での成功率やtoken・費用改善は未測定である。

この運用は、CodexとClaudeのユーザースコープで使う。利用者はHTMLで計画と進捗を見て、実装者は短い計画と必要な資料だけを読む。正本は既存の`30_plan.md`、表示は既存のRoadmap生成器に統一する。HTMLを会話のたびに全文生成したり、表示だけを手で完了へ書き換えたりしない。

これは無欠陥や数学的な最適性を保証する仕組みではない。検出できる漏れを完了前に止め、見逃した失敗を次の検査へ戻せる構成である。

## 通常の進め方

| まとまり | 残すもの | 次へ進む条件 |
| --- | --- | --- |
| 把握（Phase 0–1） | 目的、範囲、完了条件、仮定、調査の根拠 | 要求と現状の差を説明できる |
| 計画（Phase 2–2.5） | Taskごとの対象、依存、手順、成果物、検証方法 | 独立した要件がTaskと検証へ対応し、HTMLを同期できる |
| 実装・検証（Phase 3–4） | 実際の変更、実行結果、修正した指摘 | 必須条件を直接検証し、必要な独立レビューを通る |
| 完了・学習（Phase 5–5.5） | 証跡、残るリスク、次回に使う訂正 | 完了検査を通り、実装済みと効果確認済みを区別できる |

小さな低リスク作業は`log-only`を使い、計画HTMLや証拠束を無理に作らない。複数工程、継続作業、計画閲覧の明示依頼は`roadmap`または`explicit-roadmap`へ進む。routeと省略条件の正本は[workflow-rules](../../context/workflow-rules.md)である。

## 薄い計画にしないための条件

Taskには、何を変えるかだけでなく「何を観測すれば終わりか」を書く。次を満たさないTaskは実装前に補う。

- 目的とacceptance IDを結び、対象外も明示する。
- 変更対象を具体的なファイルまたは成果物へ絞る。
- 依存するTaskと、先に確認する外部条件を書く。
- 実装のチェック項目と、正常・異常時の検証を書く。
- 成果物、実行証跡、完了に必要な段階を区別する。

「認証を改善する」だけでは不十分である。「期限切れsessionで再認証へ移る。成功後は元の画面へ戻る。cancel時は保存しない」のように、利用者が通る状態と確認方法を書く。計画の長さを増やすための説明や、既知のコード全文は入れない。

形式の正本は[memory-file-formats](../../context/memory-file-formats.md)、表示の正本は[viewing-plans](../../skills/viewing-plans/SKILL.md)。要件、計画、証拠束に同じ説明を複製せず、IDと参照で結ぶ。

## 文脈の持ち方

常時読むのは入口、今回の目的・制約・完了条件、現在の一単位と参照先に絞る。詳細なschemaはartifactを作るとき、専門Skillは該当する作業、過去の証跡は同じ失敗を調べるときだけ開く。

保存済み計画の発見と再開には`scripts/task-context.py`を使う。memory rootとtaskを明示して選び、最も新しいtaskへ自動接続しない。briefは入口であり、省略された安全条件や変更対象は参照先で確認する。要約を正本や検証証跡の代わりにしない。

再開時はsessionが一致するhandoverを優先し、taskの目的、未完了項目、現在のファイル状態を確認する。古いHTMLや進捗率だけでは完了を判断しない。人が追記した内容と最新の指示が優先される。

## 両環境を一つの検査へつなぐ

Codexの`sync-roadmap.py`を共通の入口にする。Claude側の旧script、既存設定、hookは削除・置換しない。既存の利用経路がすべて強制的に切り替わったという意味ではなく、新しい既定手順から共通入口へ到達する。

```bash
python3 ~/.codex/scripts/sync-roadmap.py ~/.claude/.local/memory/TASK \
  --workspace-root ~/.claude --memory-root ~/.claude/.local/memory \
  --run-id RUN --phase 2
```

`TASK`と`RUN`は対象taskと実際のrun IDに置き換える。Phase 3/4/5も同じ入口を使う。通常実行は指定taskのHTML・snapshot・metadataを更新し、`--dry-run`は書き込まない。共有CLIが存在しない環境では停止して依存関係を案内し、旧生成器へ黙って切り替えない。

これは両homeを持つこのPC向けの運用である。別PC、cloud、Codex homeを移動した環境では依存を確認する。既に読込済みのtaskには文書の再読が必要であり、hookによる全経路の強制ではない。

## 完了検査と限界

roadmap系のPhase 5は表示の更新前に、元のチェック項目、acceptanceの対応、必須ファイルと検証結果のhash、未解決指摘、到達段階を検査する。進捗ファイルに100%と書いても、未完了のチェック項目を覆い隠せない。

`task_completion.py`は既存Evidence Bundle契約を利用する検査libraryで、別の状態機械や実行権限を持たない。検証文字列を実行する仕組みも追加しない。planで宣言した対象と証跡の対応は検査できるが、意図的な虚偽、要件自体の欠落、宣言されていない変更の意味は自動証明できない。Git差分の照合、直接実行、リスクに応じた独立レビューが必要である。

完了表示と成果の到達段階は別である。`implemented`は実装と直接検証、`wired`は入口への接続、`piloted`は実sampleの処理、`effective`は比較による効果確認、`adopted`は運用責任・承認・戻し方まで含む。Work Packetのない作業から効果を推測しない。

## 育て方

失敗やユーザーの訂正を受けたら、[改善記録](learning-record.md)へ根拠、適用範囲、再現手順を残す。自己反省だけではルールを増やさない。

1. `candidate`: 検出できなかった失敗と、検査を追加する仮説を残す。
2. `trial`: 固定した正常例と負例、別の実taskで試す。成功、漏れ、誤拒否、出力量、所要時間を比べる。
3. 採否: 効果と負担を見て採用・保留・却下を記録する。権限やruntime policyの昇格は既存の承認境界を通す。

導入した構造も見直す。モデル更新後に効果がなくなった追加review、reset、複数agentを慣習で残さない。常に同じ条件で一要素ずつ比較する。今回の実装にも、代表taskを継続運用した成功率・実token・費用の改善はまだ実測されていない。

## 調査の根拠

[一次資料台帳](primary-sources.md)は31件（原論文20件、公式文書・記事・仕様11件）。原論文は概要・metadata中心で、全論文の全文読了とは区別する。[JSON台帳](primary-sources.json)にも読了範囲と限界を保存した。

必要時のcontext取得は[Anthropicの解説](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、成果物による引継ぎは[long-running harnessの実験](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)、検証の独立性は[agent評価の解説](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)を参考にした。単純な構成を優先する判断には[Agentless](https://arxiv.org/abs/2407.01489)も用いた。これらは設計判断の根拠であり、この環境での改善率を示す証拠ではない。

## 導入時の測定

既定workflow文書はCodexで784→104行、Claudeで709→102行に整理した。省いた通常手順の重複と、条件付き詳細への移動による差である。これは文書量の測定であり、料金やモデル入力tokenの削減率ではない。導入時に発見した失敗は[改善記録](learning-record.md)の固定検査へ戻す。
