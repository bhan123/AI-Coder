# Editorial Prompt Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten Hermes article generation rules for fact anchors, lower meme density, varied narrative entrances, harder author judgment, better visual brief direction, and no real-name leakage.

**Architecture:** Keep the pipeline unchanged. Encode the behavior in the existing scoring, factual draft, and editorial prompt files, with prompt contract tests to catch regression.

**Tech Stack:** Python pytest, Markdown prompt files.

---

### Task 1: Prompt contract regression tests

**Files:**
- Modify: `tests/ai_content_loop/test_generation.py`

- [ ] **Step 1: Write the failing test**

Add assertions in `test_active_prompts_state_two_pass_contracts` for:

```python
assert "Prompt version: factual-v6" in factual_prompt
assert "Prompt version: editorial-v10" in editorial_prompt
assert "Prompt version: scoring-v5" in scoring_prompt
assert "每篇最多 2 个强梗" in editorial_prompt
assert "叙事入口" in editorial_prompt
assert "产品经理 + 数据工程师判断" in editorial_prompt
assert "证据截图拼贴" in editorial_prompt
assert "不得出现真实姓名" in editorial_prompt
private_name = "".join(chr(codepoint) for codepoint in (0x97E9, 0x579A))
assert private_name not in factual_prompt + editorial_prompt + scoring_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py::test_active_prompts_state_two_pass_contracts -q
```

Expected: FAIL because prompts still use older versions and contain the hard-coded real name.

### Task 2: Prompt MD upgrades

**Files:**
- Modify: `ai_content_loop/prompts/scoring.md`
- Modify: `ai_content_loop/prompts/factual_draft.md`
- Modify: `ai_content_loop/prompts/editorial_voice.md`

- [ ] **Step 1: Update scoring prompt**

Set `Prompt version: scoring-v5` and add sourceability plus judgment-space rules so weakly sourced numbers and no-opinion topics score lower.

- [ ] **Step 2: Update factual prompt**

Set `Prompt version: factual-v6` and require every concrete number, price, benchmark, forecast, Star/Fork count, and time claim to be anchored to a named source in the same paragraph.

- [ ] **Step 3: Update editorial prompt**

Set `Prompt version: editorial-v10`, remove the real name, cap strong jokes to two per article, vary narrative entrances, require a hard product-manager/data-engineer judgment in the first third, and replace vague visual guidance with explicit visual schemes.

### Task 3: Verification and deployment

**Files:**
- No new local files beyond Task 1 and Task 2.

- [ ] **Step 1: Run targeted tests**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py::test_active_prompts_state_two_pass_contracts -q
```

Expected: PASS.

- [ ] **Step 2: Run diff whitespace check**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Deploy to Lighthouse**

Copy the updated source tree to `/opt/ai-content-loop/repo`, back up the previous source, install requirements if needed, restart `ai-content-review.service`, and verify prompt versions on the server.
