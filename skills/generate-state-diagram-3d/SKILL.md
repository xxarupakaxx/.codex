---
name: generate-state-diagram-3d
description: Generate a workflow-html-app MCP-backed 2.5D state diagram from branch changes. Use when the user asks for 3D/2.5D state diagrams, layered diagrams, graphJson output, workflow-html-app diagram viewer output, or a more inspectable alternative to flat Mermaid diagrams.
allowed-tools: Read, Bash, Glob, Grep, Write, mcp__workflow-html-app__view-diagram
---

# Generate State Diagram 3D

## Overview

Create a 2.5D layered state diagram for branch changes. This skill is separate from `generate-state-diagram`: the base skill owns Mermaid/Markdown diagrams, while this skill owns Graph JSON, optional timeline replay data, and the workflow-html-app 2.5D/timeline viewer path.

## Hard Requirement

Use `workflow-html-app MCP` for the interactive 2.5D view.

Call `mcp__workflow-html-app__view-diagram` with all three fields:

```text
mermaidCode: "<main Mermaid diagram>"
title: "<diagram title>"
graphJson: "<91_state_diagram_graph.json as a string>"
```

Do not treat hand-written static 3D HTML as the normal path. If `mcp__workflow-html-app__view-diagram` is unavailable, save the Markdown and Graph JSON artifacts, then report that interactive 2.5D display is blocked by the missing workflow-html-app MCP. Generate a static fallback only when the user explicitly asks for file-only output or fallback HTML.

## Outputs

Save these files in the task memory directory:

- `91_state_diagram_3d.md`: explanation, main Mermaid diagram, usage notes, glossary, and file map
- `91_state_diagram_graph.json`: Graph JSON consumed by workflow-html-app. Include optional `timeline` data when time progression is essential to understanding.
- `91_state_diagram_3d.html`: optional fallback only when MCP display is unavailable or user asks for a standalone file

Do not overwrite `91_state_diagram.md` unless the user explicitly asks to replace the base Mermaid diagram output.

## Workflow

### Step 1: Inspect Branch Changes

Run:

```bash
git diff <BASE_BRANCH>...HEAD --stat
git log <BASE_BRANCH>..HEAD --oneline
```

Identify:

- workflow or orchestration layers
- stateful entities and status columns
- UI interactions and URL/client state
- API, Server Action, usecase, domain, and persistence boundaries
- external systems, queues, webhooks, cron, retry, and failure paths

### Step 2: Decide Layers

Use these layer names exactly where possible:

```text
UI / API / Domain / DB / External / Queue / Ops / Test / Unknown
```

Map the axes as:

| Axis | Meaning |
|------|---------|
| X | process order from trigger to final result |
| Y | parallel branches or same-step alternatives |
| Z | technical layer boundary |

### Step 2.5: Decide Whether Timeline Replay Is Needed

Add `timeline` to Graph JSON when the reader must understand temporal progression, not only static topology.

Use timeline replay for:

- multi-commit or multi-phase migrations
- retries, queues, async work, background jobs, or staged failure recovery
- agent/team workflows where work moves between roles
- UI flows where the user sees different states over time
- incident, debugging, or performance narratives where the sequence explains causality
- diagrams where the user asked for replay, scrubber, timeline, animation, or time-based progression

Do not add timeline replay for:

- static entity relationships
- simple one-pass request/response flows
- small changes where Mermaid already explains the flow
- decorative animation that does not clarify a state change

Timeline quality rules:

- Keep the static Mermaid diagram as the overview. Timeline replay augments it; it does not replace it.
- Prefer 5-20 meaningful steps. Do not dump every commit or log line into `timeline.steps`.
- Each step must explain what changed and why it matters in `summary`.
- Use `eventType` plus visible labels. Do not make color the only carrier of meaning.
- If animation is disabled, the step summaries and details pane must still explain the sequence.
- Avoid moving the camera and changing node state at the same time; highlight state changes instead.

### Step 3: Create Mermaid Context

Create a compact main Mermaid diagram to act as the 2D reference in the viewer. Use `stateDiagram-v2` for lifecycle/state-heavy flows and `flowchart LR` for data-heavy flows.

Read `references/mermaid-syntax.md` before writing Mermaid if the diagram contains Japanese labels, special characters, nested state blocks, or class/entity relationships.

Validate Mermaid using `references/validator-loop.md` when a Mermaid validator MCP is available. If validation is unavailable, keep syntax conservative and mention that live validation was not available.

### Step 4: Create Graph JSON

Read `references/graph-json-schema.md` before building `91_state_diagram_graph.json`.

Graph JSON rules:

- Every node must have `id`, `label`, `layer`, and `why`.
- `why` must explain why the step exists, not just what it does.
- `files` should use repository-relative paths.
- `order` should be stable and roughly monotonic along the main path.
- Every edge must reference existing node IDs.
- Add stable `id` to edges when a timeline needs to refer to them.
- Use `type: "async"` for queue/event/background work and `type: "error"` for failure paths.
- When timeline replay is needed, add a compact `timeline` object:
  - `timeline.steps[].at` is the numeric ordering and display position, not a promise of real-time playback duration.
  - `timeline.steps[].activeNodes` and `activeEdges` reference existing graph IDs.
  - `timeline.steps[].changedNodes` and `changedEdges` identify the local delta from the previous step.
  - `timeline.steps[].summary` explains why this frame matters.
  - `timeline.steps[].eventType` stays within `normal`, `trigger`, `decision`, `error`, `fix`, `review`, and `apply` where possible.
  - Do not add node-level timeline fields in v1. The viewer infers past/future state from timeline step references.

### Step 5: Save Files

Save `91_state_diagram_3d.md` with:

- purpose and branch
- main Mermaid diagram
- short explanation of how to read the 2.5D view and the timeline replay if present
- glossary
- file map
- Graph JSON file path
- workflow-html-app MCP invocation summary

Save `91_state_diagram_graph.json` as strict JSON with no comments.

### Step 6: Display With MCP

Call:

```text
mcp__workflow-html-app__view-diagram(
  mermaidCode: "<main Mermaid diagram>",
  title: "<feature name> 2.5D state diagram",
  graphJson: "<contents of 91_state_diagram_graph.json>"
)
```

This call is required for normal completion. The final report must say whether the MCP viewer was displayed.

## Quality Bar

- Mermaid remains readable as a flat fallback.
- Graph JSON opens in workflow-html-app without breaking Mermaid display.
- Layer placement helps comprehension; do not create arbitrary decorative 3D.
- The reader can click a node and understand why it exists, what files implement it, and what it connects to.
- If timeline replay is present, the reader can scrub to a step and understand what changed since the previous step.
- Failure and retry paths are represented when they affect state or user-visible behavior.
- If Graph JSON is invalid or the MCP is unavailable, do not claim the 2.5D view was delivered.
- If timeline parsing fails but Mermaid renders, report the timeline failure separately and keep the static diagram available.
