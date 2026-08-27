#!/usr/bin/env node
import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const scriptsRoot = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(scriptsRoot, "..");
const repoRoot = resolve(packageRoot, "..", "..", "..");
const manifestPath = join(repoRoot, "config", "html-surfaces.json");
const pointerPath = join(packageRoot, "dist", "ui-current.json");
const versionedBundlesRoot = join(packageRoot, "dist", "ui-versions");
const expectedFiles = [
  "plan-viewer.html",
  "diagram-viewer.html",
  "verification-viewer.html",
];
const sourcePathByFile = {
  "plan-viewer.html": "claude-compat/mcp-servers/workflow-html-app/ui/plan-viewer.html",
  "diagram-viewer.html": "claude-compat/mcp-servers/workflow-html-app/ui/diagram-viewer.html",
  "verification-viewer.html": "claude-compat/mcp-servers/workflow-html-app/ui/verification-viewer.html",
};

function parseArgs(argv) {
  const args = {
    inputDir: defaultInputDir(),
    skipBrowser: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--input-dir") {
      args.inputDir = resolve(argv[index + 1]);
      index += 1;
    } else if (value === "--skip-browser") {
      args.skipBrowser = true;
    } else {
      throw new Error(`unknown argument: ${value}`);
    }
  }
  return args;
}

function defaultInputDir() {
  let pointer;
  try {
    pointer = JSON.parse(readFileSync(pointerPath, "utf8"));
  } catch (error) {
    throw new Error(`UI pointer missing or unreadable: ${pointerPath}`);
  }
  const version = pointer.version;
  if (typeof version === "string" && /^[A-Za-z0-9._-]+$/.test(version)) {
    return join(versionedBundlesRoot, version);
  }
  throw new Error(`UI pointer has an invalid version: ${pointerPath}`);
}

function readManifest() {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const producer = manifest.producers.find(
    (entry) => entry.id === "claude-compat-workflow-html-app",
  );
  if (!producer) {
    throw new Error("claude-compat-workflow-html-app producer missing from html-surfaces manifest");
  }
  const surfaces = expectedFiles.map((fileName) => {
    const sourcePath = sourcePathByFile[fileName];
    const surface = manifest.surfaces.find((entry) => entry.path === sourcePath);
    if (!surface) {
      throw new Error(`${sourcePath} surface missing from html-surfaces manifest`);
    }
    const browserProfile = manifest.browserProfiles[surface.browserProfile] || [];
    return {
      fileName,
      sourcePath,
      browserProfile,
      browserProfileName: surface.browserProfile,
      viewports: browserProfile
        .filter((entry) => /^\d+x\d+$/.test(entry))
        .map((entry) => {
          const [width, height] = entry.split("x").map(Number);
          return { label: entry, width, height };
        }),
    };
  });
  return {
    producer,
    surfaces,
  };
}

function assertStaticHtml(fileName, html) {
  const errors = [];
  const markup = html
    .replace(/<script\b[\s\S]*?<\/script>/gi, "<script></script>")
    .replace(/<style\b[\s\S]*?<\/style>/gi, "<style></style>");

  if (!/^<!doctype html>/i.test(html.trim())) {
    errors.push("missing HTML5 doctype");
  }
  if (!/<html\b[^>]*\blang=/i.test(markup)) {
    errors.push("missing html lang");
  }
  if (!/<meta\b[^>]*charset=/i.test(markup)) {
    errors.push("missing charset meta");
  }
  if (!/<meta\b[^>]*name=["']viewport["']/i.test(markup)) {
    errors.push("missing viewport meta");
  }
  if (!/<title>[^<]+<\/title>/i.test(markup)) {
    errors.push("missing title");
  }
  if (!/Content-Security-Policy/i.test(markup)) {
    errors.push("missing Content-Security-Policy meta");
  }
  if (/<script\b[^>]*\bsrc=["']https?:\/\//i.test(html)
    || /<(?:link|img|iframe|audio|video|source)\b[^>]*(?:src|href)=["']https?:\/\//i.test(markup)) {
    errors.push("loads external resources");
  }
  if (/<\w+\b[^>]*\son\w+=/i.test(markup)) {
    errors.push("contains inline event handler attributes");
  }
  if (/<(?:object|embed)\b/i.test(markup)) {
    errors.push("contains forbidden object/embed element");
  }

  const ids = new Map();
  for (const match of markup.matchAll(/\bid=["']([^"']+)["']/gi)) {
    const id = match[1];
    ids.set(id, (ids.get(id) || 0) + 1);
  }
  const duplicateIds = [...ids.entries()].filter(([, count]) => count > 1);
  if (duplicateIds.length > 0) {
    errors.push(`duplicate ids: ${duplicateIds.map(([id]) => id).join(", ")}`);
  }

  if (errors.length > 0) {
    throw new Error(`${fileName}: ${errors.join("; ")}`);
  }
}

function payloadFor(fileName) {
  if (fileName === "diagram-viewer.html") {
    return {
      text: JSON.stringify({
        mermaidCode: "flowchart TD\n  Start[Start] --> Done[Done]",
        title: "Matrix Diagram",
        graphJson: JSON.stringify({
          nodes: [
            { id: "start", label: "Start", layer: "UI", order: 0 },
            { id: "done", label: "Done", layer: "API", order: 1 },
          ],
          edges: [{ id: "start_done", from: "start", to: "done", label: "complete" }],
        }),
      }),
      routeKind: "diagram",
    };
  }
  if (fileName === "verification-viewer.html") {
    return {
      text: "# Matrix Report\n\n## Checks\n- [ ] Browser matrix\n- [x] Static scan\n",
      routeKind: "verification",
    };
  }
  return {
    text: "# Matrix Report\n\n## Tasks\n- [ ] Browser matrix\n- [x] Static scan\n",
    routeKind: "plan",
  };
}

function markerFor(fileName) {
  if (fileName === "diagram-viewer.html") return "Matrix Diagram";
  if (fileName === "verification-viewer.html") return "検証ガイドを読む";
  return "計画を読む";
}

function hostHtml(fileUrl) {
  return `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>MCP Apps verification host</title>
<style>html,body{margin:0;width:100%;height:100%;}iframe{border:0;display:block;width:100vw;height:100vh;}</style></head>
<body>
  <iframe id="app" title="MCP App under test" src=${JSON.stringify(fileUrl)} sandbox="allow-scripts allow-same-origin allow-forms"></iframe>
  <script>
    const iframe = document.getElementById('app');
    window.__messages = [];
    window.__initialized = false;
    window.__sendToolResult = (payload) => {
      const result = typeof payload === 'string' ? { text: payload } : payload;
      const routeKind = result && typeof result.routeKind === 'string' ? result.routeKind : undefined;
      iframe.contentWindow.postMessage({
        jsonrpc: '2.0',
        method: 'ui/notifications/tool-result',
        params: {
          content: [{ type: 'text', text: result.text }],
          structuredContent: routeKind ? { routeKind } : undefined,
          _meta: routeKind ? { 'workflow-html-app/routeKind': routeKind } : undefined
        }
      }, '*');
    };
    window.addEventListener('message', (event) => {
      if (event.source !== iframe.contentWindow) return;
      const message = event.data;
      window.__messages.push(message);
      if (!message || message.jsonrpc !== '2.0') return;
      if (message.method === 'ui/initialize') {
        event.source.postMessage({
          jsonrpc: '2.0',
          id: message.id,
          result: {
            protocolVersion: '2026-01-26',
            hostInfo: { name: 'workflow-html-app-verifier', version: '1.0.0' },
            hostCapabilities: {
              message: { text: {} },
              sandbox: { csp: { connectDomains: [], resourceDomains: [] } }
            },
            hostContext: {
              theme: 'light',
              displayMode: 'inline',
              availableDisplayModes: ['inline'],
              containerDimensions: { width: window.innerWidth, maxHeight: window.innerHeight }
            }
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

async function launchBrowser() {
  try {
    return await chromium.launch({ channel: "chrome", headless: true });
  } catch {
    return chromium.launch({ headless: true });
  }
}

async function startStaticServer(inputDir) {
  const server = createServer((request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    const fileName = url.pathname.replace(/^\//, "");
    if (!expectedFiles.includes(fileName)) {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("not found");
      return;
    }
    const filePath = join(inputDir, fileName);
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(readFileSync(filePath, "utf8"));
  });
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("failed to allocate local verification server");
  }
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    close: () => new Promise((resolveClose) => server.close(resolveClose)),
  };
}

function parseRgb(value) {
  const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function luminance([r, g, b]) {
  const channel = [r, g, b].map((value) => {
    const normalized = value / 255;
    return normalized <= 0.03928
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channel[0] + 0.7152 * channel[1] + 0.0722 * channel[2];
}

function contrastRatio(foreground, background) {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

async function verifyFrameState(frame, fileName, checks) {
  const marker = markerFor(fileName);
  await frame.waitForFunction(
    (expected) => document.body.innerText.includes(expected),
    marker,
    { timeout: 10_000 },
  );
  if (checks.includes("svg-visible")) {
    const mermaidToggle = frame.locator("#view-mermaid");
    if (await mermaidToggle.count()) {
      await mermaidToggle.click();
    }
    await frame.waitForSelector("#diagram svg, svg", {
      state: "visible",
      timeout: 10_000,
    });
  }

  const state = await frame.evaluate(() => {
    const styles = getComputedStyle(document.body);
    return {
      scrollWidth: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth),
      clientWidth: document.documentElement.clientWidth,
      textColor: styles.color,
      backgroundColor: styles.backgroundColor,
      hasMain: Boolean(document.querySelector("main, [role='main'], .container")),
      hasButton: Boolean(document.querySelector("button, textarea, a[href]")),
    };
  });

  if (checks.includes("overflow") && state.scrollWidth > state.clientWidth + 2) {
    throw new Error(`${fileName}: body overflows horizontally (${state.scrollWidth} > ${state.clientWidth})`);
  }
  if (!state.hasMain) {
    throw new Error(`${fileName}: missing main landmark or application container`);
  }
  if (checks.includes("contrast")) {
    const foreground = parseRgb(state.textColor);
    const background = parseRgb(state.backgroundColor);
    if (foreground && background && contrastRatio(foreground, background) < 4.5) {
      throw new Error(`${fileName}: body text contrast is below 4.5:1`);
    }
  }
  if (checks.includes("keyboard") || checks.includes("focus") || checks.includes("focus-restoration")) {
    if (!state.hasButton) {
      throw new Error(`${fileName}: no keyboard-focusable controls found`);
    }
  }
}

async function verifyBrowserFile(browser, fileUrl, fileName, viewport, checks, media = {}) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    reducedMotion: media.reducedMotion,
    forcedColors: media.forcedColors,
  });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.setContent(hostHtml(fileUrl), {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(() => window.__initialized === true, null, {
      timeout: 10_000,
    });
    const frame = page.frames().find((candidate) => candidate.url().includes(fileName));
    if (!frame) {
      throw new Error(`${fileName}: app iframe did not load`);
    }
    await page.evaluate((payload) => window.__sendToolResult(payload), payloadFor(fileName));
    await verifyFrameState(frame, fileName, checks);

    if (checks.includes("keyboard") || checks.includes("focus") || checks.includes("focus-restoration")) {
      await frame.locator("body").click({ position: { x: 8, y: 8 } });
      await page.keyboard.press("Tab");
      const activeTag = await frame.evaluate(() => document.activeElement?.tagName || "");
      if (activeTag === "" || activeTag === "BODY" || activeTag === "HTML") {
        throw new Error(`${fileName}: Tab did not move focus to an interactive element`);
      }
    }

    if (checks.includes("200%-zoom")) {
      await frame.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
      });
      await verifyFrameState(frame, fileName, ["overflow"]);
    }

    await frame.evaluate(() => {
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          jsonrpc: "2.0",
          method: "ui/notifications/tool-result",
          params: { content: [{ type: "text", text: "Spoofed Source Payload" }] },
        },
        source: window,
      }));
    });
    const spoofed = await frame.evaluate(() => document.body.innerText.includes("Spoofed Source Payload"));
    if (spoofed) {
      throw new Error(`${fileName}: spoofed source message changed the DOM`);
    }

    if (consoleErrors.length > 0 || pageErrors.length > 0) {
      throw new Error(`${fileName}: browser errors: ${[...consoleErrors, ...pageErrors].join(" | ")}`);
    }
  } finally {
    await context.close();
  }
}

async function verifyBrowser(inputDir, matrix) {
  const browser = await launchBrowser();
  const server = await startStaticServer(inputDir);
  try {
    for (const surface of matrix.surfaces) {
      const { fileName, browserProfile } = surface;
      const viewports = surface.viewports.length > 0
        ? surface.viewports
        : [{ label: "1440x900", width: 1440, height: 900 }];
      const fileUrl = `${server.baseUrl}/${fileName}`;
      for (const viewport of viewports) {
        await verifyBrowserFile(browser, fileUrl, fileName, viewport, browserProfile);
      }
      if (browserProfile.includes("reduced-motion")) {
        await verifyBrowserFile(
          browser,
          fileUrl,
          fileName,
          viewports[0],
          ["overflow"],
          { reducedMotion: "reduce" },
        );
      }
      if (browserProfile.includes("forced-colors")) {
        await verifyBrowserFile(
          browser,
          fileUrl,
          fileName,
          viewports[0],
          ["overflow", "keyboard"],
          { forcedColors: "active" },
        );
      }
    }
  } finally {
    await server.close();
    await browser.close();
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const matrix = readManifest();
  for (const fileName of expectedFiles) {
    const filePath = join(args.inputDir, fileName);
    if (!existsSync(filePath)) {
      throw new Error(`${fileName} missing from ${args.inputDir}`);
    }
    assertStaticHtml(fileName, readFileSync(filePath, "utf8"));
  }
  if (!args.skipBrowser) {
    await verifyBrowser(args.inputDir, matrix);
  }
  console.log(`html artifacts verified: ${expectedFiles.join(", ")}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
