# 計画から実装への判断契約

目的、前提、計画、実装、利用結果をこの順に照合する。仕様やテストがあること自体を、方針が正しい根拠にしない。適用対象は30_plan.htmlを持つroadmap / explicit-roadmapの実装。通常の局所作業には新しいartifactを強制しないが、目的の確認は省略しない。

## 審査の順序

| 段階 | 確かめること | 差し戻す条件と戻り先 |
|---|---|---|
| 目的・前提 | 元の依頼、現実の困り事、利用者、制約、成功場面に対して要件と方針が妥当か | 目的を手段に置換、未確認の前提、成功しても困り事が残る → 要件・方案の再検討 |
| 計画 | その手順を実行すると成功場面まで到達するか。実装者に未定義の判断を押し付けていないか | 手順、依存、失敗時の扱い、判断境界、検証方法が欠ける → 計画の修正 |
| 成果物 | 元の依頼の場面を成果物で実行できるか。仕様自体の誤りを再確認する | 仕様通りでも目的未達、主要場面を実行できない → 要件または実装へ戻す |
| 内部品質 | 上記が成立する実装のAPI契約、性能、保守性、安全性 | 根拠のある欠陥 → 対応する実装と検証へ戻す |

上位段階にblocking findingがあれば、下位の合格で相殺しない。例えば「必要な情報を探せる」が目的なら、APIが200を返しても検索結果から情報へ到達できなければ目的適合は不合格。reviewerは「仕様通りだから正しい」と結論しない。

目的と計画はmakerから独立したcheckerが審査する。同じcheckerが順に担当してよい。初めに元の依頼と現在の事実から成功条件を再構築し、その後に作成済みの仕様・計画と比較する。固定人数や固定roundを要求しない。意味のある独立審査を実行できなければ未審査のまま残し、passを補完しない。

`receiving-code-review`は指摘を採用する前の検証規律。既存codebase全体の方案監査には`reviewing-codebases-architecture-first`がある。本契約はそれらの代わりに毎回大規模監査を起動せず、計画から実装への遷移を担当する。

## 計画の本文

ユーザーの依頼と、その後の目的・範囲を変える追加指示の該当箇所をtaskの`00_request.md`へ保存し、引用と解釈を区別する。secretや無関係な会話を含めない。makerの都合で書き換えない。ユーザーの追加指示で目的が変わった場合は出典と変更を残し、再審査する。

`30_plan.html`を人とLLM共通の正本にする。全体に`data-field="execution-contract-version"`のsectionを置き、本文値を`1`にする。snapshotのschema 2とは別の実行契約versionである。さらに次の`data-field`を持つsectionを置く。本文を別JSONへ複製しない。

| field | 本文に書く内容 |
|---|---|
| intent | 誰のどの困り事をどう解消するか。手段の実装だけを成功にしない |
| assumptions | 現在の事実とsource、未確認の仮定、制約。仮定が外れた場合の影響 |
| approach | 採用案と理由、検討した代替案、対象外、要件が目的に必要な理由 |
| success-scenarios | 利用開始の状態、操作、観測できる成功結果。重要な失敗場面 |

各Taskは既存のpurpose / targets / implementation / outputs / verification / acceptance / blocked-byに加え、次を本文へ置く。

| field | 本文に書く内容 |
|---|---|
| implementation | 順序付きの手順。確認するsourceや関数、変更する挙動、接続先、途中の確認点。必要ならコード・入出力例を置く |
| decision-boundaries | 実装者が選べること、守る判断、変更対象・対象外。モデルを替えても変わらない境界 |
| stop-conditions | 想定と違った場合、未決の判断が必要な場合、検査が通らない場合の停止条件と戻り先 |
| negative-paths | もっともらしいが不合格な実装例、失敗時の期待挙動、それを検出する方法 |

UI mockだけでは手順にならない。画面操作から状態変更・処理・表示結果までを記述する。verificationはコマンド名だけでなく期待結果を持ち、各acceptance IDと成功場面を対応させる。実装者は不明点を独自解釈で埋めず、stop-conditionsに従ってleadへ返す。

## 審査記録と開始検査

共通実装は`~/.codex/scripts/plan_execution_contract.py`。計画は既存parserが抽出する。審査記録は同じtaskの`plan-review.json`に置く。

```json
{
  "schemaVersion": 1,
  "authorId": "実際の計画作成agentまたは担当者",
  "planDesignSha256": "helperが返した計画契約hash",
  "requestSha256": "helperが返した00_request.mdのhash",
  "reviews": {
    "intent": {
      "verdict": "pass",
      "reviewerId": "実際の独立checker",
      "basis": "元依頼と前提に照らした判定理由",
      "counterexample": "目的を満たさない反例を検討した結果",
      "evidence": "実際のreview出力への参照",
      "evidenceSha256": "intent-review.mdのSHA-256",
      "openFindings": []
    },
    "plan": {
      "verdict": "pass",
      "reviewerId": "実際の独立checker",
      "basis": "手順・依存・判断境界・検証の判定理由",
      "counterexample": "別の実装者が誤読し得る点を検討した結果",
      "evidence": "実際のreview出力への参照",
      "evidenceSha256": "plan-review.mdのSHA-256",
      "intentReviewSha256": "intent審査objectのcanonical JSONのSHA-256",
      "openFindings": []
    }
  }
}
```

実際の目的審査出力を`intent-review.md`、計画審査出力を`plan-review.md`へ保存し、それぞれのraw bytesのhashを結ぶ。目的審査がpassになった後に計画審査を行い、planのintentReviewSha256にはintent objectを`json.dumps(ensure_ascii=False, sort_keys=True, separators=(",", ":"))`で符号化したUTF-8 bytesのSHA-256を記録する。証拠の改変や審査結果の差替えは失効する。

verdictは`pass`、`revise`、`blocked`を使う。未解決の正しさに関するfindingはopenFindingsへ残し、passで隠さない。leadが独立checkerの実際の出力と元sourceを照合して記録する。名前の文字列やhashは本人性、意味的正しさ、ユーザー承認の証明ではない。fixtureで作ったpassを実taskへ流用しない。

閲覧・審査用の`task-context.py brief TASK --memory-root ROOT`は従来通り要約を返す。`executionReadiness.canImplement`とblockersで不足を確認できる。従来の`state: ready`は要約取得可能を表し、実装承認には使わない。

実装者へ渡す直前に次を実行し、非zeroなら実装・委譲を止める。

    python3 ~/.codex/scripts/task-context.py brief TASK --memory-root ROOT --task-id ID --execution

成功時は`executionBrief`に元依頼、全体の判断契約、選択Taskの全文・順序・コードを含むDOM、受入条件、sourceを返す。閲覧用selectedTaskには短縮があるため実装入力に使わない。実行briefはUTF-8 JSONで256 KiB、元依頼・各審査記録・receiptは各128 KiBを上限とする。超過時は非zeroで停止する。大きすぎる場合はTaskを再分割し、契約の末尾を切って渡さない。開始前にsourceと前提が今も成立するか確認する。

`sync-roadmap.py --phase 3|4|5`も同じreadinessを検査する。Phase 2は未審査の計画を表示・審査するために使える。過去のHTML/Markdownは閲覧を維持し、実装再開前にHTML契約と審査を補う。旧Markdownを削除・改名しない。CLIを通さない任意のfile writeをOSレベルで防ぐ仕組みではないため、両runtimeのworkflowと委譲入口から必ず呼ぶ。

計画本文、受入条件、依存、mock、fragmentまたは依頼が変われば審査をやり直す。hashは計画のsemantic DOM、head CSS・metaとfragmentを対象とし、進捗属性とimplementation内のcheckbox状態だけを除く。コード例や手順の末尾も対象。raw source hashは既存同期が別途維持する。進捗属性へ設計情報を隠さない。計画のCSS変更も審査を失効させ、見た目の既存HTML確認を適用する。

## 完了レビューと既存契約

最終checkerも00_request.md、成功場面、現在の前提から入り、実際の成果物と証拠を照合する。上位の方針に問題があれば内部品質reviewを保留し、80_review.mdへ目的・計画・成果物・内部品質の判定と戻り先を分けて残す。

Approved PRD、Work Packet、Evidence Bundleとcompletion_targetは既存の契約を維持する。plan-review.jsonは計画段階の審査を実装入口へ接続する記録であり、Evidence Bundleや外部write承認を代用しない。新しいモデル設定、権限、認証、公開・課金への許可を発行しない。

ローカル負例検査と今回の計画で動作確認した段階をpilotedとする。継続運用で有効性を確かめる際は、目的のズレが最終reviewまで漏れた件数と、不要な差戻し・開始不能の件数を元の作業記録に照合する。baselineがなければ改善率を主張しない。
