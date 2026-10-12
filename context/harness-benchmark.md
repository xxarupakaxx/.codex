# Harness比較runner

このrunnerは、I03、I04、必要な場合はI05を、個人データと既存認証から隔離した8件の合成fixtureで比較する。比較できない状態を成功として補完せず、未確認、非対応、拒否、中断、品質不合格を結果へ残す。

## 実行境界

- 1候補は、8 fixture × baseline/candidate × 3回 × 2 runtimeの96 runである。3候補とsmoke 2件を合わせた上限は290 run。
- 1 runは停止猶予を含め600秒、run root全体は最初の実行から49時間、retryは0回である。Codexはtool event 40件、Claudeは20 turnを上限とする。Claudeの出力は当該invocationのassistant usageで8,192 token超を観測した時点で失敗にし、call単位usage欠測も成功にしない。final `modelUsage`はresume前を含み得るsession累積として別記録し、当該runの上限判定には使わない。
- stdoutは16 MiB、stderrは16 MiB、1行は1 MiBまで保存する。workspaceは128 file、256 entry、合計16 MiB、1 file 4 MiBまでとする。通常fileとdirectory以外、公開mode、上限超過を拒否する。子processにはfile size、open file、CPU、core dumpのresource limitも課す。終了時は残存process groupにもTERMを送り、5秒後にKILLする。
- `/private/tmp/harness-benchmark-<run-id>`配下でrunnerが作るdirectoryは0700、fileは0600にする。runner管理treeは件数上限付きの`lstat`で再帰検査し、root外参照、symlink、特殊file、公開mode、runner以外が所有する既存JSONを拒否して自動削除しない。モデルrunの`TMPDIR`は当該workspace内のprivate directory、非モデルprobeの`TMPDIR`はruntime別のRUN内private directoryへ固定する。
- 子processへ渡す環境変数は固定した`PATH`、locale、`TERM`、`SHELL`と、値を変えない`HOME`に限定する。固定値と`HOME`の非可逆hashはmanifestへ保存し、境界ごとに照合する。Codexには`CODEX_HOME`と`CODEX_SQLITE_HOME`、ClaudeにはCLI状態用の`CLAUDE_CONFIG_DIR`とharness metadata用の`CLAUDE_HOME`をRUN配下へ明示する。handoverのmemory、task memory、plan、hook observationのstate、suggestion、transcriptも専用`CLAUDE_HOME`配下へ固定する。`HOME`を直接参照する未管理hookは隔離済みと扱わない。`HOOK_OBSERVATIONS_SCRIPT`、`HOOK_OBSERVATIONS_METRICS_SCRIPT`、`SESSION_HANDOVER_CORE`は検査済みsourceがbundleへ固定され、実読書先をprobeできるまで設定せず、hook比較をHOLDする。
- Codexは専用configのpermission profileでrootをdeny、minimalをread、workspaceだけをwriteにし、networkを無効化する。Claudeは`--restricted`、空のstrict MCP設定、unsandboxed commandを拒否する公式sandbox設定を使う。Bashはfixtureが要求する完全一致commandだけをscoped `--allowedTools`へ登録し、file toolとともに`dontAsk`で未知操作を拒否する。sandboxはlive HOME、RUN内の両runtime state、結果、log、bundle、fixture、別workspaceをread/writeともdenyし、現在のworkspaceだけをread/writeへ戻す。

## 準備入力

`prepare`には、runtime能力の証拠と比較bundleが必要である。能力証拠は、CodexとClaudeの`compact`、`resume`、`live_home_read_isolation`ごとに、次の値を持つJSONである。

```json
{
  "source_path": "/absolute/path/to/reviewed-runtime-evidence.md",
  "codex": {
    "compact": {
      "runtime_version": "<statusと一致する版>",
      "event": "<公式event名>",
      "trigger_method": "<公式CLI経路>",
      "state": "unknown",
      "source_hash": "<source_pathの検証済みSHA-256>"
    }
  }
}
```

実ファイルでは、両runtimeの3能力をすべて記載する。`state`は`observed`、`unknown`、`unsupported`のいずれかとする。runnerは`source_path`の実hashを検証済みpolicyと照合し、手入力した`observed`では能力を昇格できない。新しい実測証拠を採用する場合は、独立レビュー後にrunnerのpolicyも更新し、新しいrun rootを準備する。prompt内の文字列、mock、小さなsmokeはnative compactの発火証拠にしない。

比較bundleは`/private/tmp/harness-comparison-<id>/manifest.json`に置く。各candidate、runtime、baseline/candidate条件について、固定した`baseline_commit`、`source_dirty: false`、通常fileの`source`、RUN内の`target`、実SHA-256、`factor`、次のclassを記載する。

- `workspace_instruction`: `AGENTS.md`または`CLAUDE.md`
- `runtime_settings`: `overrides.json`または`settings.json`
- `hook_adapter`: `hooks/`配下。正式に参照する`runtime_settings`も必要
- `host_fixture_helper`: `host/handover_core`、`host/observations_core`、`host/quiet_run`の3 file。baseline/candidateで同じ検査済みbytesを使い、差分は持たせない

runnerはbundleをRUNへ固定コピーし、条件間のtarget集合、固定file、候補factor、実hashを検査する。host modeでは、3件すべてが`host_fixture_helper`で、target集合が上記3 fileと完全一致する場合だけ受理する。`workspace_instruction`、`runtime_settings`、`hook_adapter`、重複、余分なfileを同じbundleへ混在できない。manifestは1 MiB、bundleは96 file、1 file 4 MiB、合計16 MiBを上限とし、hard linkも拒否する。baseline/candidateへ渡すprompt本文は同一にし、全runのprompt SHA-256をmanifestへ固定して実行直前に照合する。実装効果かどうかは固定controlの有無ではなく、実際に変化するfactorのclassで決める。`prepare`で指定したruntime実行fileはabsolute realpathとSHA-256を固定し、env shebangの場合は実interpreterもabsolute pathとSHA-256で固定する。`status`と各run直前に同じ実体・interpreter・versionであることを再確認する。Codex permission configもexact bytesとSHA-256をmanifestとconfig epochへ固定する。live home、dirty repository、認証・session・DBをsourceにできない。`workspace_instruction`だけのbundleは`instruction-only`となり、実装効果比較を開始できない。hookは公式sandbox外で動く可能性があるため、`hook_adapter`を含むbundleは`hook-unconfined`として、正式な隔離証拠が加わるまでモデル起動前に停止する。runnerと既存metrics adapterの実SHAもmanifestへ固定し、変更時は`--source-change-reason`を記録して新しいrootを準備する。

```sh
RUN=/private/tmp/harness-benchmark-RUN2
CAP=/private/tmp/harness-capabilities-v1.json
BUNDLE=/private/tmp/harness-comparison-v1/manifest.json
python3 ~/.codex/scripts/harness_benchmark.py prepare "$RUN" --capability-evidence "$CAP" --comparison-bundle "$BUNDLE" --codex-bin /Users/yoshiki/.local/share/npm-global/bin/codex --claude-bin /Users/yoshiki/.local/bin/claude --host-node-bin /opt/homebrew/Cellar/node/25.8.2/bin/node --host-tsc-js /absolute/reviewed/typescript/lib/_tsc.js --source-change-reason initial --include-i05
python3 ~/.codex/scripts/harness_benchmark.py status "$RUN"
```

fixtureが起動するPythonもabsolute realpathとSHA-256を固定し、各境界で再照合する。`repo_tsc_once`は実TypeScript CLIを一度だけ起動する。検査済み実行fileがある場合は`prepare`へ`--tsc-bin /absolute/reviewed/tsc`を加える。env shebangの場合は固定したNodeと実tsc scriptのabsolute argvを使う。未指定時はcanned診断へ置き換えず、`typescript_cli: unsupported`としてnative比較をモデル起動前に止める。native fixtureのworkspace成果物とcommand eventだけでは、診断の実行時点と診断の再利用を証明できないため、このprimary outcomeはnative 24 runで未評価のままHOLDする。v13のhost subsetは、trusted parentが固定Node shimと実tsc JSを起動し、O_EXCL marker、実argv、終了値、raw診断hashを独立に照合する。`cli_quiet_retrieve`も、検査済み`quiet-run.py`による大量errorの保存と末尾の選択再取得を、trusted parentの実process記録から採点する。

## 専用runtimeの認証

最初の`status`は、専用runtimeが未認証なら終了コード3になり、そのfalse状態を非機密baselineとして保存する。利用者本人がrunnerの`login`経由で公式loginを新規に行う。このsubcommandは固定したruntime実体を使い、親processのAPI key、provider、profile、secure-storage overrideを渡さない。起動前にRUN内の専用0700 directoryが空で、通常directoryであり、runner所有であることを再検査し、そこへ移動してから`execve`する。呼出元のproject cwdは継承しない。既存homeの認証file、Keychain entry、token、session、DBはコピーしない。login後に`attest-login`でfalseからtrueへの遷移を記録し、再度`status`を実行する。認証値は読まず、証跡にはruntime identity、版、時刻、booleanだけを残す。

```sh
python3 ~/.codex/scripts/harness_benchmark.py login "$RUN" codex
python3 ~/.codex/scripts/harness_benchmark.py attest-login "$RUN" codex
python3 ~/.codex/scripts/harness_benchmark.py login "$RUN" claude
python3 ~/.codex/scripts/harness_benchmark.py attest-login "$RUN" claude
python3 ~/.codex/scripts/harness_benchmark.py status "$RUN"
```

`status`が表示・保存する値は、認証遷移を確認済みか、runtime版、private layout、完了件数、能力stateである。Codexはモデルを使わず、workspace内の読書き成功と、検証済みの非機密live-home markerの読取拒否も検査する。Claude 2.1.251のrestricted file境界は、現時点では`local_tested: false`として残す。Claude smokeはworkspace内の読書き成功に加え、RUN内の専用Claude config markerとcross-runtime Codex config markerの読取拒否、live HOME内の専用非機密probe pathへの書込み拒否をnative tool resultで確認する。probe pathが既に存在する場合は起動前に停止し、自動削除しない。hook、MCP、helperはBash sandbox外なので、検査済みsourceと専用pathへの配線が揃うまでhook比較を開始しない。版番号だけでは解除しない。認証値やsession本文は扱わない。

## Smokeと比較

model、effort、requested tier、固定環境、600秒のrun上限はrun rootへ固定する。partial resumeでも変更できない。Codexは固定binary・versionと完全一致の`--model`、`model_reasoning_effort` argvを確認源にできる。Claudeのmodelはassistantまたはresult eventでの一致を必須とし、effortは完全一致argvを確認源にできる。いずれもevent値が存在する場合は固定値との一致が必須で、競合や不一致を失敗にする。各runとreportへ`runtime_event`、`locked_exact_argv`などの確認源を保存する。確認済みmodelだけをmetricsへ渡し、actual tierはnative出力で観測できた場合だけ渡す。

```sh
COMMON=(--codex-model "$CODEX_MODEL" --codex-effort "$CODEX_EFFORT" --claude-model "$CLAUDE_MODEL" --claude-effort "$CLAUDE_EFFORT")
python3 ~/.codex/scripts/harness_benchmark.py run "$RUN" --smoke-only --smoke-runtime codex "${COMMON[@]}"
python3 ~/.codex/scripts/harness_benchmark.py run "$RUN" --smoke-only --smoke-runtime claude "${COMMON[@]}"
python3 ~/.codex/scripts/harness_benchmark.py run "$RUN" --candidate I03 "${COMMON[@]}"
python3 ~/.codex/scripts/harness_benchmark.py report "$RUN"
```

smokeはruntimeごとに1件ずつ実行する。Codex smokeは認証、runtime版、非通信marker probeの合格後だけ開始する。Claude smokeは認証、runtime版、restricted設定の静的確認後に、境界検証専用として一度だけ開始できる。workspace内のread/write成功と、専用credential、cross-runtime state、live HOMEへの3操作がnative tool resultで拒否されたことを同じsmokeで採点する。拒否を本文から推測しない。通常の接続smokeと境界検証を別runとして重複させない。Codex JSONLにmodelやeffortがないことだけでsmokeを失敗にせず、固定した実行file、version、完全一致argvを`locked_exact_argv`として記録する。Claude model eventの欠測は引き続きsmoke失敗にする。

比較前には両smokeの境界検証成功、実効model・effortの一致、usage経路に加え、compactとresumeの`observed`証拠、runnerに登録済みの正式trigger adapter、実装bundle、実TypeScript CLIが必要である。現在の証拠が`unknown`または`unsupported`なら、runnerはモデル通信前に理由を出して停止する。

`long_compact`は実際のcompact eventをrun内でも要求する。外部証拠が`observed`でも、証拠の`trigger_method`に対応するrunner adapterが未登録なら比較を開始しない。現在は両runtimeともadapter未登録である。`long_resume`は同じcandidate、runtime、variant、repeat、config epoch、bundle hash、session identityを持つ成功済みcompact結果だけを使い、別workspaceで完全な値を復元する。

各runはprivateな`O_EXCL` markerで一度だけ取得する。実行中の別processが持つrunは拒否し、終了したprocessの開始記録だけが残る場合は中断として確定する。完了済みrunは再実行しない。候補はI03、I04、必要な場合はI05の順で進める。native比較は前候補96件、host subsetは前候補72件の記録が揃うまで次へ進めない。source、model、effort、runtime版を変える場合は、新しいrootを準備する。

## v13 host subset

v13はnative eventを置き換えず、6件の非native fixtureだけをhost-supervised方式でも評価する。候補ごとの固定分母は、6 fixture × baseline/candidate × 3回 × 2 runtimeの72 runである。`long_compact`と`long_resume`の24 runはnative subsetとしてHOLDを維持し、host subsetの成功を96 run完了やnative発火として表示しない。

trusted parentは同じ`harness_fixture_helper.py`、同じsource、同じinterpreter、同じ結果schemaを両条件で使う。baseline/candidate間で変わる外側の値は、runner-private requestの`strategy: raw|improved`だけである。strategyはモデルへ渡すcanonical resultに含めず、prompt templateの`__HOST_MECHANISM_CONTEXT__` 1 slotへ、同じschemaのpayloadを1件だけ挿入する。bundleの3 sourceは両条件で同じSHA-256に固定し、モデルworkspaceへコピーしない。

runnerは検証済みhelper resultのcanonical bytesからslotを親側で再構成し、helperが返す別のprompt文字列を入力に採用しない。template、materialized prompt、実送信済みpromptのSHA-256とUTF-8 byte数を分け、materialized promptと実際に`run_finite`へ渡すbytesを一致させる。process起動、prompt送信、最初のstructured model responseを独立に記録し、`model_received_helper_result`はstructured responseを観測した場合だけtrueにする。起動失敗、setup timeout、response前の終了ではfalseである。helper開始からmodel終了までのend-to-end時間も、helper時間とmodel時間とは別に全terminal resultへ記録する。

helperはtrusted parent processへ直接importし、helper自身をsubprocessとして起動しない。実processとして起動できるのは、固定operation manifestに完全一致した機構commandだけである。manifestとledgerはabsolute argv、正規化argv、hash、cwd、入力、固定env、許可終了値、timeout、CPU・open file・process数を含むresource上限、検査済みsource identityを持つ。直接起動数と、quiet logまたはTSC markerで確認した機構内の子起動数を分けて記録する。I03は実`quiet-run.py`による保存と再取得を扱う。I04のrawは固定したClaude baseline commitの`stop-save-handover.sh`と`session-start-inject.sh`の実bytesを、合成`05_log.md`、`30_plan.md`、transcriptへ順に実行し、生成したHANDOVER全文と注入stdoutを親が照合する。candidateは実handover coreによるinit、save、loadと証拠失効を扱う。モデルへ渡す前に時刻と物理pathだけをlogical値へ正規化し、両条件の必須factsを構造比較する。I05は実observations core、固定Node shim、RUN内へ固定exportした実tsc JSによる診断1回とfailure resetを扱う。primary counterはrendererの申告値を採用せず、別のcalculatorがraw command ledger、終了値、完全なprivate log、reset直後のstate snapshot、O_EXCL marker、診断hashから再計算する。TSC markerはrun、task、nonce、slot、argv、shim・Node・tscのSHA-256、終了値、診断hashを親operationへ結合する。両者の不一致、余分なmarker、source drift、子processの回収不能はモデル起動前の失敗である。

helper process全体は120秒、個別commandは30秒、retryは0回である。stdoutとstderrは各16 MiB、canonical requestとresultは各256 KiB、生成fileは64件、1 fileは4 MiB、生成合計は16 MiBを上限にする。macOS sandboxでnetwork、live HOME、`/private/tmp`全体をdenyした後、当該runのworkと検査済みsourceだけを許可する。HOMEは置き換えずidentityだけを照合し、子環境は固定PATHとlocaleに限定してparentのcredential、provider、profile、proxy、preloadを渡さない。I04の実path、canonical marker、artifact hashはprivate evidenceだけに保存し、モデルへ渡すcontextはlogical pathと検証済み必須factsから構造化して再生成する。raw controlはbaselineのCodex `51ee53e`、Claude `7152ca3`、計画SHA、埋込みcontrol blob SHAへ結合する。失敗、欠測、上限超過、source driftはclaimへ記録し、最終treeの予約込み検査後に、返却resultと同じhashを持つterminal ledgerを一度だけ確定する。状態は`pre_model_failed`となり、当該pairをモデル起動前に停止する。残りの同candidateは`pending_helper_blocked`として残す。

host subsetは、専用loginとruntime別隔離smokeが完了した後、次のように候補ごとに実行する。現時点ではloginとsmokeを実行していないため、コマンドは再開手順であり、実行済み証拠ではない。

```sh
python3 ~/.codex/scripts/harness_benchmark.py run "$RUN" --candidate I03 --host-subset "${COMMON[@]}"
python3 ~/.codex/scripts/harness_benchmark.py run "$RUN" --candidate I04 --host-subset "${COMMON[@]}"
python3 ~/.codex/scripts/harness_benchmark.py run "$RUN" --candidate I05 --host-subset "${COMMON[@]}"
python3 ~/.codex/scripts/harness_benchmark.py report "$RUN"
```

各host runは`helper_mechanism_observed`、`model_received_helper_result`、`task_outcome_passed`を別々に記録する。一般taskの成功やhelper機構の成功だけでは、モデルが結果を受け取ったことや課題を解決したことにしない。helperのwall/CPU/process数、request・operation input、operation output、model result、private raw bytesはmodelのelapsed、token、tool、USDと分けて記録する。report schema 5は候補ごとにhost 72件とnative 24件を別分母で集計し、target fixtureは機構観測を期待数と照合し、neutral fixtureはhelper観測の期待数を0としてcall 0を照合する。host探索選別は、72件すべてのpairが成功分類まで完了し、usage、tool、outcomeが100% qualifiedで、runtimeごとのtargetとneutralの成功件数がそれぞれ減らず、品質・境界違反が0件で、target input token中央値が10%以上減った場合だけ通過する。費用coverageやactual tierの欠測はUSDをNAにして本採用をHOLDするが、上記の探索指標を一律に無効にしない。`pre_model_failed`はrun記録へ残してもcomplete pairへ数えない。`native_effect: false`と`adopted: false`は固定し、host subsetは探索証拠として本採用判定に使わない。

v13の変更量目標は、runner統合60〜100行、runner test 80〜140行、helper 400〜500行、helper test 240〜320行、config 0件だった。実測は、runnerが2,636 physical行、1,795 AST statementで、v13差分はphysical純増814行、AST statement純増468件、diffは+862/-48行である。runner testは1,242 physical行、1,029 AST statementで、physical純増685行、AST statement純増533件、diffは+688/-3行だった。新規helperは1,414 physical行、949 AST statement、helper testは542 physical行、475 AST statementである。上限との差は、runner統合physical +714行、AST +368件、runner test physical +545行、AST +393件、helper physical +914行、AST +449件、helper test physical +222行、AST +155件となり、4 pathすべてが25%を超える。config追加は0件である。

runnerの増分は、72件と24件の分母分離、host専用bundleの排他検査、materialized・sent promptのhashとbyte数、process起動・入力送信・structured responseの三段階、pre-model failureのterminal記録、end-to-end時間、探索selection gateを既存のrun/report lifecycleへ接続するために必要だった。helperは、独立counter、OS sandbox、有限process回収、durable terminal、source identity、固定baselineの全文生成・注入、I04のlogical context、TSC marker結合、reset snapshotを同じ信頼境界で検証する。両testの超過は、launch failure、欠測coverage、source drift、counter偽装、全candidateと8 fixtureのneutral組合せを削らずに固定するために生じた。この設計は、大きな2つのtrusted moduleを同時に確認する保守負担があり、prompt・result・report schemaの変更には両moduleの再レビューが必要になる。次版では、認証・モデル実行・native fixtureをhelperへ移さず、report集計とprompt provenanceを独立したreview済みmoduleへ分け、重複する負例をparameter化する余地がある。分割は新しい計画と開始審査を通すまで行わず、安全処理や負例を行数調整のために削除しない。この超過は目標の変更ではなく、v13だけの設計varianceとして独立完了レビューの対象にする。

## 結果の判定

`results/report.json`は、candidate × runtime × variantごとに期待数24を固定分母として、fixture × repeatのbaseline/candidate pairを保存する。I03のquiet失敗・保存済み結果取得とI04のgate確認は、合成scriptのcounterと正規化したnative command argvの完全一致が各1回のときだけ品質合格にする。I05は固定した実TypeScript CLIのnative command argvが1回で、機能testも通る場合だけ合格にする。`echo`などにcommand文字列を含めただけでは合格しない。部分実行を100%として表示せず、全pairの完了と各metricsの`coverage.<metric>.qualified`、scopeを別々に判定する。tool callが0件でも、collectorが0件を完全観測した場合は有効である。

input tokenはusage、tool回数はtool_calls、終了分類はoutcome、USDはcostとoutcomeの資格に加え、親子を含むtop-level `comparison_qualified`が24件すべて揃った場合だけ`estimated_usd_with_subagents`から集計する。ClaudeはAgent toolを許可せず空のMCP設定を使うため`includes_children=no`、Codexは子実行を否定する正式証拠がないため`unknown`としてusageと費用を保留する。fixtureごとの3 pairは差分の中央値と範囲を、repository・CLI・longのtask群は期待数と終了分類を保存する。actual tierまたは費用coverageが不明でも、条件を満たすinput/tool指標まで一律に無効にしない。成功0件または費用欠測時の成功単価はNAである。10%減は探索候補の選別にだけ使い、本採用の根拠にしない。

各runは`configured`、`fired`、`local_tested`、`effective`、`adopted`を分けて記録する。一般taskの成功だけでは候補固有の効果を観測したことにしない。候補runtimeの24件すべてで登録済みのnative effect evidenceが確認され、全pairのusage、tool_calls、outcome、inclusive cost coverageが揃い、candidateの成功件数がbaseline以上で必須品質違反が0件の場合だけ`adoption_gate.eligible`をtrueにできる。actual tierや親子費用が欠測なら、input/toolの探索結果は表示しても採用判定はHOLDする。現時点ではeffect adapter未登録のためfalseである。採用判断と本番反映はrunnerの責務外である。
