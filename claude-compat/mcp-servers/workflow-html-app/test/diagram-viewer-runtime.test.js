import { join, resolve } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFileSync } from "node:fs";

const distRoot = resolve("dist");
const pointerPath = join(distRoot, "ui-current.json");
const versionedBundlesRoot = join(distRoot, "ui-versions");

const mermaidCode = `stateDiagram-v2
    [*] --> Request
    Request --> API : Submit
    API --> Domain : Validate
    Domain --> DB : Save
    DB --> [*] : Persisted`;

const legacyGraph = {
  nodes: [
    { id: "ui", label: "Submit form", layer: "UI", why: "User intent starts the workflow.", order: 0 },
    { id: "api", label: "Server action", layer: "API", why: "The API boundary validates input.", order: 1 },
  ],
  edges: [
    { id: "ui_api", from: "ui", to: "api", label: "submit", type: "sync" },
  ],
};

const timelineGraph = {
  ...legacyGraph,
  timeline: {
    unit: "phase",
    steps: [
      {
        id: "step_0",
        at: 10,
        label: "Submit",
        timestamp: "phase 1",
        summary: "The UI starts the workflow.",
        eventType: "trigger",
        activeNodes: ["ui"],
        changedNodes: ["ui"],
      },
      {
        id: "step_1",
        at: 30,
        label: "Validate",
        timestamp: "phase 2",
        summary: "The API validates the request.",
        eventType: "review",
        activeNodes: ["api"],
        activeEdges: ["ui_api"],
        changedNodes: ["api"],
        changedEdges: ["ui_api"],
      },
    ],
  },
};

async function withPage(t, callback) {
  let browser;
  const staticServer = await startStaticServer();
  try {
    browser = await chromium.launch({ channel: "chrome", headless: true });
  } catch (error) {
    t.diagnostic(`System Chrome launch failed; trying bundled Chromium. ${error.message}`);
    browser = await chromium.launch({ headless: true });
  }
  try {
    const page = await browser.newPage({ viewport: { width: 960, height: 720 } });
    await page.setContent(hostHtml(`${staticServer.baseUrl}/diagram-viewer.html`), { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.__initialized === true);
    const frame = page.frames().find((candidate) => candidate.url().includes("diagram-viewer.html"));
    assert.ok(frame, "diagram viewer iframe should load");
    await callback(page, frame);
    await page.close();
  } finally {
    await browser.close();
    await staticServer.close();
  }
}

async function startStaticServer() {
  const server = createServer((request, response) => {
    if (request.url !== "/diagram-viewer.html") {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("not found");
      return;
    }
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(readPublishedHtml("diagram-viewer.html"));
  });
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    close: () => new Promise((resolveClose) => server.close(resolveClose)),
  };
}

function readPublishedHtml(fileName) {
  const pointer = JSON.parse(readFileSync(pointerPath, "utf8"));
  assert.match(pointer.version, /^[A-Za-z0-9._-]+$/);
  return readFileSync(join(versionedBundlesRoot, pointer.version, fileName), "utf8");
}

function hostHtml(fileUrl) {
  return `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Diagram host</title>
<style>html,body{margin:0;width:100%;height:100%;}iframe{border:0;display:block;width:100vw;height:100vh;}</style></head>
<body>
  <iframe id="app" title="Diagram Viewer" src="${fileUrl}" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>
  <script>
    const iframe = document.getElementById('app');
    window.__initialized = false;
    window.__sendToolResult = (text) => {
      iframe.contentWindow.postMessage({
        jsonrpc: '2.0',
        method: 'ui/notifications/tool-result',
        params: { content: [{ type: 'text', text }] }
      }, '*');
    };
    window.addEventListener('message', (event) => {
      if (event.source !== iframe.contentWindow) return;
      const message = event.data;
      if (!message || message.jsonrpc !== '2.0') return;
      if (message.method === 'ui/initialize') {
        event.source.postMessage({
          jsonrpc: '2.0',
          id: message.id,
          result: {
            protocolVersion: '2026-01-26',
            hostInfo: { name: 'diagram-test-host', version: '1.0.0' },
            hostCapabilities: {
              message: { text: {} },
              sandbox: { csp: { connectDomains: [], resourceDomains: [] } }
            },
            hostContext: { theme: 'dark', displayMode: 'inline' }
          }
        }, '*');
      }
      if (message.method === 'ui/notifications/initialized') {
        window.__initialized = true;
      }
    });
  </script>
</body>
</html>`;
}

async function sendPayload(page, frame, payload) {
  await page.evaluate((payloadText) => {
    window.__sendToolResult(payloadText);
  }, JSON.stringify(payload));
  await frame.waitForFunction((title) => document.querySelector("#title")?.textContent === title, payload.title);
}

test("legacy graph payload keeps timeline controls hidden", async (t) => {
  await withPage(t, async (page, frame) => {
    await sendPayload(page, frame, {
      mermaidCode,
      title: "Legacy Graph",
      graphJson: JSON.stringify(legacyGraph),
    });

    await frame.waitForSelector("#view-graph:not([hidden])");
    await frame.waitForFunction(() => document.querySelector("#view-timeline")?.hidden === true);
    const state = await frame.evaluate(() => ({
      timelineHidden: document.querySelector("#view-timeline")?.hidden,
      graphNodes: document.querySelectorAll(".graph-node").length,
      graphVisible: document.querySelector("#view-graph")?.classList.contains("active"),
    }));

    assert.equal(state.timelineHidden, true);
    assert.equal(state.graphNodes, 2);
    assert.equal(state.graphVisible, true);
  });
});

test("timeline payload exposes replay controls and step-driven graph state", async (t) => {
  await withPage(t, async (page, frame) => {
    await sendPayload(page, frame, {
      mermaidCode,
      title: "Timeline Graph",
      graphJson: JSON.stringify(timelineGraph),
    });

    await frame.waitForSelector("#view-timeline:not([hidden])");
    await frame.click("#view-timeline");
    await frame.click("#timeline-next");

    const state = await frame.evaluate(() => ({
      caption: document.querySelector("#timeline-caption")?.textContent,
      ariaValue: document.querySelector("#timeline-slider")?.getAttribute("aria-valuetext"),
      activeNodes: [...document.querySelectorAll(".graph-node.timeline-active")].map((node) => node.dataset.id),
      changedEdges: document.querySelectorAll("[data-edge-id].timeline-changed").length,
      timelineLive: document.querySelector("#timeline-live")?.textContent,
    }));

    assert.match(state.caption, /2\/2/);
    assert.match(state.ariaValue, /Validate/);
    assert.deepEqual(state.activeNodes, ["api"]);
    assert.ok(state.changedEdges > 0);
    assert.match(state.timelineLive, /API validates/);
  });
});

test("invalid timeline falls back to static graph without hiding Mermaid", async (t) => {
  await withPage(t, async (page, frame) => {
    await sendPayload(page, frame, {
      mermaidCode,
      title: "Invalid Timeline",
      graphJson: JSON.stringify({ ...legacyGraph, timeline: { steps: "bad" } }),
    });

    await frame.waitForSelector("#view-graph:not([hidden])");
    await frame.waitForFunction(() => /Timeline invalid/.test(document.querySelector("#status")?.textContent || ""));
    await frame.waitForSelector("#diagram svg", { state: "attached" });
    const state = await frame.evaluate(() => ({
      status: document.querySelector("#status")?.textContent,
      timelineHidden: document.querySelector("#view-timeline")?.hidden,
      mermaidSvg: document.querySelectorAll("#diagram svg").length,
      graphNodes: document.querySelectorAll(".graph-node").length,
    }));

    assert.match(state.status, /Timeline invalid/);
    assert.equal(state.timelineHidden, true);
    assert.equal(state.mermaidSvg, 1);
    assert.equal(state.graphNodes, 2);
  });
});
