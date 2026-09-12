# 実装前に目的と根拠を確かめる

要件ごとに「なぜ必要か」「何を根拠にしたか」「何が分かれば見直すか」を記録する。重要な前提が未確認のまま、計画の体裁だけで実装へ進むことを防ぐための補助検査である。根拠の内容や市場需要の真偽は独立reviewで判断する。

## 使う場面

新しい製品、利用者の行動に関する仮説、外部調査を根拠にした方針など、前提が外れると実装をやり直す作業に使う。既存の実行契約version 1は維持する。version 2を選んだ計画では、この検査と審査済みの根拠への紐付けが実装開始条件になる。通常の局所修正に記録一式を強制しない。

## 記録から実装まで

以下の`TASK`は対象taskのdirectoryへ、`ID`は実行するTaskのIDへ置き換える。空白を含むpathはquoteする。

1. taskの`00_request.md`に元の依頼を保存する。`30_plan.html`の受入条件へIDを付け、`execution-contract-version`を`2`にする。
2. `python3 ~/.codex/scripts/decision-preflight.py TASK --template`で未記入の雛形を表示する。この操作ではファイルを作らない。対象taskに新しく`decision-evidence.json`を開き、表示されたJSONを貼り付けて保存する。既存の記録があれば上書きせず読み直す。内容を実際の観測結果で埋める。雛形は合格例ではない。
3. 根拠の抜粋と観測方法を`decision-sources/observation.md`へ保存する。個人情報・secret・認証sessionを入れない。URLは出典の記録であり、検査中に取得しない。`shasum -a 256 "TASK/decision-sources/observation.md"`で表示される先頭の64桁を、その資料の`sha256`へ記録する。
4. `python3 ~/.codex/scripts/decision-preflight.py TASK`で対応漏れや期限切れを確認する。不足があれば資料や要件へ戻る。
5. makerから独立したcheckerが元依頼、前提、資料の内容を審査し、その後に計画を審査する。leadは実際の出力を照合し、`plan-review.json`の`decisionEvidenceSha256`へ審査したJSONのSHA-256を記録する。
6. `python3 ~/.codex/scripts/task-context.py brief TASK --task-id ID --execution`で開始可否を確認する。`readyForReview`だけで実装を開始しない。

## 記録の形式

JSONの最上位は`schemaVersion: 1`、元依頼の`requestSha256`、`claims`、`evidence`、`market`。未知のfield、重複key、不正な型は拒否する。`--template`は元依頼hashと受入条件IDを取り込むが、判断や根拠は未記入のまま返す。

各claimには次を記録する。

| field | 内容 |
|---|---|
| `id` | 他と重複しないclaim ID |
| `statement` / `why` | 検証する前提と、元の困り事に必要な理由 |
| `acceptanceIds` | 計画の受入条件IDの配列 |
| `critical` | 外れたときに方針を見直す重要な前提なら`true` |
| `status` | `supported`、`unknown`、`refuted` |
| `evidenceIds` | 支持根拠のIDの配列。未確認なら空配列を残す |
| `falsification` | 何を観測したら、この前提を見直すか |
| `counterevidence` | `status`、`evidenceIds`、`rationale`を持つobject。statusは`not-checked`、`none-found`、`addressed`、`unresolved`。探索範囲と残る限界をrationaleへ記録する |

`evidence`の各項目には、`id`、`kind`、`path`、`sha256`、`observedAt`、`validUntil`、`source`を入れる。kindは`repository`、`primary-source`、`customer-observation`、`experiment`、`synthetic`のいずれか。pathはtaskからの相対path、sourceは確認したURLやrepositoryの参照で、両者を区別する。sha256は保存したMarkdownの実際のbytesから算出する。

`market`は`applicability`、`rationale`、`claimIds`、`alternatives`を持つ。非該当の場合は理由を書き、claimIdsとalternativesを空配列にする。該当する場合は、検証すべきclaim IDと、比較した既存の代替手段をそれぞれ配列で記録する。

## 判定の読み方

| 結果 | 次の作業 |
|---|---|
| `readyForReview: false` | `blockers`に示された未確認の前提、資料の不一致、期限切れなどを解消する |
| `readyForReview: true` | 構造と参照が揃った状態。独立した目的・計画reviewへ進む |
| `warnings`あり | 重要ではない未確認の前提などをreviewで確認し、残す理由を説明する |
| `canImplement: false` | 既存の実装開始検査で示された不足へ戻る。審査済みの根拠が変更された場合も再審査する |

すべての受入条件を少なくとも一つのclaimへ結ぶ。少なくとも一つは`critical: true`にする。重要なclaimは`status: supported`と実在する非syntheticの根拠を必要とし、反証の調査が未実施・未解決なら停止する。AIが作った想定インタビューを実在の利用者の証言として扱わない。

市場需要を前提とする場合は`market.applicability: required`を選び、既存の代替手段と検証対象のclaimを記録する。そのclaimを`critical: true`にし、利用者の観測か実験の資料を結ぶ。製品紹介を読むだけでは需要を確認したことにならない。社内・個人用の整備など市場需要を前提にしない場合は、`not-applicable`と具体的な理由を記録する。

## 資料を更新するとき

各資料にはSHA-256、観測日`observedAt`、有効期限`validUntil`を記録する。日付はUTCの`YYYY-MM-DD`で、期限当日は有効。未来の観測日、期限切れ、資料とhashの不一致は停止する。期限は資料の変化しやすさに合わせ、reviewで妥当性を確認する。

JSONを更新すると審査済みのdigestが一致しなくなる。資料だけを変更してもhash検査で停止する。内容を確認し直してから審査記録を更新する。通すためだけに期限やhashを変更しない。

資料は同じtaskの`decision-sources/`直下のMarkdownに限定する。ファイル名は英数字で始め、英数字・ハイフン・アンダースコア・ピリオドを使い、拡張子を`.md`にする。symlink、親directoryへの遡及、秘密を含みそうなpath、UTF-8でない内容、NULを拒否する。JSONと各資料は128 KiB以下、資料は32個以下にする。実行briefは資料全文を含まず、既存の256 KiB上限を維持する。

## 検査で分からないこと

資料の種類、重要度、市場検証の対象外という分類は作成者が記入する。文字列が正しいだけでは、その分類や資料の主張が正しいと証明できない。checkerは元資料を読み、都合の悪い結果を省略していないか、成功しても困り事が残らないかを確かめる。

この仕組みはCLIを経由する開始検査であり、任意のfile writeをOSレベルで禁止するものではない。reviewerの本人性、外部writeの承認、PMF、継続運用での手戻り削減も証明しない。実際の効果は目的のズレの見逃しと不要な差戻しを作業記録で追う。

設計の参考は、重要で未確認の仮説から検証する[Strategyzerのassumptions mapping](https://www.strategyzer.com/library/how-assumptions-mapping-can-focus-your-teams-on-running-experiments-that-matter)と、生成した回答を利用者の証言に置き換えない[Product Talkの調査上の注意](https://www.producttalk.org/generative-ai-discovery/)。具体的な実行契約は[計画から実装への判断契約](plan-execution-contract.md)を参照する。
