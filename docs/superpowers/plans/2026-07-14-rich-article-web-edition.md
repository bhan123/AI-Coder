# Rich Article Web Edition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce readable, evidence-safe rich previews and approved-only static web editions while preserving existing four-platform Markdown outputs.

**Architecture:** Add a constrained `article_layout` to final JSON. Hermes emits fact-bound semantic blocks only; Python validates, escapes, renders, and exports them. Flask previews that same renderer output and exposes the web exporter only after approval.

**Tech Stack:** Python 3.11+, Flask, markdown-it-py, Pillow, SQLite, vanilla JavaScript/CSS, pytest.

---

## First-principles constraints

Attention is earned in order: relevance, comprehension, trust, then sharing. The implementation therefore makes one reader payoff visible at the top, groups prose into meaningful units, preserves evidence/source constraints, and creates a shareable artifact only after human approval. The model never controls HTML, CSS, JavaScript, URLs, or asset paths.

### Task 1: Add the safe article-layout schema

**Files:**
- Modify: `ai_content_loop/editorial/schema.py:18-305`
- Test: `tests/ai_content_loop/test_editorial_schema.py`

- [ ] **Step 1: Write failing schema tests**

~~~python
def test_legacy_final_payload_gets_empty_article_layout():
    normalized = normalize_final_payload(legacy_payload())
    assert normalized["article_layout"] == {"theme": "press", "blocks": []}


def test_article_layout_rejects_unknown_block_type():
    payload = enriched_payload()
    payload["article_layout"] = {
        "theme": "press",
        "blocks": [{"type": "raw_html", "value": "<script>alert(1)</script>"}],
    }
    with pytest.raises(FinalSchemaError, match="article_layout block type"):
        normalize_final_payload(payload)
~~~

- [ ] **Step 2: Verify RED**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_editorial_schema.py -q --basetemp .pytest_tmp_layout_schema`

Expected: FAIL because `article_layout` has no normalizer or validator.

- [ ] **Step 3: Implement the minimum contract**

Add `empty_article_layout()` and `_validate_article_layout()`. Accept only theme `press` and block types `hero`, `lead`, `key_judgment`, `section`, `workflow_compare`, `quote`, `callout`, and `source_note`. Require bounded text and typed paragraph lists; reject unknown keys. Normalize legacy payloads to the empty layout.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_editorial_schema.py -q --basetemp .pytest_tmp_layout_schema_green`

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add ai_content_loop/editorial/schema.py tests/ai_content_loop/test_editorial_schema.py
git commit -m "feat: add constrained article layout schema"
~~~

### Task 2: Generate fact-bound reading structure

**Files:**
- Modify: `ai_content_loop/prompts/editorial_voice.md`
- Modify: `ai_content_loop/generation.py:216-385`
- Test: `tests/ai_content_loop/test_generation.py`

- [ ] **Step 1: Write failing generation tests**

~~~python
def test_generation_requires_article_layout():
    payload = valid_editorial_payload()
    payload.pop("article_layout")
    assert "missing_article_layout" in validate_generation_payload(
        payload, source_url="https://example.com/source"
    )


def test_generation_rejects_layout_markup():
    payload = valid_editorial_payload()
    payload["article_layout"]["blocks"] = [
        {"type": "lead", "text": "<img onerror=alert(1)>"}
    ]
    assert "article_layout:unsafe_text" in validate_generation_payload(
        payload, source_url="https://example.com/source"
    )
~~~

- [ ] **Step 2: Verify RED**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py -q --basetemp .pytest_tmp_layout_generation`

Expected: FAIL because generation validation ignores the new field.

- [ ] **Step 3: Extend prompt and validator**

Add `article_layout` to the editorial JSON response. Require a concrete lead, one evidence-backed judgment, short meaningful sections, optional comparison/callout only when facts support it, and a canonical source note. Prohibit HTML, CSS, JavaScript, image Markdown, and fabricated quotations. Reuse schema normalization from `validate_generation_payload()`.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py -q --basetemp .pytest_tmp_layout_generation_green`

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add ai_content_loop/prompts/editorial_voice.md ai_content_loop/generation.py tests/ai_content_loop/test_generation.py
git commit -m "feat: generate evidence-bound article layouts"
~~~

### Task 3: Build the press rich-article renderer and preview API

**Files:**
- Create: `ai_content_loop/review/rich_article.py`
- Modify: `ai_content_loop/review/app.py:140-175`
- Test: `tests/ai_content_loop/test_review_rendering.py`
- Test: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write the failing renderer test**

~~~python
def test_rich_article_escapes_layout_text_and_builds_toc():
    payload = make_payload(article_layout={
        "theme": "press",
        "blocks": [
            {"type": "hero", "deck": "A <b>safe</b> payoff"},
            {"type": "section", "heading": "Why now",
             "paragraphs": ["<script>x</script>"]},
            {"type": "source_note", "url": "https://example.com/source"},
        ],
    })
    html = render_rich_article(payload, asset_urls={})
    assert '<nav class="rich-toc"' in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<script>x</script>" not in html
~~~

- [ ] **Step 2: Verify RED**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_rendering.py -q --basetemp .pytest_tmp_rich_render`

Expected: FAIL because `render_rich_article` does not exist.

- [ ] **Step 3: Implement renderer and preview**

Create `render_rich_article(payload, asset_urls)` with inline press theme tokens, deterministic section IDs, accessible TOC, and `html.escape` for every model-originated string. Emit images only from server-resolved `asset_urls`. Add authenticated `POST /api/rich-preview` that loads by opaque article ID and returns `{"html": ...}`.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_rendering.py tests\ai_content_loop\test_review_api.py -q --basetemp .pytest_tmp_rich_render_green`

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add ai_content_loop/review/rich_article.py ai_content_loop/review/app.py tests/ai_content_loop/test_review_rendering.py tests/ai_content_loop/test_review_api.py
git commit -m "feat: render press-style article previews"
~~~

### Task 4: Export a web edition only after approval

**Files:**
- Create: `ai_content_loop/review/web_edition.py`
- Modify: `ai_content_loop/review/repository.py:119-443`
- Modify: `ai_content_loop/review/app.py:47-270`
- Test: `tests/ai_content_loop/test_review_repository.py`
- Test: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write failing approval-gate tests**

~~~python
def test_web_export_rejects_unapproved_article(review_app):
    client = login(review_app)
    response = client.post(f"/api/articles/{ARTICLE_ID}/web-edition")
    assert response.status_code == 409


def test_web_export_writes_html_after_approval(review_app, tmp_path):
    client = login(review_app)
    client.put(f"/api/articles/{ARTICLE_ID}/status", json={"status": "approved"})
    response = client.post(f"/api/articles/{ARTICLE_ID}/web-edition")
    assert response.status_code == 200
    assert (tmp_path / "out" / "web" / f"{ARTICLE_ID}.html").exists()
~~~

- [ ] **Step 2: Verify RED**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_repository.py tests\ai_content_loop\test_review_api.py -q --basetemp .pytest_tmp_web_export`

Expected: FAIL because there is no export route or exporter.

- [ ] **Step 3: Implement atomic export**

Create `export_web_edition(output_path, payload, asset_urls)` which wraps renderer output in a complete UTF-8 HTML document, writes a sibling temporary file, fsyncs it, and atomically replaces `out/web/<article-id>.html`. Add repository methods that require status exactly `approved`. Add authenticated export and same-origin serving routes; resolve all paths under the configured web root.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_repository.py tests\ai_content_loop\test_review_api.py -q --basetemp .pytest_tmp_web_export_green`

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add ai_content_loop/review/web_edition.py ai_content_loop/review/repository.py ai_content_loop/review/app.py tests/ai_content_loop/test_review_repository.py tests/ai_content_loop/test_review_api.py
git commit -m "feat: export approved articles as web editions"
~~~

### Task 5: Integrate the rich preview and export controls

**Files:**
- Modify: `ai_content_loop/review/templates/review.html:71-179`
- Modify: `ai_content_loop/review/static/review.js:102-507`
- Modify: `ai_content_loop/review/static/review.css`
- Test: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write the failing review shell test**

~~~python
def test_review_page_contains_rich_preview_and_export_controls(review_app):
    client = login(review_app)
    html = client.get("/").get_data(as_text=True)
    assert 'id="rich-preview-button"' in html
    assert 'id="export-web-edition-button"' in html
~~~

- [ ] **Step 2: Verify RED**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_api.py -q --basetemp .pytest_tmp_rich_ui`

Expected: FAIL because the controls do not exist.

- [ ] **Step 3: Implement the review interaction**

Add a rich-preview pane and button calling `/api/rich-preview`. Add a disabled-by-default export button; enable only for an approved loaded article, call the export API, then expose the returned same-origin URL. Use CSS for narrow reading width, warm press hierarchy, cover, verdict card, source note, mobile layout, and reduced-motion support.

- [ ] **Step 4: Verify GREEN**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_api.py -q --basetemp .pytest_tmp_rich_ui_green`

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add ai_content_loop/review/templates/review.html ai_content_loop/review/static/review.js ai_content_loop/review/static/review.css tests/ai_content_loop/test_review_api.py
git commit -m "feat: add rich article review controls"
~~~

### Task 6: Run the full flow and document production operation

**Files:**
- Modify: `docs/ai-content-loop/lighthouse-deployment.md`
- Modify: `docs/ai-content-loop/operator-runbook.md`
- Test: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write the end-to-end gate test**

~~~python
def test_rich_preview_then_web_export_requires_approval(review_app):
    client = login(review_app)
    assert client.post("/api/rich-preview", json={"article_id": ARTICLE_ID}).status_code == 200
    assert client.post(f"/api/articles/{ARTICLE_ID}/web-edition").status_code == 409
    client.put(f"/api/articles/{ARTICLE_ID}/status", json={"status": "approved"})
    assert client.post(f"/api/articles/{ARTICLE_ID}/web-edition").status_code == 200
~~~

- [ ] **Step 2: Verify RED before the prior slices are merged**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_api.py::test_rich_preview_then_web_export_requires_approval -q --basetemp .pytest_tmp_rich_flow`

Expected: FAIL; after Tasks 3-5 it must PASS.

- [ ] **Step 3: Document operation**

Document persistent `out/web/`, backup requirements, approval-only export, local validation URL, and rollback. State explicitly that the daily timer creates reviewable JSON only: it neither publishes nor auto-exports web editions.

- [ ] **Step 4: Run full verification**

Run: `D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop -q --basetemp .pytest_tmp_rich_full`

Expected: all tests PASS; only existing documented skips/deprecation warnings may remain.

- [ ] **Step 5: Commit and verify workspace**

~~~bash
git add docs/ai-content-loop/lighthouse-deployment.md docs/ai-content-loop/operator-runbook.md tests/ai_content_loop/test_review_api.py
git commit -m "docs: operate rich article web editions"
git status --short
git diff --check
~~~

Expected: no feature changes remain unstaged and no whitespace errors.

## Plan self-review

- Spec coverage: Tasks 1-2 define safe content structure; Tasks 3 and 5 create review readability; Task 4 gates durable sharing; Task 6 verifies and operates it.
- First-principles coverage: opening payoff and reading rhythm are structured in the contract, trust is owned by validation and escaping, and sharing is protected by approval.
- Scope: arbitrary model HTML, a Vite/React runtime, automatic export, and replacement of platform publishing remain excluded.
- Type consistency: `article_layout`, `render_rich_article`, `rich-preview`, and `web-edition` are used consistently in schema, API, UI, tests, and docs.

