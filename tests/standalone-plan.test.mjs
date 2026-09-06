import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CODEX_PLAYWRIGHT_MODULE || '/Users/yoshiki/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = fileURLToPath(new URL('..', import.meta.url));

function runPython(args) {
  const result = spawnSync('python3', args, { cwd: root, encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return result.stdout;
}

test('standalone plan preserves the visible source in the full browser matrix', async () => {
  let source = process.env.CODEX_PLAN_HTML;
  if (!source) {
    const directory = mkdtempSync(path.join(tmpdir(), 'standalone-plan-'));
    source = path.join(directory, '30_plan.html');
    const fixture = runPython(['-c', 'import sys; sys.path.insert(0, "tests"); from test_standalone_plan import plan_html; print(plan_html(), end="")']);
    writeFileSync(source, fixture);
    runPython(['scripts/generate-roadmap-view.py', directory, '--json', '--source-root', directory]);
  }
  const published = path.join(path.dirname(source), 'roadmap.html');
  assert.ok(readFileSync(published, 'utf8').includes('embedded-snapshot'));
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ javaScriptEnabled: false });
    const failures = [];
    page.on('pageerror', error => failures.push(error.message));
    page.on('console', event => { if (event.type() === 'error') failures.push(event.text()); });
    const unexpected = [];
    page.on('request', request => {
      if (/^https?:/.test(request.url())) unexpected.push(request.url());
    });
    for (const [width, height] of [[375, 812], [768, 1024], [1440, 900]]) {
      await page.setViewportSize({ width, height });
      let original;
      for (const filename of [source, published]) {
        await page.goto(pathToFileURL(filename).href);
        const observation = await page.evaluate(() => ({
          text: document.body.innerText,
          layout: [...document.querySelectorAll('main, h1, pre, figure, [data-ui-side]')].map(node => {
            const rect = node.getBoundingClientRect();
            return [node.tagName, Math.round(rect.x), Math.round(rect.width), Math.round(rect.height), getComputedStyle(node).display];
          }),
          overflow: document.documentElement.scrollWidth > innerWidth,
          executableScripts: [...document.scripts].filter(script => script.type !== 'application/json').length,
          brokenImages: [...document.images].filter(img => !img.complete || !img.naturalWidth).length,
          obsolete: document.querySelectorAll('#codemap-figure, .task-appendix').length,
        }));
        assert.equal(observation.overflow, false, `overflow at ${width}: ${filename}`);
        assert.equal(observation.executableScripts, 0);
        assert.equal(observation.brokenImages, 0);
        assert.equal(observation.obsolete, 0);
        if (!original) original = observation;
        else assert.deepEqual(observation, original, 'published plan must preserve source appearance and prose');
      }
    }
    // Keyboard focus works with JavaScript disabled; reload keeps the same anchor target.
    await page.goto(pathToFileURL(published).href);
    await page.keyboard.press('Tab');
    const focus = await page.evaluate(() => ({
      tag: document.activeElement.tagName,
      outline: getComputedStyle(document.activeElement).outlineStyle,
      href: document.activeElement.getAttribute('href'),
    }));
    assert.equal(focus.tag, 'A');
    assert.notEqual(focus.outline, 'none');
    await page.keyboard.press('Enter');
    const fragment = new URL(page.url()).hash;
    assert.ok(fragment.length > 1);
    await page.reload();
    assert.equal(new URL(page.url()).hash, fragment);

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => { document.body.style.zoom = '2'; });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, '200% zoom overflow');
    await page.evaluate(() => { document.body.style.zoom = ''; });
    await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.keyboard.press('Tab');
    assert.notEqual(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), 'none');
    assert.equal(await page.evaluate(() => [...document.querySelectorAll('*')].some(node => {
      const style = getComputedStyle(node);
      return style.animationName !== 'none' && style.animationDuration !== '0s';
    })), false);
    await page.emulateMedia({ forcedColors: 'none', reducedMotion: 'no-preference' });
    const contrast = await page.evaluate(() => {
      const luminance = color => {
        const rgb = color.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
        return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
      };
      const style = getComputedStyle(document.body);
      const values = [luminance(style.color), luminance(style.backgroundColor)].sort((a, b) => b - a);
      return (values[0] + 0.05) / (values[1] + 0.05);
    });
    assert.ok(contrast >= 4.5, `body text contrast ${contrast}`);
    assert.deepEqual(failures, []);
    assert.deepEqual(unexpected, []);
    if (process.env.CODEX_PLAN_SCREENSHOT) {
      await page.goto(pathToFileURL(source).href);
      await page.screenshot({ path: process.env.CODEX_PLAN_SCREENSHOT, fullPage: true });
    }
  } finally {
    await browser.close();
  }
});
