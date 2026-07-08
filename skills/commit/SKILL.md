---
allowed-tools: Bash(git:*)
argument-hint: [--push]
description: 変更をコミット
---

# /commit コマンド

変更をコミットします。`--push` 引数でpushも実行。

## 引数

- `--push`: コミット後にpushする（デフォルト: false）

## 実行手順

### 1. 現在の状態確認

```bash
git status
git diff --stat
git log --oneline -5
```

### 2. コミットメッセージの決定

変更内容を分析し、git-cz形式でコミットメッセージを作成:

- prefix: feat/fix/docs/refactor/test/chore など
- 絵文字なし
- prefix以外は日本語
- 例: `feat: ユーザー認証機能を追加`

### 3. ステージング

```bash
git add <files>
```

NOTE: CLAUDE.mdがglobal gitignoreされている場合は `git add -f` で追加

NOTE: rebase中にコンフリクトを検出した場合は `git status` で `UU` ファイルを特定し、base/ours/theirsを比較して両ブランチの意図を統合してから `git add` → `git rebase --continue` で完了する（出典: memories/rollout_summaries/2026-06-18T04-14-24-sLqw-git_pull_conflict_resolved_and_merged_to_main.md「Task 1」）。

### 4. コミット

```bash
git commit -m "$(cat <<'EOF'
<コミットメッセージ>
EOF
)"
```

### 5. push（引数に --push がある場合のみ）

$ARGUMENTS に `--push` が含まれる場合:

```bash
git push
```

### 6. 結果の報告

- コミットハッシュ
- pushした場合はその旨

## 実績由来の知見

- `git push` が `Repository not found` を返したら、repo URLを疑う前に `gh auth status` でactive accountとremote ownerの一致を確認する（仕事repoと個人repoでアカウントを使い分けている環境では、切替忘れによる失敗が繰り返し発生している）。認証transportの片方が死んでいる場合はもう片方へ切替える（SSH疎通は `git ls-remote git@github.com:<owner>/<repo>.git` で確認、HTTPSへ戻すなら `gh auth setup-git`）（出典: memories/rollout_summaries/2026-06-23T06-22-45-7rsk-plugin_routing_sot_team_run_push.md「Task 2 Failures」、memories/rollout_summaries/2026-06-23T01-00-42-uYoW-claude_to_codex_config_sync_and_dotfiles_push.md「Task 2 Failures」、memories/rollout_summaries/2026-06-26T09-36-25-4B26-release_db_migration_sync_develop_before_pr3049.md「Task 1 Preference signals」）
- sandbox内で `git commit` / `git worktree add` / rebase が `.git/index.lock` 等のpermissionエラーで失敗したら、コミット内容を変えずescalated permissionsで再実行する（複数rolloutで再発した既知事象）（出典: memories/rollout_summaries/2026-06-23T06-22-45-7rsk-plugin_routing_sot_team_run_push.md「Task 2 Failures」）
- ユーザーがpushを指示している作業（設定・docs含む）はremoteへのpush完了までがdone。進捗報告より先にpushを完了させる（出典: memories/rollout_summaries/2026-06-23T01-00-42-uYoW-claude_to_codex_config_sync_and_dotfiles_push.md「Task 1/2 Preference signals」）
