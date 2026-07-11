---
name: one-page-concept-sketch
description: Create a hand-drawn, black-and-white concept sketch that makes an idea understandable at a glance without omitting central information. Use when the user asks for an image, diagram, infographic, explainer sheet, one-page summary, whiteboard-style visual, handwritten Japanese style, sketchnote, or one image that shows what this is about. Invoke $imagegen for generated raster visuals, and preserve an exact SVG/HTML-derived PNG when Japanese text or layout must remain accurate. For automation notes in this Vault, save the result under Inbox/automation/concept-sketches/ and follow [[11_one-page-concept-sketch]].
---

# One Page Concept Sketch

Turn an idea into one readable knowledge image that explains the concept, not a decorative poster.
For a note, article, paper, transcript, meeting record, or research summary, the primary artifact is a text-bearing Exact Board PNG.
The image itself must explain what the source is about, what it says, why the conclusion follows, what the reader should decide or do, and what the desired end state is.
Dual mode may add a separately named imagegen companion, but the exact board remains the authoritative knowledge artifact.
Do not reduce a long source into a few vague labels.
For source-based automation notes, the artifact must let a reader reconstruct what was read, what changed, what matters, and what decision remains without opening the source note.
The saved Markdown note must also work as a one-page text note.
Images are embedded evidence and memory hooks, not a replacement for the note's own readable explanation.

Optimize for three outcomes:

- A reader can say what the topic is within 3 seconds.
- A reader can explain the core mechanism within 30 seconds.
- A reader can identify the desired end state and the next decision or action without opening the source note.
- The visual works as an A4 landscape board: wide enough to compare sections side by side, but still readable when zoomed or previewed on a phone.

## Vault Output Contract

For Vault automations, follow [[11_one-page-concept-sketch]].

- Save the artifact as `Inbox/automation/concept-sketches/concept-sketch-YYYY-MM-DD-<lane>.md`. If that note already exists, create `-v2.md` or the next free version and link the actual saved note; do not overwrite or rename the earlier note.
- Create `Inbox/automation/concept-sketches/` before saving if it is missing.
- Link it from the source note and from `Daily/YYYY-MM-DD.md`.
- Keep the source coverage map in the saved note.
- Keep a `## Text Board` section in the saved note.
  This section must restate the claim, inputs, findings, mechanism, decision/action, and limits in Markdown text so the note remains understandable when images are not opened.
- Save the Exact Board as `attachments/<lane>-concept-YYYY-MM-DD.png`. If it already exists and replacement was not explicitly requested, use `-v2.png` or the next free version.
- Save an imagegen output as `attachments/<lane>-concept-YYYY-MM-DD-imagegen.png`. If that name already exists and replacement was not explicitly requested, use `-imagegen-v2.png` or the next free version.
- In Dual mode, embed the Exact Board first and the imagegen companion in a separate `Imagegen Companion` section. In Imagegen mode, embed only the `-imagegen.png` file under `Sketch`.
- Use A4 landscape orientation for both Exact Board and imagegen companion by default.
  The target aspect ratio is about 1.414:1, such as 1400 x 990 CSS px rendered at 2x, unless the user explicitly asks for portrait or square.
- Do not rename or delete existing notes.
- Put final Markdown artifacts under `Inbox/automation/concept-sketches/` and final image artifacts under `attachments/`. Do not write final artifacts elsewhere unless the caller explicitly asks for another target. Temporary files outside the Vault are allowed only for an explicitly approved CLI fallback.

## Output Mode

Choose the production mode before drafting. Do not stop at SVG/HTML or a prompt when the user asked for an actual image.

- **Exact Board mode**: Use SVG or HTML/CSS when exact Japanese text, labels, citations, numbers, or long explanations must be readable. Rasterize the completed board deterministically and save the resulting PNG.
- **Imagegen mode**: Invoke `$imagegen` and the built-in `image_gen` tool when the user mainly wants a bitmap illustration, mood, metaphor, or rough visual direction. Save the generated bitmap with the `-imagegen.png` suffix and embed it as the only image under `Sketch`.
- **Dual mode**: Keep the exact board PNG as the main knowledge artifact and also invoke `$imagegen` to create a separate illustrative companion. Share the core claim and semantic structure, not the Exact Board's dense layout or long text.
- **Prompt-only mode**: Use a prompt plus layout spec only when the user explicitly asks for guidance instead of an actual file.

For source-based summaries, including Vault automations, use Exact Board mode by default.
Use Imagegen or Dual mode only when the caller explicitly asks for generated illustration, metaphor, mood, or an imagegen companion.
An imagegen companion is optional supporting material and never counts as the summary image or primary artifact.

Do not pass a completed SVG or HTML board to imagegen as an edit target. Rasterization is the exact conversion path. For the imagegen companion, translate the coverage map, visual hierarchy, metaphor, and style into a fresh generation prompt.

If using imagegen, omit text by default. Put exact Japanese wording in the Exact Board. This text-free policy applies only to the optional imagegen companion, never to the primary Exact Board summary. If the generated image's meaning is wrong, revise once with a concrete prompt; if it still fails, keep the Exact Board as primary and record the imagegen limitation rather than presenting the companion as authoritative.
Do not make the imagegen companion the only visible explanation.
If the companion is mostly icons, metaphors, or a flow drawing, the Markdown `Text Board` must explicitly say what the drawing represents and why it matters.

### Imagegen triggers

Treat these as explicit Imagegen requests:

- `$imagegen`
- `imagegen`
- a request that explicitly asks for AI-generated imagery, a generated illustration, or a generated bitmap
- `imagen` when the surrounding context clearly uses it to mean image generation

Do not treat `PNG conversion`, `make this viewable as an image`, `make this readable in Obsidian`, or `convert the SVG to an image` alone as an Imagegen trigger. Those phrases request deterministic Exact Board rasterization unless another explicit Imagegen trigger also applies.

Mode priority:

1. Explicit prompt or layout guidance only: Prompt-only mode.
2. Explicit Imagegen trigger plus exact Japanese, citations, or numbers: Dual mode.
3. Explicit Imagegen trigger plus illustration, mood, or metaphor as the main goal: Imagegen mode.
4. Source-based summary or Vault automation without an explicit Imagegen trigger: Exact Board mode.
5. Otherwise: Exact Board mode.

## Imagegen Invocation Contract

When Imagegen or Dual mode applies:

1. Complete the Source Coverage Contract and text layout spec first.
2. Invoke `$imagegen` and use the built-in `image_gen` tool. Do not merely return a prompt or say that an image could be generated.
3. Generate a new bitmap from the concept's meaning. Do not use the SVG/HTML file as an image-edit target, and do not copy the dense Exact Board layout into the generation prompt.
4. Include the use case, A4 landscape composition, monochrome hand-drawn style, text policy, required concepts, and forbidden decorative elements in the prompt.
5. Inspect the generated result visually. Check topic fidelity, missing core claims, accidental text, malformed Japanese, cropping, A4 landscape shape, and readability.
6. Persist the selected output under `attachments/` with the `-imagegen.png` suffix. Never overwrite an existing image unless the user explicitly requested replacement.
7. Embed the saved file in the concept-sketch note with an Obsidian image wikilink.
8. If the tool is unavailable, blocked, or does not return a persistable artifact, do not silently skip it. In Dual mode, preserve the Exact Board but mark Dual mode and the imagegen companion incomplete. In Imagegen mode, no final image exists, so mark the entire task incomplete. Never claim a saved image or add a broken wikilink.

Use this prompt skeleton:

```text
Use case: one-page concept illustration
Source claim: <one sentence>
Required concepts: <three to six concrete ideas>
Mechanism or contrast: <causal flow, branch, before/after, or trade-off>
Composition: <simplified visual hierarchy created for the imagegen companion; A4 landscape by default>
Style: monochrome hand-drawn sketchnote, warm-white paper, thin imperfect black ink
Text: no text
Avoid: letters, Japanese pseudo-text, logos, watermark, decorative filler, stock-poster style, glossy effects, color gradients, invented facts
```

### Imagegen persistence gate

- Do not assume that built-in `image_gen` accepts a Vault destination argument.
- Before generation, record the known candidate files under `$CODEX_HOME/generated_images/` when the runtime exposes that directory.
- After generation, select only the concrete file returned by the tool or a newly created output that can be tied unambiguously to that call. Do not guess from modification time alone and do not select a file that existed before the call.
- Inspect the source image's real format with `file` or image metadata. Copy it directly only when it is actually PNG. If it is WebP, JPEG, or another bitmap format, convert the image data to PNG before using a `.png` filename; never change only the extension.
- Save the selected PNG under `attachments/` before adding its wikilink. Use `-imagegen-v2.png` or the next free version if the intended name already exists and replacement was not requested.
- Verify that the saved file exists, its real format is PNG, it opens successfully, and it matches the intended output. Add the Obsidian wikilink only after this check passes.
- Some runtimes do not permit local post-processing after a built-in image generation call. If the output path cannot be obtained uniquely, or the runtime cannot perform the copy, do not claim that the image was saved and do not create a broken wikilink.
- In Dual mode, a blocked persistence gate leaves only the Exact Board complete; mark Dual mode and the Imagegen Companion incomplete.
- In Imagegen mode, a blocked persistence gate means the task has no completed image. Mark the task incomplete, do not claim Vault persistence, and do not create a wikilink.
- If the user explicitly approves the system imagegen CLI fallback, keep CLI intermediates and raw outputs outside the Vault, such as under `/private/tmp/imagegen/<task>/`. Copy only the final verified image into `attachments/`. Never create and then delete CLI temporary files inside this Vault.

## Source Coverage Contract

When the input is an article, URL, paper, transcript, long note, or user-specified source, do not start from visual layout.
First establish what must be represented.

Create a compact coverage map before drawing:

- **Source scope**: what source material was read and what was not accessible.
- **Core claims**: the source's central claims, not every sentence.
- **Mechanism**: the causal chain, decision rule, process, or trade-off that explains those claims.
- **Evidence anchors**: the facts, examples, or citations that support each core claim.
- **Nuance and limits**: caveats, counterpoints, uncertainty, and scope restrictions.
- **Visual slot**: where each core claim appears in the image.

Every core claim must be either represented in the image or explicitly excluded as non-essential for the requested visual.
Do not silently drop a claim because it is inconvenient to draw.

If a source cannot fit into one readable image, keep the image focused and provide a short companion note with:

- what the image covers,
- what was intentionally left out,
- why it was left out,
- where the omitted detail belongs if the user wants a fuller artifact.

## Copy-to-Learn Contract

For a source-based summary, organize the Exact Board so that copying it by hand in the indicated order reconstructs the source's reasoning.
The board is not a collection of independent cards.
It is a guided learning path whose sequence makes each statement prepare the reader for the next one.

Use this learning sequence unless the source itself requires another order:

1. **Question**: what problem or question the source addresses.
2. **Premise**: the background, definitions, or current condition needed to follow the argument.
3. **Reasoning**: the causal chain, comparison, process, or decision rule that connects the premise to the conclusion.
4. **Concrete example**: one example that makes the abstract mechanism easier to understand.
5. **Contrast or change**: the wrong and better framing, or the current and desired states.
6. **Conclusion**: what the reader should understand, decide, or do.
7. **Desired end state**: what should be observably true when the conclusion has been applied successfully.

Show the reading and copying order with spatial flow, numbering, or meaningful arrows.
Each step must use a short sentence or clause that makes sense when copied into a notebook.
Do not rely on isolated nouns, category labels, icons, or unlabeled arrows to carry the reasoning.
Do not add a separate reproduction exercise, worksheet, or "try it yourself" area unless the caller explicitly requests one.

## Information Completeness Guardrail

Rework the artifact if any of these are true:

- The visual alone does not reveal the source's subject, target, and conclusion.
- The visual does not state the desired end state or show how it differs from the current state.
- The visual contains no meaningful explanatory text beyond a title or isolated keywords.
- Bullets are only keywords, source titles, or labels without why they matter.
- The input, interpretation, and decision areas do not contain concrete source material.
- Major sections in the source note have no matching slot in the visual or companion note.
- The reader must open the source note to understand the meaning, not merely to inspect details.

In Dual mode, evaluate Source Coverage and reconstructability primarily against the Exact Board. The imagegen companion passes when it reinforces the core claim, does not contradict the Exact Board, and contains no meaningless pseudo-text; it does not need to reproduce the note's exact wording.

For automation notes, the one-page artifact must include:

- **Claim**: the day's conclusion in one sentence.
- **Inputs**: specific sources, scan ranges, or materials used.
- **Findings**: three to six concrete findings, each with enough context to stand alone.
- **Mechanism**: two to four steps explaining why the claim follows or how information flows.
- **Decision / Action**: what the human should decide, inspect, or do next.
- **Desired end state**: what should be true when the idea, recommendation, or process has been carried through successfully.
- **Limits**: inaccessible sources, unverified details, and intentionally omitted material.

For dense daily notes, prefer an A4 landscape HTML/CSS one-page board or a larger landscape SVG over tiny text labels.
Completeness and reconstructability are more important than looking minimal.

## Structure

Use this layout grammar by default:

1. Title at top center.
2. One-line subtitle that states the claim.
3. A4 landscape canvas with three to five information sections arranged side by side where useful.
4. Each section contains concrete source material, not only category names, and its place in the reading order is visible.
5. Put one boxed "Decision" or "Point" note in the middle or right side.
6. Show the desired end state explicitly, using a labeled box, endpoint, before/after destination, or acceptance condition.
7. End with a bottom summary band that names the takeaway, action, desired end state, and limit.

Prefer a single argument over a catalog.
If the source has many ideas, select the one tension that explains the rest.

## Visual Language

Use a restrained hand-drawn style:

- White or warm-white background.
- Black ink only, with gray allowed for secondary guide lines.
- Thin, slightly imperfect strokes.
- Rounded rectangles, speech bubbles, arrows, timelines, simple stick figures, and small charts.
- Handwritten-looking Japanese and Latin text, monoline, rounded, with generous spacing.
- No gradients, glossy effects, stock illustration, heavy shadows, or dense color palettes.

## Content Compression

Before drawing, reduce the idea to:

- **Title**: concrete subject name.
- **Claim**: one sentence that changes how the reader thinks.
- **Mechanism**: two or three steps that explain why the claim is true.
- **Contrast**: wrong intuition versus better framing.
- **Takeaway**: what to preserve, avoid, decide, or do next.
- **Desired end state**: the observable condition that should exist after the recommendation or process succeeds.

Delete only supporting details that do not change the source's core claims, mechanism, caveats, or decision implications.
If a sentence cannot fit in a small label, turn it into a shorter noun phrase or move it to a point box.
If a detail is important but too dense for the image, preserve it in the companion note rather than pretending it does not matter.
Keep proper nouns, task names, article names, hypotheses, and verification ideas when they identify the source's substance.

## Text Rules

Keep labels concise but meaningful. A source-based Exact Board must contain enough readable text to stand alone; do not optimize for short labels at the cost of comprehension.

- Title: 6 to 14 Japanese characters, or 2 to 5 English words.
- Subtitle: one line.
- Box labels: 3 to 12 characters where possible.
- Point boxes: up to 5 short lines.
- Body captions: one idea per line.

Avoid long prose inside the image.
If a concept needs long prose, make the image simpler and provide the prose outside the image.

## Common Patterns

Use one of these patterns:

- **Cost of early commitment**: show "decide now" losing options versus "wait for information" preserving choices.
- **Before/after**: show the old model on the left and the better model on the right.
- **Trade-off map**: show two axes, the risky zone, and the recommended zone.
- **Lifecycle**: show how a thing moves through states over time.
- **System loop**: show inputs, process, feedback, and failure point.
- **Decision rule**: show a branch and the criterion that chooses the branch.

Do not mix more than two patterns in one image.

## Workflow

1. Identify whether the request is source-based or concept-only.
2. For source-based requests, run the Source Coverage Contract before visual drafting.
3. Extract the concept and write the compression bullets.
4. Choose one common pattern.
5. Draft the Copy-to-Learn sequence and the Markdown Text Board as text first: question, premise, reasoning, concrete example, contrast or change, conclusion, desired end state, and limits.
6. Map every core claim to a visible slot or the companion note.
7. Produce the artifact in Exact Board, Imagegen, or Dual mode. For source-based summaries and Vault automations, default to Exact Board mode unless Imagegen was explicitly requested.
8. When Imagegen or Dual mode applies, invoke `$imagegen` and the built-in `image_gen` tool. A prompt or layout spec alone is incomplete.
9. Apply the Imagegen persistence gate. Embed an imagegen wikilink only after the selected output has been copied into `attachments/` and verified.
10. Check both artifacts as A4 landscape boards. The exact board must preserve text; the imagegen companion must preserve meaning and must not drift into a vertical poster.
11. Remove any decorative element that does not explain the idea.

## Quality Check

Except in Prompt-only mode, pass the artifact only if all checks are true:

- For source-based requests, every core claim is covered in the image or named in the companion note.
- The image reflects the source's caveats and scope limits when they affect the takeaway.
- The artifact avoids both missing central information and dumping raw detail into tiny unreadable text.
- The title and subtitle are readable in the A4 landscape PNG and remain legible when previewed smaller.
- The main PNG is landscape, preferably near A4 landscape ratio, unless the caller explicitly requested another shape.
- The main claim is visible without reading every caption.
- The image alone states the topic, central claim, mechanism, desired end state, next decision or action, and material limits.
- The image contains meaningful explanatory sentences or short clauses, not only concepts, icons, arrows, and isolated labels.
- The reading and copying order is unambiguous from the layout, numbering, or meaningful arrows.
- Copying the board in that order would preserve the source's question, premises, reasoning, example, conclusion, and desired end state.
- No separate reproduction exercise or worksheet has been added unless the caller requested one.
- Arrows show cause, time, or choice clearly.
- Right-side point boxes add judgment, not repetition.
- The bottom summary band contains the practical takeaway.
- No section has more than one main message.
- The visual style is hand-drawn and monochrome, not a slide deck or marketing hero.
- The visual is not a low-information word cloud. It should be possible to evaluate the source note's overall content from the artifact itself.
- A source-based artifact fails if the reader must use the Markdown Text Board or reopen the source to discover the conclusion, mechanism, desired end state, or next action. The Markdown note is a fallback and evidence surface, not a substitute for an incomplete image.
- The saved Markdown note is not image-only.
  Even if every image is hidden, broken, or visually ambiguous, `Source Coverage`, `Text Board`, and `Companion Note` must let the reader understand the topic, claim, mechanism, decision, and limits.
- Imagegen-only and Dual outputs must not present a wordless generated drawing as the whole artifact.
  The generated image may be a metaphor, but the Markdown note must carry the precise textual explanation.
- An actual PNG exists in `attachments/` and is embedded with an Obsidian image wikilink.
- When Imagegen or Dual mode applies, the available `imagegen` skill was read and a built-in `image_gen` call was made. A prompt or layout spec alone is a failure.
- Imagegen is saved only when the selected built-in output was copied from a concrete tool-returned path or an unambiguous new `$CODEX_HOME/generated_images/` output, and the copied bitmap was verified before linking.
- In Dual mode, the exact board and imagegen companion use different filenames, and the generated file does not overwrite the exact board.
- Generated visuals do not become the authoritative source for exact Japanese text, citations, or numbers.
- Every image wikilink resolves to a readable file under `attachments/`: one link in Exact Board or Imagegen mode, and two links in completed Dual mode.
- Completed Imagegen mode requires one verified generated PNG under `attachments/`.
- Completed Dual mode requires both a verified Exact Board PNG and a verified generated PNG under `attachments/`.
- If Dual persistence is blocked, the Exact Board artifact may be complete, but Dual mode does not pass this Quality Check.
- A built-in `image_gen` call without a persistable, verified generated PNG is not a completed Imagegen or Dual result.
