---
name: hatch-pet
description: Create or repair a Codex v2 animated pet when the deliverable needs nine standard rows, sixteen look directions, deterministic QA, and spriteVersionNumber 2 packaging. Use for new, existing, built-in, or brand-inspired pet art; require user art or brand cues as grounding when supplied.
---

# Hatch Pet

Use this skill for a complete Codex-compatible animated pet. It covers preparation, visual generation, deterministic atlas processing, independent visual QA, repair, and v2 packaging. A new or upgraded pet must finish with an 8x11 atlas: nine standard rows plus sixteen clockwise look cells. The 8x9 atlas is an intermediate review artifact and must never be packaged.

## Contract

Read the conditional references before the corresponding stage:

- [animation-rows.md](references/animation-rows.md) is the source for row names, frame counts, durations, and state semantics.
- [codex-pet-contract.md](references/codex-pet-contract.md) is the source for package and atlas invariants.
- [qa-rubric.md](references/qa-rubric.md) is the source for visual review criteria.

The final asset is exactly 1536x2288 pixels, with 192x208 cells, and contains spriteVersionNumber 2 in pet.json. The standard 1536x1872 atlas is intermediate only. The standard row order is:

| Row | State | Frames |
| --- | --- | --- |
| 0 | idle | 8 |
| 1 | running-right | 8 |
| 2 | running-left | 8 |
| 3 | waving | 8 |
| 4 | jumping | 8 |
| 5 | failed | 8 |
| 6 | waiting | 8 |
| 7 | running | 8 |
| 8 | review | 8 |
| 9 | look directions 000 through 157.5 | 8 |
| 10 | look directions 180 through 337.5 | 8 |

Keep user-provided art, generated images, valid atlases, contact sheets, and built-in pet art as grounding inputs. Validate an existing 8x9 source before reusing rows 0-8. Preserve approved standard rows in an existing 8x11 source. A generated look repair must replace its complete coherent eight-frame row; an already-approved user-provided 16-cell set may use the individual-cell assembly option below.

If a source has a dedicated neutral/front frame, pass it through --neutral-cell. Otherwise use the approved idle/default frame. Direction 000 is up, never neutral/front; neutral is a renderer fallback to idle.

## Generation and runtime boundaries

Use $imagegen for every normal visual job: base, standard row strips, the cardinal strip, and both look row strips. Before generating, read:

~~~text
${CODEX_HOME:-$HOME/.codex}/skills/.system/imagegen/SKILL.md
~~~

Do not call an image API, image CLI, local raster generator, or one-off generation script. If $imagegen reports that a fallback needs confirmation, stop for that user confirmation. Keep prompts state-specific and concise; put contract and QA rules here and in the deterministic scripts. Never ask $imagegen for a complete atlas.

Before any bundled script, call load_workspace_dependencies and set PYTHON to the exact executable it returns. Use "$PYTHON" for every command; stop if the bundled runtime (including Pillow) is unavailable. Set:

~~~bash
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/hatch-pet"
~~~

Use one lightweight generation worker per visual job when delegation is permitted; if the user prohibits delegation, keep the same one-job boundaries in the parent. Workers return only selected_source and qa_note, never image previews, base64, or extra attachments. The parent owns manifest updates, decoded copies, deterministic scripts, packaging, and cleanup; it inspects the final contact sheet rather than every generated PNG. After copying a selected file from generated_images, remove that original and its empty directory when possible. Do not batch visual jobs into one worker or exceed three concurrent generation workers without explicit user direction.

## Brand-only requests

When the user gives only a brand, company, product, or prospect name, run a narrow discovery worker before preparation. Skip it when a concrete avatar description or reference image already supplies the visual grounding, unless the user asks for research. Prefer two to four official brand, product, docs, about, press, or brand pages; use reputable secondary sources only when official sources are too thin.

The worker writes an adaptive brief covering identity, audience, visual system, tone, product motifs, mascot translation, avoidances, evidence, and confidence. Mark inferred mascot guidance as inference. Do not copy logos, readable marks, UI screenshots, slogans, or text. End the brief with this compact handoff:

~~~text
brand_name=<canonical name>
brand_brief=<one sentence, max 45 words>
avatar_seed=<mascot-safe visual idea>
avoid=<comma-separated avoidances>
brand_sources=<comma-separated source URLs>
~~~

Save the full brief, then pass its path as --brand-discovery-file, the compact fields as --brand-name, --brand-brief, --pet-notes, and repeated --brand-source arguments. If search is unavailable and the request is only a bare name, ask for brand cues before generating.

## Run workflow

Keep this visible checklist, with one active item:

1. Getting <Pet> ready.
2. Imagining <Pet>'s main look.
3. Picturing <Pet>'s poses.
4. Hatching <Pet>.

Only mark an item complete when the real file, image, or decision exists. A repair run starts at its first affected item.

### 1. Prepare

~~~bash
"$PYTHON" "$SKILL_DIR/scripts/prepare_pet_run.py" \
  --pet-name "<Name>" \
  --description "<one sentence>" \
  --reference /absolute/path/to/reference.png \
  --output-dir /absolute/path/to/run \
  --pet-notes "<stable pet description>" \
  --brand-discovery-file /absolute/path/to/brand-discovery.md \
  --brand-name "<optional researched brand name>" \
  --brand-brief "<optional compact brand cue sentence>" \
  --brand-source "https://example.com/source" \
  --style-preset auto \
  --style-notes "<optional style notes>" \
  --force
~~~

All arguments are optional except those needed to express the request. For text-only input, use --pet-notes and omit --reference. The script infers missing name, description, chroma key, and output directory.

Inspect the manifest directly:

~~~bash
jq '.jobs[] | {id, kind, status, depends_on, prompt_file, retry_prompt_file, input_images, output_path, derivation_policy}' /absolute/path/to/run/imagegen-jobs.json
~~~

The graph has up to thirteen jobs: base, nine standard row strips, look-cardinals, look-row-9, and look-row-10. A job is ready only when it is incomplete and all depends_on jobs are complete. Base may be prompt-only. Every row job must attach every input_images entry, including the canonical base reference and the row layout guide. Layout guides are invisible construction references; reject guide boxes, labels, borders, center marks, guide colors, or guide backgrounds in the output.

### 2. Generate and record outputs

Generate base first, then idle and running-right as identity and gait checks. Generate all other standard rows independently, or derive running-left only after running-right is generated, visually inspected, and explicitly approved as safe to mirror. Never derive waiting, running, failed, review, jumping, or waving from another state. For a transport-level Bad Request, retry the same row once using its retry_prompt_file and the same references; if it fails again, stop and report the row and prompt paths.

Copy the selected output exactly into the manifest's decoded output path before marking the job complete:

~~~bash
RUN_DIR=/absolute/path/to/run
JOB_ID=<job-id>
SOURCE=/absolute/path/to/generated-output.png
OUTPUT_REL=$(jq -r --arg id "$JOB_ID" '.jobs[] | select(.id == $id) | .output_path' "$RUN_DIR/imagegen-jobs.json")
mkdir -p "$(dirname "$RUN_DIR/$OUTPUT_REL")"
cp "$SOURCE" "$RUN_DIR/$OUTPUT_REL"
if [ "$JOB_ID" = "base" ]; then
  mkdir -p "$RUN_DIR/references"
  cp "$RUN_DIR/$OUTPUT_REL" "$RUN_DIR/references/canonical-base.png"
fi
UPDATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TMP_MANIFEST=$(mktemp)
jq --arg id "$JOB_ID" --arg source "$SOURCE" --arg at "$UPDATED_AT" \
  '(.jobs[] | select(.id == $id)) += {status: "complete", source_path: $source, completed_at: $at}' \
  "$RUN_DIR/imagegen-jobs.json" > "$TMP_MANIFEST"
mv "$TMP_MANIFEST" "$RUN_DIR/imagegen-jobs.json"
~~~

For each standard row, extract and inspect immediately:

~~~bash
ROW_QA_DIR="$RUN_DIR/qa/rows/$JOB_ID"
"$PYTHON" "$SKILL_DIR/scripts/extract_strip_frames.py" \
  --decoded-dir "$RUN_DIR/decoded" --output-dir "$ROW_QA_DIR/frames" \
  --states "$JOB_ID" --method auto
"$PYTHON" "$SKILL_DIR/scripts/inspect_frames.py" \
  --frames-root "$ROW_QA_DIR/frames" --json-out "$ROW_QA_DIR/review.json" \
  --states "$JOB_ID" --require-components
~~~

Errors block acceptance. Review warnings before continuing. If only component extraction fails while the source strip has stable scale and placement, rerun with --method stable-slots and --allow-stable-slots; do not use that mode to hide clipping or a bad source strip. Chroma cleanup belongs to the one post-assembly despill pass and does not trigger row regeneration.

To derive running-left while preserving temporal order:

~~~bash
"$PYTHON" "$SKILL_DIR/scripts/derive_running_left_from_running_right.py" \
  --run-dir /absolute/path/to/run \
  --confirm-appropriate-mirror \
  --decision-note "<why the mirror preserves identity>"
~~~

If SOURCE is under ${CODEX_HOME:-$HOME/.codex}/generated_images, remove it only after the decoded copy exists:

~~~bash
GENERATED_ROOT="${CODEX_HOME:-$HOME/.codex}/generated_images"
case "$SOURCE" in
  "$GENERATED_ROOT"/*) rm -f "$SOURCE"; rmdir "$(dirname "$SOURCE")" 2>/dev/null || true ;;
esac
~~~

### 3. Standard atlas gate

After all nine standard jobs pass incremental checks, build and review the intermediate 8x9 atlas:

~~~bash
mkdir -p "$RUN_DIR/final" "$RUN_DIR/qa"
"$PYTHON" "$SKILL_DIR/scripts/extract_strip_frames.py" \
  --decoded-dir "$RUN_DIR/decoded" --output-dir "$RUN_DIR/frames" \
  --states all --method auto
"$PYTHON" "$SKILL_DIR/scripts/inspect_frames.py" \
  --frames-root "$RUN_DIR/frames" --json-out "$RUN_DIR/qa/review.json" \
  --require-components
"$PYTHON" "$SKILL_DIR/scripts/compose_atlas.py" \
  --frames-root "$RUN_DIR/frames" \
  --output "$RUN_DIR/final/spritesheet.png" \
  --webp-output "$RUN_DIR/final/spritesheet.webp"
"$PYTHON" "$SKILL_DIR/scripts/make_contact_sheet.py" \
  "$RUN_DIR/final/spritesheet.webp" --output "$RUN_DIR/qa/contact-sheet.png"
"$PYTHON" "$SKILL_DIR/scripts/render_animation_previews.py" \
  --frames-root "$RUN_DIR/frames" --output-dir "$RUN_DIR/qa/previews"
~~~

Inspect the contact sheet and previews before look generation. Block identity, style, prop-handedness, silhouette, clipping, wrong facing, reversed or inert cadence, guide pixels, accidental interior transparent holes, detached effects, or white/nontransparent backgrounds. If extraction itself causes size or baseline pops and the source is stable, rerun the deliberate stable-slots correction and all dependent checks. Do not package or clean up at this gate.

### 4. Look mechanics and directions

After rows 0-8 pass, write qa/look-mechanics.md before generating the cardinal strip. State what stays anchored, what leads and follows the gaze, how the head/body/appendages deform, and how each prop is constrained. Decide how the original eye construction moves: physical eyeballs move as whole eye surfaces; printed, sticker, or screen eyes keep their surface fixed while appropriate features change. Do not add googly eyes, replacement whites, floating pupils, or a second eye layer. Pupil-only motion needs a mechanics reason.

Use one coherent cardinal strip in viewer/screen coordinates and this fixed order: 000 up, 090 screen-right, 180 down, 270 screen-left. Extract and approve all four at final pet size:

~~~bash
CHROMA_KEY=$(jq -r '.chroma_key.hex' "$RUN_DIR/pet_request.json")
"$PYTHON" "$SKILL_DIR/scripts/extract_cardinal_anchors.py" \
  --strip "$RUN_DIR/decoded/look-cardinals.png" \
  --output-dir "$RUN_DIR/decoded/look-anchors" \
  --chroma-key "$CHROMA_KEY" \
  --json-out "$RUN_DIR/qa/cardinal-anchors.json"
"$PYTHON" "$SKILL_DIR/scripts/compose_cardinal_anchor_strip.py" \
  --anchors-dir "$RUN_DIR/decoded/look-anchors" \
  --output "$RUN_DIR/decoded/look-anchors-approved.png"
~~~

If a cardinal fails, regenerate that anchor with prompts/look-anchor-repairs/<degree>.md and rerun extraction/composition. A wrong or ambiguous cardinal blocks all look rows. For ordinary humanoids, preserve facial proportions with eye/eyelid/eyebrow participation plus restrained head/neck follow-through. For eyeless objects, preserve the readable face or surface and use a natural hinge, tip, lean, bend, pitch, yaw, or attached-part motion; do not spin the whole sprite unless it is literally a rotating object. Keep a stable base/torso anchor, even 22.5-degree motion, continuous prop attachment, and no broad raster warps.

Generate row 9 as one complete coherent family from the approved cardinals, in 000, 022.5, 045, 067.5, 090, 112.5, 135, 157.5 order. Register it with the final transform and review before row 10:

~~~bash
"$PYTHON" "$SKILL_DIR/scripts/assemble_extended_atlas.py" \
  --base-atlas "$RUN_DIR/final/spritesheet.webp" \
  --look-row-9 "$RUN_DIR/decoded/look-row-9.png" \
  --neutral-cell "$RUN_DIR/frames/idle/00.png" \
  --chroma-key "$CHROMA_KEY" --chroma-threshold 96 \
  --registered-row-output "$RUN_DIR/qa/look-row-9-registered.png" \
  --registration-manifest-output "$RUN_DIR/qa/look-row-9-registration.json"
~~~

Inspect the eight registered cells at normal pet size, record per-direction semantics and continuity, and regenerate the complete row for any hard failure. Only after row 9 passes may row 10 be generated. Row 10 contains 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5 and must use the approved cardinal strip plus completed row 9. The boundary pairs 157.5 -> 180 and 337.5 -> 000 must be continuous. Never individually patch a newly generated look cell, mirror/recenter adjacent cells, or let every cell remain front-facing.

Hard direction failures are a wrong or ambiguous cardinal, wrong quadrant, visible reversal, conspicuous snap/scale or identity change, broken prop attachment, clipping, accidental interior hole, replacement eyes, or whole-sprite rotation that breaks identity. Similar intermediate poses, subtle diagonal cues, blind disagreement, or metric warnings are review warnings when labeled normal-size loop review confirms the intended axes and cohesion.

### 5. Extended assembly and QA

Generate look-cardinals, row 9, and row 10 through $imagegen with the canonical base and all manifest-listed inputs. Do not use locally drawn, tiled, transformed, or code-generated replacements. Assemble both coherent rows:

~~~bash
"$PYTHON" "$SKILL_DIR/scripts/assemble_extended_atlas.py" \
  --base-atlas "$RUN_DIR/final/spritesheet.webp" \
  --registered-row-9 "$RUN_DIR/qa/look-row-9-registered.png" \
  --row-9-registration "$RUN_DIR/qa/look-row-9-registration.json" \
  --look-row-10 "$RUN_DIR/decoded/look-row-10.png" \
  --neutral-cell "$RUN_DIR/frames/idle/00.png" \
  --chroma-key "$CHROMA_KEY" --chroma-threshold 96 \
  --output "$RUN_DIR/final/spritesheet-extended.png" \
  --webp-output "$RUN_DIR/final/spritesheet-extended.webp" \
  --manifest-output "$RUN_DIR/final/spritesheet-extended.json"
~~~

For an already-approved user-provided 16-cell set only, the alternate input is:

~~~bash
"$PYTHON" "$SKILL_DIR/scripts/assemble_extended_atlas.py" \
  --base-atlas "$RUN_DIR/final/spritesheet.webp" \
  --look-cells-dir /absolute/path/to/look-cells \
  --neutral-cell "$RUN_DIR/frames/idle/00.png" \
  --chroma-key "$CHROMA_KEY" --chroma-threshold 96 \
  --output "$RUN_DIR/final/spritesheet-extended.png" \
  --webp-output "$RUN_DIR/final/spritesheet-extended.webp" \
  --manifest-output "$RUN_DIR/final/spritesheet-extended.json"
~~~

The assembler recovers complete pose groups, applies one shared scale/baseline/lower-body anchor, and checks final-cell edges. If recovery or fit is ambiguous, resynthesize the complete row; never rescale row 9, patch a final cell, or relax acceptance.

Run the single deterministic despill pass, then v2 validation and sheets:

~~~bash
"$PYTHON" "$SKILL_DIR/scripts/despill_chroma_edges.py" \
  "$RUN_DIR/final/spritesheet-extended.png" \
  --output "$RUN_DIR/final/spritesheet-extended.png" \
  --webp-output "$RUN_DIR/final/spritesheet-extended.webp" \
  --chroma-key "$CHROMA_KEY" \
  --json-out "$RUN_DIR/qa/chroma-despill-extended.json"
"$PYTHON" "$SKILL_DIR/scripts/validate_atlas.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --json-out "$RUN_DIR/final/validation-extended.json" \
  --chroma-key "$CHROMA_KEY" --require-v2
"$PYTHON" "$SKILL_DIR/scripts/make_contact_sheet.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --output "$RUN_DIR/qa/contact-sheet-extended.png"
"$PYTHON" "$SKILL_DIR/scripts/make_direction_qa_sheet.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --output "$RUN_DIR/qa/look-directions.png"
~~~

The despill report and validator are authoritative for chroma. Once both pass, do not regenerate imagery, tune thresholds, or run another cleanup pass for perceived fringe. A look sheet with chroma panels, guide pixels, cropped bodies, repeated tiles, or accidental interior holes still fails visual QA.

Record pass, warning, or fail for every direction in qa/direction-semantics.json, with expected, observed, reason, and separate horizontal/vertical evidence where applicable. Review qa/look-continuity.json as visual evidence; metrics alone do not fail a coherent loop. The final visual worker must inspect both contact sheets, previews, look-directions.png, semantics, continuity, blind validation, and v2 validation, and return:

~~~text
visual_qa=pass|fail
qa_note=<one sentence>
direction_semantics=<semicolon-separated direction verdicts>
review_warnings=<semicolon-separated warnings, or none>
repair_rows=<comma-separated row ids, or none>
repair_notes=<short notes, or none>
~~~

The worker must not edit files, queue repairs, package, clean up, or inspect unrelated files. Do not let the parent self-approve a repaired look direction; use this independent worker or explicit user inspection.

### 6. Blind axis review

After both look rows exist, create the randomized unlabeled challenge:

~~~bash
"$PYTHON" "$SKILL_DIR/scripts/make_direction_blind_qa_sheet.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --output "$RUN_DIR/qa/direction-blind-pairs.png" \
  --answer-key "$RUN_DIR/qa/direction-blind-answer-key.json"
~~~

Give three fresh isolated workers only direction-blind-pairs.png. They classify every A/B cell on its named horizontal or vertical axis as screen-left, screen-right, up, down, or ambiguous. They must not see labels, prompts, degree order, answer key, atlas, or another verdict. Combine exactly three verdicts and validate the hidden key:

~~~bash
"$PYTHON" "$SKILL_DIR/scripts/combine_direction_blind_verdicts.py" \
  --verdicts "$RUN_DIR/qa/direction-blind-verdicts-1.json" \
  --verdicts "$RUN_DIR/qa/direction-blind-verdicts-2.json" \
  --verdicts "$RUN_DIR/qa/direction-blind-verdicts-3.json" \
  --json-out "$RUN_DIR/qa/direction-blind-verdicts.json"
"$PYTHON" "$SKILL_DIR/scripts/validate_direction_blind_verdicts.py" \
  --answer-key "$RUN_DIR/qa/direction-blind-answer-key.json" \
  --verdicts "$RUN_DIR/qa/direction-blind-verdicts.json" \
  --json-out "$RUN_DIR/qa/direction-blind-validation.json"
"$PYTHON" "$SKILL_DIR/scripts/measure_direction_continuity.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --json-out "$RUN_DIR/qa/look-continuity.json"
~~~

The cardinal pairs 000/180 and 090/270 are hard gates. Intermediate mismatches or ambiguity remain warnings for labeled loop review. A worker that has seen labels or direction prompts cannot perform blind classification.

### 7. Repair and package

Classify each failure before acting: semantics, identity, source geometry, connectivity, extraction, chroma, continuity, or final QA. Use deterministic correction first; regenerate only a genuinely wrong source. Compare against the prior result and require fewer or less severe failures. If the same root failure recurs twice, change the mechanics, construction, extraction strategy, or row prompt rather than varying wording. Major failures require complete-row repair. A minor blind/intermediate warning may be overridden only in qa/blind-review-resolution.json with severity, failed checks, labeled/continuity evidence, and reviewed_by parent or user; never override a cardinal, deterministic, clipping, identity, hole, or reversal failure.

After all gates pass, package the cleaned v2 atlas:

~~~bash
PET_ID=$(jq -r '.pet_id' "$RUN_DIR/pet_request.json")
DISPLAY_NAME=$(jq -r '.display_name' "$RUN_DIR/pet_request.json")
DESCRIPTION=$(jq -r '.description' "$RUN_DIR/pet_request.json")
PET_DIR="${CODEX_HOME:-$HOME/.codex}/pets/$PET_ID"
mkdir -p "$PET_DIR"
cp "$RUN_DIR/final/spritesheet-extended.webp" "$PET_DIR/spritesheet.webp"
jq -n --arg id "$PET_ID" --arg displayName "$DISPLAY_NAME" --arg description "$DESCRIPTION" \
  '{id: $id, displayName: $displayName, description: $description, spriteVersionNumber: 2, spritesheetPath: "spritesheet.webp"}' \
  > "$PET_DIR/pet.json"
~~~

Write a run summary containing the run directory, atlas, v2 validation, despill, contact sheets, direction semantics, blind validation, continuity, review, and package paths. Keep pet_request.json, final/spritesheet-extended.webp, final/validation-extended.json, qa/chroma-despill-extended.json, both contact sheets, look-directions.png, direction-blind-pairs.png, direction-blind-answer-key.json, direction-blind-verdicts.json, direction-blind-validation.json, direction-semantics.json, look-continuity.json, qa/review.json, previews, run-summary.json, and any used minor-resolution file. Remove prompts, guides, row strips, extracted PNGs, the intermediate 8x9 atlas, and the manifest unless the user requests debug artifacts.

## Worker contracts

Use the smallest capable current runtime model, resolved through model routing, for brand discovery and visual workers unless the user explicitly prohibits delegation. The parent handles all orchestration and writes.

- Base worker: read prompts/base-pet.md and listed references; use $imagegen; return only selected_source and one QA sentence. Do not edit manifests, decoded files, scripts, or packages.
- Row worker: handle exactly one row; read its prompt, retry prompt, look-mechanics file when applicable, and all inputs; generate the complete strip coherently; sanity-check count, identity, chroma, separation, clipping, baseline, and effects; return only selected_source and one QA sentence.
- Cardinal worker: generate the four slots in order and cite concrete screen-coordinate landmarks; ambiguous cardinals fail.
- Blind worker: inspect only the randomized A/B sheet and return one JSON object with every pair; do not infer from pair order.
- Final worker: inspect all supplied QA artifacts and return the compact result above; do not edit, repair, package, or clean up.

## Acceptance

Do not report success or install a pet until all of these hold:

- the final PNG/WebP is exactly 1536x2288 with 192x208 cells and pet.json has spriteVersionNumber 2;
- rows and durations match animation-rows.md, all used cells are populated, and unused cells are transparent;
- qa/review.json has no errors, standard previews show complete non-inert state motion, and identity/style/props remain coherent;
- the cardinal strip is extracted and semantically approved, both coherent look rows use it, row 9 passes before row 10, and the fixed clockwise order is preserved;
- post-registration edge checks, labeled semantics for all 16 directions, continuity review, focused direction sheet, three-worker blind validation, and independent final visual QA are complete;
- qa/chroma-despill-extended.json and validate_atlas.py --require-v2 both pass with the run's chroma key;
- no wrong cardinal, wrong quadrant, reversal, clipping, accidental interior hole, detached forbidden effect, replacement eye design, or unresolved major QA failure remains;
- package files are staged together under ${CODEX_HOME:-$HOME/.codex}/pets/<pet-id>/.
