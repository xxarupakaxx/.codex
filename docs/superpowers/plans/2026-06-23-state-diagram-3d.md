# State Diagram 3D Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional 2.5D graph viewer path backed by `workflow-html-app MCP`, then expose it through a separate `generate-state-diagram-3d` skill. Keep `generate-state-diagram` focused on Mermaid/Markdown output.

**Architecture:** Extend the existing MCP `view-diagram` payload with optional `graphJson`. Render Mermaid exactly as before when no graph is provided; render an additional CSS 3D layered graph when graph data is present. The 3D skill owns Graph JSON and the MCP-backed viewer path; the base skill remains the 2D Mermaid path.

**Tech Stack:** TypeScript MCP server, Zod schemas, static HTML/CSS/JavaScript, Mermaid, Node built-in test runner.

---

### Task 1: Add Contract Tests

**Files:**
- Create: `claude-compat/mcp-servers/workflow-html-app/test/diagram-viewer-contract.test.js`
- Modify: `claude-compat/mcp-servers/workflow-html-app/package.json`

- [ ] **Step 1: Write failing contract tests**

Add tests that assert `graphJson` exists in the server schema/payload, the HTML viewer includes graph rendering hooks, `generate-state-diagram-3d` documents Graph JSON/MCP usage, and the base `generate-state-diagram` does not own Graph JSON output.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test` from `claude-compat/mcp-servers/workflow-html-app`

Expected: FAIL because `graphJson` and graph viewer hooks are absent.

### Task 2: Implement MCP Payload and 2.5D Viewer

**Files:**
- Modify: `claude-compat/mcp-servers/workflow-html-app/server.ts`
- Modify: `claude-compat/mcp-servers/workflow-html-app/ui/diagram-viewer.html`
- Modify: `claude-compat/mcp-servers/workflow-html-app/package.json`
- Create: `claude-compat/mcp-servers/workflow-html-app/scripts/copy-static-ui.mjs`

- [ ] **Step 1: Extend `view-diagram` schema**

Add optional `graphJson: z.string().optional()` and include it in the returned JSON payload.

- [ ] **Step 2: Add viewer controls**

Add Mermaid/2.5D view buttons, layer filter area, selected node detail panel, and Graph JSON copy support.

- [ ] **Step 3: Add graph renderer**

Parse `{ nodes, edges }`, compute stable positions from process order and layer, render nodes and edges with CSS 3D transforms, and allow pointer drag rotation.

- [ ] **Step 4: Run tests**

Run: `npm test`

Expected: PASS.

- [ ] **Step 5: Ensure dist server can load diagram UI**

Keep `vite-plugin-singlefile` on the existing single plan viewer input, then copy `ui/diagram-viewer.html` and `ui/verification-viewer.html` into `dist/ui` after Vite build.

### Task 3: Add Separate 3D Skill Documentation

**Files:**
- Create: `skills/generate-state-diagram-3d/SKILL.md`
- Create: `skills/generate-state-diagram-3d/references/graph-json-schema.md`
- Modify: `skills/generate-state-diagram/SKILL.md`

- [ ] **Step 1: Create `generate-state-diagram-3d`**

Document `91_state_diagram_3d.md`, `91_state_diagram_graph.json`, optional fallback `91_state_diagram_3d.html`, and the required `workflow-html-app MCP` call.

- [ ] **Step 2: Document schema and generation rules**

Document node/edge schema, layer meanings, generation conditions, and `mcp__workflow-html-app__view-diagram` usage with `graphJson` in the 3D skill and reference file.

- [ ] **Step 3: Keep base skill Mermaid-focused**

Remove `graphJson`, `91_state_diagram_graph.json`, and 2.5D ownership from `generate-state-diagram`.

- [ ] **Step 4: Run tests and build**

Run: `npm test` and `npm run build`

Expected: both PASS.
