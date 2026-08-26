import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(resolve(root, path), 'utf8');

test('commit skill binds a tool-free Fast draft to the exact staged snapshot', () => {
  const skill = read('skills/commit/SKILL.md');
  for (const marker of [
    'git_delivery_contract.py staged',
    'Fast class',
    'toolなし',
    'DRAFT_STALE',
    'git commit --file',
    'exact staging',
    'draft_delivery_message.py',
  ]) {
    assert.ok(skill.includes(marker), `missing commit marker: ${marker}`);
  }
  assert.doesNotMatch(skill, /^git add -A|cat <<|\$\(cat/m);
});

test('PR skill separates evidence-bound drafting from approved external write', () => {
  const skill = read('skills/pr/SKILL.md');
  for (const marker of [
    'git_delivery_contract.py range',
    '--body-file',
    '--base',
    '--head',
    'gh auth status',
    'verified approval evidence',
    'DRAFT_STALE',
    'draft_delivery_message.py',
  ]) {
    assert.ok(skill.includes(marker), `missing PR marker: ${marker}`);
  }
  assert.doesNotMatch(skill, /^gh pr create --dry-run|cat <<|\$\(cat/m);
});

test('active helper guidance resolves the canonical Fast class without legacy slugs', () => {
  const paths = [
    'context/team-run.md',
    'skills/team-run/SKILL.md',
    'skills/create-subagent/SKILL.md',
    'skills/create-subagent/references/agent-template.md',
  ];
  for (const path of paths) {
    const content = read(path);
    assert.doesNotMatch(content, /gpt-5\.4-mini/, `${path} retains legacy mini routing`);
    assert.match(content, /Fast class/, `${path} must defer to Fast class`);
  }
});

test('delivery draft artifact and trust boundary are documented', () => {
  const memory = read('context/memory-file-formats.md');
  const routing = read('context/agent-team-routing.md');
  for (const marker of ['### Delivery Draft Input', '### Delivery Draft Output', 'claim_references']) {
    assert.ok(memory.includes(marker), `missing artifact marker: ${marker}`);
  }
  assert.match(routing, /Fast worker.*文案/);
  assert.match(routing, /Git\/GitHub tool/);
  assert.match(routing, /親.*external write/);
});

test('legacy command and prompt entrypoints are thin canonical shims', () => {
  for (const [path, canonical] of [
    ['commands/commit.md', 'skills/commit/SKILL.md'],
    ['prompts/commit.md', 'skills/commit/SKILL.md'],
    ['commands/pr.md', 'skills/pr/SKILL.md'],
    ['prompts/pr.md', 'skills/pr/SKILL.md'],
  ]) {
    const content = read(path);
    assert.match(content, /compatibility shim/);
    assert.ok(content.includes(canonical), `${path} does not delegate to ${canonical}`);
    assert.doesNotMatch(content, /cat <<|git add <|--body \"\$\(/);
  }
});
