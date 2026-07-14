# Editorial Prompt Razor Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generated articles less templated, less joke-heavy, better sourced, and easier to review while keeping every structurally valid draft non-blocking.

**Architecture:** Keep the existing factual-pass then editorial-pass pipeline. Tighten prompt contracts, remove fixed ordering from bundle templates, add soft platform quality warnings in generation validation, and make rendered body images decorative.

**Tech Stack:** Python 3.13, pytest, Markdown prompts, browser-side review UI.

---

### Task 1: Prompt and writing-brief contracts

**Files:**
- Modify: `tests/ai_content_loop/test_generation.py`
- Modify: `tests/ai_content_loop/test_quality_templates.py`
- Modify: `ai_content_loop/prompts/factual_draft.md`
- Modify: `ai_content_loop/prompts/editorial_voice.md`
- Modify: `ai_content_loop/templates.py`

- [x] **Step 1: Write failing prompt and template assertions**

Assert factual-v7/editorial-v11, balanced humor, hypothetical-scene constraints, numbered source anchors, no fixed `场景一 → 场景二` skeleton, and no `humor_level: "spicy"`.

- [x] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py::test_active_prompts_state_two_pass_contracts tests\ai_content_loop\test_quality_templates.py::test_templates_create_brief_and_platform_skeletons -q --basetemp D:\NR_Projects\.tmp\pytest-editorial-razor-red-prompts
```

Expected: failures for old prompt versions, spicy humor, and fixed skeleton copy.

- [x] **Step 3: Implement the minimal prompt and template changes**

Replace duplicated prompt sections with prioritized rules, keep the output JSON schema intact, and convert template structure instructions into unordered coverage requirements.

- [x] **Step 4: Run focused tests and confirm GREEN**

Run the Step 2 command with a fresh `--basetemp` suffix and expect all tests to pass.

### Task 2: Non-blocking platform quality warnings

**Files:**
- Modify: `tests/ai_content_loop/test_generation.py`
- Modify: `ai_content_loop/generation.py`
- Modify: `ai_content_loop/review/static/review.js`

- [x] **Step 1: Write failing validation tests**

Add a short body to each platform and assert `below_target_length` warnings. Add literal editorial placeholder text and assert `editorial_placeholder` warnings. Assert `hard == []` in both cases.

- [x] **Step 2: Run the focused tests and confirm RED**

Run the two new tests and verify the warning codes are absent.

- [x] **Step 3: Implement minimal warning rules**

Use platform targets `wechat=1000`, `xiaohongshu=450`, `toutiao=1000`, `zhihu=1200`. Detect `正文配图`, `封面配图`, and `图片占位` in stored copy. Add Chinese labels in the review UI.

- [x] **Step 4: Run focused tests and confirm GREEN**

Run the new tests and expect all assertions to pass with no hard blockers.

### Task 3: Decorative preview image alt text

**Files:**
- Modify: `tests/ai_content_loop/test_review_rendering.py`
- Modify: `ai_content_loop/review/rendering.py`

- [x] **Step 1: Write a failing rendering assertion**

Assert rendered asset HTML contains `alt=""` and does not contain `正文配图`.

- [x] **Step 2: Run the focused rendering test and confirm RED**

Run the target rendering test and verify it fails on the old alt text.

- [x] **Step 3: Render the body asset with empty alt text**

Change the server-side replacement Markdown from `![正文配图](...)` to `![](...)`.

- [x] **Step 4: Run the focused rendering test and confirm GREEN**

Run the target test and expect it to pass.

### Task 4: Regression verification

**Files:**
- No additional production files.

- [x] **Step 1: Run related tests**

Run generation, quality-template, editorial-quality, and review-rendering tests with a fresh explicit base temp directory.

- [x] **Step 2: Run compile and whitespace checks**

Run `python -m compileall -q ai_content_loop` and `git diff --check -- ai_content_loop tests/ai_content_loop docs/superpowers`.

- [x] **Step 3: Review the scoped diff**

Confirm only approved prompt, template, warning, rendering, test, and documentation changes are included.
