# Editorial Prompt Razor Pass Design

## Goal

Improve article readability and trust without adding another generation stage or blocking drafts from the human review desk.

## Scope

- Simplify the factual and editorial Markdown prompts.
- Remove fixed article-order instructions from the Python writing brief.
- Keep facts, privacy, source links, JSON schema, and two-pass generation constraints.
- Add non-blocking platform-length and editorial-placeholder warnings.
- Prevent the preview renderer from exposing the literal text `正文配图` when an image is copied or unavailable.

The factual/editorial/visual/platform pipeline remains unchanged in this pass. Splitting visual generation and per-platform adaptation into separate model calls is deferred because it changes orchestration and retry behavior.

## Prompt behavior

The factual pass produces evidence-grounded copy but treats column requirements as coverage rather than a fixed sequence. Precise claims cite the named source in the paragraph and use a numbered source marker tied to the exact URL at the end.

The editorial pass uses a balanced voice with at most two strong jokes and no repeated metaphor. Hypothetical scenarios must be labeled as hypothetical; people, durations, prices, and effects cannot be invented. The prompt prioritizes six rules: preserve facts, front-load the judgment, use one varied narrative entrance, explain one or two evidence-backed scenes, state an author judgment, and finish with a useful boundary or next step.

## Quality behavior

Quality problems remain warnings. Every structurally reviewable article still reaches the review desk. Platform-specific minimum character targets add warnings for short drafts, and raw editorial placeholders such as `正文配图` add a warning rather than blocking output.

## Preview behavior

Generated body images are decorative in the review preview, so they use empty alternative text. The asset marker remains server-managed and is not authored by the model.

## Verification

- Prompt contract tests prove the concise rules and balanced profile are present.
- Template tests prove fixed article-order skeletons are gone.
- Generation tests prove platform length and placeholder issues are warnings, not blockers.
- Rendering tests prove preview images no longer expose the literal placeholder text.

## Reader-first amendment

Public copy must not contain numbered citation markers such as `来源1` or `来源2`. The main URL appears once at the end as `来源：<source_url>`; important claims use occasional natural attribution such as “据论文摘要” or “据项目官方页面”. Attribution exists to support trust and must not interrupt every sentence.

The first sentence must create a concrete picture, result, conflict, surprise, or useful promise. Generic introductions such as “最近有个变化值得普通读者看一眼” are not acceptable. Every article chooses one primary reader payoff—practical value, emotional value, or useful new understanding—and makes that payoff clear in the opening third.

Internal checks must not leak into published prose. Phrases such as “两个证据充分的场景”, “差异方面”, “限制必须老实写”, “作者判断（个人观点）”, and “可执行的下一步” are editorial scaffolding, not article headings. Unsupported time horizons and named product comparisons are also prohibited. Pure research topics without a usable demo or a strong reader payoff receive lower selection priority and should be shorter when selected.
