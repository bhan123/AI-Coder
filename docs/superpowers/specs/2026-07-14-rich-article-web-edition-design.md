# Rich Article and Web Edition Design

## Goal

Make AI Content Loop articles easier to read and more visually deliberate on native publishing platforms, while letting an approved article become a shareable, static web edition without replacing the existing Hermes batch workflow.

## Decision

Adopt a hybrid model inspired by `beautiful-article`:

- Keep the current evidence-first Hermes generation pipeline and its four platform Markdown outputs.
- Add a constrained semantic article-layout model rather than allowing generated HTML or CSS.
- Render that model in the review desk for rich reading and editing.
- Generate a static web edition only after a human approves an article.

The first visual theme is `press`: editorial and readable rather than a dense report or a promotional poster.

## Scope

### In scope

- A validated `article_layout` object stored with each final article.
- Prompt instructions that produce a selected narrative entrance, semantic reading blocks, and visual intent grounded in locked facts.
- A review-desk long-form preview that renders semantic blocks consistently.
- A reviewer action that exports approved content to `out/web/<article-id>.html`.
- A static, self-contained HTML article with cover, table of contents, source note, and existing generated visual assets where available.
- Tests for schema validation, safe rendering, export determinism, and approval gating.

### Out of scope

- Replacing Hermes, the source/evidence model, or the existing platform Markdown contract.
- Rendering arbitrary model-authored HTML, CSS, JavaScript, or remote embeds.
- Generating a web edition for every scheduled daily article.
- Replacing native-platform publishing with the web edition.
- Adding a Vite/React runtime or copying the upstream skill's interactive approval harness into production.

## Architecture

```text
locked facts + editorial prompt
          |
          v
final article JSON
  - master_markdown
  - platform_markdown
  - visual_brief
  - article_layout       <- new constrained model
          |
          +--> review desk rich preview
          |
          +--> approved-only static HTML exporter --> out/web/
```

`article_layout` is a presentation plan, not a second independently authored article. Each block either points to a fact-backed excerpt or references an existing field from the final article. The renderer owns all markup, styling, escaping, asset paths, and theme tokens.

## Article Layout Contract

The initial contract contains a small set of block types:

- `hero`: title, deck, selected theme, and optional existing cover asset.
- `lead`: a short opening that delivers the article's reader payoff.
- `key_judgment`: one evidence-grounded, memorable editorial conclusion.
- `section`: heading plus an ordered list of paragraphs sourced from the master article.
- `workflow_compare`: an optional before / after / remaining-friction comparison.
- `quote`: a short source-backed statement or explicitly marked editorial judgment.
- `callout`: a concise boundary, limitation, or next action.
- `source_note`: the canonical source URL and attribution.

Each layout has a `theme` field. Initial accepted value: `press`. Rendering must reject unknown block types, missing required fields, unsafe URLs, and content that fails the current final-article validation.

## Content Rules

- Use narrative variety: a concrete change, counter-intuitive conclusion, workflow compression, factual number, or limitation can open an article. Do not force every article into one paragraph sequence.
- The first third must make one reader payoff explicit: practical value, emotional value, or cognitive value.
- Use short paragraphs, meaningful subheads, and callouts to create pauses without padding.
- Visual blocks must explain a claim, a workflow change, or an evidence point; they must not restate the full article as generic cards.
- Preserve the current fact, source, privacy, and prohibited-claim constraints.

## Review and Export Flow

1. The daily pipeline writes validated final JSON, including `article_layout`.
2. The review desk renders a rich preview alongside existing platform views.
3. A reviewer edits or restores content through the existing review workflow.
4. Only an article in the approved review state exposes `Generate web edition`.
5. Export writes a self-contained HTML file atomically under `out/web/`, records its path in review metadata, and shows a preview/open action.
6. Re-export after an approved edit replaces the prior edition through the existing versioning/audit model.

## Visual Direction

`press` uses a paper-like warm background, strong serif/sans hierarchy, a narrow readable column, restrained rule lines, one highlighted verdict, and a 3:4 cover with the existing visual pipeline's fact-grounded artwork. It is deliberately not a PPT card deck, a dense technical report, or a high-motion landing page.

## Acceptance Criteria

- Existing four platform outputs remain schema-compatible and publishable.
- Every rich preview and exported page renders only renderer-owned HTML and escaped article text.
- An unapproved article cannot be exported.
- An approved article produces a self-contained `out/web/*.html` with title, TOC, source note, and an accessible reading order.
- Existing cover/body images appear only if they exist and remain inside the article output root.
- Current final-article tests and new schema/render/export tests pass.
- A first-spread sample is reviewed before the full exporter becomes available for all approved articles.

## Rollout

1. Introduce the layout schema and generate it for one sample article.
2. Build the rich preview and validate one first spread with the user.
3. Add approval-gated HTML export behind the review desk.
4. Deploy to Lighthouse, export one approved article, and verify the static page plus existing review service.
