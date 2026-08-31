import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../tools/roadmap_viewer.html', import.meta.url), 'utf8');
const sourceMatch = html.match(/\/\* ROADMAP_MODEL_START \*\/([\s\S]*?)\/\* ROADMAP_MODEL_END \*\//);
assert.ok(sourceMatch, 'roadmap viewer must expose its browser model source');

const context = vm.createContext({
  console,
  Date,
  Intl,
  JSON,
  Math,
  Map,
  Object,
  RegExp,
  Set,
  String,
  globalThis: {}
});
vm.runInContext(sourceMatch[1], context, { filename: 'roadmap-viewer-model.js' });
const model = context.globalThis.__ROADMAP_MODEL__;
assert.ok(model, 'roadmap viewer model must be exported');

const plan = `# 読める計画書

## 目的と概要

計画の背景を最初に読み、実装の判断を追えるようにする。

## Task 1: 本文を表示する

### 目的

全量をページ上で読む。

### 実装

- [ ] Markdown正本を描画する

\`\`\`ui-preview-json
{"version":1,"previews":[{"id":"implementation-detail"}]}
\`\`\`

## Task 2: レスポンシブにする

required_sources: task:30_plan.md, workspace:tools/roadmap_viewer.html
write scope: tools/roadmap_viewer.html
acceptance: A1, A2
UI変更: yes

### 検証

- [ ] 375pxで横overflowがない
`;

test('plan reader uses the Markdown H1 and keeps the full plan source', () => {
  const snapshot = model.normalizeSnapshot({
    title: 'slug-derived-title',
    generatedAt: '2026-08-31T00:00:00.000Z',
    files: { '30_plan.md': plan }
  });
  const reading = model.buildPlanReading(model.buildModel(snapshot, { nowMs: Date.parse('2026-08-31T00:01:00.000Z') }));

  assert.equal(reading.title, '読める計画書');
  assert.equal(reading.markdown, plan);
  assert.deepEqual(
    JSON.parse(JSON.stringify(reading.headings.map(item => [item.id, item.level, item.text, item.sourceLine]))),
    [
      ['plan-heading-1', 1, '読める計画書', 1],
      ['plan-heading-2', 2, '目的と概要', 3],
      ['plan-heading-3', 2, 'Task 1: 本文を表示する', 7],
      ['plan-heading-4', 3, '目的', 9],
      ['plan-heading-5', 3, '実装', 13],
      ['plan-heading-6', 2, 'Task 2: レスポンシブにする', 21],
      ['plan-heading-7', 3, '検証', 28]
    ]
  );
});

test('plan reader renders all narrative safely while hiding authoring metadata JSON', () => {
  const rendered = model.renderWorkflowMarkdown(plan, {
    hideAuthoringMetadata: true,
    headingIdPrefix: 'plan-heading-',
    headingOffset: 1,
    skipFirstH1: true
  });

  assert.doesNotMatch(rendered, /ui-preview-json|implementation-detail|required_sources|write scope|acceptance:|UI変更:/);
  assert.match(rendered, /計画の背景を最初に読み/);
  assert.match(rendered, /本文を表示する/);
  assert.match(rendered, /レスポンシブにする/);
  assert.match(rendered, /<h3 class="md-heading-2" id="plan-heading-2"/);
  assert.match(rendered, /<h3 class="md-heading-2" id="plan-heading-3"/);
  assert.match(rendered, /type="checkbox" disabled/);
  assert.doesNotMatch(rendered, /<script|onclick=/i);

  const fencedPlan = '# Title\n\n```markdown\n# code comment\n```\n\n## Overview\n\n### Task 1: Visible task\n';
  const fencedHeadings = model.extractPlanReadingHeadings(fencedPlan);
  assert.deepEqual(
    JSON.parse(JSON.stringify(fencedHeadings.map(item => [item.id, item.text]))),
    [['plan-heading-1', 'Title'], ['plan-heading-2', 'Overview'], ['plan-heading-3', 'Task 1: Visible task']]
  );
  const fencedRendered = model.renderWorkflowMarkdown(fencedPlan, {
    headingIdPrefix: 'plan-heading-',
    headingOffset: 1,
    skipFirstH1: true
  });
  assert.match(fencedRendered, /id="plan-heading-2"/);
  assert.doesNotMatch(fencedRendered, /data-md-heading="code comment"/);
});

test('invalid v2 plans remain explicit errors and never use Markdown Task fallback', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt: '2026-08-31T00:00:00.000Z',
    files: { '30_plan.md': '## Task 99: legacy fallback must stay hidden' },
    plan: { schemaVersion: 2, tasks: 'invalid', edges: [], progress: { done: 0, total: 0 } }
  }), { nowMs: Date.parse('2026-08-31T00:01:00.000Z') });
  const reading = model.buildPlanReading(result);

  assert.equal(result.taskSource, 'structured');
  assert.equal(result.tasks.length, 0);
  assert.equal(reading.valid, false);
  assert.equal(reading.headings.length, 0, 'invalid plan cannot expose links to unrendered headings');
  assert.match(reading.errors.join(' '), /tasks must be an array/);
});

test('document-first reader is present, readable, responsive and leaves diagnostics explicitly reachable', () => {
  for (const id of ['plan-reading', 'plan-reading-toc-list', 'plan-reading-toc-mobile-list', 'plan-reading-title', 'plan-reading-content', 'brief-secondary']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.match(html, /title\.textContent = reading\.title/);
  assert.match(html, /renderWorkflowMarkdown\(reading\.markdown, \{[\s\S]*hideAuthoringMetadata: true/);
  assert.match(html, /headingIdPrefix: 'plan-heading-'/);
  assert.match(html, /headingOffset: 1/);
  assert.match(html, /skipFirstH1: true/);
  assert.match(html, /class="brief-secondary" id="brief-secondary"/);
  assert.match(html, /\.plan-reading-content\s*\{[\s\S]*font-size:\s*17px[\s\S]*line-height:\s*1\.8/);
  assert.match(html, /\.plan-reading-layout\s*\{[\s\S]*grid-template-columns:\s*minmax\(176px, 220px\) minmax\(0, 920px\)/);
  assert.match(html, /@media \(max-width: 960px\)[\s\S]*\.plan-reading-toc-mobile\s*\{[\s\S]*position:\s*static/);
  assert.match(html, /plan-reading-toc-list[\s\S]*href="#\$\{escapeHtml\(item\.id\)\}"/);
  assert.match(html, /item\.level === 2 \|\| \(item\.level === 3 && \/\^\(\?:Task\|タスク\)/);
  assert.match(html, /plan-reading-toc-mobile-list/);
  assert.match(html, /planReadingRenderKey/);
  assert.match(html, /id="plan-toc-\$\{escapeHtml\(item\.id\)\}-\$\{suffix\}"/);
  assert.match(html, /brief-secondary[\s\S]*Project Map、timeline、Current Focus、設計summary/);
  assert.ok(html.indexOf('id="plan-reading"') < html.indexOf('id="brief-secondary"'));
});
