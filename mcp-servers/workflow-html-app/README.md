# workflow-html-app

MCP Appsプロトコルを使用したインタラクティブHTMLワークフローViewer。HTML route、lifecycle、static/browser gateは `../../context/html-artifact-contract.md` と `../../config/html-surfaces.json` を正本にする。

## 機能

- `view-plan`: 計画ファイル（30_plan.md）をインタラクティブHTMLで表示
  - Markdownレンダリング
  - コメント入力（対応hostへのフィードバック）
  - responsiveな文書・outline・review UI
- `view-log`: 作業ログ（05_log.md）を独立したLog Viewerとして表示
  - Plan Viewerと同じsanitized Markdown描画を共有
  - ログ見出しとコメントprefixを自動切替
- `view-verification`: 検証ガイド（90_verification.md）をHTMLで表示
  - checklist進捗を維持
  - Plan / Logと共有する安全なdocument bundleから生成されるaliasとして配布
- `view-diagram`: 図をHTMLで表示
  - 既存tool schema互換を維持
  - durable artifactではSVGを正本にし、HTMLは派生成果物として扱う

UI resourceは `text/html;profile=mcp-app` として返す。MCP Apps非対応hostではtool resultのtext fallbackを利用可能にする。

## ビルドと検証

```bash
npm install
npm run build
npm test
python3 ../../scripts/verify-html-surfaces.py
```

配布用distは、temporary outputをbuildし、static/browser gateが成功した場合だけpublishする。build失敗やHTML contract違反で既存の有効distを上書きしない。

## Codex連携設定

`~/.codex/config.toml` に以下を追加:

```toml
[mcp_servers.workflow-html-app]
command = "bash"
args = [
  "-lc",
  "exec node \"$HOME/.codex/mcp-servers/workflow-html-app/dist/main.js\"",
]
startup_timeout_sec = 30
```

## 使用方法

Codexから:
```
# view-plan ツールを呼び出し
mcp__workflow-html-app__view-plan content="# 計画\n\n## タスク\n- [x] 完了"

# view-log ツールを呼び出し
mcp__workflow-html-app__view-log content="# 作業ログ\n\n## Phase 1: 調査\n- 完了"
```

## 技術スタック

- MCP SDK (`@modelcontextprotocol/sdk`)
- Vite + vite-plugin-singlefile（HTMLバンドル）
- Mermaid互換renderer（既存diagram input互換用。新規diagram artifactの正本はSVG）
- Marked.js（Markdownレンダリング）

## 注意事項

- tool名とresource URIは互換契約であり、変更する場合はmanifestとAcceptanceを更新する。
- canonical UIからcompatibility UIを生成し、許可adapter以外のdriftを持たせない。
- Plan / Log / Verificationは同じdocument bundleを共有し、Verificationだけを独立hand-maintainしない。
- HTML UIの表示はホスト側のMCP Apps対応が必要。非対応hostではtext fallbackを使う。
