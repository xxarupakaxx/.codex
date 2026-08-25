import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const testsDir = dirname(fileURLToPath(import.meta.url));
const skillPath = resolve(testsDir, '../skills/pr-review/SKILL.md');
const contractPath = resolve(testsDir, '../skills/pr-review/references/review-contract.md');
const skill = readFileSync(skillPath, 'utf8');
const contract = readFileSync(contractPath, 'utf8');

test('skill keeps a compact model-invoked entrypoint', () => {
  assert.match(skill, /^---\nname: pr-review\ndescription: .+\ncontext: fork\n---/);
  assert.ok(skill.split('\n').length <= 200, 'SKILL.md must stay within 200 lines');
});

test('progressive disclosure target exists and is mandatory', () => {
  assert.ok(existsSync(contractPath));
  assert.match(skill, /`references\/review-contract\.md`を全文読み/);
});

test('review is read-only and separates all write actions', () => {
  assert.match(skill, /read-only checker/);
  for (const action of ['コード修正', 'review comment', 'approve', 'commit', 'push']) {
    assert.ok(skill.includes(action), `missing separated action: ${action}`);
  }
  assert.match(skill, /workflows\/pr-review-loop\.js.*所有/);
  for (const writeSemantic of ['CREATE_FIX_WORK_PACKET', 'autoFix', '指摘を修正して再レビュー']) {
    assert.doesNotMatch(skill, new RegExp(writeSemantic));
  }
});

test('branch input must resolve to exactly one remote pull request', () => {
  assert.match(skill, /branchはremote PRを一意に特定できる場合だけ/);
  assert.match(skill, /PRがないbranchは`@skills\/reviewing-code\/SKILL\.md`へルーティング/);
});

test('snapshot pins base, head, merge-base and detects drift', () => {
  for (const token of ['base_sha', 'head_sha', 'merge_base_sha', 'snapshot drift', 'STALE']) {
    assert.ok(`${skill}\n${contract}`.includes(token), `missing snapshot token: ${token}`);
  }
  assert.match(skill, /base\/head SHAを再取得し、merge-baseを再計算/);
});

test('coverage ledger accounts for every changed path', () => {
  assert.match(skill, /全changed path/);
  assert.match(contract, /ledgerのpath集合はchanged path集合と完全一致/);
  for (const classification of ['human-authored', 'generated/vendor', 'binary/submodule']) {
    assert.ok(contract.includes(classification));
  }
});

test('finding gate requires a reproducible failure and counter-evidence search', () => {
  for (const field of ['failure_scenario:', 'preconditions:', 'behavior:', 'impact:', 'counter_evidence_checked:', 'verification:']) {
    assert.ok(contract.includes(field), `missing finding field: ${field}`);
  }
  assert.match(skill, /guard、caller、test/);
});

test('unproven candidates cannot become findings', () => {
  assert.match(skill, /findingへ昇格させず/);
  assert.match(contract, /context不足 \| question/);
});

test('reviewer routing is risk based rather than fixed fan-out', () => {
  assert.match(skill, /最小reviewer/);
  assert.match(skill, /起動・省略理由/);
  assert.doesNotMatch(skill, /コアレビューアー（常時起動）/);
  assert.match(skill, /独立reviewerまたはhuman gateが必須/);
  assert.match(skill, /独立性を確保できなければ`BLOCKED`/);
});

test('untrusted fork code execution is gated', () => {
  assert.match(skill, /未信頼fork/);
  assert.match(contract, /任意コード実行/);
  assert.match(contract, /隔離環境/);
});

test('merge decisions are mechanically defined', () => {
  for (const decision of ['READY', 'NOT_READY', 'BLOCKED', 'STALE']) {
    assert.ok(contract.includes(`\`${decision}\``), `missing decision: ${decision}`);
  }
  assert.match(contract, /CRITICAL=0、IMPORTANT=0、coverage gap=0/);
});

test('legacy runtime-specific and unsafe auth instructions are absent', () => {
  for (const legacy of ['multi_agent_v1', 'AskUserQuestion', 'gh auth switch', 'claude -p']) {
    assert.doesNotMatch(skill, new RegExp(legacy.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(skill, /現在のGitHub principalを確認/);
  assert.match(contract, /`gh auth status`/);
  assert.match(contract, /別accountへの切替はユーザーが選ぶ操作/);
});

test('contract retains primary source provenance', () => {
  for (const source of [
    'docs.github.com/en/pull-requests/reference/pull-requests',
    'docs.github.com/en/rest/pulls/pulls',
    'google.github.io/eng-practices/review/reviewer/looking-for.html',
    'owasp.org/www-project-code-review-guide/',
    'csrc.nist.gov/pubs/sp/800/218/final',
    'arxiv.org/abs/2505.16339',
  ]) {
    assert.ok(contract.includes(source), `missing source: ${source}`);
  }
});
