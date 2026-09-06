# Codemap（退役互換ページ）

新しい作業では、ファイル依存グラフをRoadmapへ読み込むCodemap preflightを使わない。`codemap.source.json`、`codemap.json`、`codemap.lock`、`codemap.html`と過去のtask memoryは履歴・互換のため保持し、再生成・削除・改名しない。

## 現行の根拠

コード変更の影響は、対象module、呼出元・呼出先、直接import、関連style、guarding testをsourceから必要な範囲で確認し、`30_plan.html`の「変更対象」「実装」「implementation-evidence」「verification」へ明示する。Roadmapのtask順、更新時刻、path名だけから関係を推測しない。

componentとdata flowを図で説明する必要がある場合は、計画Task内に実装構成を明示した`diagram` fragment（`kind: "architecture"`、`diagramData`）を置き、`plan_architecture.py`でmatching figureのSVGをauthoring中に生成する。同期前に`plan_architecture.py --check`でfragmentとSVGをread-only検証する。詳細は[Archify計画図](../skills/viewing-plans/references/archify-overview.md)を参照する。

## 互換境界

旧`generate-codemap.py`と既存Codemap payloadは、過去artifactを読み取る互換用途に限る。再生成せず、現行のRoadmap generator、snapshot、Task HubはCodemapを入力・freshness・表示の根拠にしない。新しい`codemap.html`を作らず、歴史artifactを現行成果物と混同しない。
