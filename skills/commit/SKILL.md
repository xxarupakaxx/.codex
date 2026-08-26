---
allowed-tools: Bash(git:*), Bash(python3:*)
argument-hint: [--push]
description: 検証済みの変更だけをcommitし、必要時に文案をFast workerへ委譲
---

# /commit

commit文案の生成とGit副作用を分離する。Fast workerはtoolなしで文案だけを返し、exact staging、事実確認、commit、pushはleadまたはtrusted local executorが行う。

## 境界

- 文案の事実源は、Evidence Bundleと`git_delivery_contract.py`が固定したstaged snapshotだけである。
- workerへGit/GitHub tool、command、approval、external writeを渡さない。
- worker出力は未信頼のproposalであり、`validate_delivery_draft_pair`を通るまで使用しない。
- commitはlocal Git write、pushはexternal writeとして別gateにする。
- `git add -A`、暗黙の全stage、here-documentによるmessage展開を使わない。

## 1. 対象を確定してexact stagingする

`git status --short`、対象差分、直近logを確認する。user由来のdirty stateを分け、今回の対象pathだけを明示してstageする。deleteまたはrenameは依頼範囲と一致する場合だけ個別に許可する。

stage後に次を使い、各対象を`--allowed-path`で列挙したsnapshotを作る。

```bash
python3 ~/.codex/scripts/git_delivery_contract.py staged <repo-root> \
  --allowed-path <path-1> --allowed-path <path-2>
```

`DRAFT_BLOCKED`、空差分、対象外path、unmerged、未許可delete/rename、secret、上限超過があればFast文案生成へ進まない。secret hitがscanner自身のpatternまたは明示的なfake test fixtureだけだと親が対象行を直接確認した場合は、hit pathと根拠をEvidenceへ残し、`worker_patch`を渡さずL0 local文案へ戻せる。実credentialの可能性が残る場合やその他のviolationではcommitへ進まない。
この既定出力は`worker_patch`を除いた永続snapshotであり、task memoryへ保存できる。

## 2. LocalかFast classかを選ぶ

単一目的で定型的なsubjectだけならlocal templateを使う。複数の意図、理由、trade-offを短く要約する価値が、委譲と統合のコストを上回る場合だけ`rules/model-routing.md`のFast classを使う。

Fast classへ渡すのは、`Delivery Draft Input`、snapshotのpath/stat/hash、安全な範囲の`worker_patch`、Evidence参照だけである。raw diffが必要な場合だけ同じexact allowlistで`staged --include-worker-patch`を再実行し、永続snapshotと`source_hash`が一致することを確認してmemoryへ保存せず一時入力へ置く。`scripts/draft_delivery_message.py <temporary-input.json> --expected-source-hash <trusted-snapshot-hash>`が、user configとtool featureを無効化したisolated Luna Maxを起動し、typed outputを親validatorへ戻す。失敗時は弱いmodelへfallbackせずleadへ戻す。

commit outputは次を満たす。

- `status`: `DRAFT_READY`または`DRAFT_BLOCKED`
- `content.type`: 許可されたgit-cz type
- `content.subject`: 日本語、70文字以内、絵文字なし
- `content.body`: 必要な場合だけwhat / why / trade-off
- `claim_references`: inputで許可したpath、acceptance、test、riskだけ

## 3. 親が文案を検証する

まず`validate_delivery_draft_structure`でinput/outputを検証する。さらに実差分を読み、type、subject、bodyの各主張を確認し、合格した文案の`content_hash`と全`claim_references`へ束縛したClaim Verification Evidenceを親が作る。その証跡とtrusted snapshotの`source_hash`を`validate_delivery_draft_pair`へ渡し、意味reviewを飛ばした文案を拒否する。

検証済みmessageをtask-localな一時fileへ平文で保存する。Fast worker自身にはfileを書かせない。

## 4. driftを再確認してcommitする

実行直前に、保存したsnapshotへ`git_delivery_contract.py check-staged`を実行し、snapshot fileとは別に保持した`--expected-source-hash`、最初と同じ全`--allowed-path`、delete/rename policyをtrusted parentから再指定する。結果が`DRAFT_STALE`または`DRAFT_BLOCKED`ならcommitせず、snapshotから作り直す。

`READY`の場合だけ次を実行する。

```bash
git commit --file=<validated-message-file>
```

commit後にSHA、実際のchanged paths、hook結果を確認し、Evidence Bundleの`writes_performed`へ接続する。

## 5. pushは別gateで行う

`--push`が指定されても、project policyまたはverified approval evidenceがpush対象を許可していることを確認する。remote、branch、現在のprincipalを確認し、accountを自動切替しない。許可がなければcommit済みで停止し、push待ちとして報告する。

## 完了報告

- commit SHAとmessage
- committed paths
- test / hook結果
- pushの実行有無とremote
- 対象外dirty stateの残存状況
