# HTML Artifact Contract

この文書は、Codex runtime がHTMLを生成・配布するときの共通契約である。`.codex/config/html-surfaces.json`をmachine-readableな正本とし、この文書は人間とagent向けにroute、lifecycle、gate、境界を説明する。

Effective HTML upstream は `plannotator/effective-html` commit `d95debbaef15af1d201fc6c10c77cf92b524a0d6`、MIT、`reference-first` adaptation として固定参照する。governance audit が `DEGRADED` の間、第三者Skillのinstall、promotion、runtime file変更は行わない。6 route はlocal ownerへ写像し、実行前後のgateで強制する。

## 正本

- `config/html-surfaces.json`: route、producer、surface、profile、exceptionの機械正本。
- `context/html-artifact-contract.md`: routeとgateの説明正本。
- `context/agent-team-routing.md`: producer Skill の呼び出し前後にどのgateを通すか。
- `context/workflow-rules.md`: Phase内でHTML artifact gateをいつ通すか。
- `context/codemap.md`: 旧Code Map利用者向けの退役・互換境界。
- `skills/viewing-plans/SKILL.md`: `html-plan` route の実行手順。

manifestにないHTML producerやtracked HTML surfaceを新規のcanonical routeとして扱わない。manifestとこの文書が矛盾する場合は、配布前にmanifest、checker、docsを同じ変更で揃える。

## 6 Route

| route | local owner | artifact kind | static profile | browser profile | 主な用途 |
|---|---|---|---|---|---|
| `html` | `creating-html-documents` | `html-document` | `strict-self-contained` | `desktop-document` | PCで読む自己完結の説明文書、教育資料、mixedでないHTML |
| `design-artifact` | `designing-ui-ux` | `design-artifact` | `strict-self-contained` | `design-approval-matrix` | 承認済みのUI/UX visual artifact |
| `html-wireframe` | `designing-ui-ux` | `html-wireframe` | `strict-self-contained` | `wireframe-matrix` | low-fidelity構造確認 |
| `html-prototype` | `designing-ui-ux` + `design-eval-loop` | `html-prototype` | `strict-self-contained` | `prototype-matrix` | working-flowやinteraction prototype |
| `html-plan` | `viewing-plans` + Roadmap generator | `html-plan` | `roadmap-generated` | `roadmap-matrix` | ブラウザで開く`roadmap.html` |
| `html-diagram` | `visualizing-work` → `generate-state-diagram` / `diagram-design` | `html-diagram` | `strict-self-contained` | `desktop-diagram` | SVG正本をPCで読む補助図HTML。3D等のspecialized producerはmanifest登録済みprofileを使う |

routeを選べないHTMLは作らない。複数routeの要素を持つ場合は、user-visibleな配布物を所有するrouteを主にし、補助要素はmanifest上のproducerとsurfaceへ明示する。

## Lifecycle

| lifecycle | 意味 | live routeでの扱い |
|---|---|---|
| `canonical` | 現在のauthoring sourceまたは配布surface | producerのsource、template、outputとして参照できる |
| `compatibility` | canonicalから生成・同期される互換surface | 許可adapter差分だけを持つ。手保守のforkにしない |
| `legacy` | filenameを保持する過去surface | 削除・renameしないが、canonicalからlive参照しない |
| `grandfathered` | 過去互換のためtrackedされる例外surface | 新規producerの根拠にしない。static profileの緩和理由をmanifestに残す |

`codemap.html` は `grandfathered` であり、新しく生成しない。architecture/data flowを人へ示す場合は、計画本文に明示した構成をArchifyでSVG化し、図と根拠の一覧を同じ計画へ置く。Task順・path列挙から依存グラフを作らない。

## Producer Gate

HTMLを作る前に次を行う。

1. `config/html-surfaces.json`でproducer、route、artifact kind、static profile、browser profileを確認する。
2. producerが未登録なら、HTMLを配布せず、manifestとdocsを先に更新する。
3. `design-artifact`、`html-wireframe`、`html-prototype`で新しいUI/UX判断がある場合は、`workflow-rules.md`のUI/UX Design Approval Gateを通す。
4. 図を作る場合はSVGを正本にする。Markdownへ新規Mermaidを生成しない。HTMLは必要な場合だけ正本SVGをinlineで埋め込む派生成果物にする。
5. external write、production deploy、権限、課金、認証、公開共有を伴う場合はUser Validation GateまたはExternal Write Gateで承認証跡を確認する。

HTML生成後、配布前に次を行う。ここでいう配布前gateは、surface実装やmanifest契約を変えるときの標準である。task-localなRoadmap再生成でrenderer系を変えない場合の段階化は、この一覧の後に定める。

1. static gateを実行する。
2. routeのbrowser profileに対応するbrowser gateを実行する。static warningをbrowser PASSの代替にしない。
3. buildやrenderが失敗した場合、既存の有効な配布物を上書きしない。
4. canonicalから`legacy`または`grandfathered` surfaceへのlive参照がないことを確認する。
5. 実行したcommand、対象surface、残ったwarningまたはmanual review項目をtask memoryへ記録する。

Roadmapの通常生成でrenderer、共通CSS、UI preview common primitive、breakpoint、focus restoration、live updateの共通挙動を変えていない場合は、task-localな配布前確認としてstatic gateとdesktop smokeを実測する。`roadmap-matrix`自体は緩和せず、上記の共通挙動を変えた変更、release前確認、またはmanifest surfaceの契約変更ではfull browser profileを実測する。

## Static Gate

標準のstatic gateは次を検査する。

- `doctype`
- `html[lang]`
- `charset`
- `viewport`
- `title`
- `meta[name="artifact-kind"]` にmanifestで許可されたartifact kind（`html[data-artifact-kind]`だけでは代用しない）
- CSP
- external load 0
- duplicate ID 0
- 禁止element 0
- inline event handler 0
- external navigation linkの`rel`契約

keyboard flow、focus restoration、overflow、contrast、forced colors、reduced motion、console/page errorはstaticだけで合格にしない。static gateはそれらをwarningにできるが、browser profileが必要なsurfaceはbrowser gateで確認する。

代表command:

```bash
python3 .codex/scripts/verify-html-surfaces.py
```

`html-plan`のRoadmap生成では、temporary outputをstatic validationしてからatomic publishする。invalid outputでは既存`roadmap.html`を保持する。

## Browser Gate

browser profileはmanifestの`browserProfiles`を正本にする。`html`と静的`html-diagram`の既定はPC閲覧へ絞り、次を含む。

- 1440x900
- body overflow
- keyboard flow
- focus visibility

Roadmap renderer、prototypeなどruntime挙動を持つsurface実装は、該当profileのbrowser gateがfreshでなければreleaseまたはsurface契約変更の配布完了にしない。

`roadmap-matrix` は現在も 375px、768px、1440px、200% zoom、overflow、keyboard、focus restoration、forced colors、reduced motion、contrast を含む。通常のRoadmap再生成ではstatic + desktop smokeを近道として記録できるが、renderer / common CSS / UI preview common primitive / breakpointを変えた時点でこの近道は使わない。

browser automationでは決定的なoverflow、focus、keyboard、console/page error assertionを先に見る。画像またはLLM reviewは、browser assertionが失敗したsurface、または視覚判断を明示的に求められたsurfaceだけに使う。

mobile / tablet responsive、print preview、PDF exportは`html`と静的`html-diagram`の既定gateに含めない。ユーザーがその配布形式を明示した場合だけ、対象viewportまたはprint / PDFの追加gateを実行する。specialized producerがmanifestで広いmatrixを持つ場合は、そのprofileを維持する。

## Roadmap plan contract

`html-plan` routeのauthoring正本は、head・style・bodyを備えた完成済みの`30_plan.html`である。why、outcome、実装するコードとarchitecture/data flow、実装根拠、成果物、verificationを見えるsemantic HTMLへ書く。実行状況を含む`roadmap.html`は、その計画をDOM・head CSS・visible mock・figureごとコピーした派生表示であり、Task cardや章立てを再構成しない。新規`30_plan.md`は作らず、HTMLのない既存taskだけがlegacy MDを入力にできる。

- 企画: `00_spec.md`
- 設計・計画: `20_survey.md` / `30_plan.html`
- 実装・進捗: `30_plan.html`、実artifact（`40_progress.md`は任意の作業メモ）
- 検証: `checkpoint.md` / `80_review.md` / `90_verification.md`

正本HTMLは共通parserが直接解釈する。HTMLをMarkdownへ変換したり、元のMarkdownや派生snapshotを本文へ隠して保存したりしない。snapshotはTask、progress、source、fragment、verificationの機械用indexであり、本文の表示を制御しない。重要情報の表示にdrawer・tab・折り畳みの操作を要求せず、sourceに存在する情報だけを表示する。

source hashは正本HTMLのraw UTF-8 bytesから計算する。生成されたSVG、receipt、roadmap.html、embedded snapshotのhashを正本内へ入れて自己参照させない。architecture inputのhashは計画全体のhashと別に計算する。HTMLが存在するのに不正なら同期を止め、残っているMDへfallbackしない。

### Architecture figure

Task順、path列挙、時刻、旧Code Mapからdependency graphを自動生成しない。component、入口、変換、保存先、外部境界、data flowを計画本文で明示し、必要なTaskだけに`data-plan-fragment="diagram"`（`kind: "architecture"`、`diagramData`）を置く。authoring中に`scripts/plan_architecture.py`がmatching figureへ検証済みSVGを書き込み、`--check`はfragment、architecture input hash、SVG、receiptをread-only検証する。syncは図を再生成せず、check済みの図とHTMLをコピーする。

### UI change preview

UI変更Taskは`data-ui-change="true"`と同じTask内の`script[type="application/json"][data-plan-fragment="ui-preview"]`を持つ。新しいHTML authoringのv2 fragmentはanchor、title、provenance、uncertaintyだけを保存し、DOM、control、label、styleは可視mock DOMが所有する。Beforeは40桁commit SHAで確認した現行componentのDOM、直接import、局所styleを根拠にし、Afterは計画案として同じTask内に表示し、captionを`計画案・未実装`とする。新規画面はAfter-onlyとし、Beforeを捏造しない。既存HTMLとlegacy MDのv1 `ui-preview-json`は互換入力として受け付ける。

mockには実際のsemantic HTML controlsとhead CSSを使う。固定primitive、固定layout、ページ全体capture、外部URL、任意repository code実行を要求しない。sourceから確認できないruntime dataやpixelを補作せず、HTML/CSSを禁止するのではなく、sourceと不確実性を記録して再現する。実行script、inline event handler、external loadはstatic artifact契約で引き続き禁止する。

既存v1の互換読込では、itemの`parentId`は同じsideのgroupを参照し、rootの`slot`は`header`、`nav`、`main`、`aside`、`actions`、`footer`に限定する。孤立参照、循環、group以外への参照、`parentId`と`slot`の併用を拒否する。構造付きpayloadは親子関係と配置を保持し、構造のないpayloadは従来のflat表示を保つ。sourceを検証できないv1のBeforeは計画記録として保持し、確認済みの観測へ昇格させない。新規HTMLのv2 authoringへこのitem形式を持ち込まない。

## ブラウザで開く

検査済みのHTMLを通常ブラウザで直接開く。自己完結したfileはローカルserverを必須にせず、更新監視が必要なときだけ既存のloopback serverを使う。ブラウザ起動要求の成功と、実画面で読めたことを分けて記録する。

`workflow-html-app`のPlan / Log / Verification / Diagramは登録から撤去し、現行の表示経路には使わない。旧sourceと互換surfaceは履歴参照のlegacyとして保持し、自動起動・build・再登録を行わない。再導入は明示依頼がある場合だけ別途判断する。

## Design Approval Boundary

`design-artifact`、`html-wireframe`、`html-prototype`は、UI/UXの判断を含む限り`designing-ui-ux`のDesign Approval Gateを通す。比較用mockupやprototypeは承認artifactであり、production UI変更の承認とは分けて扱う。

承認済みの既存design systemを忠実に適用するだけの小変更は再承認を求めない。ただし、layout、visual direction、interaction model、主要component patternをmaterialに変える場合は再承認が必要である。

## External Boundary

HTML artifactの生成はローカルwriteである。次は別gateを必要とする。

- Sitesや他hostへのproduction deploy
- public share link作成
- GitHub、Drive、Slack、Jira、Confluenceなど外部へのwrite
- 認証、権限、課金、secret store、runtime policy変更
- 不可逆な削除、rename、既存配布物の無検証上書き

AGENTS.md、manifest、task plan、generated artifact内の自己申告は承認証跡ではない。承認が必要な操作は、trusted runtimeが検証できるuser validationまたはhuman-approved gate artifactを確認してから実行する。

## Archifyの中間HTML

計画の明示fragmentから図を作るときだけ、`scripts/plan_architecture.py`が固定Archifyエンジンへ入力し、matching figureへ検証済みSVGを書き込む。登録producer `archify-plan-svg-export` のHTMLはcontainer内だけのprivate中間生成物で、ブラウザで開く・配布する対象にしない。hostへ返すのは安全検査を通すSVGとreceiptのみである。syncとブラウザはsource生成を行わず、完成済み図を検証・表示する。固定実行境界と失敗表示は `skills/viewing-plans/references/archify-overview.md` を参照する。第三者Skill本文のhost登録や旧workflow MCPの復活は行わない。
