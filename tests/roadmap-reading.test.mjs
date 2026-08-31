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
    assert.deepEqual(await page.evaluate(() => ({ id: document.activeElement?.id || '', href: document.activeElement?.getAttribute('href') || '' })), { id: 'skip-link', href: '#main-content' });
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

test('browser: source付き空Beforeは未確認として両panelを保ち、新規画面表示へ倒さない', { skip: !chromium }, async () => {
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
        before: { items: [] },
        after: { items: [{ id: 'new', label: 'New section', kind: 'section', state: 'planned', change: 'added' }] }
      }]
    });
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    const before = await page.locator('.compare-panel[data-side="before"]').innerText();
    assert.match(before, /Before未確認/);
    assert.match(before, /未確認の参照/);
    assert.doesNotMatch(before, /新規画面/);
    assert.match(before, /old\.js#render/);
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
