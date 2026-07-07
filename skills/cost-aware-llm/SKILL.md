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
 routine specialist?             → YES → gpt-5.4 + service_tier priority（custom時のみ明示）
セキュリティ/PRD/複雑判断？       → YES → gpt-5.5 + service_tier priority（custom時のみ明示）
迷ったら                         → role既定、またはmodel省略
```

## いつ呼ぶか

- ✅ サブエージェント起動前に「どのモデル？」と迷ったとき
- ✅ コスト最適化リクエスト（「もっと安く」「重いmodel指定を減らしたい」等）
- ❌ ルーチンレビュー（rules/model-routing.md に自動適用される）

## コスト削減 Tips

1. `MAX_THINKING_TOKENS=10000` で思考トークン制限（設定済）
2. `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` で早期 compact（設定済）
3. 並列 > 逐次（同情報を何度も渡すよりまとめて）
4. `/compact` を論理的ブレークポイントで

## 月間コスト目安

| パターン | 推定比 |
|----------|--------|
| すべて高精度モデル指定 | 100% |
| 通常タスクは親モデル継承に任せる | ~60% |
| 複雑判断のみ必要に応じて `model = "gpt-5.5"` + `service_tier = "priority"` に昇格 | ~70% |

## NG例: 一律格上げ

軽量/routineタスクまで一律で上位モデル（`gpt-5.5`等）に格上げすると、role default のルーティングポリシーと不整合を起こす。明示モデル指定は判定・レビュー等の重い用途に限定し、軽量/routineタスクは既定モデル（role default）に委ねる（出典: memories/23_evidence_summary.md「S-008」）。

## model明示時の互換性検証

`model` を明示する設定変更を行った場合は `~/.codex/scripts/verify-codex-model-compat.py` でリグレッションガードする。明示 `model = ...` の近傍に `service_tier = "priority"` があるかを検査するスクリプトで、対象パスを指定して実行する（出典: memories/23_evidence_summary.md「S-005」）。

## 関連

- `rules/model-routing.md` — 詳細な選択基準とサブエージェント別の割り当て
- Tier 1-3 レビューアーは各 agent 定義の懐疑姿勢とルーブリックで品質を担保する
