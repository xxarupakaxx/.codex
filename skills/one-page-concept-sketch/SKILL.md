---
name: one-page-concept-sketch
description: Create a single hand-drawn, black-and-white concept sketch that makes an idea understandable at a glance without omitting central information. Use when the user asks for an image, diagram, infographic, explainer sheet, one-page summary, whiteboard-style visual, handwritten Japanese style, sketchnote, or one image that shows what this is about. For automation notes in this Vault, save the result under Inbox/automation/concept-sketches/ and follow [[11_one-page-concept-sketch]].
---

# One Page Concept Sketch

Turn an idea into one readable image that explains the concept, not a decorative poster.

Optimize for three outcomes:

- A reader can say what the topic is within 3 seconds.
- A reader can explain the core mechanism within 30 seconds.
- The visual still works when viewed as a screenshot on a phone.

## Vault Output Contract

For Vault automations, follow [[11_one-page-concept-sketch]].

- Save the artifact as `Inbox/automation/concept-sketches/concept-sketch-YYYY-MM-DD-<lane>.md`.
- Create `Inbox/automation/concept-sketches/` before saving if it is missing.
- Link it from the source note and from `Daily/YYYY-MM-DD.md`.
- Keep the source coverage map in the saved note.
- Do not rename or delete existing notes.
- Do not write outside `Inbox/automation/concept-sketches/` unless the caller explicitly asks for another target.

## Output Mode

Choose the production mode before drafting.

- Use SVG or HTML/CSS when exact Japanese text, labels, or long explanations must be readable.
- Use image generation when the user mainly wants a bitmap illustration, mood, or rough visual direction.
- Use a prompt plus layout spec when the user asks for guidance rather than an actual file.

If using an image generation tool, keep text short and expect to manually revise or rebuild text-heavy areas as SVG/HTML if legibility fails.

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

## Structure

Use this layout grammar by default:

1. Title at top center.
2. One-line subtitle that states the claim.
3. Two or three numbered sections separated by thin horizontal rules.
4. Each section contains a left-to-right causal flow, comparison, or timeline.
5. Put one boxed "Point" note on the right side of each main section.
6. End with a bottom summary band that names the takeaway and action.

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

Delete only supporting details that do not change the source's core claims, mechanism, caveats, or decision implications.
If a sentence cannot fit in a small label, turn it into a shorter noun phrase or move it to a point box.
If a detail is important but too dense for the image, preserve it in the companion note rather than pretending it does not matter.

## Text Rules

Keep labels short.

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
5. Draft the layout as text first: title, subtitle, sections, point boxes, summary band.
6. Map every core claim to a visible slot or the companion note.
7. Produce the artifact in the chosen output mode.
8. Check legibility at small size.
9. Remove any decorative element that does not explain the idea.

## Quality Check

Pass the artifact only if all checks are true:

- For source-based requests, every core claim is covered in the image or named in the companion note.
- The image reflects the source's caveats and scope limits when they affect the takeaway.
- The artifact avoids both missing central information and dumping raw detail into tiny unreadable text.
- The title and subtitle are readable at phone width.
- The main claim is visible without reading every caption.
- Arrows show cause, time, or choice clearly.
- Right-side point boxes add judgment, not repetition.
- The bottom summary band contains the practical takeaway.
- No section has more than one main message.
- The visual style is hand-drawn and monochrome, not a slide deck or marketing hero.
