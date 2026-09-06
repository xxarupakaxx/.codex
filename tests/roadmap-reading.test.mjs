import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const playwrightModule = process.env.CODEX_PLAYWRIGHT_MODULE || '/Users/yoshiki/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
let chromium = null;
if (existsSync(playwrightModule)) {
  try { ({ chromium } = require(playwrightModule)); } catch { chromium = null; }
}

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

導入の文章 INTRO_ONCE。<script>alert('xss')</script>

required_sources: task:30_plan.md, workspace:tools/roadmap_viewer.html
write scope: tools/roadmap_viewer.html, tests/roadmap-reading.test.mjs
acceptance: A1, A2
UI変更: yes
owner: この本文は保持する。

\`\`\`yaml
required_sources: fenced metadata stays
write scope: fenced scope stays
acceptance: fenced acceptance stays
UI変更: fenced flag stays
\`\`\`

## 目的と概要

背景の文章 BACKGROUND_ONCE。

## Task 1: 通読する

### 目的

目的の文章 PURPOSE_ONCE。

### 実装

- [ ] 実装の文章 IMPLEMENTATION_ONCE

\`\`\`ui-preview-json
{"version":1,"taskNumber":"1","previews":[{"id":"implementation-detail"}]}
\`\`\`

### 変更対象

- src/example.js

#### 実装根拠

- repo:src/example.js#build

### 成果物

- 成果物の文章 OUTPUT_ONCE

### 検証

- 検証の文章 VERIFY_ONCE

## Task 2: 目次から移動する

### 実装

- [ ] 目次の文章 TASK_TWO_ONCE

## Task 3: 狭幅で読む

### 実装

- [ ] 狭幅の文章 TASK_THREE_ONCE

## Task 4: 最終確認をする

### 実装

- [ ] 最終確認の文章 TASK_FOUR_ONCE

## 任意section

任意sectionの文章 OPTIONAL_ONCE。
`;

function fixtureSnapshot(overrides = {}) {
  return {
    version: 1,
    title: 'slug-derived-title',
    generatedAt: '2026-08-31T00:00:00.000Z',
    fingerprint: 'fixture-fingerprint',
    files: {
      '30_plan.md': plan,
      '90_verification.md': '# 検証\n\n検証本文 VERIFICATION_ONCE。',
      '80_review.md': '# Review\n\nCRITICAL 0\nIMPORTANT 0',
      '05_log.md': '## Phase 2\n\n検証を記録した。'
    },
    sourcePreviews: [{
      taskNumber: '1',
      path: 'src/example.js',
      anchor: 'build',
      language: 'javascript',
      startLine: 1,
      endLine: 1,
      code: 'const codeOnce = "<script>";',
      status: 'resolved',
      message: '',
      truncated: false
    }],
    uiPreviews: [{
      version: 1,
      taskNumber: '1',
      layout: 'list',
      title: 'Before / After',
      provenance: {
        before: { source: 'repo:src/example.js#build', baseRef: 'a'.repeat(40), observedLabels: ['Old'] },
        after: { source: '30_plan.md#Task 1' }
      },
      before: { items: [{ id: 'old', label: 'Old', kind: 'section', state: 'visible', change: 'modified' }] },
      after: { items: [{ id: 'new', label: 'New', kind: 'section', state: 'planned', change: 'added' }] }
    }],
    ...overrides
  };
}

const htmlPlanDocument = {
  format: 'html',
  title: 'HTML正本の計画',
  nodes: [
    { tag: 'h1', attrs: { id: 'html-plan-title' }, children: [{ text: 'HTML正本の計画' }] },
    { tag: 'p', attrs: { 'data-field': 'intro', class: 'dependency-narrow visually-hidden skip-link' }, children: [{ text: 'HTML本文 INTRO_HTML_ONCE。<script>alert("xss")</script>' }] },
    { tag: 'details', children: [{ tag: 'summary', children: [{ text: '補足' }] }, { tag: 'p', children: [{ text: 'details内容 DETAILS_HTML_ONCE' }] }] },
    { tag: 'p', children: [{ tag: 'a', attrs: { href: 'https://example.com/source', target: '_blank', rel: 'noopener noreferrer' }, children: [{ text: '外部出典' }] }] },
    {
      tag: 'section',
      attrs: { 'data-task-id': '1', 'data-field': 'task' },
      children: [
        { tag: 'h2', attrs: { id: 'task-1' }, children: [{ text: 'Task 1: HTMLを読む' }] },
        { tag: 'h3', attrs: { 'data-field': 'purpose' }, children: [{ text: '目的' }] },
        { tag: 'p', children: [{ text: 'HTML目的 PURPOSE_HTML_ONCE。' }] },
        { tag: 'h3', attrs: { 'data-field': 'implementation' }, children: [{ text: '実装' }] },
        { tag: 'ul', children: [{ tag: 'li', children: [{ tag: 'input', attrs: { type: 'checkbox', checked: 'true' } }, { text: 'HTML実装 IMPLEMENTATION_HTML_ONCE' }] }] },
        { tag: 'h3', children: [{ text: '成果物' }] },
        { tag: 'p', children: [{ text: 'HTML成果物 OUTPUT_HTML_ONCE。' }] },
        { tag: 'h3', children: [{ text: '表' }] },
        {
          tag: 'table', attrs: { 'data-field': 'table' }, children: [
            { tag: 'thead', children: [{ tag: 'tr', children: [{ tag: 'th', children: [{ text: '項目' }] }, { tag: 'th', children: [{ text: '状態' }] }] }] },
            { tag: 'tbody', children: [{ tag: 'tr', children: [{ tag: 'td', children: [{ text: 'HTML' }] }, { tag: 'td', children: [{ text: '確認済み' }] }] }] }
          ]
        },
        {
          tag: 'svg', attrs: { viewBox: '0 0 100 40', xmlns: 'http://www.w3.org/2000/svg', role: 'img', 'aria-label': 'HTMLの図' }, children: [
            { tag: 'title', children: [{ text: 'HTMLの図' }] },
            { tag: 'desc', children: [{ text: 'HTML planの安全な図' }] },
            { tag: 'defs', children: [{ tag: 'marker', attrs: { id: 'arrow', markerWidth: '6', markerHeight: '6' }, children: [{ tag: 'path', attrs: { d: 'M0 0 L6 3 L0 6 Z', 'marker-end': 'url(#arrow)' } }] }] },
            { tag: 'rect', attrs: { x: '4', y: '4', width: '92', height: '32', fill: 'none', stroke: 'currentColor' } },
            { tag: 'text', attrs: { x: '10', y: '24' }, children: [{ text: 'safe SVG' }] }
          ]
        }
      ]
    },
    { tag: 'div', attrs: { id: 'sources' }, children: [{ tag: 'a', attrs: { href: '#sources' }, children: [{ text: '内部anchor' }] }] },
    {
      tag: 'section',
      attrs: { 'data-task-id': '2', 'data-field': 'task' },
      children: [
        { tag: 'h2', attrs: { id: 'task-2' }, children: [{ text: 'Task 2: HTMLを検証する' }] },
        { tag: 'h3', children: [{ text: '検証' }] },
        { tag: 'p', children: [{ text: 'HTML検証 VERIFY_HTML_ONCE。' }] }
      ]
    },
    { tag: 'p', attrs: { 'data-field': 'optional' }, children: [{ text: '任意section OPTIONAL_HTML_ONCE。' }] }
  ]
};
const HTML_PLAN_RAW_SHA256 = 'a'.repeat(64);

function htmlFixtureSnapshot(overrides = {}) {
  return {
    version: 1,
    title: 'folder title must not win',
    generatedAt: '2026-08-31T00:00:00.000Z',
    fingerprint: 'html-fixture-fingerprint',
    planSource: '30_plan.html',
    planSourceRawSha256: HTML_PLAN_RAW_SHA256,
    requiredSources: ['task:30_plan.html', 'workspace:tools/roadmap_viewer.html'],
    planDocument: htmlPlanDocument,
    files: {
      '30_plan.md': '# SHOULD_NOT_RENDER\n\n## Task 99: MD sibling\n',
      '40_progress.md': '# operational note\n',
      '90_verification.md': '# Verification\n\nHTML verification note.'
    },
    plan: {
      schemaVersion: 2,
      parserVersion: 'html-fixture',
      sourceHash: 'html-source-hash',
      sourceKind: 'html',
      planSource: '30_plan.html',
      planSourceRawSha256: HTML_PLAN_RAW_SHA256,
      sourceHashes: { '30_plan.html': HTML_PLAN_RAW_SHA256 },
      requiredSources: ['task:30_plan.html', 'workspace:tools/roadmap_viewer.html'],
      tasks: [
        { number: '1', title: 'HTMLを読む', purpose: 'HTML目的 PURPOSE_HTML_ONCE', implementation: ['HTML実装 IMPLEMENTATION_HTML_ONCE'], outputs: ['HTML成果物 OUTPUT_HTML_ONCE'], verification: ['HTML検証'], acceptanceIds: ['H1'], sourceRefs: ['repo:tools/roadmap_viewer.html#renderPlanSource'], steps: [{ label: 'HTML実装', complete: true }], done: 1, total: 1, status: 'complete', source: { file: '30_plan.html', lineStart: 1, lineEnd: 28 } },
        { number: '2', title: 'HTMLを検証する', purpose: 'HTML検証', implementation: ['HTML検証'], outputs: ['検証結果'], verification: ['browser'], acceptanceIds: ['H5'], sourceRefs: [], steps: [], done: 0, total: 1, status: 'planned', source: { file: '30_plan.html', lineStart: 29, lineEnd: 40 } }
      ],
      edges: [{ id: 'html-edge', from: '1', to: '2', kind: 'blockedBy', relation: 'blockedBy' }],
      progress: { done: 1, total: 2, globalComplete: false },
      diagnostics: [],
      sources: { plan: '30_plan.html', progress: '40_progress.md' }
    },
    sourcePreviews: [{ taskNumber: '1', path: 'tools/roadmap_viewer.html', anchor: 'renderPlanSource', language: 'javascript', startLine: 1, endLine: 1, code: 'const htmlSource = "<safe>";', status: 'resolved', message: '', truncated: false }],
    uiPreviews: [],
    artifacts: [],
    ...overrides
  };
}

function completeHtmlFixtureSnapshot() {
  const taskDir = '/workspace/.local/memory/html-task';
  const snapshot = htmlFixtureSnapshot({
    taskDir,
    files: {
      '30_plan.html': '<main data-plan-schema="2">canonical HTML plan</main>',
      '40_progress.md': '# optional operational note\n',
      '80_review.md': '# Review\n\nCRITICAL: 0\nIMPORTANT: 0',
      '90_verification.md': '# Verification\n\nPASS',
      'checkpoint.md': '# Acceptance\n\nH1 PASS'
    }
  });
  snapshot.plan = {
    ...snapshot.plan,
    sources: { plan: `${taskDir}/30_plan.html`, progress: `${taskDir}/30_plan.html` }
  };
  return snapshot;
}

test('HTML plan snapshot is source-aware and never projects the sibling Markdown file', () => {
  const normalized = model.normalizeSnapshot(htmlFixtureSnapshot());

  assert.equal(normalized.planSource, '30_plan.html');
  assert.equal(normalized.title, 'HTML正本の計画');
  assert.equal(normalized.planDocumentState.valid, true);
  assert.equal(normalized.planDocument.format, 'html');
  assert.equal(normalized.planSourceRawSha256, HTML_PLAN_RAW_SHA256);
  assert.equal(normalized.plan.planSourceRawSha256, HTML_PLAN_RAW_SHA256);
  assert.equal(normalized.files['30_plan.md'], undefined);
  assert.equal(normalized.plan.tasks[0].acceptanceIds[0], 'H1');
  assert.equal(normalized.plan.tasks[0].sourceRefs[0], 'repo:tools/roadmap_viewer.html#renderPlanSource');
  assert.equal(model.planSourceText(normalized).includes('HTML本文 INTRO_HTML_ONCE'), true);
  assert.equal(model.planSourceText(normalized).includes('SHOULD_NOT_RENDER'), false);
  assert.notEqual(model.snapshotSignature(htmlFixtureSnapshot()), model.snapshotSignature(htmlFixtureSnapshot({ planDocument: {
    ...htmlPlanDocument,
    nodes: [...htmlPlanDocument.nodes, { text: 'changed' }]
  } })), 'HTML source changes must invalidate the snapshot signature');
});

test('HTML raw source hash is required and legacy Markdown snapshots remain optional', () => {
  const html = htmlFixtureSnapshot();
  const missingTopLevel = model.normalizeSnapshot({ ...html, planSourceRawSha256: '' });
  assert.equal(missingTopLevel.plan.valid, false);
  assert.match(missingTopLevel.plan.errors.join(' '), /snapshot\.planSourceRawSha256 is required/);

  const missingPlanField = model.normalizeSnapshot({
    ...html,
    plan: { ...html.plan, planSourceRawSha256: '' }
  });
  assert.equal(missingPlanField.plan.valid, false);
  assert.match(missingPlanField.plan.errors.join(' '), /HTML planSourceRawSha256 is required/);

  const legacy = model.normalizeSnapshot(fixtureSnapshot());
  assert.equal(legacy.planSource, '30_plan.md');
  assert.equal(legacy.planSourceRawSha256, '');
});

test('any HTML identity signal fails closed instead of falling back to a Markdown sibling', () => {
  const sourceKindOnly = htmlFixtureSnapshot();
  delete sourceKindOnly.planSource;
  delete sourceKindOnly.planDocument;
  const missingDocument = model.normalizeSnapshot(sourceKindOnly);
  assert.equal(missingDocument.planSource, '30_plan.html');
  assert.equal(missingDocument.planDocumentState.valid, false);
  assert.equal(missingDocument.files['30_plan.md'], undefined);

  for (const planSource of ['30_plan.md', 'future-plan.json']) {
    const mismatched = model.normalizeSnapshot(htmlFixtureSnapshot({ planSource }));
    assert.equal(mismatched.planSource, '30_plan.html', planSource);
    assert.equal(mismatched.plan.valid, false, planSource);
    assert.equal(mismatched.files['30_plan.md'], undefined, planSource);
    assert.match(mismatched.plan.errors.join(' '), /HTML plan identity|unsupported planSource/, planSource);
  }

  const nestedHtmlSource = htmlFixtureSnapshot();
  delete nestedHtmlSource.planSource;
  delete nestedHtmlSource.planDocument;
  nestedHtmlSource.plan = {
    ...nestedHtmlSource.plan,
    sourceKind: '',
    planSource: '',
    sources: { plan: '30_plan.html', progress: '30_plan.html' },
    sourceHashes: { '30_plan.html': HTML_PLAN_RAW_SHA256 }
  };
  const nestedSignal = model.normalizeSnapshot(nestedHtmlSource);
  assert.equal(nestedSignal.planSource, '30_plan.html');
  assert.equal(nestedSignal.planDocumentState.valid, false);
  assert.equal(nestedSignal.files['30_plan.md'], undefined);

  const legacy = model.normalizeSnapshot(fixtureSnapshot());
  assert.equal(legacy.planSource, '30_plan.md');
  assert.match(legacy.files['30_plan.md'], /legacy fallback must stay hidden|読める計画書/);
  assert.equal(Object.prototype.hasOwnProperty.call(legacy, 'planDocument'), false);
  assert.equal(model.normalizeSnapshot(legacy).planSource, '30_plan.md');
});

test('top-level and nested planDocument properties force the HTML contract for every value type', () => {
  const values = [null, [], {}, '', false, 0];
  for (const value of values) {
    const topLevel = htmlFixtureSnapshot({ requiredSources: [], planSourceRawSha256: HTML_PLAN_RAW_SHA256, planDocument: value });
    delete topLevel.planSource;
    topLevel.plan = {
      ...topLevel.plan,
      sourceKind: '',
      planSource: '',
      sourceHashes: { '30_plan.md': 'legacy-source-hash' },
      sources: { plan: '30_plan.md', progress: '40_progress.md' }
    };
    const topNormalized = model.normalizeSnapshot(topLevel);
    assert.equal(topNormalized.planSource, '30_plan.html', `top-level ${String(value)}`);
    assert.equal(topNormalized.planDocumentState.valid, false, `top-level ${String(value)}`);
    assert.equal(topNormalized.files['30_plan.md'], undefined, `top-level ${String(value)}`);

    const nested = htmlFixtureSnapshot({ requiredSources: [], planSourceRawSha256: HTML_PLAN_RAW_SHA256 });
    delete nested.planSource;
    delete nested.planDocument;
    nested.plan = {
      ...nested.plan,
      sourceKind: '',
      planSource: '',
      sourceHashes: { '30_plan.md': 'legacy-source-hash' },
      sources: { plan: '30_plan.md', progress: '40_progress.md' },
      planDocument: value
    };
    const nestedNormalized = model.normalizeSnapshot(nested);
    assert.equal(nestedNormalized.planSource, '30_plan.html', `nested ${String(value)}`);
    assert.equal(nestedNormalized.planDocumentState.valid, false, `nested ${String(value)}`);
    assert.equal(nestedNormalized.files['30_plan.md'], undefined, `nested ${String(value)}`);
  }
});

test('HTML plan.sources.plan accepts the canonical absolute taskDir location only', () => {
  const taskDir = '/workspace/.local/memory/html-task';
  const absolute = htmlFixtureSnapshot({ taskDir });
  absolute.plan = {
    ...absolute.plan,
    sources: { plan: `${taskDir}/30_plan.html`, progress: `${taskDir}/30_plan.html` }
  };
  const normalized = model.normalizeSnapshot(absolute);
  assert.equal(normalized.planSource, '30_plan.html');
  assert.equal(normalized.plan.valid, true);
  assert.equal(normalized.planDocumentState.valid, true);

  for (const planSource of ['/other/task/30_plan.html', `${taskDir}/other.html`, 'unknown-source']) {
    const invalid = htmlFixtureSnapshot({ taskDir });
    invalid.plan = {
      ...invalid.plan,
      sources: { plan: planSource, progress: `${taskDir}/30_plan.html` }
    };
    const invalidNormalized = model.normalizeSnapshot(invalid);
    assert.equal(invalidNormalized.planSource, '30_plan.html', planSource);
    assert.equal(invalidNormalized.plan.valid, false, planSource);
    assert.equal(invalidNormalized.files['30_plan.md'], undefined, planSource);
    assert.match(invalidNormalized.plan.errors.join(' '), /plan\.sources\.plan/, planSource);
  }
});

test('HTML typed plan and acceptance do not invent missing Outcome Trace or implementation warnings', () => {
  const result = model.buildModel(model.normalizeSnapshot(completeHtmlFixtureSnapshot()), { nowMs: Date.parse('2026-08-31T00:01:00.000Z') });
  assert.equal(result.artifactWarnings.some(warning => warning.kind === 'missing-trace'), false);
  assert.equal(result.artifactWarnings.some(warning => warning.file === '30_plan.md'), false);
  assert.equal(result.artifactWarnings.some(warning => warning.message === 'Implementation plan未作成'), false);
  assert.equal(result.traceSummary.missingTotal, 0);
  assert.equal(result.nextDecision.file, '30_plan.html');
  const brief = model.buildExecutionBrief(result);
  assert.equal(brief.artifacts.find(artifact => artifact.label === '実装計画')?.path, '30_plan.html');
  const tree = model.buildTreeViewModel(result);
  assert.ok(tree.nodes.filter(node => node.kind === 'task').every(node => node.artifact === '30_plan.html'));
});

test('malformed HTML planDocument fails closed without falling back to sibling Markdown', () => {
  const normalized = model.normalizeSnapshot(htmlFixtureSnapshot({
    planDocument: {
      format: 'html',
      title: '壊れたHTML',
      nodes: [{ tag: 'script', children: [{ text: 'SHOULD_NOT_RENDER' }] }]
    }
  }));

  assert.equal(normalized.planSource, '30_plan.html');
  assert.equal(normalized.planDocumentState.valid, false);
  assert.equal(normalized.planDocument, null);
  assert.equal(normalized.files['30_plan.md'], undefined);
  assert.match(normalized.planDocumentState.errors.join(' '), /tag is not allowed/);

  const unsafeHref = model.normalizeSnapshot(htmlFixtureSnapshot({
    planDocument: { format: 'html', title: 'unsafe href', nodes: [{ tag: 'a', attrs: { href: 'javascript:alert(1)' }, children: [{ text: 'external' }] }] }
  }));
  assert.equal(unsafeHref.planDocumentState.valid, false);
  assert.match(unsafeHref.planDocumentState.errors.join(' '), /safe URL/);

  const externalWithoutRel = model.normalizeSnapshot(htmlFixtureSnapshot({
    planDocument: { format: 'html', title: 'external link contract', nodes: [{ tag: 'a', attrs: { href: 'https://example.com/source' }, children: [{ text: 'external' }] }] }
  }));
  assert.equal(externalWithoutRel.planDocumentState.valid, false);
  assert.match(externalWithoutRel.planDocumentState.errors.join(' '), /target=_blank/);

  for (const href of [
    'https://example.com:0/source',
    'https://example.com:65536/source',
    'https://example.com/source`',
    'https://example.com/source\\path',
    'https://example.com/<source'
  ]) {
    const unsafeHrefValue = model.normalizeSnapshot(htmlFixtureSnapshot({
      planDocument: { format: 'html', title: 'unsafe href', nodes: [{ tag: 'a', attrs: { href, target: '_blank', rel: 'noopener noreferrer' }, children: [{ text: 'external' }] }] }
    }));
    assert.equal(unsafeHrefValue.planDocumentState.valid, false, href);
    assert.match(unsafeHrefValue.planDocumentState.errors.join(' '), /safe URL/, href);
  }

  const safeLocalSvg = model.normalizeSnapshot(htmlFixtureSnapshot({
    planDocument: { format: 'html', title: 'safe svg', nodes: [{ tag: 'svg', attrs: { fill: 'url(#paint)' }, children: [] }] }
  }));
  assert.equal(safeLocalSvg.planDocumentState.valid, true);

  for (const fill of [
    'url(file:///tmp/paint)',
    'url(ftp://evil.test/paint)',
    'url(/absolute/paint)',
    'url(//evil.test/paint)',
    'u\\72l(file:///tmp/paint)',
    'u\\72l(//evil.test/paint)',
    'u/**/rl(//evil.test/paint)'
  ]) {
    const unsafeSvg = model.normalizeSnapshot(htmlFixtureSnapshot({
      planDocument: { format: 'html', title: 'unsafe svg', nodes: [{ tag: 'svg', attrs: { fill }, children: [] }] }
    }));
    assert.equal(unsafeSvg.planDocumentState.valid, false, fill);
    assert.match(unsafeSvg.planDocumentState.errors.join(' '), /external resource/, fill);
  }

  const tableWithColumnSpan = model.normalizeSnapshot(htmlFixtureSnapshot({
    planDocument: {
      format: 'html',
      title: 'table span',
      nodes: [{ tag: 'table', children: [{ tag: 'colgroup', attrs: { span: '2' }, children: [{ tag: 'col', attrs: { span: '2' }, children: [] }] }] }]
    }
  }));
  assert.equal(tableWithColumnSpan.planDocumentState.valid, true);
});

test('invalid v2 is explicit and never falls back to Markdown Tasks', () => {
  const snapshot = model.normalizeSnapshot({
    generatedAt: '2026-08-31T00:00:00.000Z',
    files: { '30_plan.md': '## Task 99: legacy fallback must stay hidden' },
    plan: { schemaVersion: 2, tasks: 'invalid', edges: [], progress: { done: 0, total: 0 } }
  });
  const result = model.buildModel(snapshot, { nowMs: Date.parse('2026-08-31T00:01:00.000Z') });
  const tree = model.buildTreeViewModel(result);

  assert.equal(result.taskSource, 'structured');
  assert.equal(result.tasks.length, 0);
  assert.equal(result.planState.valid, false);
  assert.equal(tree.planError, true);
  assert.equal(tree.columns.task.length, 0);
  assert.match(tree.propositions.join(' '), /Plan error/);
});

test('reader template follows the document-first structure without the old drawer API', () => {
  const template = html.slice(0, html.indexOf('<script id="embedded-snapshot"'));
  for (const id of ['plan-document', 'plan-source-document', 'plan-source-content', 'plan-index-list', 'dependencies', 'verification', 'sources']) {
    assert.match(template, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.doesNotMatch(template, /plan-reading|brief-secondary|toc-mobile|detail-drawer|data-detail-tab|role=["']tab["']/);
  assert.match(html, /function renderPlanSource\(model\)/);
  assert.match(html, /renderMarkdown\(displaySource, 0\)/);
  assert.match(html, /function stripPlanMetadata\(markdown\)/);
  assert.match(html, /metadataEntries/);
  assert.match(html, /function sourcePreviewId\(task, preview\)/);
});

test('browser: full narrative, title, metadata projection, escape and evidence order remain readable', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const snapshot = fixtureSnapshot();
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    await page.waitForTimeout(40);
    const view = await page.evaluate(() => {
      const source = document.querySelector('#plan-source-content');
      const sourceText = source?.textContent || '';
      const sourceHtml = source?.innerHTML || '';
      const taskHeading = document.querySelector('[data-plan-task]');
      const sourceEvidence = document.querySelector('.task-source');
      const verification = document.querySelector('#verification');
      const taskLabels = [...document.querySelectorAll('#plan-index-list a')].map(node => node.textContent.trim());
      const count = needle => sourceText.split(needle).length - 1;
      return {
        title: document.querySelector('#task-title')?.textContent || '',
        documentTitle: document.title,
        sourceH1Count: source?.querySelectorAll('h1').length || 0,
        sourceHeadingTag: taskHeading?.tagName || '',
        purposeTag: source?.querySelector('[data-md-heading="目的"]')?.tagName || '',
        counts: Object.fromEntries(['INTRO_ONCE', 'BACKGROUND_ONCE', 'PURPOSE_ONCE', 'IMPLEMENTATION_ONCE', 'OUTPUT_ONCE', 'VERIFY_ONCE', 'OPTIONAL_ONCE', 'codeOnce'].map(item => [item, count(item)])),
        metadataInSource: [
          'required_sources: task:30_plan.md, workspace:tools/roadmap_viewer.html',
          'write scope: tools/roadmap_viewer.html, tests/roadmap-reading.test.mjs',
          'acceptance: A1, A2',
          'UI変更: yes'
        ].filter(item => sourceText.includes(item)),
        fencedMetadata: sourceText.includes('required_sources: fenced metadata stays') && sourceText.includes('write scope: fenced scope stays'),
        rawProjection: /ui-preview-json|implementation-detail/.test(sourceText) || /ui-preview-json|implementation-detail/.test(sourceHtml),
        escapedScript: source?.querySelectorAll('script').length === 0 && sourceHtml.includes('&lt;script&gt;'),
        sourceLedger: document.querySelector('#source-ledger')?.textContent || '',
        taskLabels,
        sourceEvidenceIndex: source && sourceEvidence ? [...source.children].indexOf(sourceEvidence.closest('.task-appendix')) : -1,
        implementationIndex: source ? [...source.children].findIndex(node => node.textContent.includes('実装の文章 IMPLEMENTATION_ONCE')) : -1,
        verificationAfterSource: Boolean(source && verification && source.closest('#plan-source-document')?.compareDocumentPosition(verification) & Node.DOCUMENT_POSITION_FOLLOWING),
        bodyScrollWidth: document.body.scrollWidth,
        innerWidth: innerWidth,
        disclosures: document.querySelectorAll('details, [role="dialog"]').length
      };
    });
    assert.deepEqual(errors, []);
    assert.equal(view.title, '読める計画書');
    assert.equal(view.documentTitle, '読める計画書');
    assert.equal(view.sourceH1Count, 0);
    assert.equal(view.sourceHeadingTag, 'H2');
    assert.equal(view.purposeTag, 'H3');
    assert.deepEqual(view.counts, {
      INTRO_ONCE: 1,
      BACKGROUND_ONCE: 1,
      PURPOSE_ONCE: 1,
      IMPLEMENTATION_ONCE: 1,
      OUTPUT_ONCE: 1,
      VERIFY_ONCE: 1,
      OPTIONAL_ONCE: 1,
      codeOnce: 1
    });
    assert.deepEqual(view.metadataInSource, []);
    for (const value of ['required_sources', 'write scope', 'acceptance', 'UI変更', 'A1, A2', 'tools/roadmap_viewer.html']) {
      assert.match(view.sourceLedger, new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    }
    assert.equal(view.fencedMetadata, true);
    assert.equal(view.rawProjection, false);
    assert.equal(view.escapedScript, true);
    assert.ok(view.taskLabels.every(label => /Task \d+ · .+/.test(label)));
    assert.equal(view.sourceEvidenceIndex > view.implementationIndex, true);
    assert.equal(view.verificationAfterSource, true);
    assert.equal(view.bodyScrollWidth, view.innerWidth);
    assert.equal(view.disclosures, 0);

    await page.keyboard.press('Tab');
    const skip = await page.evaluate(() => ({ id: document.activeElement?.id || '', href: document.activeElement?.getAttribute('href') || '' }));
    assert.equal(skip.id, 'skip-link');
    assert.equal(skip.href, '#main-content');
    await page.locator('#plan-index-list a[data-plan-jump="1"]').click();
    assert.equal(await page.evaluate(() => document.activeElement?.id || ''), 'task-1');

    await page.setViewportSize({ width: 375, height: 812 });
    const mobile = await page.evaluate(() => ({
      bodyScrollWidth: document.body.scrollWidth,
      innerWidth: innerWidth,
      links: [...document.querySelectorAll('#plan-index-list a')].map(node => ({ text: node.textContent.trim(), right: node.getBoundingClientRect().right }))
    }));
    assert.equal(mobile.bodyScrollWidth, 375);
    assert.ok(mobile.links.every(link => link.right <= mobile.innerWidth + 1));
    assert.ok(mobile.links.some(link => link.text.includes('Task 4 · 最終確認をする')));
  } finally {
    await browser.close();
  }
});

test('browser: HTML正本を安全なDOM treeとして一度だけ描画し、MD siblingを読まない', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
    const errors = [];
    const requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), htmlFixtureSnapshot());
    await page.waitForTimeout(40);
    const view = await page.evaluate(() => {
      const source = document.querySelector('#plan-source-content');
      const textContent = source?.textContent || '';
      const taskSections = [...source.querySelectorAll('[data-task-id]')];
      const sourceBlock = source.querySelector('.task-source');
      const taskSection = source.querySelector('[data-task-id="1"]');
      const sourceCode = source.querySelector('.source-code');
      return {
        title: document.querySelector('#task-title')?.textContent || '',
        documentTitle: document.title,
        sourceSummary: document.querySelector('#plan-source-summary')?.textContent || '',
        hashCount: (document.querySelector('#plan-document')?.innerText.match(/sourceHash/g) || []).length,
        sourceText: textContent,
        introVisible: (() => { const node = source?.querySelector('[data-field="intro"]'); const style = node ? getComputedStyle(node) : null; return Boolean(node && style && style.display !== 'none' && style.visibility !== 'hidden'); })(),
        introClass: source?.querySelector('[data-field="intro"]')?.className || '',
        detailsOpen: source?.querySelector('details')?.open === true,
        externalLink: (() => { const link = source?.querySelector('a[href^="https://"]'); return link ? { href: link.href, target: link.target, rel: link.rel } : null; })(),
        mdSiblingRendered: textContent.includes('SHOULD_NOT_RENDER'),
        introCount: (textContent.match(/INTRO_HTML_ONCE/g) || []).length,
        purposeCount: (textContent.match(/PURPOSE_HTML_ONCE/g) || []).length,
        implementationCount: (textContent.match(/IMPLEMENTATION_HTML_ONCE/g) || []).length,
        outputCount: (textContent.match(/OUTPUT_HTML_ONCE/g) || []).length,
        verifyCount: (textContent.match(/VERIFY_HTML_ONCE/g) || []).length,
        optionalCount: (textContent.match(/OPTIONAL_HTML_ONCE/g) || []).length,
        h1Count: source.querySelectorAll('h1').length,
        taskTags: taskSections.map(node => [node.getAttribute('data-task-id'), node.querySelector('h2')?.tagName || '']),
        taskId: document.querySelector('#task-1')?.id || '',
        inputDisabled: source.querySelector('input')?.disabled === true,
        inputChecked: source.querySelector('input')?.checked === true,
        svgSafe: source.querySelectorAll('svg').length === 1 && source.querySelectorAll('svg script, svg style').length === 0,
        authorId: source.querySelector('[id="sources"]')?.id || '',
        innerAnchor: source.querySelector('a[href^="#"]')?.getAttribute('href') || '',
        markerId: source.querySelector('marker')?.id || '',
        markerRef: source.querySelector('path')?.getAttribute('marker-end') || '',
        sourceCodePresent: Boolean(sourceCode),
        sourceCodeAfterBody: Boolean(sourceBlock && taskSection && taskSection.compareDocumentPosition(sourceBlock) & Node.DOCUMENT_POSITION_FOLLOWING),
        sourceLedger: document.querySelector('#source-ledger')?.textContent || '',
        bodyScrollWidth: document.body.scrollWidth,
        innerWidth: innerWidth,
        unsafeElements: source.querySelectorAll('script,style,iframe,object,embed').length,
        unsafeAttrs: source.querySelectorAll('[onclick],[onerror],[style],[src]').length,
        details: document.querySelectorAll('details,[role="dialog"]').length
      };
    });
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    assert.equal(view.title, 'HTML正本の計画');
    assert.equal(view.documentTitle, 'HTML正本の計画');
    assert.equal(view.sourceSummary, '30_plan.html · Plan v2');
    assert.equal(view.hashCount, 1);
    assert.equal(view.mdSiblingRendered, false);
    assert.deepEqual({
      intro: view.introCount,
      purpose: view.purposeCount,
      implementation: view.implementationCount,
      output: view.outputCount,
      verify: view.verifyCount,
      optional: view.optionalCount
    }, { intro: 1, purpose: 1, implementation: 1, output: 1, verify: 1, optional: 1 });
    assert.equal(view.introVisible, true);
    assert.doesNotMatch(view.introClass, /dependency-narrow|visually-hidden|skip-link/);
    assert.match(view.introClass, /plan-author-/);
    assert.equal(view.detailsOpen, true);
    assert.deepEqual(view.externalLink, { href: 'https://example.com/source', target: '_blank', rel: 'noopener noreferrer' });
    assert.equal(view.h1Count, 0);
    assert.deepEqual(view.taskTags, [['1', 'H2'], ['2', 'H2']]);
    assert.equal(view.taskId, 'task-1');
    assert.equal(view.inputDisabled, true);
    assert.equal(view.inputChecked, true);
    assert.equal(view.svgSafe, true);
    assert.equal(view.authorId, '');
    assert.match(view.innerAnchor, /^#plan-node-/);
    assert.match(view.markerId, /^plan-node-/);
    assert.equal(view.markerRef, 'url(#' + view.markerId + ')');
    assert.equal(view.sourceCodePresent, true);
    assert.equal(view.sourceCodeAfterBody, true);
    assert.match(view.sourceLedger, /30_plan\.html/);
    assert.match(view.sourceLedger, /task:30_plan\.html/);
    assert.equal(view.bodyScrollWidth, view.innerWidth);
    assert.equal(view.unsafeElements, 0);
    assert.equal(view.unsafeAttrs, 0);
    assert.equal(view.details, 1);

    await page.keyboard.press('Tab');
    const skip = await page.evaluate(() => ({ id: document.activeElement?.id || '', href: document.activeElement?.getAttribute('href') || '' }));
    assert.equal(skip.id, 'skip-link');
    assert.equal(skip.href, '#main-content');
    await page.locator('#plan-index-list a[data-plan-jump="2"]').click();
    assert.equal(await page.evaluate(() => document.activeElement?.id || ''), 'task-2');
    await page.setViewportSize({ width: 375, height: 812 });
    for (const width of [375, 640, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 812 });
      const matrix = await page.evaluate(() => {
        const intro = document.querySelector('#plan-source-content [data-field="intro"]');
        const style = intro ? getComputedStyle(intro) : null;
        return { body: document.body.scrollWidth, viewport: innerWidth, introVisible: Boolean(intro && style && style.display !== 'none' && style.visibility !== 'hidden') };
      });
      assert.equal(matrix.body, width);
      assert.equal(matrix.viewport, width);
      assert.equal(matrix.introVisible, true);
      assert.equal(await page.locator('#plan-source-content [data-task-id]').count(), 2);
    }
  } finally {
    await browser.close();
  }
});

test('browser: unsafe SVG resource values are rejected before any request', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
    const requests = [];
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    page.on('request', request => {
      if (/evil\.test|unsafe|file:|ftp:|absolute/i.test(request.url())) requests.push(request.url());
    });
    for (const fill of [
      'url(file:///tmp/paint)',
      'url(ftp://evil.test/paint)',
      'url(/absolute/paint)',
      'url(//evil.test/paint)',
      'u\\72l(file:///tmp/paint)',
      'u\\72l(//evil.test/paint)'
    ]) {
      await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), htmlFixtureSnapshot({
        planDocument: { format: 'html', title: 'unsafe svg', nodes: [{ tag: 'svg', attrs: { fill }, children: [] }] }
      }));
      assert.equal(await page.locator('#plan-source-content svg').count(), 0, fill);
    }
    assert.deepEqual(requests, []);
  } finally {
    await browser.close();
  }
});

test('browser: invalid HTML planDocument shows explicit error and never falls back to MD', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const snapshot = htmlFixtureSnapshot({
      planDocument: { format: 'html', title: 'invalid HTML', nodes: [{ tag: 'script', children: [{ text: 'SHOULD_NOT_RENDER' }] }] },
      files: { '30_plan.md': '# MD fallback must not render\n\n## Task 99: MD sibling\n' }
    });
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    const view = await page.evaluate(() => ({
      content: document.querySelector('#plan-source-content')?.textContent || '',
      html: document.querySelector('#plan-source-content')?.innerHTML || '',
      indexLinks: document.querySelectorAll('#plan-index-list a').length,
      summary: document.querySelector('#plan-source-summary')?.textContent || ''
    }));
    assert.match(view.content, /30_plan\.htmlを表示できません/);
    assert.doesNotMatch(view.content, /SHOULD_NOT_RENDER|MD fallback must not render|Task 99/);
    assert.doesNotMatch(view.html, /<script|onerror=|style=/i);
    assert.equal(view.indexLinks, 0);
    assert.equal(view.summary, '30_plan.html · Plan v2');
  } finally {
    await browser.close();
  }
});

test('browser: canonical absolute plan.sources.plan remains a valid HTML identity', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const taskDir = '/workspace/.local/memory/html-task';
    const snapshot = htmlFixtureSnapshot({ taskDir });
    snapshot.plan = {
      ...snapshot.plan,
      sources: { plan: `${taskDir}/30_plan.html`, progress: `${taskDir}/30_plan.html` }
    };
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    const view = await page.evaluate(() => ({
      content: document.querySelector('#plan-source-content')?.textContent || '',
      summary: document.querySelector('#plan-source-summary')?.textContent || '',
      taskCount: document.querySelectorAll('#plan-source-content [data-task-id]').length
    }));
    assert.equal(view.summary, '30_plan.html · Plan v2');
    assert.doesNotMatch(view.content, /30_plan\.htmlを表示できません/);
    assert.match(view.content, /HTML本文 INTRO_HTML_ONCE/);
    assert.equal(view.taskCount, 2);
  } finally {
    await browser.close();
  }
});

test('browser: HTML typed plan does not report missing Outcome Trace or implementation plan', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), completeHtmlFixtureSnapshot());
    const view = await page.evaluate(() => ({
      summary: document.querySelector('#verification-summary')?.textContent || '',
      sourceSummary: document.querySelector('#plan-source-summary')?.textContent || '',
      sourceText: document.querySelector('#plan-source-content')?.textContent || ''
    }));
    assert.equal(view.sourceSummary, '30_plan.html · Plan v2');
    assert.doesNotMatch(view.summary, /Outcome Trace未作成|Implementation plan未作成|30_plan\.md/);
    assert.match(view.summary, /成果物欠損の明示記録なし/);
    assert.match(view.sourceText, /HTML本文 INTRO_HTML_ONCE/);
  } finally {
    await browser.close();
  }
});

test('browser: conflicting or missing HTML identity never renders an MD sibling', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const sourceKindOnly = htmlFixtureSnapshot();
    delete sourceKindOnly.planSource;
    delete sourceKindOnly.planDocument;
    const cases = [
      sourceKindOnly,
      htmlFixtureSnapshot({ planDocument: null }),
      htmlFixtureSnapshot({ planDocument: [] }),
      htmlFixtureSnapshot({ planSource: '30_plan.md' }),
      htmlFixtureSnapshot({ planSource: 'future-plan.json' }),
      (() => {
        const wrongRoot = htmlFixtureSnapshot({ taskDir: '/workspace/.local/memory/html-task' });
        wrongRoot.plan = { ...wrongRoot.plan, sources: { plan: '/other/task/30_plan.html', progress: '/workspace/.local/memory/html-task/30_plan.html' } };
        return wrongRoot;
      })()
    ];
    for (const snapshot of cases) {
      await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
      const view = await page.evaluate(() => ({
        content: document.querySelector('#plan-source-content')?.textContent || '',
        summary: document.querySelector('#plan-source-summary')?.textContent || '',
        indexLinks: document.querySelectorAll('#plan-index-list a').length
      }));
      assert.match(view.summary, /^30_plan\.html/);
      assert.match(view.content, /30_plan\.htmlを表示できません/);
      assert.doesNotMatch(view.content, /SHOULD_NOT_RENDER|MD sibling|folder title must not win/);
      assert.equal(view.indexLinks, 0);
    }
  } finally {
    await browser.close();
  }
});

test('browser: source excerpt focus survives reorder and returns to Task when source disappears', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const snapshot = fixtureSnapshot();
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    const excerpt = page.locator('.source-code').first();
    const excerptId = await excerpt.getAttribute('id');
    assert.match(excerptId || '', /^source-excerpt-/);
    await excerpt.focus();
    const before = await page.evaluate(() => ({ id: document.activeElement?.id || '', scrollY }));
    const reordered = {
      ...snapshot,
      sourcePreviews: [
        { taskNumber: '1', path: 'src/other.js', anchor: 'other', language: 'javascript', startLine: 1, endLine: 1, code: 'const other = 1;', status: 'resolved', message: '', truncated: false },
        snapshot.sourcePreviews[0]
      ]
    };
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), reordered);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const after = await page.evaluate(() => ({ id: document.activeElement?.id || '', scrollY }));
    assert.equal(after.id, before.id);
    assert.equal(after.scrollY, before.scrollY);
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), { ...snapshot, sourcePreviews: [] });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(() => document.activeElement?.id || ''), 'task-1');
  } finally {
    await browser.close();
  }
});

test('browser: source検証失敗時も計画記録のBeforeを保ち、差分と未確認状態を併記する', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 812 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const snapshot = fixtureSnapshot({
      uiPreviews: [{
        version: 1,
        taskNumber: '1',
        layout: 'list',
        title: 'source付きの未確認Before',
        status: 'unverified',
        isNewScreen: true,
        provenance: {
          before: { source: 'repo:src/old.js#render', baseRef: 'a'.repeat(40) },
          after: { source: '30_plan.md#Task 1' }
        },
        before: { items: [{ id: 'existing', label: 'Existing section', kind: 'section', state: 'visible', change: 'same' }] },
        after: { items: [
          { id: 'existing', label: 'Existing section', kind: 'section', state: 'visible', change: 'same' },
          { id: 'new', label: 'New section', kind: 'section', state: 'planned', change: 'added' }
        ] }
      }]
    });
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    const before = await page.locator('.compare-panel[data-side="before"]').innerText();
    assert.match(before, /Before未確認/);
    assert.match(before, /未確認の計画記録/);
    assert.match(before, /Existing section/);
    assert.doesNotMatch(before, /新規画面/);
    assert.match(before, /old\.js#render/);
    const after = await page.locator('.compare-panel[data-side="after"]').innerText();
    assert.match(after, /New section/);
    assert.match(after, /追加/);
    assert.equal(await page.locator('.task-change .compare-panel').count(), 2);
  } finally {
    await browser.close();
  }
});

test('browser: sourceなしの実際の新規画面はAfter-onlyで未実装と明示する', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 812 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const snapshot = {
      version: 1,
      title: '新規画面 fixture',
      generatedAt: new Date().toISOString(),
      files: { '30_plan.md': '# 新規画面 fixture\n\n## Task 1: 新規画面\n\n### 実装\n\n- Afterだけを計画する。\n' },
      uiPreviews: [{
        version: 1,
        taskNumber: '1',
        layout: 'list',
        title: '新規画面',
        status: 'planned',
        isNewScreen: true,
        provenance: { before: {}, after: { source: '30_plan.md#Task 1' } },
        before: { items: [] },
        after: { items: [{ id: 'new', label: '新しい領域', kind: 'section', state: 'planned', change: 'added' }] }
      }]
    };
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    assert.equal(await page.locator('.task-change .compare-panel').count(), 1);
    const after = await page.locator('.compare-panel[data-side="after"]').innerText();
    assert.match(after, /新規画面/);
    assert.match(after, /未実装/);
    assert.equal(await page.locator('.compare-panel[data-side="before"]').count(), 0);
  } finally {
    await browser.close();
  }
});
