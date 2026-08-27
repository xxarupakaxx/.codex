import {
  RESOURCE_MIME_TYPE,
  registerAppResource,
  registerAppTool,
} from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = existsSync(join(__dirname, "package.json"))
  ? __dirname
  : join(__dirname, "..");
const distRoot = join(packageRoot, "dist");
const pointerPath = join(distRoot, "ui-current.json");
const versionRoot = join(distRoot, "ui-versions");

const PLAN_VIEWER_URI = "ui://plan-viewer/index.html";
const LOG_VIEWER_URI = "ui://log-viewer/index.html";
const DIAGRAM_VIEWER_URI = "ui://diagram-viewer/index.html";
const VERIFICATION_VIEWER_URI = "ui://verification-viewer/index.html";
const ROUTE_KIND_META_KEY = "workflow-html-app/routeKind";

type DocumentRouteKind = "plan" | "log" | "verification";

const resourceUiMeta = {
  ui: {
    csp: {
      connectDomains: [],
      resourceDomains: [],
      frameDomains: [],
      baseUriDomains: [],
    },
    prefersBorder: true,
  },
};

function currentBundleFile(fileName: string) {
  const pointer = JSON.parse(readFileSync(pointerPath, "utf-8"));
  const version = pointer.version;
  if (typeof version !== "string" || !/^[A-Za-z0-9._-]+$/.test(version)) {
    throw new Error("invalid UI bundle pointer version");
  }
  if (Array.isArray(pointer.files) && !pointer.files.includes(fileName)) {
    throw new Error(`UI bundle pointer does not include ${fileName}`);
  }
  const bundleRoot = resolve(versionRoot, version);
  const relativePath = relative(versionRoot, bundleRoot).split(sep).join("/");
  if (!relativePath || relativePath === "." || relativePath.startsWith("../") || isAbsolute(relativePath)) {
    throw new Error("UI bundle pointer escapes version root");
  }
  return join(bundleRoot, fileName);
}

function htmlResource(uriHref: string, fileName: string) {
  const htmlContent = readFileSync(currentBundleFile(fileName), "utf-8");
  return {
    contents: [
      {
        uri: uriHref,
        mimeType: RESOURCE_MIME_TYPE,
        text: htmlContent,
        _meta: resourceUiMeta,
      },
    ],
  };
}

function resourceError(uriHref: string, fileName: string, error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return {
    contents: [
      {
        uri: uriHref,
        mimeType: "text/plain",
        text: `Verified UI bundle is unavailable for ${fileName}: ${message}`,
      },
    ],
  };
}

function safeHtmlResource(uriHref: string, fileName: string) {
  try {
    return htmlResource(uriHref, fileName);
  } catch (error) {
    return resourceError(uriHref, fileName, error);
  }
}

function documentToolResult(content: string, routeKind: DocumentRouteKind) {
  return {
    content: [
      {
        type: "text" as const,
        text: content,
      },
    ],
    structuredContent: {
      routeKind,
    },
    _meta: {
      [ROUTE_KIND_META_KEY]: routeKind,
    },
  };
}

export function createServer(): McpServer {
  const server = new McpServer({
    name: "workflow-html-app",
    version: "0.1.0",
  });

  registerAppTool(
    server,
    "view-plan",
    {
      title: "View Plan",
      description: "計画ファイル（30_plan.md）をインタラクティブHTMLで表示。Markdownコンテンツを渡すとHTML UIで可視化",
      inputSchema: {
        content: z.string().describe("Markdownコンテンツ"),
      },
      _meta: {
        ui: {
          resourceUri: PLAN_VIEWER_URI,
          visibility: ["model"],
        },
      },
    },
    async ({ content }) => documentToolResult(content, "plan"),
  );

  registerAppResource(
    server,
    "plan-viewer-ui",
    PLAN_VIEWER_URI,
    {
      description: "Plan Viewer MCP App resource",
      _meta: resourceUiMeta,
    },
    async (uri) => safeHtmlResource(uri.href, "plan-viewer.html"),
  );

  registerAppTool(
    server,
    "view-log",
    {
      title: "View Log",
      description: "作業ログ（05_log.md）をインタラクティブHTMLで表示。Markdownコンテンツを渡すとLog Viewerで可視化",
      inputSchema: {
        content: z.string().describe("Markdownコンテンツ"),
      },
      _meta: {
        ui: {
          resourceUri: LOG_VIEWER_URI,
          visibility: ["model"],
        },
      },
    },
    async ({ content }) => documentToolResult(content, "log"),
  );

  registerAppResource(
    server,
    "log-viewer-ui",
    LOG_VIEWER_URI,
    {
      description: "Log Viewer MCP App resource backed by the shared document bundle",
      _meta: resourceUiMeta,
    },
    async (uri) => safeHtmlResource(uri.href, "plan-viewer.html"),
  );

  registerAppTool(
    server,
    "view-diagram",
    {
      title: "View Diagram",
      description: "Mermaid図と任意のGraph JSONをインタラクティブHTMLで表示。Mermaidのズーム・パン、2.5Dレイヤービュー、Graph JSON timeline再生に対応",
      inputSchema: {
        mermaidCode: z.string().describe("Mermaidダイアグラムコード"),
        title: z.string().optional().describe("図のタイトル（オプション）"),
        graphJson: z.string().optional().describe("2.5Dレイヤービュー用のGraph JSON（オプション）"),
      },
      _meta: {
        ui: {
          resourceUri: DIAGRAM_VIEWER_URI,
          visibility: ["model"],
        },
      },
    },
    async ({ mermaidCode, title, graphJson }) => ({
      content: [
        {
          type: "text" as const,
          text: JSON.stringify({ mermaidCode, title: title || "Diagram", graphJson }),
        },
      ],
    }),
  );

  registerAppResource(
    server,
    "diagram-viewer-ui",
    DIAGRAM_VIEWER_URI,
    {
      description: "Diagram Viewer MCP App resource",
      _meta: resourceUiMeta,
    },
    async (uri) => safeHtmlResource(uri.href, "diagram-viewer.html"),
  );

  registerAppTool(
    server,
    "view-verification",
    {
      title: "View Verification",
      description: "検証ガイド（90_verification.md）をインタラクティブHTMLで表示。チェックリストの進捗トラッキング付き",
      inputSchema: {
        content: z.string().describe("Markdownコンテンツ"),
      },
      _meta: {
        ui: {
          resourceUri: VERIFICATION_VIEWER_URI,
          visibility: ["model"],
        },
      },
    },
    async ({ content }) => documentToolResult(content, "verification"),
  );

  registerAppResource(
    server,
    "verification-viewer-ui",
    VERIFICATION_VIEWER_URI,
    {
      description: "Verification Viewer MCP App resource generated from the document bundle",
      _meta: resourceUiMeta,
    },
    async (uri) => safeHtmlResource(uri.href, "verification-viewer.html"),
  );

  return server;
}
