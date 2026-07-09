---
name: cost-aware-llm
description: LLMコスト最適化。サブエージェントの model override を指定するか、親モデル継承に任せるかの判断ガイド。「コスト最適化して」「どのモデルを使うべき」等の依頼時に参照。詳細ルートは rules/model-routing.md に集約。
---

# Cost-Aware LLM Pipeline

サブエージェント起動時の **モデル選択判断スキル**。
Codex の `multi_agent_v1.spawn_agent` は、まず `agent_type` の role 既定を使う。`default` / custom sub-agent で `model` を明示する場合は、必ず `service_tier = "priority"` も併記する。

詳細ルールは `rules/model-routing.md` に集約済み。本スキルは判断の起点として使う。

## クイック判断

```
通常の検索/読み取り/定形タスク？ → YES → explorer等のrole既定、またはmodel省略
default/custom の短い定型作業？     → YES → metadataで利用可能なら gpt-5.4-mini + service_tier priority + low effort
 routine specialist?             → YES → gpt-5.4 + service_tier priority（custom時のみ明示）
セキュリティ/PRD/複雑判断？       → YES → gpt-5.5 + service_tier priority（custom時のみ明示）
迷ったら                         → role既定、またはmodel省略
```

## いつ呼ぶか

- ✅ サブエージェント起動前に「どのモデル？」と迷ったとき
- ✅ コスト最適化リクエスト（「もっと安く」「重いmodel指定を減らしたい」等）
- ✅ model / service_tier / routing 差分をレビューするとき
- ❌ 通常のルーチンレビュー（rules/model-routing.md に自動適用される）

## コスト削減 Tips

前提として、この Vault の custom/default sub-agent では `service_tier = "priority"` を維持する。
これは API 一般の最安構成ではないため、低コスト化は tier ではなく次のレバーで行う。

1. shell / `rg` / `git diff` で足りる作業は local で済ませる
2. 独立したローカル読み取りは `multi_tool_use.parallel` を優先する
3. sub-agent 並列は、独立性と価値がある時だけ使う
4. sub-agent には全文脈ではなく、目的・write scope・合格基準・直近の失敗原因だけを渡す
5. commit文案、短い要約、定型整形は、metadata で利用可能な場合に `default` + `gpt-5.4-mini` + `service_tier="priority"` + `reasoning_effort="low"` を検討する
6. 不確実性、矛盾、複数ファイル判断が出たら mini を続けず role 既定へ昇格する

## 月間コスト目安

| レバー | 期待効果 |
|--------|----------|
| local `rg` / diff / script を優先 | sub-agent 起動そのものを減らす |
| Team Journal で context slimming | 同じ背景を何度も渡さない |
| Heat 0/1 を正しく使う | 不要な reviewer fan-out を避ける |
| mini を限定投入 | 短い定型作業の単価と待ち時間を下げる |

## NG例: 一律格上げ

軽量/routineタスクまで一律で上位モデル（`gpt-5.5`等）に格上げすると、role default のルーティングポリシーと不整合を起こす。明示モデル指定は、default/custom の短い定型作業では `gpt-5.4-mini`、判定・レビュー等の重い用途では `gpt-5.5` / `gpt-5.4` に限定し、role がある作業は既定モデルに委ねる。custom/default sub-agent で model を明示するときは `service_tier = "priority"` も併記する（出典: memories/23_evidence_summary.md「S-008」）。

## Mini 利用のガードレール

`gpt-5.4-mini` は安く速いが、team-run の品質ゲートを代替しない。次の条件を全て満たすときだけ使う。

- 現セッションの `spawn_agent` metadata で `gpt-5.4-mini` が利用可能である。
- default/custom sub-agent であり、適切な role が存在しない。
- 入力と出力が短く、lead が即座に検査できる。
- 成果物が commit文案、短い要約、定型変換、重複検出などに限られる。
- 失敗しても外部副作用や大きな手戻りがない。
- `service_tier = "priority"` と `reasoning_effort = "low"` を併記できる。

次は使わない。

- `spawn_agent` metadata に `gpt-5.4-mini` がない環境。
- GO/NO-GO、設計判断、セキュリティ、レビュー最終判定。
- 3ファイル以上の実装、未知コードの変更、外部書き込み。
- 引用精度が必要な調査、ソース間に矛盾がある調査。

## model明示時の互換性検証

`model` を明示する設定変更を行った場合は `~/.codex/scripts/verify-codex-model-compat.py` でリグレッションガードする。明示 `model = ...` の近傍に `service_tier = "priority"` があるかを検査するスクリプトで、対象パスを指定して実行する（出典: memories/23_evidence_summary.md「S-005」）。

## 関連

- `rules/model-routing.md` — 詳細な選択基準とサブエージェント別の割り当て
- Tier 1-3 レビューアーは各 agent 定義の懐疑姿勢とルーブリックで品質を担保する
