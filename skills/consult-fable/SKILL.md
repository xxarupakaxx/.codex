---
name: consult-fable
description: "GPT(Codex)オーケストレーターが、必要な局面だけ Claude Fable 5 に単発の戦略相談を投げる Model-invoked スキル。不可逆分岐・案の拮抗・2周連続失敗・taste判断のときに使う。並列ワーカー・並列レビューアーの起動には使わない（それは spawn_agent）。"
---

# /consult-fable — Fable 5 への単発戦略相談（Board Advisor）

GPT が Plan → Delegate → Verify → Synthesize のメインループを回す。Fable 5 は hot path に入らない
on-demand の Board Advisor であり、このスキル経由でのみ相談を受ける。

## 設計判断の記録（ADR 代替・2026-07-13）

- **常設 workflow（workflows/*.js）にしない**: workflow は決定的台本であり、on-demand の相談を常設段にすると hot path 化する。また workflow の `agent()` は Codex モデル前提で Fable を呼ぶ口がない。
- **`_shared-ai/` に置かない**: 呼び出し元は Codex のみ（配置方針「1つのツールだけで使うものは各ツール側」）。人間可読ミラーは既存 sync-manifest 機構が同期する。
- **Claude 側には対称スキル `consult-gpt`（Claude→GPT相談）がある**: 主オーケストレーターが異なるため、双方向ブリッジは共通化せず各ツール側に独立実装する（プロバイダ間は設定共有でなく概念写像）。

## いつ呼ぶ（いずれか1つ以上を満たすときだけ）

1. **後戻りが困難な分岐**: アーキテクチャ選定・公開API・DBスキーマ等（`rules/adr-criteria.md` の Hard to reverse 相当）
2. **自案が拮抗して確信が持てない**: 複数案の優劣を自力で判定できない
3. **同一の合格基準で2周連続失敗**: ループがスタックしている
4. **taste 判断**: 命名・文言・設計の質感など、機械検証できない質的判断
5. **ユーザーの明示要求**

## 呼ばない

- routine 実装、テスト・lint 等の機械検証で判定できるもの
- ワーカー結果の単純集約
- 1回目の失敗（まず自力でリトライ）
- 並列レビュー・並列実装のワーカーとして（それは `multi_agent_v1.spawn_agent`）

## 実行方法

```bash
~/.codex/scripts/consult-fable.sh "（下の骨格で組んだ相談）"
# 追い質問（最大1回）: 出力 JSON の session_id を使う
~/.codex/scripts/consult-fable.sh --resume <session_id> "追い質問"
```

- 出力は JSON（`result` に回答、`session_id`、`total_cost_usd`）。
- Fable に許可されるツールは Read / Grep / Glob の3種のみ（`--allowedTools` で制限。書き込み・実行は不可）。
- Board Advisor 役割（結論1文→根拠3点以内→代替案最大1つ）は新規相談時に `--append-system-prompt` で注入される。`--resume` の追い質問では再注入されず、元セッションの設定を引き継ぐ。
- 日次上限 8 回の機械ガードあり。超過時は本当に必要かユーザーに確認する。
- **実行 CWD は相談対象のリポジトリにする**。Fable がそのプロジェクトの CLAUDE.md / rules を自動ロードし、Read/Grep/Glob でコードを読んだ上で批評を返す（これが API 直呼びに対する本質的な優位）。

## 相談プロンプト骨格

```text
## 相談種別
（不可逆分岐 / 案の比較 / スタック打開 / taste判断）

## 背景（3-5行）
何のタスクで、いま何が決まっていて、何が決まっていないか。

## 論点（1つに絞る）
判断してほしいことを疑問文で1つ。

## 自分の現在の案と確信度
A案: … / B案: …（自分は A 寄り、確信60%）

## 制約・参照
締切・互換性・コスト等。読んでほしいファイルパスがあれば列挙（本文を貼らずパスを渡す）。
```

相談が長時間の設計レビュー級に膨らむ場合のみ `prompting-fable` スキルの全項目チェックを併用する
（1往復相談には過剰なので既定では使わない）。

## 形式ガード（hot path 化の防止）

- **1往復原則**。追い質問は最大1回（`--resume`）。それでも決まらないなら、相談ではなくタスク委任か人間へのエスカレーションに切り替える。
- 相談の要旨と回答は作業メモリ（メモリディレクトリの 05_log.md 等）に記録し、**同一論点を再相談しない**。
- 相談ログを Vault のノートには書かない（`Claude-note/` 停止境界・`source_system` 契約との衝突を避ける）。

## 責務境界（CRITICAL）

- `claude -p` の使用は**このスキル経由の Fable 相談に限る**。並列レビューアー・並列ワーカーの起動は引き続き `multi_agent_v1.spawn_agent`（`skills/pr-review` の禁止指示は並列起動について引き続き有効）。
- `fable` は claude CLI の引数であり、**`spawn_agent` の model には決して書かない**（`rules/model-routing.md` の「Claude-only model aliases are not valid in Codex examples or prompts」は維持）。

## セキュリティ境界

**この節は呼び出し側（GPT）の運用規律であり、スクリプトは技術的に強制しない**（CWD・プロンプト内容の検証は行わない）。

- 既定 CWD は相談対象のリポジトリ。**Vault ルートを CWD にしない**（`Living/`・`Life/` 等の個人機密が Read/Grep 可能になるため）。
- Vault 内の知識を相談に使う場合も、`automation_read: false` のノートは対象外。ノート本文を相談文に貼らず、必要ならパスだけを渡す。
