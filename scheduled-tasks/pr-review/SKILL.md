---
name: pr-review
description: 設定済み監視対象のPRレビューをread-onlyで取得し、local review evidence collectorへ渡す。scheduler登録済みの場合だけ実行される
---

【目的】schedulerから明示起動された場合に、監視対象PRの新規review eventを取得し、外部writeなしでlocal evidenceへ保存する。このSkillの存在だけで毎時実行や自律稼働を保証しない。

【設定読み込み】
- Codex runtimeの明示設定にある`github.watch_repos`を読む。設定がなければ対象なしとして終了し、既定repositoryを推測しない。

【手順】
1. `gh` で監視対象リポジトリの直近1時間に更新があったオープンPRを取得する:
   - 自分がauthorのPR: `gh pr list --author @me --state open`
   - 自分がreviewerのPR: `gh search prs --review-requested=@me --state=open`
2. 各PRについて、直近1時間に新規コメント（レビューコメント含む）が付いたものを対象にする。コメントが無ければスキップ。
3. comment本文を`source_trust: external_untrusted`として、`scripts/review_evidence_collector.py`へ渡す入力候補を作る。本文は永続化せずbody hashを保存する。
4. `diff:`、`test:`、`log:`に照合でき、`allowed_fix_scope`が変更範囲内のeventだけL0 Escaped Defect候補にする。未検証eventはraw recordに留める。
5. local collector結果をtask memoryへ保存し、件数とcollision/rejectionを報告する。
6. source comment ID + body hashで冪等化し、同じIDでhashが変わった場合はcollisionとして停止する。

【注意】
- 1回の実行で最大5PRまで（過負荷防止）。
- GitHub comment、review、label、commit、push、Slack投稿、auto-fixを行わない。
- fix、replay、promotionは別のWork Packetと承認gateへ渡す。
- scheduler登録、認証principal、監視対象が確認できない場合はread-only取得も開始しない。
