import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const templatePath = fileURLToPath(new URL("../../../tools/roadmap_viewer.html", import.meta.url));
const graphMap = `# Concept Map

\`\`\`mermaid
flowchart TB
  G["理解できる計画"]
  F["snapshotに本文がある"]
  D{"brief-firstを採用"}
  A["実行計画"]
  V["browserで検証"]
  G -->|"必要とする"| D
  F -->|"判断材料にする"| D
  D -->|"生み出す"| A
  V -->|"検証する"| A
\`\`\`
`;

function buildSnapshot() {
  return {
    version: 1,
    title: "Roadmap Viewerの読解可能性を再設計",
    generatedAt: new Date().toISOString(),
    files: {
      "00_spec.md": `# 機能要求

## 目的

実行Task、仕様、実装根拠、順序、事実、成果物を第一画面で理解できるようにする。

## 必須要件

- Taskと仕様を同時に読める。

## 制約事項

- snapshot schema version 1を維持する。

## 現在の事実

- snapshotにはMarkdown本文が残っている。

## 採用判断

- 第一画面をbrief-firstにする。

## 未確定

- 古いtaskの見出し揺れ。
`,
      "20_survey.md": `## 現在の事実

- graph-first表示がTaskを隠していた。
`,
      "30_plan.md": `# 実装計画

## 実装方針

\`buildExecutionBrief()\` を \`.codex/tools/roadmap_viewer.html\` に追加する。

## Task 1: contractを固定する

### 目的

第一画面の読解要件をtestにする。

### 変更対象

- \`.codex/tests/roadmap-viewer.test.mjs\`

### 成果物

- contract test

### 検証

\`node --test .codex/tests/roadmap-viewer.test.mjs\`

## Task 2: brief UIを実装する

### 目的

6項目を画面へ表示する。

### 変更対象

- \`.codex/tools/roadmap_viewer.html\`
`,
      "40_progress.md": `# 進捗

| Task | 状態 | 進捗 |
| --- | --- | --- |
| Task 1 | 進行中 | 1/2 |
| Task 2 | 未着手 | 0/1 |

## 実測

- Node contractはgreen。
`,
      "team-journal.md": `## Decisions

- primary briefとgraph inspectorを分離する。

## Open Questions

- code anchorがないtaskの表示。
`,
      "graph-map.md": graphMap,
    },
  };
}

function writeFixture(snapshotInput = buildSnapshot()) {
  const directory = mkdtempSync(join(tmpdir(), "roadmap-viewer-runtime-"));
  const template = readFileSync(templatePath, "utf8");
  const snapshot = JSON.stringify(snapshotInput).replaceAll("<", "\\u003c");
  const html = template.replace('{"__ROADMAP_SNAPSHOT_JSON__": true}', snapshot);
  const path = join(directory, "roadmap.html");
  writeFileSync(path, html);
  return { directory, path };
}

async function withPage(t, viewport, callback, snapshot = buildSnapshot()) {
  const fixture = writeFixture(snapshot);
  let browser;
  try {
    try {
      browser = await chromium.launch({ channel: "chrome", headless: true });
    } catch (error) {
      t.diagnostic(`System Chrome launch failed; trying bundled Chromium. ${error.message}`);
      browser = await chromium.launch({ headless: true });
    }
    const page = await browser.newPage({ viewport });
    await page.goto(`file://${fixture.path}`);
    await page.waitForSelector("#brief-flow .brief-flow-item");
    await callback(page);
    await page.close();
  } finally {
    await browser?.close();
    rmSync(fixture.directory, { recursive: true, force: true });
  }
}

async function withLivePage(t, viewport, callback) {
  const fixture = writeFixture();
  let snapshot = buildSnapshot();
  const server = createServer((request, response) => {
    if (request.url?.startsWith("/roadmap-snapshot.json")) {
      response.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      response.end(JSON.stringify(snapshot));
      return;
    }
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(readFileSync(fixture.path));
  });
  let browser;
  try {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    try {
      browser = await chromium.launch({ channel: "chrome", headless: true });
    } catch (error) {
      t.diagnostic(`System Chrome launch failed; trying bundled Chromium. ${error.message}`);
      browser = await chromium.launch({ headless: true });
    }
    const page = await browser.newPage({ viewport });
    const address = server.address();
    await page.goto(`http://127.0.0.1:${address.port}/roadmap.html`);
    await page.waitForSelector("#brief-flow .brief-flow-item");
    await callback(page, (nextSnapshot) => { snapshot = nextSnapshot; });
    await page.close();
  } finally {
    await browser?.close();
    await new Promise((resolve) => server.close(resolve));
    rmSync(fixture.directory, { recursive: true, force: true });
  }
}

test("first screen exposes concrete task spec code claims and artifacts", async (t) => {
  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
    const state = await page.evaluate(() => ({
      executionVisible: document.querySelector("#execution-brief")?.getBoundingClientRect().height > 0,
      firstTask: document.querySelector("#brief-flow .brief-flow-item strong")?.textContent,
      purpose: document.querySelector("#brief-summary")?.textContent,
      spec: document.querySelector("#brief-spec-summary")?.textContent,
      next: document.querySelector("#brief-next-status")?.textContent,
      anchors: [...document.querySelectorAll("#brief-code-anchors code")].map((node) => node.textContent),
      claimHeadings: [...document.querySelectorAll("#brief-claims h4")].map((node) => node.textContent),
      artifacts: [...document.querySelectorAll("#brief-artifact-grid [data-artifact]")].map((node) => node.dataset.artifact),
      graphOpen: document.querySelector("#concept-map-disclosure")?.open,
    }));

    assert.equal(state.executionVisible, true);
    assert.equal(state.firstTask, "contractを固定する");
    assert.match(state.purpose, /実行Task/);
    assert.match(state.spec, /要件:/);
    assert.match(state.spec, /制約:/);
    assert.notEqual(state.purpose, state.spec);
    assert.match(state.next, /Task 2/);
    assert.ok(state.anchors.includes("buildExecutionBrief()"));
    assert.deepEqual(state.claimHeadings, ["事実", "判断", "未確定"]);
    assert.deepEqual(state.artifacts, ["00_spec.md", "30_plan.md", "40_progress.md", "80_review.md"]);
    assert.equal(state.graphOpen, false);
  });
});

test("concept map interaction does not overwrite the primary brief", async (t) => {
  await withPage(t, { width: 1280, height: 900 }, async (page) => {
    const before = await page.locator("#brief-current-status").textContent();
    const summaryBefore = await page.locator("#brief-summary").textContent();

    await page.locator("#concept-map-disclosure > summary").click();
    await page.waitForFunction(() => document.querySelectorAll("#graph-edges path").length > 0);
    const edgeBeforeResize = await page.locator("#graph-edges path").first().getAttribute("d");
    await page.locator('[data-graph-node="D"]').click();

    assert.equal(await page.locator("#brief-current-status").textContent(), before);
    assert.equal(await page.locator("#brief-summary").textContent(), summaryBefore);
    assert.equal(await page.locator("#decision-evidence").isHidden(), true);
    assert.match(await page.locator("#inspector-title").textContent(), /brief-first/);

    await page.locator('[data-graph-node="D"]').focus();
    await page.keyboard.press("ArrowRight");
    await page.waitForFunction(() => document.activeElement?.dataset.graphNode === "A");
    assert.equal(await page.locator('[data-graph-node="A"]').getAttribute("aria-current"), "true");

    await page.setViewportSize({ width: 980, height: 900 });
    await page.waitForFunction((previous) => {
      const current = document.querySelector("#graph-edges path")?.getAttribute("d");
      return Boolean(current && current !== previous);
    }, edgeBeforeResize);
  });
});

test("desktop tablet and mobile preserve section order without horizontal overflow", async (t) => {
  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 768, height: 900 },
    { width: 375, height: 812 },
  ]) {
    await withPage(t, viewport, async (page) => {
      const state = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        executionTop: document.querySelector("#execution-brief")?.getBoundingClientRect().top,
        conceptTop: document.querySelector("#concept-map-disclosure")?.getBoundingClientRect().top,
        claimColumns: getComputedStyle(document.querySelector(".claim-grid")).gridTemplateColumns.split(" ").length,
        quickSpecInViewport: document.querySelector('#brief-quick-links [data-artifact="00_spec.md"]')?.getBoundingClientRect().bottom <= innerHeight,
      }));

      assert.ok(state.overflow <= 1, `${viewport.width}px has horizontal overflow ${state.overflow}px`);
      assert.ok(state.executionTop < state.conceptTop);
      assert.equal(state.quickSpecInViewport, true);
      if (viewport.width === 375) assert.equal(state.claimColumns, 1);
    });
  }
});

test("keyboard opens a source artifact and the concept disclosure on mobile", async (t) => {
  await withPage(t, { width: 375, height: 812 }, async (page) => {
    const specLink = page.locator('#brief-quick-links [data-artifact="00_spec.md"]');
    await specLink.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.querySelector("#utility-disclosure")?.open);
    assert.match(await page.locator("#source-preview").textContent(), /実行Task/);
    assert.equal(await page.evaluate(() => document.activeElement?.id), "source-preview");

    const summary = page.locator("#concept-map-disclosure > summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#concept-map-disclosure").getAttribute("open"), "");
  });
});

test("missing code anchors and claim classifications stay explicit", async (t) => {
  const snapshot = buildSnapshot();
  snapshot.files["30_plan.md"] = `## Task 1: 古いTask

- [ ] 実行する
`;
  snapshot.files["00_spec.md"] = `## 目的

古いTaskを読む。

## 必須要件

- 記録済みの内容だけを表示する。

## 制約事項

- sourceにない内容を推論しない。
`;
  delete snapshot.files["20_survey.md"];
  delete snapshot.files["40_progress.md"];
  delete snapshot.files["team-journal.md"];

  await withPage(t, { width: 1280, height: 900 }, async (page) => {
    assert.equal(await page.locator("#brief-code-anchors").textContent(), "実装根拠が未記録");
    assert.deepEqual(
      await page.locator("#brief-claims .brief-missing").allTextContents(),
      ["明示分類なし", "明示分類なし", "明示分類なし"],
    );
  }, snapshot);
});

test("live polling refreshes freshness and a changed snapshot updates the current task", async (t) => {
  await withLivePage(t, { width: 1280, height: 900 }, async (page, setSnapshot) => {
    await page.waitForFunction(() => document.querySelector("#live-status-text")?.textContent === "Live");
    const stale = buildSnapshot();
    stale.generatedAt = "2020-01-01T00:00:00.000Z";
    setSnapshot(stale);
    await page.evaluate(() => pollSnapshot(pollGeneration));
    assert.equal(await page.locator("#brief-status").textContent(), "更新待ち");

    const freshSameSignature = { ...stale, generatedAt: new Date().toISOString() };
    setSnapshot(freshSameSignature);
    await page.evaluate(() => pollSnapshot(pollGeneration));
    assert.equal(await page.locator("#brief-status").textContent(), "Task 1 進行中");
    assert.equal(await page.locator("#live-status-text").textContent(), "Live");

    const changed = structuredClone(freshSameSignature);
    changed.files["40_progress.md"] = `# 進捗

| Task | 状態 | 進捗 |
| --- | --- | --- |
| Task 1 | 完了 | 2/2 |
| Task 2 | 進行中 | 0/1 |

## 実測

- runtime snapshotを更新した。
`;
    setSnapshot(changed);
    await page.evaluate(() => pollSnapshot(pollGeneration));
    assert.match(await page.locator("#brief-current-status").textContent(), /Task 2/);
    assert.equal(await page.locator("#brief-progress").textContent(), "1 / 2 Task");
  });
});
