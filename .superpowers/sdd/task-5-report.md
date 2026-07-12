# Task 5 Report: Browser Model and Two-Layer UI

## Status

Implemented the browser-facing Task Hub while preserving the existing embedded snapshot v1 and manual-file Roadmap Viewer paths.

## Delivered

- Added browser model functions for three task sections, settings normalization, approval normalization, and distinct design/implementation Plan extraction.
- Kept candidate memory matches unconfirmed and excluded their files from the selected task detail.
- Added the desktop persistent-sidebar and mobile list/detail Task Hub shell.
- Rendered detail content in the required order with the existing safe `renderWorkflowMarkdown()` implementation.
- Added visible provider disconnect, last-successful-sync, per-task freshness/stopped status, two-second polling, five-second heartbeat, keyboard list navigation, mobile back navigation, reduced-motion compatibility, and persisted settings.
- Implemented only the existing `/open` endpoint. A 409 response copies the returned Codex thread ID, with a visible text fallback when clipboard access is unavailable.
- Scope expansion approved by the lead: added the minimal backend `GET /` route so `start_url()` can load the self-contained viewer. The shell contains no session key, uses `Cache-Control: no-store`, and all `/api/*` routes remain header-authenticated.

## TDD Evidence

- Red: model tests failed because `groupTaskSections`, `extractPlanSections`, and `taskHubSettings` did not exist.
- Green: implemented the minimal model functions and exported them through the existing model marker.
- Red: backend root contract returned 403.
- Green: served `tools/roadmap_viewer.html` at `/` before the API authentication boundary.
- Refactor/self-review: fixed static-mode visibility (`[hidden]`), filtered recent completion by the stored window, persisted collapse state, and prevented the polling path from forcing heading focus.

## Verification

- `node --test tests/roadmap-viewer.test.mjs` — 20 passed.
- `python3 -m unittest tests/test_generate_roadmap_view.py tests/test_roadmap_task_hub.py -q` — 31 passed.
- `python3 -m py_compile scripts/generate-roadmap-view.py scripts/roadmap_task_hub.py` — passed.
- Extracted executable inline scripts (excluding the embedded JSON snapshot block), then `node --check /tmp/roadmap-viewer-inline.js` — passed.
- `git diff --check` — passed.

## Self-review

- Confirmed raw HTML and JavaScript links remain inert and malformed tables remain visible as escaped source.
- Confirmed no session key is embedded in the served document and unauthenticated API access remains 403.
- Confirmed hub detection is fragment-only and the original static initialization path is unchanged when no session fragment exists.

## Concerns

- No browser automation suite is present for this self-contained HTML. DOM structure, behavior hooks, model logic, backend integration, and inline syntax are covered, but the final responsive appearance was not exercised by Playwright.
