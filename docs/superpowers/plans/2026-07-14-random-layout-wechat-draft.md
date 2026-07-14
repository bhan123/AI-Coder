# Random article layouts and WeChat drafts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist one random theme and structure for every new article, render the same semantic layout in the review desk/web edition/WeChat HTML, and let an approved reviewer create a WeChat draft without auto-publishing.

**Architecture:** Generation selects one theme from `press`, `tufte`, `magazine`, `vignelli` and one structure from `briefing`, `explainer`, `essay`, then passes both to Hermes and stores them in `article_layout`. Renderers consume that persisted pair and never randomize at render time. A separate WeChat adapter obtains a token, uploads approved assets, converts the layout to escaped inline-styled HTML, and creates a draft through an authenticated review action.

**Tech Stack:** Python 3.13, Flask, SQLite, stdlib `urllib.request`, pytest, vanilla review JavaScript/CSS, systemd environment file.

---

### Task 1: Extend the layout contract without breaking legacy articles

**Files:**
- Modify: `ai_content_loop/editorial/schema.py:43-68,132-133,334-385`
- Modify: `ai_content_loop/generation.py:319-397,549-565`
- Test: `tests/ai_content_loop/test_editorial_schema.py`
- Test: `tests/ai_content_loop/test_generation.py`

- [ ] **Step 1: Write failing tests.** Add tests that accept all four themes and all three structures, reject unknown values, and normalize the old two-key `{theme, blocks}` layout without rewriting legacy JSON.
- [ ] **Step 2: Run the focused tests and confirm failure.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_editorial_schema.py tests/ai_content_loop/test_generation.py -q`; expect failures because only `press` and the old shape are accepted.
- [ ] **Step 3: Implement the compatible contract.** Add `ARTICLE_THEMES = ("press", "tufte", "magazine", "vignelli")` and `ARTICLE_STRUCTURES = ("briefing", "explainer", "essay")`. Accept the legacy shape for old payloads, infer `briefing` in memory, require `structure` for new non-empty layouts, and keep `empty_article_layout()` compatible with existing callers.
- [ ] **Step 4: Run the focused tests again.** Expect all schema and generation tests to pass.
- [ ] **Step 5: Commit.** Run `git add ai_content_loop/editorial/schema.py ai_content_loop/generation.py tests/ai_content_loop/test_editorial_schema.py tests/ai_content_loop/test_generation.py; git commit -m "feat: extend article layout themes and structures"`.

### Task 2: Select and persist random layout requests during generation

**Files:**
- Modify: `ai_content_loop/generation.py:700-730,1333-1390`
- Modify: `ai_content_loop/prompts/editorial_voice.md:121-133,191-202`
- Test: `tests/ai_content_loop/test_generation.py`

- [ ] **Step 1: Write failing tests.** Patch `secrets.choice` to return `vignelli` and `essay`, run the fake Hermes generation, and assert the captured prompt and saved JSON contain the same pair. Add a retry test proving the pair is selected once and reused.
- [ ] **Step 2: Run the focused tests and confirm failure.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_generation.py -k "layout_request or random_theme or structure" -q`; expect failure because no machine-owned request is passed to Hermes.
- [ ] **Step 3: Implement one-time selection.** Add `choose_article_layout() -> dict[str, str]` using `secrets.choice(ARTICLE_THEMES)` and `secrets.choice(ARTICLE_STRUCTURES)`. Add `requested_article_layout` to the editorial input, require Hermes to echo the exact pair, and make mismatches retryable hard failures.
- [ ] **Step 4: Run generation tests.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_generation.py -q`; expect pass.
- [ ] **Step 5: Commit.** Run `git add ai_content_loop/generation.py ai_content_loop/prompts/editorial_voice.md tests/ai_content_loop/test_generation.py; git commit -m "feat: persist random article layout selection"`.

### Task 3: Render all four themes consistently

**Files:**
- Modify: `ai_content_loop/review/rich_article.py:35-210`
- Modify: `ai_content_loop/review/static/rich_article.css`
- Modify: `ai_content_loop/review/web_edition.py:10-72`
- Test: `tests/ai_content_loop/test_review_rendering.py`
- Test: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write failing tests.** Parametrize rich rendering and web export over all themes and structures; assert the theme class/CSS is selected, legacy layouts still render, text is escaped, and no script is emitted.
- [ ] **Step 2: Run tests and confirm failure.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_rendering.py tests/ai_content_loop/test_review_api.py -q`; expect failure because only `press` is trusted.
- [ ] **Step 3: Implement theme-aware rendering.** Normalize a missing structure to `briefing`, validate the theme against `ARTICLE_THEMES`, emit `rich-article--<theme> rich-article--<structure>`, add CSS tokens for press/tufte/magazine/vignelli, and replace the single web CSS string with a theme map. Keep markup renderer-owned.
- [ ] **Step 4: Run renderer/API tests.** Expect pass.
- [ ] **Step 5: Commit.** Run `git add ai_content_loop/review/rich_article.py ai_content_loop/review/static/rich_article.css ai_content_loop/review/web_edition.py tests/ai_content_loop/test_review_rendering.py tests/ai_content_loop/test_review_api.py; git commit -m "feat: render persisted article themes"`.

### Task 4: Add the WeChat HTML renderer

**Files:**
- Create: `ai_content_loop/wechat/__init__.py`
- Create: `ai_content_loop/wechat/rendering.py`
- Test: `tests/ai_content_loop/test_wechat_rendering.py`

- [ ] **Step 1: Write failing tests.** Test `render_wechat_article(layout, fallback_title, fallback_markdown, image_urls)` for every theme/structure, asserting inline styles, escaped content, safe image URLs, headings, callouts, source text, and no scripts.
- [ ] **Step 2: Run the new tests and confirm failure.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_wechat_rendering.py -q`; expect module-not-found failure.
- [ ] **Step 3: Implement the pure renderer.** Render only semantic blocks with `html.escape`, theme tokens, and server-provided image URLs. Use fallback Markdown only for legacy empty layouts. Reject model-authored HTML/CSS/JS and arbitrary URLs.
- [ ] **Step 4: Run renderer tests.** Expect pass.
- [ ] **Step 5: Commit.** Run `git add ai_content_loop/wechat tests/ai_content_loop/test_wechat_rendering.py; git commit -m "feat: render WeChat-compatible article HTML"`.

### Task 5: Implement the WeChat API client with fake transport

**Files:**
- Create: `ai_content_loop/wechat/client.py`
- Test: `tests/ai_content_loop/test_wechat_client.py`

- [ ] **Step 1: Write failing tests.** Use an injected fake transport to cover token retrieval, cover material upload, article-image upload, draft creation, non-zero `errcode`, and timeout mapping. Assert secrets/tokens never appear in logs.
- [ ] **Step 2: Run tests and confirm failure.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_wechat_client.py -q`; expect module-not-found failure.
- [ ] **Step 3: Implement `WechatClient`.** Use stdlib `urllib.request` with `app_id`, `app_secret`, `base_url`, injectable transport, and bounded timeouts. Call token, permanent image, article-image, and draft-add endpoints; parse JSON and raise `WechatApiError` for every non-zero error code.
- [ ] **Step 4: Run client tests.** Expect pass without network access.
- [ ] **Step 5: Commit.** Run `git add ai_content_loop/wechat/client.py tests/ai_content_loop/test_wechat_client.py; git commit -m "feat: add WeChat draft API client"`.

### Task 6: Persist draft sync state and gate it on approval

**Files:**
- Modify: `ai_content_loop/db.py:66-72,100-120`
- Modify: `ai_content_loop/review/repository.py:124-160,450-525`
- Modify: `ai_content_loop/review/app.py:43-70,263-351`
- Test: `tests/ai_content_loop/test_review_repository.py`
- Test: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write failing tests.** Cover non-approved rejection without network calls, missing credentials, successful cover/body upload and draft creation, idempotent re-sync, version conflict, CSRF/auth, and preserving the prior successful record after a failed retry.
- [ ] **Step 2: Run tests and confirm failure.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_repository.py tests/ai_content_loop/test_review_api.py -k "wechat or draft" -q`; expect failure because no table, method, or route exists.
- [ ] **Step 3: Implement persistence/orchestration.** Add `wechat_draft_syncs` keyed by `dedupe_key` with media ID, status, provider error, and timestamps. Add repository orchestration that loads an approved article, resolves safe asset paths, uploads assets, renders HTML, creates the draft, and updates the record only after full success. Add authenticated, CSRF-protected `POST /api/articles/<article_id>/wechat/draft`.
- [ ] **Step 4: Run persistence/API tests.** Expect pass.
- [ ] **Step 5: Commit.** Run `git add ai_content_loop/db.py ai_content_loop/review/repository.py ai_content_loop/review/app.py tests/ai_content_loop/test_review_repository.py tests/ai_content_loop/test_review_api.py; git commit -m "feat: create approval-gated WeChat drafts"`.

### Task 7: Add review action, status display, and deployment configuration

**Files:**
- Modify: `ai_content_loop/review/templates/review.html:185-225`
- Modify: `ai_content_loop/review/static/review.js:1-60,180-240,500-560`
- Modify: `ai_content_loop/review/static/review.css`
- Modify: `docs/ai-content-loop/operator-runbook.md`
- Modify: `docs/ai-content-loop/lighthouse-deployment.md`
- Test: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write failing UI/API tests.** Assert a disabled-by-default `同步公众号草稿` action, status element, `not_configured` response, success response, and stable error rendering contract.
- [ ] **Step 2: Run tests and confirm failure.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_api.py -k "wechat or draft or template" -q`; expect failure.
- [ ] **Step 3: Implement the action.** Add the button beside `导出网页`, enable it only for approved/configured articles, call the route with the current version, and display draft status/media ID without exposing secrets. Read only `WECHAT_APP_ID`, `WECHAT_APP_SECRET`, and optional `WECHAT_API_BASE_URL` from the review service environment.
- [ ] **Step 4: Document deployment.** Document a mode-600 environment file, restart/health checks, one-article verification, and the explicit no-auto-publish rule.
- [ ] **Step 5: Run API tests and commit.** Run `D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_api.py -q`; then commit with `git add ai_content_loop/review/templates/review.html ai_content_loop/review/static/review.js ai_content_loop/review/static/review.css docs/ai-content-loop/operator-runbook.md docs/ai-content-loop/lighthouse-deployment.md tests/ai_content_loop/test_review_api.py; git commit -m "feat: expose WeChat draft sync in review desk"`.

### Task 8: Full verification and controlled rollout

**Files:**
- Test: all `tests/ai_content_loop/`
- Verify: deployed `ai-content-review.service` and one approved article

- [ ] **Step 1: Run the complete local suite.** Run `D:\Users\36997\anaconda3\python.exe -m pytest -q`; expect all tests to pass with no network calls.
- [ ] **Step 2: Run static checks.** Run `git diff --check HEAD~8..HEAD`; expect no output.
- [ ] **Step 3: Deploy without credentials.** Restart the review service and verify the button reports configuration missing rather than making a network call.
- [ ] **Step 4: Add credentials only on the server.** Create a mode-600 environment file, add AppID/AppSecret without sending them through chat, restart the service, and verify no secret is logged.
- [ ] **Step 5: Create one controlled draft.** Approve one article with a cover asset, click `同步公众号草稿`, inspect the draft in the WeChat backend, and confirm stored media ID/status. Do not invoke the final publish endpoint.

