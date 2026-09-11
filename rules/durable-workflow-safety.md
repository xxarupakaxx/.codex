# Durable workflowと大量処理の安全契約

batch、queue、Temporal等のdurable workflow、外部API同期、完了待ちpollingを変更するときに適用する。対象件数が少ないunit testや型検査だけでは、直列化上限、履歴肥大、停止不能を検出できないため、出荷前に実運用上限を使った境界証拠を残す。

## 1. 最大負荷を先に固定する

入力制約、実データ統計、既存上限のいずれかから `max_cardinality` を決める。平均件数や今回たまたま小さいsampleへ置き換えない。上限が不明なら未確認として扱い、無制限の配列をworkflow境界へ渡さない設計を選ぶ。

次の各境界を列挙する。

- API request / response
- workflow input / result / query
- Activity input / result
- signal / update / child workflow
- DB JSON / report snapshot
- UI polling response

各境界について、最大件数fixtureを実際のserializerへ通した `serialized_bytes` と、runtimeの `limit_bytes` を比較する。概算や要素数だけを合格証拠にしない。全件配列を別のActivityへ渡し直す、完了reportへ再包含する、workflow resultへ返す場合は別境界として再測定する。

## 2. 履歴と外部呼出しを予算化する

Activity、timer、retry、signalの個数から `history_growth` を最大件数で見積もる。1 entity / Activityを採る場合は、履歴上限と運用上の可読性を満たす根拠を示す。batch化してもActivity内で外部APIを無制限並列化しない。

外部APIごとに `rate_limit_scope` を記録する。

- 制限単位がentity、HTTP request、integration、workspace、processのどれか
- read / writeのどちらへ適用されるか
- retry、pagination、複数workerで実request数がどう増えるか
- concurrency、間隔、backoff、timeout、部分成功後の再開方法

「1 entity/秒」を「1 request/秒」と同一視しない。sourceまたは計測で確認できない保証は未確認として残す。

## 3. 全終了経路を同じ状態機械で閉じる

正常完了だけでなく、failed、canceled、terminated、timeout、worker crash、外部からの停止を列挙する。各経路で `terminal_convergence` を確認する。

- workflowの終端状態とDBの業務状態が収束する
- lease、lock、generation、processing itemが回収または失効する
- pollingは全終端状態で停止する
- staleなactive状態を再取得時に修復できる
- 手動停止は外部処理とDB状態の片方だけを更新しない
- 失敗時responseへ巨大snapshotを載せ続けない

catch内のActivityだけに失敗記録を依存すると、Activity scheduling自体の失敗や外部Terminateでは実行されない。workflow外の照合経路を含めて検証する。

## 4. dry-runと実行を別々に検証する

dry-runは副作用がないことを示す機能であり、処理容量、完走性、rate limit耐性、停止性の証明ではない。dry-runにも本実行と同じ最大件数・payload・履歴・終了経路の検査を適用する。

本実行については、部分成功、retry、resume、重複開始、承認後のsource変化を確認する。dry-run結果のhashやsnapshotを使う場合、実行時に同じ対象を再検証できることを証拠にする。

## 5. 出荷証拠

高負荷経路を変更したWork PacketまたはPRでは、少なくとも次を残す。

1. 最大件数fixtureによる全境界のbyte計測
2. 最大件数に対するActivity / history / 外部request数
3. rate limitのscopeとretry込みの呼出し速度
4. success / failed / canceled / terminatedでのDB状態とpolling停止
5. 実データを変更しないreplayまたはtest

`scripts/validate-durable-workflow-evidence.py`で証拠JSONを検査する。fixtureは本番credentialや実データを含めず、測定元のcommit、serializer、runtime limitのsourceを参照する。
