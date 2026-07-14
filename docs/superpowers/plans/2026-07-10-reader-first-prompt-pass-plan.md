# Reader-First Prompt Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove citation clutter and make Hermes articles hook-first, accessible, interesting, and clearly useful to non-specialist readers.

**Architecture:** Keep the current two-pass generation and JSON schemas. Change only the scoring, factual-draft, and editorial Markdown contracts, with one prompt-contract regression test.

**Tech Stack:** Markdown prompts, Python pytest.

---

### Task 1: Reader-first prompt contract

**Files:**
- Modify: `tests/ai_content_loop/test_generation.py`

- [ ] **Step 1: Write failing assertions**

Require `scoring-v6`, `factual-v8`, and `editorial-v12`; assert the prompts prohibit numbered citation markers, generic openings, leaked editorial scaffolding, unsupported time forecasts, and unsupported named comparisons. Require explicit practical, emotional, or knowledge payoff.

- [ ] **Step 2: Verify RED**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py::test_active_prompts_state_two_pass_contracts -q -p no:cacheprovider
```

Expected: failure on the old prompt versions and `[来源1]` requirements.

### Task 2: Prompt rewrite

**Files:**
- Modify: `ai_content_loop/prompts/scoring.md`
- Modify: `ai_content_loop/prompts/factual_draft.md`
- Modify: `ai_content_loop/prompts/editorial_voice.md`

- [ ] **Step 1: Update scoring**

Lower scores for research-only topics without a public demo, accessible use, emotional interest, or strong workflow implication. Require the angle to name the reader payoff and opening picture.

- [ ] **Step 2: Update factual drafting**

Replace numbered citation markers with sparse natural attribution and one raw URL at the end. Preserve the fact boundary and exact URL requirement.

- [ ] **Step 3: Update editorial voice**

Strengthen first-sentence hooks and non-specialist language; forbid editorial scaffold phrases, arbitrary time horizons, and unsupported named comparisons; require one clear reader payoff.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 test and expect it to pass.

### Task 3: Regression and deployment

**Files:**
- No additional source files.

- [ ] **Step 1: Run the full AI content test suite**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop -q -p no:cacheprovider
```

- [ ] **Step 2: Run prompt scans and whitespace checks**

Confirm no active prompt contains `[来源1]`, `来源1`, or `来源2`, and run `git diff --check` for the scoped files.

- [ ] **Step 3: Deploy and verify**

Back up `/opt/ai-content-loop/repo`, overlay the tested `ai_content_loop` package, compile as `agentuser`, restart `ai-content-review.service`, and verify prompt versions plus HTTP 200 on `/login`.
