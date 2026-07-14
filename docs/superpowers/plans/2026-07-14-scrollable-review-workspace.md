# Scrollable Review Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the review action bar reachable by vertical scrolling at short viewport heights.

**Architecture:** Keep the existing editor-shell grid, content panes, rich-preview state, and action bar unchanged. The existing `.workspace` becomes the single outer scroll boundary, so fixed-height metadata can no longer be clipped before the action bar.

**Tech Stack:** Flask-rendered HTML, CSS Grid, pytest static layout regression test.

---

### Task 1: Allow the review workspace to scroll

**Files:**
- Modify: `ai_content_loop/review/static/review.css:135-139`
- Modify: `tests/ai_content_loop/test_review_api.py:706-719`

- [ ] **Step 1: Write the failing regression assertion**

Add the following assertions to `test_review_layout_keeps_rich_preview_in_scrollable_workspace`:

```python
assert ".workspace" in css
assert "min-height: 0;" in css
assert "overflow-x: hidden;" in css
assert "overflow-y: auto;" in css
```

- [ ] **Step 2: Run the regression test and verify it fails**

Run:

```powershell
& 'D:\Users\36997\anaconda3\python.exe' -m pytest tests\ai_content_loop\test_review_api.py::test_review_layout_keeps_rich_preview_in_scrollable_workspace -q --basetemp .pytest_tmp_scroll_red
```

Expected: failure because `.workspace` still uses `overflow: hidden` and lacks the explicit vertical scroll boundary.

- [ ] **Step 3: Make the minimal CSS change**

Replace the `.workspace` rule with:

```css
.workspace {
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  background: var(--surface);
}
```

- [ ] **Step 4: Run the regression and review suites**

Run:

```powershell
& 'D:\Users\36997\anaconda3\python.exe' -m pytest tests\ai_content_loop\test_review_api.py -q --basetemp .pytest_tmp_scroll_green
```

Expected: all review API tests pass.

- [ ] **Step 5: Verify CSS syntax and commit**

Run:

```powershell
git diff --check
git add ai_content_loop/review/static/review.css tests/ai_content_loop/test_review_api.py
git commit -m "fix: keep review action bar scrollable"
```

Expected: no whitespace errors and one focused commit.

## Plan Self-Review

- Spec coverage: Task 1 keeps the DOM and behavior unchanged, adds only the
  outer vertical scroll boundary, preserves horizontal clipping, and protects
  the intended behavior with a regression assertion.
- Placeholder scan: no incomplete steps or deferred work.
- Consistency: the CSS selector and test name match the existing review desk.
