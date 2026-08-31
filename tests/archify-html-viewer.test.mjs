import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
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

const sourceUrl = new URL('../tools/roadmap_viewer.html', import.meta.url);
const html = readFileSync(sourceUrl, 'utf8');
const sourceMatch = html.match(/\/\* ROADMAP_MODEL_START \*\/([\s\S]*?)\/\* ROADMAP_MODEL_END \*\//);
assert.ok(sourceMatch, 'roadmap_viewer.html must expose the browser model source');
const context = vm.createContext({ console, Date, Intl, JSON, Math, Map, Object, RegExp, Set, String, globalThis: {} });
vm.runInContext(sourceMatch[1], context, { filename: 'roadmap-viewer-model.js' });
const model = context.globalThis.__ROADMAP_MODEL__;
assert.ok(model, 'the browser model must be exported');

const memoryRoot = '/Users/yoshiki/Notes/Vault/.local/memory/260831_archify-integration';
const realStage = JSON.parse(readFileSync(`${memoryRoot}/stage-real-roadmap-snapshot.json`, 'utf8'));
const updatedStage = JSON.parse(readFileSync(`${memoryRoot}/stage-updated-roadmap-snapshot.json`, 'utf8'));
const revision = '5de7275fe87a66a19d52a4d9b0b3a4f2a5a90115';

function sha256(value) {
  return createHash('sha256').update(Buffer.from(value, 'utf8')).digest('hex');
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function htmlPlan(title, body = 'HTML本文を意味要素として表示します。') {
  return `<article><h1>${title}</h1><p>${body}</p><h2 id="task-1">Task 1: HTML表示</h2><h3>目的</h3><p>生のMarkdown記号を表示せずに読む。</p><h3>実装</h3><ul><li>安全なASTを描画する</li><li><code>planDocument</code>を使う</li></ul><table><thead><tr><th>項目</th><th>状態</th></tr></thead><tbody><tr><td>図</td><td>検証済み</td></tr></tbody></table></article>`;
}

function htmlPlanDocument(title = 'HTML表示計画') {
  return {
    format: 'html',
    title,
    nodes: [
      { tag: 'p', children: [{ text: 'HTML本文を意味要素として表示します。' }] },
      { tag: 'h2', attrs: { id: 'task-1' }, children: [{ text: 'Task 1: HTML表示' }] },
      { tag: 'h3', children: [{ text: '目的' }] },
      { tag: 'p', children: [{ text: '生のMarkdown記号を表示せずに読む。' }] },
      { tag: 'h3', children: [{ text: '実装' }] },
      { tag: 'ul', children: [{ tag: 'li', children: [{ text: '安全なASTを描画する' }] }, { tag: 'li', children: [{ tag: 'code', children: [{ text: 'planDocument' }] }] }] },
      { tag: 'table', children: [{ tag: 'thead', children: [{ tag: 'tr', children: [{ tag: 'th', children: [{ text: '項目' }] }, { tag: 'th', children: [{ text: '状態' }] }] }] }, { tag: 'tbody', children: [{ tag: 'tr', children: [{ tag: 'td', children: [{ text: '図' }] }, { tag: 'td', children: [{ text: '検証済み' }] }] }] }] }
    ]
  };
}

function htmlSnapshot(stage, title, rawText, overviewSource) {
  const rawHash = sha256(rawText);
  const planDocument = htmlPlanDocument(title);
  const plan = {
    schemaVersion: 2,
    parserVersion: 'html-fixture',
    sourceKind: 'html',
    planSource: '30_plan.html',
    planSourceRawSha256: rawHash,
    sourceHash: 'html-plan-structured',
    sourceHashes: {},
    tasks: [{ number: '1', title: 'HTML表示', purpose: '生の記号を避ける', implementation: ['ASTを描画する'], outputs: ['HTML viewer'], verification: ['browser'], blockedBy: '', steps: [], done: 0, total: 1, status: 'in-progress', body: 'Task本文' }],
    edges: [],
    progress: { done: 0, total: 1, globalComplete: false, signals: {} },
    diagnostics: [],
    sources: { plan: '/review/task/30_plan.html' }
  };
  const archify = clone(overviewSource);
  archify.provider = 'archify';
  archify.revision = revision;
  archify.status = 'verified';
  archify.source.planSha256 = rawHash;
  return {
    version: stage.version,
    kind: 'roadmap',
    title,
    generatedAt: stage.generatedAt,
    planSource: '30_plan.html',
    planSourceRawSha256: rawHash,
    files: { '30_plan.html': rawText },
    taskDir: '/review/task',
    sources: [{ name: '30_plan.html', size: rawText.length }],
    artifacts: [{ name: '30_plan.html', path: '30_plan.html', type: 'html', size: rawText.length }],
    planDocument,
    plan,
    archify,
    sourcePreviews: [],
    uiPreviews: [],
    codemapStatus: 'not-applicable',
    timeline: []
  };
}

test('HTML正本はraw hash・typed plan・Archifyを同じsnapshot境界で結び、signatureにも含める', () => {
  const rawText = htmlPlan('HTML正本');
  const rawHash = sha256(rawText);
  const snapshot = htmlSnapshot(realStage, 'HTML正本', rawText, realStage.archify);
  const normalized = model.normalizeSnapshot(snapshot);
  assert.equal(normalized.planSource, '30_plan.html');
  assert.equal(normalized.files['30_plan.html'], rawText);
  assert.equal(normalized.files['30_plan.md'], undefined);
  assert.equal(normalized.planSourceRawSha256, rawHash);
  assert.equal(normalized.plan.planSourceRawSha256, rawHash);
  assert.equal(normalized.planDocumentState.valid, true);
  assert.equal(normalized.archify.source.planSha256, rawHash);
  const changed = clone(snapshot);
  changed.archify.source.planSha256 = '0'.repeat(64);
  assert.notEqual(model.snapshotSignature(snapshot), model.snapshotSignature(changed));
});

test('HTML正本のraw field欠落・不正AST・旧native dependency描画は採用しない契約を持つ', () => {
  const template = html.slice(0, html.indexOf('<script id="embedded-snapshot"'));
  assert.equal((template.match(/id="task-dependency-figure"/g) || []).length, 1);
  assert.ok(template.indexOf('id="task-dependency-figure"') < template.indexOf('id="plan-source-document"'));
  assert.match(template, /class="[^"]*archify-canvas/);
  assert.match(html, /function archifyPlanSource\(snapshot\)/);
  assert.match(html, /snapshotRawHash/);
  assert.match(html, /planRawHash/);
  assert.match(html, /30_plan\.htmlを検証できません/);
  assert.match(html, /generation !== archifyGeneration/);
  assert.match(html, /img\[hidden\]\s*\{\s*display:\s*none/);
  assert.doesNotMatch(html, /function dependencySvg\(/);
  assert.doesNotMatch(template, /Task間のblockedBy関係/);
});

test('MD-only snapshotはnormalizeの往復後もTaskを保持する', () => {
  const source = {
    version: 1,
    title: 'MD legacy plan',
    files: { '30_plan.md': '# 計画\n\n## Task 1: MD task\n\n### 目的\n本文を保持する。\n' },
    sourcePreviews: [],
    uiPreviews: [],
    timeline: []
  };
  const first = model.normalizeSnapshot(source);
  const second = model.normalizeSnapshot(first);
  const firstModel = model.buildModel(first);
  const secondModel = model.buildModel(second);
  const taskSummary = value => Array.from(value.tasks, task => [task.number, task.title]);
  assert.equal(first.planSource, '30_plan.md');
  assert.equal(second.planSource, '30_plan.md');
  assert.deepEqual(taskSummary(secondModel), taskSummary(firstModel));
  assert.deepEqual(Array.from(secondModel.tasks, task => task.number), ['1']);
});

test('browser: HTML本文を冒頭図と一緒に3幅で読み、更新・失敗・open/saveを実操作する', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  const browserContext = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 900 } });
  const page = await browserContext.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    const initial = htmlSnapshot(realStage, 'HTML正本', htmlPlan('HTML正本'), realStage.archify);
    const updated = htmlSnapshot(updatedStage, 'HTML正本（更新）', htmlPlan('HTML正本（更新）', '更新後も同じ安全なAST表示を使います。'), updatedStage.archify);
    for (const width of [1440, 768, 375]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(sourceUrl.href);
      await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), initial);
      await page.waitForFunction(() => document.querySelector('#archify-state')?.textContent.includes('表示しました'));
      const view = await page.evaluate(() => {
        const figure = document.querySelector('#task-dependency-figure');
        const source = document.querySelector('#plan-source-document');
        const canvas = document.querySelector('#task-dependency-svg');
        const image = document.querySelector('#archify-image');
        return {
          bodyWidth: document.body.scrollWidth,
          figureBeforeSource: figure.getBoundingClientRect().top < source.getBoundingClientRect().top,
          imageReady: !image.hidden && image.complete && image.naturalWidth > 0,
          canvasScrollable: canvas.scrollWidth >= canvas.clientWidth,
          hasJapanese: document.querySelector('#plan-source-content').textContent.includes('生のMarkdown記号を表示せずに読む。'),
          hasTable: Boolean(document.querySelector('#plan-source-content table')),
          hasRawMarkup: document.querySelector('#plan-source-content').textContent.includes('<h1>')
        };
      });
      assert.equal(view.bodyWidth, width);
      assert.equal(view.figureBeforeSource, true);
      assert.equal(view.imageReady, true);
      assert.equal(view.canvasScrollable, true);
      assert.equal(view.hasJapanese, true);
      assert.equal(view.hasTable, true);
      assert.equal(view.hasRawMarkup, false);
    }

    await page.setViewportSize({ width: 375, height: 900 });
    await page.goto(sourceUrl.href);
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), initial);
    await page.waitForFunction(() => document.querySelector('#archify-state')?.textContent.includes('表示しました'));
    await page.locator('#task-dependency-svg').focus();
    await page.evaluate(() => { document.querySelector('#task-dependency-svg').scrollLeft = 42; });
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), initial);
    await page.waitForFunction(() => document.querySelector('#archify-state')?.textContent.includes('表示しました'));
    const retained = await page.evaluate(() => ({ focus: document.activeElement?.id, scrollLeft: document.querySelector('#task-dependency-svg').scrollLeft }));
    assert.equal(retained.focus, 'task-dependency-svg');
    assert.equal(retained.scrollLeft, 42);

    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), updated);
    await page.waitForFunction(() => document.querySelector('#archify-state')?.textContent.includes('表示しました'));
    assert.equal(await page.locator('#task-title').innerText(), 'HTML正本（更新）');
    assert.equal(await page.locator('#archify-image').evaluate(image => image.hidden), false);

    const popupPromise = page.waitForEvent('popup');
    await page.locator('#archify-open').click();
    const popup = await popupPromise;
    assert.match(popup.url(), /^blob:/);
    await popup.close();
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#archify-save').click();
    const download = await downloadPromise;
    assert.equal(download.suggestedFilename(), 'archify-overview.svg');
    const downloaded = readFileSync(await download.path());
    assert.equal(sha256(downloaded.toString('utf8')), updated.archify.overview.svgSha256);

    const failed = clone(updated);
    failed.archify.status = 'invalid';
    failed.archify.revision = 'unknown';
    failed.archify.message = 'Archify overviewを検証できません。';
    await page.evaluate(({ next, bad }) => {
      window.__ROADMAP_VIEWER__.render(next);
      window.__ROADMAP_VIEWER__.render(bad);
    }, { next: updated, bad: failed });
    await page.waitForFunction(() => document.querySelector('#archify-state')?.textContent.includes('検証できません'));
    const failureView = await page.evaluate(() => ({ hidden: document.querySelector('#archify-image').hidden, src: document.querySelector('#archify-image').getAttribute('src'), openHidden: document.querySelector('#archify-open').hidden, saveHidden: document.querySelector('#archify-save').hidden }));
    assert.deepEqual(failureView, { hidden: true, src: null, openHidden: true, saveHidden: true });

    const hostile = clone(updated);
    hostile.archify.overview.svg = '<svg xmlns="http://www.w3.org/2000/svg" role="img" data-theme="light" lang="ja" xml:lang="ja"><title>図</title><desc>図</desc><foreignObject xmlns="http://www.w3.org/1999/xhtml"><div>危険</div></foreignObject></svg>';
    hostile.archify.overview.svgSha256 = sha256(hostile.archify.overview.svg);
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), hostile);
    await page.waitForFunction(() => document.querySelector('#archify-state')?.textContent.includes('namespace'));
    assert.equal(await page.locator('#archify-image').evaluate(image => image.hidden), true);

    const invalidPlan = clone(updated);
    invalidPlan.planDocument = { format: 'html', title: '壊れた計画', nodes: [{ tag: 'script', children: [{ text: '拒否' }] }] };
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), invalidPlan);
    await page.waitForFunction(() => document.querySelector('#archify-state')?.textContent.includes('30_plan.htmlを検証できません'));
    assert.equal(await page.locator('#archify-image').evaluate(image => image.hidden), true);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browserContext.close();
    await browser.close();
  }
});

test('browser: HTMLの存在・宣言とMDの併存はMD fallbackせずerrorにする', { skip: !chromium }, async () => {
  const browser = await chromium.launch({ headless: true });
  const browserContext = await browser.newContext({ viewport: { width: 768, height: 900 } });
  const page = await browserContext.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    const base = htmlSnapshot(realStage, 'HTML正本', htmlPlan('HTML正本'), realStage.archify);
    const missingPlanSource = clone(base);
    delete missingPlanSource.planSource;
    delete missingPlanSource.planDocument;
    delete missingPlanSource.planSourceRawSha256;
    delete missingPlanSource.plan.planSourceRawSha256;
    missingPlanSource.plan.sourceKind = '';
    missingPlanSource.plan.planSource = '';
    missingPlanSource.plan.sources = { plan: '30_plan.md' };
    missingPlanSource.plan.sourceHashes = {};
    missingPlanSource.files['30_plan.md'] = 'MD TRAP: fallbackしてはいけない';

    const markerOnly = clone(base);
    delete markerOnly.planSource;
    delete markerOnly.planDocument;
    markerOnly.files = { '30_plan.md': 'MD TRAP: HTML宣言だけでもfallbackしてはいけない' };
    markerOnly.sources = [];
    markerOnly.artifacts = [];
    markerOnly.plan.sourceKind = '';
    markerOnly.plan.planSource = '';
    markerOnly.plan.sources = { plan: '/review/task/30_plan.html' };
    markerOnly.plan.sourceHashes = {};

    const sourceKindOnly = clone(markerOnly);
    sourceKindOnly.plan.sourceKind = 'html';
    sourceKindOnly.plan.sources = { plan: '40_progress.md' };

    const explicitMdWithHtml = clone(base);
    explicitMdWithHtml.planSource = '30_plan.md';
    explicitMdWithHtml.files['30_plan.md'] = 'MD TRAP: 相反するsource identityを無視してはいけない';

    const cases = [missingPlanSource, markerOnly, sourceKindOnly, explicitMdWithHtml];
    await page.goto(sourceUrl.href);
    for (const snapshot of cases) {
      const normalized = model.normalizeSnapshot(snapshot);
      assert.equal(normalized.planSource, '30_plan.html');
      assert.equal(normalized.files['30_plan.md'], undefined);
      assert.equal(normalized.plan?.valid === true && normalized.planDocumentState?.valid === true, false);
      await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
      await page.waitForFunction(() => {
        const state = document.querySelector('#archify-state')?.textContent || '';
        return /30_plan\.html|HTML plan/.test(state) && !/検証しています|読み込んでいます/.test(state);
      });
      const view = await page.evaluate(() => ({
        bodyText: document.body.textContent,
        state: document.querySelector('#archify-state')?.textContent || '',
        imageHidden: document.querySelector('#archify-image')?.hidden,
        imageSrc: document.querySelector('#archify-image')?.getAttribute('src'),
        openHidden: document.querySelector('#archify-open')?.hidden,
        saveHidden: document.querySelector('#archify-save')?.hidden,
        nativeSvg: Boolean(document.querySelector('#task-dependency-svg > svg'))
      }));
      assert.match(view.state, /30_plan\.html|HTML plan/);
      assert.match(view.state, /未記録|不正|一致|検証できません|表示できません/);
      assert.doesNotMatch(view.bodyText, /MD TRAP/);
      assert.equal(view.imageHidden, true);
      assert.equal(view.imageSrc, null);
      assert.equal(view.openHidden, true);
      assert.equal(view.saveHidden, true);
      assert.equal(view.nativeSvg, false);
    }
    assert.deepEqual(pageErrors, []);
  } finally {
    await browserContext.close();
    await browser.close();
  }
});
