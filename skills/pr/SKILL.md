---
name: pr
allowed-tools: Bash(git:*), Bash(gh:*), Bash(python3:*)
argument-hint: [base-branch]
description: Evidenceに拘束された文案を検証し、承認後にDraft PRを作成
---

# /pr

PR本文の文案生成とGitHubへのexternal writeを分離する。Fast workerはtoolなしのproposalだけを返し、leadがEvidence、template、base/head、principal、承認を検証してからDraft PRを作る。

## 境界

- base branchとhead branchを明示し、生成時と作成直前のSHAを拘束する。
- Evidence Bundleが不完全、CRITICAL / IMPORTANTが未解決、未承認writeがある場合は停止する。
- workerへGit/GitHub tool、command、approval、認証済みsessionを渡さない。
- `gh pr create --dry-run`はpushを伴う場合があるためpreflightへ使わない。
- PR作成はverified approval evidenceまたは明示されたproject policyが対象repositoryと操作を許可する場合だけ行う。

## 1. repositoryとPR範囲を確定する

現在branch、remote、head SHAを確認する。base argumentがなければproject `AGENTS.md`のbase policyを使い、それもなければ候補をread-onlyで調べて一つに確定する。暗黙のfallbackで作成しない。

base/head SHAとchanged pathsを次で固定する。全changed pathを`--allowed-path`へ列挙し、delete/renameは依頼範囲と一致する場合だけ明示許可する。

```bash
python3 ~/.codex/scripts/git_delivery_contract.py range <repo-root> \
  --base <base-sha> --head <head-sha> \
  --allowed-path <path-1> --allowed-path <path-2>
```

`DRAFT_BLOCKED`なら文案作成へ進まない。
既定出力はraw diffを除いた永続snapshotである。本文生成にpatchが必要な場合だけ、同じallowlistとbase/headで`range --include-worker-patch`を再実行し、永続snapshotと`source_hash`が一致することを確認して一時入力として直接渡す。

## 2. Evidenceとtemplateを入力へ束縛する

Evidence Bundleからacceptance evidence、tests、findings、residual risks、writes performedを取得する。repositoryのPR templateを読み、必須headingを`template_sections`へ記録する。

`Delivery Draft Input`にはsnapshotの`source_hash`、base/head SHA、changed paths、Evidence ID、acceptance/test/risk ID、template sections、policy sourceを入れる。raw diffはsnapshotが安全と判定した`worker_patch`だけを一時的に渡し、長期memoryへ保存しない。

## 3. Fast classは文案だけを返す

要約が必要なPR本文は`rules/model-routing.md`のFast classへ委譲できる。`scripts/draft_delivery_message.py <temporary-input.json> --expected-source-hash <trusted-snapshot-hash>`が、user configとtool featureを無効化したisolated Luna Maxを起動し、typed outputを親validatorへ戻す。起動または検証に失敗した場合は弱いmodelへfallbackせずleadへ戻す。

outputはtitle、summary、why、trade_off、out_of_scope、impact、tests、residual_risks、template固有section、`claim_references`を含む。`status`は`DRAFT_READY`または`DRAFT_BLOCKED`だけとする。

## 4. 親が本文を検証する

まず`validate_delivery_draft_structure`でsource hash、必須section、template coverage、claim references、禁止fieldを検証する。親は各test、risk、影響範囲を実差分とEvidenceへ戻って確認し、合格した本文の`content_hash`と全`claim_references`へ束縛したClaim Verification Evidenceを作る。その証跡を`validate_delivery_draft_pair`へ渡し、意味reviewを飛ばした本文を拒否する。

検証済み本文をtask-localな平文fileへ保存する。既存templateの項目を削除せず、state diagramはcommit済みrepository pathまたは検証済み関係要約だけを使う。

## 5. external write gateを通す

`gh auth status`で現在のGitHub principalを確認し、remote ownerと照合する。別accountへ自動切替しない。verified approval evidenceがrepository、push、Draft PR作成を許可していることをtrusted runtimeで確認する。

作成直前に`git_delivery_contract.py check-range`でbase/head refを再解決し、snapshot fileとは別に保持した`--expected-source-hash`、最初と同じ全`--allowed-path`、delete/rename policyをtrusted parentから再指定する。`DRAFT_STALE`または`DRAFT_BLOCKED`なら本文を使わず、snapshotから作り直す。

## 6. Draft PRを作成する

headが対象remoteへpush済みであることを確認した後、次の形で明示する。

```bash
gh pr create --draft \
  --base <base-branch> \
  --head <head-branch> \
  --title "<validated-title>" \
  --body-file <validated-body-file>
```

作成後にPR URL、number、base/head SHAを取得し、Evidence Bundleの`writes_performed`へ記録する。

## 完了報告

- PR URLとnumber
- base/head branchとSHA
- Evidence Bundle、test、review結果
- verified approval evidenceの参照
- 対象外dirty stateと残存リスク
