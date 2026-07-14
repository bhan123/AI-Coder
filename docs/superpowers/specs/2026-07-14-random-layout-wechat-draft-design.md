# Random article layouts and WeChat draft synchronization

## Goal

Each newly generated article receives one persisted visual theme and one persisted editorial structure. The review desk and the WeChat draft use the same semantic layout so a reader-facing decision is not trapped in the rich preview. WeChat synchronization creates a draft only; it never publishes automatically.

## Decisions

- Theme pool: `press`, `tufte`, `magazine`, `vignelli`.
- Structure pool: `briefing`, `explainer`, `essay`.
- Selection happens once before editorial generation using a cryptographically strong random source and is passed to Hermes as an explicit requested layout.
- The chosen `theme` and `structure` are stored in `article_layout` and remain stable through review edits, preview refreshes, exports, and service restarts.
- Legacy final JSON without a structure remains readable and normalizes to `press` plus an inferred `briefing` compatibility value; it is not re-randomized.
- The WeChat action is available only for an article in review status `approved` and requires an explicit reviewer click.
- The action creates or updates a WeChat draft and records the returned `media_id`; it does not call the final publish endpoint.

## Architecture

```text
locked facts + selected layout
             |
             v
       Hermes editorial JSON
       article_layout(theme, structure)
          |                 |
          v                 v
  rich preview/web edition  WeChat HTML adapter
                                  |
                  upload cover/body assets to WeChat
                                  |
                         draft/add -> media_id
```

### Layout contract

`article_layout` becomes `{theme, structure, blocks}` for new payloads. The schema accepts the two themes and three structures. Existing block types remain fact-bound and renderer-owned. Structure is a semantic hint, not a new free-form HTML layer:

- `briefing`: conclusion, evidence, practical boundary; short and front-loaded.
- `explainer`: mechanism, evidence, consequence; explanatory section order.
- `essay`: tension, evidence, judgment, limitation; more narrative pacing.

The prompt receives the selected values and must return that exact pair. Validation rejects a mismatch, unknown value, unsafe text, or a layout that is not grounded in the final article. The four theme profiles are deliberately distinct: `press` is restrained editorial, `tufte` is evidence-first with marginalia, `magazine` is bold and visual, and `vignelli` is grid-led and typographic.

### WeChat adapter

Add a small API client using the Python standard library HTTP stack, with an injectable transport for tests. Credentials come only from environment/configuration and are never stored in article JSON:

- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- optional `WECHAT_API_BASE_URL` for tests, defaulting to `https://api.weixin.qq.com`

The adapter obtains an access token, uploads the cover as permanent image material for `thumb_media_id`, uploads body images through the article-image endpoint, and renders escaped semantic blocks into WeChat-compatible HTML with inline styles. The renderer omits unsupported browser-only behavior and uses plain headings, paragraphs, blockquotes, callouts, comparison tables, and safe images.

If an approved article has no cover asset, synchronization fails with an actionable `missing_cover_asset` result; it never invents a cover or sends an incomplete draft. Body images are optional. The adapter validates response error codes and never treats a non-zero WeChat error response as success.

### Review desk and persistence

Add a “同步公众号草稿” action beside the existing export action. The route is authenticated and CSRF-protected, checks the current article version and `approved` status, then calls the adapter. Persist one sync record per article with provider, `media_id`, status, error code/message, and timestamps. Re-sync updates the existing draft record only after a successful API response.

The UI shows `未同步`, `同步中`, `已同步草稿`, or `同步失败` and a link/instruction to open the WeChat draft box. It does not expose or echo `AppSecret`.

## Error handling

- Missing credentials: configuration error before any network call.
- Token/upload/draft API errors: return a stable provider error code and leave the previous successful sync record intact.
- Timeout/network failure: mark the attempt failed without claiming a draft was created.
- Article edited after approval: existing review invalidation removes the ability to sync until re-approved.
- Legacy articles: remain previewable and exportable; WeChat sync requires a valid cover and the normalized layout.

## Testing

- Schema tests for both themes, all structures, legacy normalization, and mismatch rejection.
- Generation tests proving the selected pair is passed into the prompt and persisted.
- Renderer tests for escaped WeChat HTML, inline styles, safe image URLs, all structures, and no scripts.
- API-client tests with fake transport for token, image upload, cover upload, draft creation, timeout, and WeChat error responses.
- Review API/repository tests for approval gating, CSRF/auth, idempotent re-sync, version conflicts, and sync record persistence.
- Full existing suite remains green.

## Rollout

1. Merge schema/prompt/random selection and renderer tests.
2. Deploy review service with empty WeChat credentials; the new action remains disabled with a clear configuration message.
3. Add credentials on the server through a mode-600 environment file, restart the review service, and run a controlled draft sync on one approved article.
4. Verify the article and images in the WeChat draft box, then enable the workflow for routine use.
