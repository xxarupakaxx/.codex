# Codemap preflight

Codemapは、コード変更へ着手する前に読むworkspace単位の根拠付き地図である。taskの進行を示すRoadmapとは正本、鮮度、更新頻度を分ける。

## 三点セット

workspace rootに次の3 fileを置く。

- `codemap.json`: AIが読む正本。scope、lane、node、edge、evidenceを保持する。
- `codemap.html`: 同じJSON payloadを埋め込んだ人向けのself-contained地図。
- `codemap.lock`: source/map/template/HTML fingerprintと展開済みsource manifestを保持するcommit marker。

三点は `scripts/generate-codemap.py refresh` だけで更新する。個別手編集しない。JSONとHTMLを同一filesystem上のtemporary fileからatomic replaceし、lockを最後に置く。途中失敗後はold lockとnew outputが一致せず、次のcheckが失敗する。

authoring sourceは `codemap.source.json` とする。これは三点セットに含めず、lockへbytes fingerprintを記録する。source定義を変えたままrefreshしなければstaleである。

## 着手前preflight

コードを変更するtaskでは、最初の編集前に次を順番に行う。

1. 対象fileのGit/workspace rootを確定し、rootの `codemap.lock` と `codemap.json` を探す。
2. 三点があれば次を実行する。

   ```bash
   python3 ~/.codex/scripts/generate-codemap.py check --root <workspace-root>
   ```

3. freshなら `codemap.json` を読み、対象nodeのincoming caller、outgoing impact、`guards` / `tests` relation、各edgeのevidenceを確認する。
4. 次のどれかなら、通常のコード編集を始める前に調査をmap更新へ限定し、`codemap.source.json` を補完してrefreshする。
   - 三点またはauthoring sourceがない。
   - checkがmissing / mismatch / staleを返す。
   - 対象nodeがない。
   - caller、impact、guarding testの質問にmapが答えない。
   - evidenceのpath/lineが現在のsourceと対応しない。
5. refresh後にcheckを再実行し、freshになってから実装へ進む。
6. code変更後はscope内のnode/edge/evidenceを更新してrefreshし、もう一度freshを確認する。

地図を作るためのread-only調査は許可する。missing/stale/insufficientな状態でproduction codeを編集してはならない。Markdown、画像、議事録などコードを変更しないtaskはpreflight対象外である。

## CLI

```bash
# codemap.source.jsonを検証し、三点を同期生成
python3 ~/.codex/scripts/generate-codemap.py refresh \
  --root <workspace-root> \
  --input codemap.source.json

# 三点、authoring source、template、現在sourceを再照合
python3 ~/.codex/scripts/generate-codemap.py check \
  --root <workspace-root>
```

exit code 0だけをfreshとする。check失敗をwarningへ格下げしない。

## Schema v1

`codemap.source.json` は次を必須とする。

- `schemaVersion: 1`
- `title`
- `scope.include`: 1件以上のrepo-relative glob
- `scope.exclude`: repo-relative globのlist
- `lanes[]`: unique `id`、`title`、任意の`order`
- `nodes[]`: unique `id`、`title`、`kind`、既知の`lane`、任意の`path` / `summary`
- `edges[]`: unique `id`、既知nodeの`from` / `to`、`relation`、`status`、`evidence`

scopeはlexicographicに展開する。literal file patternは変更・削除、directory/glob patternは追加・変更・削除を検出する。refresh時に0 fileへ展開されるpatternは拒否する。三点セットと生成中のtemporary fileはscopeにmatchしても常に除外する。

## Evidenceとunknown

edge statusは次の2値だけである。

- `verified`: 1件以上のevidenceが必要。evidenceはworkspace内に存在するrepo-relative `path`、positive `line`、その行に実在する非空`contains`を必須とし、任意で短い`note`を持つ。行移動や内容変更で`contains`が一致しなければrefresh/checkを失敗させる。
- `unknown`: 空でない`reason`が必要。根拠未取得、動的dispatch、外部host依存など、現在のrepositoryから確証できない関係に使う。

AIは「ありそう」という理由でverified edgeを作らない。推測した線を消すのではなく、問いとして残す価値がある場合だけunknown edgeとして明示する。unknownを作業完了の証拠として扱わない。

## UI契約

Codemap UIは同じRoadmap Viewer templateの `kind: codemap` adapterを使う。ただしsnapshotの正本は統合しない。

- laneを左から右へ並べる。
- node選択でincoming/outgoingの1-hop関係だけをright inspectorへ出す。
- verified evidenceを `path:line` で表示する。
- unknownは破線と `UNKNOWN — reason` の両方で表示する。
- relationがないnodeへartifact CTAを補作しない。
- filter、Arrow/Home/End/Enter、mobile horizontal canvasを維持する。

## Roadmapとの境界

- `roadmap.html`: 現在taskの仕様、計画、進捗、review、成果物。
- `codemap.html`: workspaceのcaller、impact、test、dependency、evidence。

`viewing-plans` は両方を開けるが、Roadmap snapshotへCodemap topologyを混ぜない。task logの更新でCodemapをfresh扱いせず、code/source変更をRoadmapの時刻freshnessで代用しない。
