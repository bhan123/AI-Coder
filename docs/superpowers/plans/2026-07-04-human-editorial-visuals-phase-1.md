# Human Editorial Voice and Visual Assets Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every newly generated article use the approved human editorial voice and ship with one versioned WeChat cover plus one versioned inline meme image that can be reviewed and changed in the existing browser desk.

**Architecture:** Keep the current evidence, queue, JSON-final, and review architecture. Add a factual Hermes pass followed by a constrained editorial pass, then render the editorial pass's structured visual brief through six deterministic Pillow templates. Store image revisions immutably under `out/assets`, reference them from the final JSON, and let the review service switch pre-generated copy or templates without a remote image provider.

**Tech Stack:** Python 3.12/3.13, Hermes CLI, Pillow 12, Flask 3, SQLite, markdown-it-py, vanilla JavaScript, pytest, systemd.

---

## Scope

This plan implements stage 1 of the approved design:

- factual draft plus constrained “tech friend” editorial pass;
- anti-AI-style and unverifiable-first-person checks;
- structured visual briefs with three selectable copy sets;
- six original meme templates rendered locally;
- immutable image revisions and review history;
- browser preview, copy cycling, template switching, and approval guard;
- migration of existing `needs_human_review` articles.

Stage 2 will separately cover repository sandbox execution, remote artwork, Tencent Hunyuan, background generation jobs, COS, and automatic publishing. Stage 1 always falls back to a local original template, so it has no missing-image path.

## File map

### Create

- `ai_content_loop/editorial/{__init__.py,schema.py,quality.py}`
- `ai_content_loop/prompts/{factual_draft.md,editorial_voice.md}`
- `ai_content_loop/visuals/{__init__.py,brief.py,templates.py,renderer.py,assets.py,pipeline.py}`
- `tests/ai_content_loop/test_editorial_schema.py`
- `tests/ai_content_loop/test_editorial_quality.py`
- `tests/ai_content_loop/test_visual_brief.py`
- `tests/ai_content_loop/test_visual_renderer.py`
- `tests/ai_content_loop/test_visual_assets.py`

### Modify

- `ai_content_loop/{generation.py,templates.py,cli.py,config.py,config.example.toml}`
- `ai_content_loop/review/{repository.py,rendering.py,app.py}`
- `ai_content_loop/review/templates/review.html`
- `ai_content_loop/review/static/{review.js,review.css}`
- `requirements-review.txt`
- `deploy/systemd/ai-content-loop.service`
- `deploy/content-review/README.md`
- existing tests under `tests/ai_content_loop/`

## Shared contract

The enriched final payload has exactly:

```python
FINAL_FIELDS = {
    "dedupe_key", "column", "master_title", "master_markdown",
    "platform_markdown", "editorial_profile",
    "visual_brief", "visual_assets",
}
```

Before rendering, `visual_assets` is `{"cover": None, "body": []}`. Legacy five-field payloads stay readable but cannot be approved until backfilled.

### Task 1: Centralize the enriched final schema

**Files:**
- Create: `ai_content_loop/editorial/__init__.py`
- Create: `ai_content_loop/editorial/schema.py`
- Create: `tests/ai_content_loop/test_editorial_schema.py`
- Modify: `ai_content_loop/generation.py`
- Modify: `ai_content_loop/review/repository.py`
- Modify: payload helpers in generation and review tests

- [ ] **Step 1: Write failing normalization tests**

```python
import pytest

from ai_content_loop.editorial.schema import (
    FinalSchemaError,
    normalize_final_payload,
)


def legacy_payload():
    body = "正文内容足够长。来源：https://example.com/source"
    return {
        "dedupe_key": "github:owner/repo",
        "column": "开源项目淘金",
        "master_title": "一个值得关注的开源项目",
        "master_markdown": body,
        "platform_markdown": {
            name: body
            for name in ("wechat", "xiaohongshu", "toutiao", "zhihu")
        },
    }


def test_normalize_legacy_payload_adds_safe_defaults():
    value = normalize_final_payload(legacy_payload())
    assert value["editorial_profile"]["version"] == "legacy"
    assert value["editorial_profile"]["quality_warnings"] == [
        "legacy_editorial_profile"
    ]
    assert value["visual_brief"] is None
    assert value["visual_assets"] == {"cover": None, "body": []}


def test_rejects_unknown_top_level_field():
    payload = legacy_payload()
    payload["surprise"] = "model-controlled"
    with pytest.raises(FinalSchemaError, match="final fields"):
        normalize_final_payload(payload)
```

- [ ] **Step 2: Run the tests and verify the import fails**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_editorial_schema.py -q
```

Expected: FAIL with `ModuleNotFoundError: ai_content_loop.editorial`.

- [ ] **Step 3: Implement strict normalization**

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

PLATFORMS = ("wechat", "xiaohongshu", "toutiao", "zhihu")
CORE_FIELDS = {
    "dedupe_key", "column", "master_title",
    "master_markdown", "platform_markdown",
}
FINAL_FIELDS = CORE_FIELDS | {
    "editorial_profile", "visual_brief", "visual_assets",
}


class FinalSchemaError(ValueError):
    pass


def legacy_editorial_profile() -> dict[str, object]:
    return {
        "version": "legacy",
        "persona": "unassigned",
        "humor_level": "unassigned",
        "verified_trial": False,
        "trial_artifact_refs": [],
        "quality_warnings": ["legacy_editorial_profile"],
    }


def empty_visual_assets() -> dict[str, object]:
    return {"cover": None, "body": []}


def normalize_final_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FinalSchemaError("final payload must be an object")
    fields = set(value)
    if fields == CORE_FIELDS:
        normalized = deepcopy(value)
        normalized["editorial_profile"] = legacy_editorial_profile()
        normalized["visual_brief"] = None
        normalized["visual_assets"] = empty_visual_assets()
        return normalized
    if fields != FINAL_FIELDS:
        raise FinalSchemaError("final fields do not match the supported schema")
    return deepcopy(value)
```

Add private validators for non-empty bounded text, four exact platforms, exact editorial-profile keys and types, and exact `{"cover", "body"}` asset keys. Error messages name fields but never echo model-controlled values.

- [ ] **Step 4: Use the shared schema in generation and review**

Generation accepts only `FINAL_FIELDS`; review calls `normalize_final_payload` so old articles still load. Add this generation test:

```python
def test_generation_rejects_legacy_payload():
    failures = validate_generation_payload(
        legacy_payload(),
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )
    assert "missing_editorial_profile" in failures
```

- [ ] **Step 5: Run focused regression tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_editorial_schema.py tests\ai_content_loop\test_generation.py tests\ai_content_loop\test_review_repository.py tests\ai_content_loop\test_review_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai_content_loop/editorial ai_content_loop/generation.py ai_content_loop/review/repository.py tests/ai_content_loop
git commit -m "feat: add enriched editorial article schema"
```

### Task 2: Add deterministic human-voice checks

**Files:**
- Create: `ai_content_loop/editorial/quality.py`
- Create: `tests/ai_content_loop/test_editorial_quality.py`
- Modify: `ai_content_loop/generation.py`
- Modify: `ai_content_loop/review/repository.py`
- Modify: `ai_content_loop/review/static/review.js`

- [ ] **Step 1: Write failing style and evidence tests**

```python
from ai_content_loop.editorial.quality import evaluate_editorial_voice


def profile(*, verified=False):
    return {
        "version": "tech_friend_v1",
        "persona": "tech_friend",
        "humor_level": "light",
        "verified_trial": verified,
        "trial_artifact_refs": ["trial/run-1.json"] if verified else [],
        "quality_warnings": [],
    }


def test_flags_ai_cliches_and_audience_roll_call():
    text = (
        "在这个数字化时代，值得一提的是，这个工具可以赋能每个人。"
        "无论你是学生、职场人、创作者还是老板，都值得使用。"
    )
    result = evaluate_editorial_voice("这个工具值得关注吗", text, profile())
    assert result.failures == ["ai_cliche", "audience_roll_call"]


def test_rejects_unverified_first_person_trial():
    result = evaluate_editorial_voice(
        "这个工具到底能不能干活",
        "我试了一下，实际使用后发现它很快。",
        profile(verified=False),
    )
    assert "unverified_first_person_trial" in result.failures


def test_allows_trial_language_with_artifact():
    result = evaluate_editorial_voice(
        "这个工具到底能不能干活",
        "我试了一下，实际使用后发现它很快。",
        profile(verified=True),
    )
    assert result.passed
```

- [ ] **Step 2: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_editorial_quality.py -q
```

Expected: FAIL because `editorial.quality` does not exist.

- [ ] **Step 3: Implement deterministic checks**

```python
from dataclasses import dataclass

AI_CLICHES = (
    "在这个数字化时代", "赋能", "值得一提的是", "总的来说",
)
AUDIENCE_ROLL_CALLS = (
    "无论你是学生", "学生、职场人、创作者", "职场人、学生、创作者",
)
FIRST_PERSON_TRIALS = (
    "我试了一下", "我实际使用", "实测下来", "我跑了一遍",
)
CHEAP_CLICKBAIT = ("震惊", "彻底颠覆", "人人都能月入过万")


@dataclass(frozen=True)
class EditorialQualityResult:
    passed: bool
    failures: list[str]


def evaluate_editorial_voice(title, wechat_markdown, profile):
    combined = f"{title}\n{wechat_markdown}"
    failures = []
    if any(item in combined for item in AI_CLICHES):
        failures.append("ai_cliche")
    if any(item in combined for item in AUDIENCE_ROLL_CALLS):
        failures.append("audience_roll_call")
    verified = profile.get("verified_trial") is True
    refs = profile.get("trial_artifact_refs")
    if any(item in combined for item in FIRST_PERSON_TRIALS) and not (
        verified and isinstance(refs, list) and refs
    ):
        failures.append("unverified_first_person_trial")
    if any(item in title for item in CHEAP_CLICKBAIT):
        failures.append("cheap_clickbait")
    if combined.count("！") + combined.count("!") > 3:
        failures.append("too_many_exclamations")
    return EditorialQualityResult(not failures, failures)
```

Do not implement emoji counting in stage 1: correct Unicode emoji segmentation needs an explicit dependency. Keep the emoji limit in the prompt and human review instead of shipping a false checker.

- [ ] **Step 4: Integrate checks into generation and review**

Generation emits `editorial:<code>` validation failures. Review returns the same codes as warnings. Add labels:

```javascript
ai_cliche: "存在常见 AI 套话",
audience_roll_call: "受众罗列过于机械",
unverified_first_person_trial: "缺少实测证据却使用第一人称体验",
cheap_clickbait: "标题存在廉价夸张词",
too_many_exclamations: "感叹号过多",
legacy_editorial_profile: "文章尚未升级到新的人格版本",
```

- [ ] **Step 5: Run focused tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_editorial_quality.py tests\ai_content_loop\test_quality_templates.py tests\ai_content_loop\test_generation.py tests\ai_content_loop\test_review_repository.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai_content_loop/editorial/quality.py ai_content_loop/generation.py ai_content_loop/review tests/ai_content_loop
git commit -m "feat: enforce human editorial voice rules"
```

### Task 3: Split Hermes generation into factual and editorial passes

**Files:**
- Create: `ai_content_loop/prompts/factual_draft.md`
- Create: `ai_content_loop/prompts/editorial_voice.md`
- Modify: `ai_content_loop/prompts/drafting.md`
- Modify: `ai_content_loop/generation.py`
- Modify: `tests/ai_content_loop/test_generation.py`

- [ ] **Step 1: Add a failing two-pass test**

Use a core five-field factual payload and an enriched final payload. The visual brief has one primary copy set plus two alternatives:

```python
def enriched_payload():
    value = valid_core_payload()
    value.update({
        "editorial_profile": {
            "version": "tech_friend_v1",
            "persona": "tech_friend",
            "humor_level": "light",
            "verified_trial": False,
            "trial_artifact_refs": [],
            "quality_warnings": [],
        },
        "visual_brief": {
            "template_hint": "ai_done_vs_tests",
            "cover_line": "AI 写完代码，人类打开测试",
            "cover_subline": "笑容不会消失，只会转移",
            "body_panels": [
                {"label": "AI 写完代码", "reaction": "自信"},
                {"label": "你打开测试", "reaction": "沉默"},
            ],
            "alternatives": [
                {
                    "cover_line": "代码写完了，问题刚开始",
                    "cover_subline": "AI 很快，测试更诚实",
                    "body_panels": [
                        {"label": "生成速度", "reaction": "起飞"},
                        {"label": "生产上线", "reaction": "先等等"},
                    ],
                },
                {
                    "cover_line": "AI 程序员上岗第一天",
                    "cover_subline": "不喝咖啡，但会烧 Token",
                    "body_panels": [
                        {"label": "老板看它", "reaction": "省钱"},
                        {"label": "同事看它", "reaction": "别动"},
                    ],
                },
            ],
        },
        "visual_assets": {"cover": None, "body": []},
    })
    return value


def test_generate_runs_factual_then_editorial_pass(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv[-1])
        payload = valid_core_payload() if len(calls) == 1 else enriched_payload()
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(payload, ensure_ascii=False), stderr=""
        )

    outcome = run_generation(tmp_path, runner, retries=0)

    assert outcome.status == "generated"
    assert outcome.attempts == 2
    assert "只写事实稿" in calls[0]
    assert "懂技术的损友" in calls[1]
```

- [ ] **Step 2: Add a failing editorial-only retry test**

```python
def test_editorial_retry_reuses_valid_factual_pass(tmp_path):
    outputs = [
        valid_core_payload(),
        {"invalid": "editorial"},
        enriched_payload(),
    ]
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv[-1])
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(outputs.pop(0), ensure_ascii=False),
            stderr="",
        )

    outcome = run_generation(tmp_path, runner, retries=1)

    assert outcome.status == "generated"
    assert outcome.attempts == 3
    assert sum("只写事实稿" in prompt for prompt in calls) == 1
```

- [ ] **Step 3: Run and verify the tests fail**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py -q
```

Expected: the new tests FAIL because generation still performs one pass.

- [ ] **Step 4: Write the factual prompt**

`factual_draft.md` must request exactly the existing five fields and state:

```markdown
# Hermes 事实稿

Prompt version: factual-v1

只写事实稿，不添加第一人称体验、段子、收入承诺或视觉素材。
所有数字、功能、限制和链接必须来自输入事实包。
公众号版本控制在 700–1000 字；只讲两个证据最充分的场景。
返回一个五字段 JSON 对象，不要解释，不要 Markdown 围栏。
```

- [ ] **Step 5: Write the editorial prompt**

`editorial_voice.md` must include the exact final-field contract and these rules:

```markdown
# 懂技术的损友编辑

Prompt version: editorial-v1

输入包含锁定事实、事实稿和来源。只改变表达，不新增或修改事实。
人格：懂技术的损友 70%，好奇实测派 30%。
每篇 2–4 个自然笑点；前 100 字给判断；只讲两个场景。
禁用 AI 套话、受众点名册、廉价夸张和无证据第一人称实测。
生成一个主视觉文案和两个备选文案。图片文字必须短。
visual_assets 必须严格返回 {"cover": null, "body": []}。
返回一个八字段 JSON 对象，不要解释，不要 Markdown 围栏。
```

Keep `drafting.md` as a one-paragraph compatibility notice pointing developers to the two active prompts. Runtime code must not read it.

- [ ] **Step 6: Refactor generation around a reusable stage call**

Add:

```python
def _run_hermes_json(
    *,
    prompt: str,
    hermes_command: str,
    timeout_seconds: int,
    runner,
) -> tuple[dict[str, Any] | None, list[str]]:
    argv = _hermes_argv(hermes_command, prompt)
    preflight = _prompt_preflight_failure(prompt, argv)
    if preflight:
        return None, [preflight]
    try:
        completed = runner(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, ["hermes_timeout"]
    except (OSError, UnicodeError) as error:
        return None, [f"hermes_launch:{type(error).__name__}"]
    if completed.returncode != 0:
        failures = [f"hermes_exit:{completed.returncode}"]
        if completed.stderr:
            failures.append("hermes_stderr_present")
        return None, failures
    try:
        return parse_generation_output(completed.stdout), []
    except ValueError as error:
        return None, [_bounded_failure("invalid_output:", str(error))]
```

Change `generate_draft` to receive `factual_prompt_path` and `editorial_prompt_path`. Run the factual stage once. Cache a valid factual payload. Retry only the editorial stage, passing the last bounded failures into `_build_prompt`. Count every Hermes subprocess invocation in `GenerationOutcome.attempts`.

On terminal failure, preserve any pre-existing final file. Write the failure artifact, but remove no current article during a schema migration.

- [ ] **Step 7: Update existing generation tests**

Update runner fixtures to return factual output on the first call and enriched output on the second. Preserve tests for prompt bounds, argv encoding, secret-safe failures, atomic writes, retries, invalid JSON, and pre-existing finals.

- [ ] **Step 8: Run generation tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add ai_content_loop/generation.py ai_content_loop/prompts tests/ai_content_loop/test_generation.py
git commit -m "feat: split factual and editorial generation"
```

### Task 4: Preserve structured evidence in bundles and wire two-pass CLI generation

**Files:**
- Modify: `ai_content_loop/templates.py`
- Modify: `ai_content_loop/cli.py`
- Modify: `tests/ai_content_loop/test_quality_templates.py`
- Modify: `tests/ai_content_loop/test_cli.py`

- [ ] **Step 1: Write failing bundle assertions**

Extend `test_build_queue_marks_new_rows_as_needs_generation`:

```python
bundle = json.loads(Path(row["bundle_path"]).read_text(encoding="utf-8"))
assert bundle["facts"] == [
    "一手来源：https://github.com/owner/repo",
]
assert isinstance(bundle["risks"], list)
assert isinstance(bundle["writing_angles"], list)
```

Add a CLI wiring test:

```python
def test_generate_drafts_passes_both_prompt_paths(
    tmp_path, monkeypatch
):
    captured = {}

    def fake_generate_draft(**kwargs):
        captured.update(kwargs)
        return GenerationOutcome(
            dedupe_key="github:owner/repo",
            status="generated",
            attempts=2,
            output_path=tmp_path / "final.json",
        )

    monkeypatch.setattr(cli, "generate_draft", fake_generate_draft)
    run_generate_drafts(seed_one_generation_row(tmp_path))

    assert captured["factual_prompt_path"].name == "factual_draft.md"
    assert captured["editorial_prompt_path"].name == "editorial_voice.md"
```

- [ ] **Step 2: Run the two failing tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_cli.py::test_build_queue_marks_new_rows_as_needs_generation tests\ai_content_loop\test_cli.py::test_generate_drafts_passes_both_prompt_paths -q
```

Expected: FAIL on missing fields and arguments.

- [ ] **Step 3: Add structured evidence to the draft bundle**

In `cmd_build_queue`, construct:

```python
payload = {
    "dedupe_key": pack.dedupe_key,
    "title": pack.title,
    "column": choose_column(pack),
    "source_url": pack.url,
    "facts": list(pack.facts),
    "risks": list(pack.risks),
    "writing_angles": list(pack.writing_angles),
    "brief": build_master_brief(pack),
    "platform_skeletons": build_platform_skeletons(pack),
}
```

Update the WeChat skeleton to 700–1000 words and remove the old instruction to enumerate every audience type.

- [ ] **Step 4: Pass both prompts from the CLI**

```python
prompt_dir = Path(__file__).parent / "prompts"
outcome = generate_draft(
    bundle_path=bundle_path,
    factual_prompt_path=prompt_dir / "factual_draft.md",
    editorial_prompt_path=prompt_dir / "editorial_voice.md",
    final_dir=cfg.output_dir / "final",
    failure_dir=cfg.output_dir / "failures",
    hermes_command=cfg.hermes_command,
    timeout_seconds=cfg.generation_timeout_seconds,
    retries=cfg.generation_retries,
)
```

- [ ] **Step 5: Run CLI and template tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_cli.py tests\ai_content_loop\test_quality_templates.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai_content_loop/templates.py ai_content_loop/cli.py tests/ai_content_loop/test_cli.py tests/ai_content_loop/test_quality_templates.py
git commit -m "feat: preserve evidence for editorial generation"
```

### Task 5: Validate visual briefs and select an original template

**Files:**
- Create: `ai_content_loop/visuals/__init__.py`
- Create: `ai_content_loop/visuals/brief.py`
- Create: `ai_content_loop/visuals/templates.py`
- Create: `tests/ai_content_loop/test_visual_brief.py`
- Modify: `ai_content_loop/editorial/schema.py`
- Modify: `ai_content_loop/generation.py`

- [ ] **Step 1: Write failing visual-contract tests**

```python
import pytest

from ai_content_loop.visuals.brief import (
    VisualBriefError,
    normalize_visual_brief,
)
from ai_content_loop.visuals.templates import select_template


def valid_brief():
    panel_a = {"label": "AI 写完代码", "reaction": "自信"}
    panel_b = {"label": "你打开测试", "reaction": "沉默"}
    return {
        "template_hint": "ai_done_vs_tests",
        "cover_line": "AI 写完代码，人类打开测试",
        "cover_subline": "笑容不会消失，只会转移",
        "body_panels": [panel_a, panel_b],
        "alternatives": [
            {
                "cover_line": "代码写完了，问题刚开始",
                "cover_subline": "AI 很快，测试更诚实",
                "body_panels": [panel_a, panel_b],
            },
            {
                "cover_line": "AI 程序员上岗第一天",
                "cover_subline": "不喝咖啡，但会烧 Token",
                "body_panels": [panel_a, panel_b],
            },
        ],
    }


def test_visual_brief_requires_two_alternatives():
    value = valid_brief()
    value["alternatives"].pop()
    with pytest.raises(VisualBriefError, match="two alternatives"):
        normalize_visual_brief(value)


def test_visual_copy_is_bounded():
    value = valid_brief()
    value["cover_line"] = "太长" * 30
    with pytest.raises(VisualBriefError, match="cover_line"):
        normalize_visual_brief(value)


def test_unknown_hint_falls_back_deterministically():
    first = select_template("github:owner/repo", "unknown")
    second = select_template("github:owner/repo", "unknown")
    assert first == second
```

- [ ] **Step 2: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_visual_brief.py -q
```

Expected: FAIL because `ai_content_loop.visuals` does not exist.

- [ ] **Step 3: Implement six template definitions**

```python
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    layout: str
    background: str
    accent: str
    foreground: str


TEMPLATES = {
    "boss_vs_worker": TemplateSpec(
        "boss_vs_worker", "split", "#FFF7E8", "#E54B4B", "#172033"
    ),
    "expectation_vs_reality": TemplateSpec(
        "expectation_vs_reality", "split", "#F4F1FF", "#6D5EF7", "#172033"
    ),
    "ai_done_vs_tests": TemplateSpec(
        "ai_done_vs_tests", "split", "#07111F", "#43F0B6", "#FFFFFF"
    ),
    "before_vs_after": TemplateSpec(
        "before_vs_after", "split", "#EDF7FF", "#1473E6", "#172033"
    ),
    "do_vs_dont": TemplateSpec(
        "do_vs_dont", "split", "#F8FAFC", "#F59E0B", "#172033"
    ),
    "one_line_verdict": TemplateSpec(
        "one_line_verdict", "verdict", "#111827", "#FDE047", "#FFFFFF"
    ),
}


def select_template(dedupe_key: str, hint: str) -> TemplateSpec:
    if hint in TEMPLATES:
        return TEMPLATES[hint]
    names = tuple(TEMPLATES)
    digest = hashlib.sha256(dedupe_key.encode("utf-8")).digest()
    return TEMPLATES[names[int.from_bytes(digest[:2], "big") % len(names)]]
```

- [ ] **Step 4: Implement bounded visual-brief normalization**

`normalize_visual_brief` requires exact keys, two body panels, two alternatives, and exact `{"label", "reaction"}` panel keys:

```python
LIMITS = {
    "cover_line": 30,
    "cover_subline": 20,
    "label": 16,
    "reaction": 10,
}
```

Reject path-like fields, URLs, HTML, and extra keys. Return a deep copy.

- [ ] **Step 5: Integrate visual validation**

Call `normalize_visual_brief` from the enriched final schema. Convert `VisualBriefError` to bounded generation failures such as `visual_brief:cover_line`.

- [ ] **Step 6: Run tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_visual_brief.py tests\ai_content_loop\test_editorial_schema.py tests\ai_content_loop\test_generation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add ai_content_loop/visuals ai_content_loop/editorial/schema.py ai_content_loop/generation.py tests/ai_content_loop
git commit -m "feat: add visual brief and meme templates"
```

### Task 6: Add Pillow and portable Chinese-font configuration

**Files:**
- Modify: `requirements-review.txt`
- Modify: `ai_content_loop/config.py`
- Modify: `ai_content_loop/config.example.toml`
- Modify: `tests/ai_content_loop/test_config.py`
- Modify: `deploy/systemd/ai-content-loop.service`
- Modify: `deploy/content-review/README.md`

- [ ] **Step 1: Write failing configuration tests**

```python
def test_load_config_reads_visual_settings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'visual_font_path = "/fonts/NotoSansCJK-Regular.ttc"\n'
        "visual_render_concurrency = 1\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.visual_font_path == Path(
        "/fonts/NotoSansCJK-Regular.ttc"
    )
    assert config.visual_render_concurrency == 1


@pytest.mark.parametrize("value", [0, -1, 2])
def test_visual_render_concurrency_is_exactly_one(tmp_path, value):
    path = tmp_path / "config.toml"
    path.write_text(
        f"visual_render_concurrency = {value}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="visual_render_concurrency"):
        load_config(path)
```

- [ ] **Step 2: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_config.py -q
```

Expected: FAIL on missing config fields.

- [ ] **Step 3: Add settings and dependency**

Use:

```python
visual_font_path: Path | None = None
visual_render_concurrency: int = 1
```

Resolve `visual_font_path` relative to the config file when supplied. Reject every concurrency value except `1` in stage 1.

Append to `requirements-review.txt`:

```text
Pillow>=12,<13
```

Pillow 12 supports both local Python 3.13 and server Python 3.12.

- [ ] **Step 4: Make both systemd services use the managed venv**

Change `ai-content-loop.service`:

```ini
ExecStart=/opt/ai-content-loop/venv/bin/python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml daily
```

Update the runbook to install `fonts-noto-cjk`, install `requirements-review.txt` into the venv, and configure:

```toml
visual_font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
visual_render_concurrency = 1
```

- [ ] **Step 5: Run tests and verify unit files**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_config.py -q
```

Expected: PASS.

On the server during deployment:

```bash
sudo systemd-analyze verify deploy/systemd/ai-content-loop.service
sudo systemd-analyze verify deploy/systemd/ai-content-review.service
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```powershell
git add requirements-review.txt ai_content_loop/config.py ai_content_loop/config.example.toml tests/ai_content_loop/test_config.py deploy
git commit -m "chore: add local visual rendering dependencies"
```

### Task 7: Render all six meme templates with Pillow

**Files:**
- Create: `ai_content_loop/visuals/renderer.py`
- Create: `tests/ai_content_loop/test_visual_renderer.py`

- [ ] **Step 1: Write failing renderer tests**

```python
from pathlib import Path

import pytest
from PIL import Image

from ai_content_loop.visuals.renderer import render_visuals
from ai_content_loop.visuals.templates import TEMPLATES


def local_chinese_font() -> Path:
    candidates = (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    )
    return next(path for path in candidates if path.exists())


@pytest.mark.parametrize("template_name", tuple(TEMPLATES))
def test_each_template_renders_bounded_images(
    tmp_path, template_name, valid_brief
):
    cover = tmp_path / f"{template_name}.jpg"
    body = tmp_path / f"{template_name}.png"

    render_visuals(
        brief=valid_brief,
        template=TEMPLATES[template_name],
        font_path=local_chinese_font(),
        cover_path=cover,
        body_path=body,
    )

    with Image.open(cover) as image:
        assert image.size == (900, 383)
        assert image.format == "JPEG"
    with Image.open(body) as image:
        assert image.size == (1080, 608)
        assert image.format == "PNG"
    assert cover.stat().st_size < 1_000_000
    assert body.stat().st_size < 2_000_000
```

Also test `_fit_font` returns a size at or above the declared minimum and raises `VisualRenderError("text_overflow")` when no allowed size fits.

- [ ] **Step 2: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_visual_renderer.py -q
```

Expected: FAIL because `renderer.py` does not exist.

- [ ] **Step 3: Implement font fitting**

```python
from PIL import Image, ImageDraw, ImageFont

COVER_SIZE = (900, 383)
BODY_SIZE = (1080, 608)


class VisualRenderError(RuntimeError):
    pass


def _fit_font(draw, text, font_path, *, max_width, max_height,
              start_size, min_size):
    for size in range(start_size, min_size - 1, -2):
        font = ImageFont.truetype(str(font_path), size=size)
        box = draw.multiline_textbbox(
            (0, 0), text, font=font, spacing=max(4, size // 5)
        )
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return font
    raise VisualRenderError("text_overflow")
```

Add `_wrap_text` using `textbbox` one Chinese character at a time, not Python character counts alone.

- [ ] **Step 4: Implement the two layout families**

`split` draws two labeled panels with original circle-and-line reaction faces. `verdict` draws one large headline and one stamped verdict. Every template uses only `TemplateSpec` colors and original geometric shapes.

Expose:

```python
def render_visuals(
    *,
    brief: dict[str, object],
    template: TemplateSpec,
    font_path: Path,
    cover_path: Path,
    body_path: Path,
) -> None:
    value = normalize_visual_brief(brief)
    cover = Image.new("RGB", COVER_SIZE, template.background)
    cover_draw = ImageDraw.Draw(cover)
    cover_font = _fit_font(
        cover_draw,
        value["cover_line"],
        font_path,
        max_width=650,
        max_height=190,
        start_size=64,
        min_size=36,
    )
    cover_draw.multiline_text(
        (70, 90),
        _wrap_text(
            cover_draw,
            value["cover_line"],
            cover_font,
            max_width=650,
        ),
        font=cover_font,
        fill=template.foreground,
        spacing=12,
    )
    cover_draw.rounded_rectangle(
        (700, 65, 840, 318),
        radius=30,
        fill=template.accent,
    )

    body = Image.new("RGB", BODY_SIZE, template.background)
    body_draw = ImageDraw.Draw(body)
    panels = value["body_panels"]
    if template.layout == "split":
        boxes = ((50, 70, 520, 538), (560, 70, 1030, 538))
    else:
        boxes = ((140, 90, 940, 518),)
        panels = [panels[0]]
    for box, panel in zip(boxes, panels, strict=True):
        body_draw.rounded_rectangle(
            box,
            radius=34,
            outline=template.accent,
            width=8,
        )
        text = f'{panel["label"]}\n{panel["reaction"]}'
        font = _fit_font(
            body_draw,
            text,
            font_path,
            max_width=box[2] - box[0] - 60,
            max_height=box[3] - box[1] - 60,
            start_size=56,
            min_size=30,
        )
        body_draw.multiline_text(
            (box[0] + 30, box[1] + 80),
            text,
            font=font,
            fill=template.foreground,
            spacing=18,
            align="center",
        )

    cover_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.parent.mkdir(parents=True, exist_ok=True)
    cover.save(cover_path, format="JPEG", quality=88, optimize=True)
    body.save(body_path, format="PNG", optimize=True)
```

Write JPEG with `quality=88`, `optimize=True`, and PNG with `optimize=True`. Create parent directories, but leave atomic directory publication to `assets.py`.

- [ ] **Step 5: Add invariant-based visual checks**

Avoid cross-platform byte hashes. Assert:

- the configured background color appears at all four corners;
- the accent color appears in a non-empty pixel region;
- split templates have distinct left/right panel regions;
- verdict templates have one central accent region;
- long valid Chinese copy stays inside declared bounding boxes.

- [ ] **Step 6: Run renderer and visual-contract tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_visual_renderer.py tests\ai_content_loop\test_visual_brief.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add ai_content_loop/visuals/renderer.py tests/ai_content_loop/test_visual_renderer.py
git commit -m "feat: render original meme image templates"
```

### Task 8: Publish immutable asset revisions and wire the daily stage

**Files:**
- Create: `ai_content_loop/visuals/assets.py`
- Create: `ai_content_loop/visuals/pipeline.py`
- Create: `tests/ai_content_loop/test_visual_assets.py`
- Modify: `ai_content_loop/editorial/schema.py`
- Modify: `ai_content_loop/cli.py`
- Modify: `tests/ai_content_loop/test_cli.py`

- [ ] **Step 1: Write failing immutable-asset tests**

```python
import json

from ai_content_loop.visuals.pipeline import generate_visual_assets


def test_render_creates_immutable_revision(
    tmp_path, enriched_payload, chinese_font
):
    first = generate_visual_assets(
        payload=enriched_payload,
        output_dir=tmp_path / "out",
        font_path=chinese_font,
    )
    first_cover = tmp_path / "out" / first["visual_assets"]["cover"]["path"]
    assert first_cover.exists()

    changed = json.loads(json.dumps(first, ensure_ascii=False))
    changed["visual_brief"]["cover_line"] = "第二版封面文案"
    second = generate_visual_assets(
        payload=changed,
        output_dir=tmp_path / "out",
        font_path=chinese_font,
    )

    assert first["visual_assets"]["cover"]["revision"] != (
        second["visual_assets"]["cover"]["revision"]
    )
    assert first_cover.exists()


def test_render_failure_does_not_change_final_json(
    tmp_path, enriched_payload, monkeypatch
):
    final_path = tmp_path / "out" / "final" / "repo.json"
    final_path.parent.mkdir(parents=True)
    final_path.write_text(
        json.dumps(enriched_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    before = final_path.read_bytes()
    monkeypatch.setattr(
        "ai_content_loop.visuals.pipeline.render_visuals",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        generate_visual_assets_for_file(
            final_path=final_path,
            output_dir=tmp_path / "out",
            font_path=tmp_path / "font.ttf",
        )

    assert final_path.read_bytes() == before
```

- [ ] **Step 2: Add a failing marker test**

```python
def test_wechat_body_gets_one_asset_marker(enriched_payload):
    updated = insert_body_asset_marker(enriched_payload)
    body = updated["platform_markdown"]["wechat"]
    assert body.count("{{asset:body-01}}") == 1
    assert body.index("{{asset:body-01}}") < body.index("来源：")
```

- [ ] **Step 3: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_visual_assets.py -q
```

Expected: FAIL because asset modules do not exist.

- [ ] **Step 4: Implement safe asset identity and paths**

Move the existing opaque article ID algorithm into `editorial.schema`:

```python
def article_id_for(dedupe_key: str) -> str:
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:24]
```

Use the same function from review and visuals. Asset paths are always:

```python
Path("assets") / article_id / revision / filename
```

No public function accepts an absolute asset path.

- [ ] **Step 5: Implement atomic revision publication**

`generate_visual_assets` must:

1. normalize the final payload;
2. normalize the selected primary or alternative visual copy;
3. choose a template;
4. compute a revision hash from renderer version, template name, and canonical visual copy;
5. render into a temporary sibling directory;
6. write `manifest.json` with hashes, sizes, template, source kind `original_template`, and `ai_generated: false`;
7. rename the complete temporary directory to the immutable revision path;
8. return a copied payload with relative asset references and one body marker.

The cover reference contains `asset_id`, `revision`, `path`, `template`,
`copy_index`, and `ai_generated`. The single body reference contains the
same keys and uses `asset_id == "body-01"`.

Expose `generate_visual_assets(*, payload, output_dir, font_path,
template_name=None, copy_index=0) -> dict[str, object]` and
`generate_visual_assets_for_file(*, final_path, output_dir, font_path,
template_name=None, copy_index=0) -> dict[str, object]`.

`generate_visual_assets_for_file` atomically writes final JSON only after the immutable asset directory is complete.

- [ ] **Step 6: Add `generate-assets` and daily orchestration**

Add a CLI command that scans final JSON files belonging to `needs_human_review`, skips valid current assets, isolates per-article failures, and prints generated/skipped/failed counts.

Update `cmd_daily`:

```python
def cmd_daily(args):
    cmd_ingest(args)
    cmd_score(args)
    cmd_build_queue(args)
    cmd_generate_drafts(args)
    cmd_generate_assets(args)
```

Add `test_daily_runs_stages_in_order` coverage for `cmd_generate_assets`.

- [ ] **Step 7: Run asset and CLI tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_visual_assets.py tests\ai_content_loop\test_cli.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add ai_content_loop/visuals ai_content_loop/editorial/schema.py ai_content_loop/cli.py tests/ai_content_loop
git commit -m "feat: generate immutable article image assets"
```

### Task 9: Render asset markers and serve only referenced images

**Files:**
- Modify: `ai_content_loop/review/rendering.py`
- Modify: `ai_content_loop/review/repository.py`
- Modify: `ai_content_loop/review/app.py`
- Modify: `tests/ai_content_loop/test_review_rendering.py`
- Modify: `tests/ai_content_loop/test_review_repository.py`
- Modify: `tests/ai_content_loop/test_review_api.py`
- Modify: `tests/ai_content_loop/test_review_auth.py`

- [ ] **Step 1: Write a failing safe-marker rendering test**

```python
def test_render_markdown_expands_known_asset_only():
    html = render_markdown(
        "开头\n\n{{asset:body-01}}\n\n结尾",
        asset_urls={"body-01": "/api/articles/a/assets/body-01/123"},
    )
    assert 'src="/api/articles/a/assets/body-01/123"' in html
    assert "{{asset:" not in html


def test_unknown_asset_marker_is_not_a_url():
    html = render_markdown(
        "{{asset:../../etc/passwd}}",
        asset_urls={},
    )
    assert "/etc/passwd" not in html
    assert "<img" not in html
```

- [ ] **Step 2: Write failing authenticated asset API tests**

```python
def test_asset_requires_login_and_serves_current_reference(review_app):
    client = review_app.test_client()
    article_id = seed_rendered_asset(review_app)

    anonymous = client.get(
        f"/api/articles/{article_id}/assets/body-01/revision-1"
    )
    assert anonymous.status_code == 401

    login(client)
    response = client.get(
        f"/api/articles/{article_id}/assets/body-01/revision-1"
    )
    assert response.status_code == 200
    assert response.mimetype == "image/png"


def test_asset_id_cannot_escape_assets_directory(review_app):
    client = review_app.test_client()
    login(client)
    response = client.get(
        "/api/articles/not-real/assets/body-01/..%2Fpasswd"
    )
    assert response.status_code in {404, 405}
```

- [ ] **Step 3: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_rendering.py tests\ai_content_loop\test_review_api.py -q
```

Expected: FAIL on the old render signature and missing route.

- [ ] **Step 4: Expand markers before Markdown rendering**

```python
ASSET_PATTERN = re.compile(r"\{\{asset:([a-z0-9-]{1,32})\}\}")


def render_markdown(
    markdown: str,
    *,
    asset_urls: dict[str, str] | None = None,
) -> str:
    if not isinstance(markdown, str):
        raise TypeError("markdown must be a string")
    urls = asset_urls or {}

    def replace(match):
        asset_id = match.group(1)
        url = urls.get(asset_id)
        return f"![正文配图]({url})" if url else "[图片尚未生成]"

    return _MARKDOWN.render(ASSET_PATTERN.sub(replace, markdown))
```

Raw HTML stays disabled.

- [ ] **Step 5: Resolve only current referenced assets**

Add `assets_dir` to `ArticleRepository`; set `self.assets_dir =
Path(assets_dir)` and `self.output_dir = self.assets_dir.parent`.
Then implement:

```python
def asset_path(
    self,
    article_id: str,
    asset_id: str,
    revision: str,
) -> Path:
    _, payload = self._find(article_id)
    refs = []
    cover = payload["visual_assets"]["cover"]
    if isinstance(cover, dict):
        refs.append(cover)
    refs.extend(payload["visual_assets"]["body"])
    match = next(
        (
            item for item in refs
            if item["asset_id"] == asset_id
            and item["revision"] == revision
        ),
        None,
    )
    if match is None:
        raise ArticleNotFound(asset_id)
    path = (self.output_dir / match["path"]).resolve()
    path.relative_to(self.assets_dir.resolve())
    if not path.is_file() or path.is_symlink():
        raise ArticleNotFound(asset_id)
    return path
```

Convert `ValueError` from `relative_to` into `ArticleNotFound`.

- [ ] **Step 6: Add preview mapping and asset route**

Add `ASSET_DIR` to production/test config. `/api/preview` must require `article_id` plus `markdown`, obtain URLs from the repository, and ignore asset paths supplied by the browser.

Add:

```python
@app.get(
    "/api/articles/<article_id>/assets/<asset_id>/<revision>"
)
@login_required
def article_asset(article_id, asset_id, revision):
    return send_file(
        repository.asset_path(article_id, asset_id, revision),
        conditional=True,
        max_age=31536000,
    )
```

The revision path segment makes each immutable image URL cache-safe.

- [ ] **Step 7: Run review tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_rendering.py tests\ai_content_loop\test_review_repository.py tests\ai_content_loop\test_review_api.py tests\ai_content_loop\test_review_auth.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add ai_content_loop/review tests/ai_content_loop
git commit -m "feat: preview and serve article image assets"
```

### Task 10: Add local copy/template rerender API and approval guard

**Files:**
- Modify: `ai_content_loop/review/repository.py`
- Modify: `ai_content_loop/review/app.py`
- Modify: `tests/ai_content_loop/test_review_repository.py`
- Modify: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write failing visual-render API tests**

```python
def test_visual_render_switches_copy_and_template(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = first_article_id(client)
    loaded = client.get(f"/api/articles/{article_id}").get_json()

    response = client.post(
        f"/api/articles/{article_id}/visuals/render",
        json={
            "version": loaded["version"],
            "template": "boss_vs_worker",
            "copy_index": 1,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    payload = response.get_json()["payload"]
    assert payload["visual_assets"]["cover"]["template"] == "boss_vs_worker"
    assert payload["visual_assets"]["cover"]["copy_index"] == 1
```

- [ ] **Step 2: Write failing approval tests**

```python
def test_cannot_approve_missing_visuals(repository):
    article_id = repository.list_articles()[0]["article_id"]
    with pytest.raises(InvalidArticle, match="visual assets"):
        repository.set_status(article_id, "approved")


def test_cannot_approve_with_editorial_warnings(repository):
    article_id = seed_article_with_assets(
        repository,
        warnings=["legacy_editorial_profile"],
    )
    with pytest.raises(InvalidArticle, match="quality warnings"):
        repository.set_status(article_id, "approved")
```

- [ ] **Step 3: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_repository.py tests\ai_content_loop\test_review_api.py -q
```

Expected: FAIL because rerender route and approval checks do not exist.

- [ ] **Step 4: Extend history operation names**

Allow:

```python
HISTORY_OPERATIONS = {
    "edit", "restore", "visual_edit", "editorial_upgrade",
}
```

The existing history envelope already stores the complete previous payload, so immutable asset references make joint text/image restore work without copying image bytes.

- [ ] **Step 5: Add approval readiness**

```python
def _approval_failures(self, payload):
    failures = list(self._warnings(payload))
    assets = payload["visual_assets"]
    if not isinstance(assets.get("cover"), dict):
        failures.append("missing_cover_asset")
    if len(assets.get("body", [])) != 1:
        failures.append("missing_body_asset")
    warnings = payload["editorial_profile"]["quality_warnings"]
    failures.extend(str(item) for item in warnings)
    return list(dict.fromkeys(failures))


def set_status(self, article_id, status):
    _, payload = self._find(article_id)
    if status == "approved":
        failures = self._approval_failures(payload)
        if failures:
            raise InvalidArticle(
                "article has unresolved editorial or visual asset warnings"
            )
    self.store.set_review_status(payload["dedupe_key"], status)
```

- [ ] **Step 6: Add local rerender route**

Configure `OUTPUT_DIR` and `VISUAL_FONT_PATH` in `create_app`. The route accepts only a 64-character version hash, one template in `TEMPLATES`, and `copy_index` in `{0, 1, 2}`.

Flow:

1. load current article and compare the browser version;
2. call `generate_visual_assets` using current payload;
3. save the returned payload with operation `visual_edit`;
4. return the same shape as `GET /api/articles/<id>`.

Do not accept paths, colors, fonts, arbitrary template JSON, or image URLs from the browser.

- [ ] **Step 7: Run review tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_repository.py tests\ai_content_loop\test_review_api.py tests\ai_content_loop\test_review_auth.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add ai_content_loop/review tests/ai_content_loop
git commit -m "feat: review and rerender visual asset versions"
```

### Task 11: Add visual review controls to the browser desk

**Files:**
- Modify: `ai_content_loop/review/templates/review.html`
- Modify: `ai_content_loop/review/static/review.js`
- Modify: `ai_content_loop/review/static/review.css`
- Modify: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Extend the failing review-shell test**

```python
def test_review_page_contains_visual_controls(review_app):
    client = review_app.test_client()
    login(client)
    html = client.get("/").get_data(as_text=True)

    assert 'id="cover-preview"' in html
    assert 'id="body-image-preview"' in html
    assert 'id="visual-template"' in html
    assert 'id="next-copy-button"' in html
    assert 'id="render-visuals-button"' in html
```

- [ ] **Step 2: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_api.py::test_review_page_contains_visual_controls -q
```

Expected: FAIL on missing IDs.

- [ ] **Step 3: Add semantic visual controls**

Add a `visual-panel` above the Markdown/preview panes:

```html
<section id="visual-panel" class="visual-panel">
  <div class="visual-card">
    <span class="pane-title">公众号封面</span>
    <img id="cover-preview" alt="公众号封面预览">
  </div>
  <div class="visual-card">
    <span class="pane-title">正文插图</span>
    <img id="body-image-preview" alt="正文插图预览">
  </div>
  <div class="visual-controls">
    <label>梗图模板
      <select id="visual-template">
        <option value="boss_vs_worker">老板 vs 打工人</option>
        <option value="expectation_vs_reality">预期 vs 现实</option>
        <option value="ai_done_vs_tests">AI 写完 vs 测试打开</option>
        <option value="before_vs_after">使用前 vs 使用后</option>
        <option value="do_vs_dont">能干 vs 别干</option>
        <option value="one_line_verdict">一句话判决</option>
      </select>
    </label>
    <button id="next-copy-button" type="button">换一句梗</button>
    <button id="render-visuals-button" type="button">应用模板</button>
  </div>
</section>
```

Images without assets show an explicit “尚未生成” placeholder; do not use broken image icons as state.

- [ ] **Step 4: Update client state and preview calls**

Add:

```javascript
visualCopyIndex: 0,
```

Preview requests send:

```javascript
body: JSON.stringify({
  article_id: state.articleId,
  markdown,
}),
```

Render current images with self-hosted URLs:

```javascript
function assetUrl(asset) {
  if (!asset) return "";
  return `/api/articles/${
    encodeURIComponent(state.articleId)
  }/assets/${encodeURIComponent(asset.asset_id)}/${
    encodeURIComponent(asset.revision)
  }`;
}
```

Whenever an article is opened or restored, synchronize the controls from the
current cover reference before rendering:

```javascript
const cover = state.payload.visual_assets?.cover;
state.visualCopyIndex = cover?.copy_index ?? 0;
visualTemplate.value = cover?.template ?? "boss_vs_worker";
```

- [ ] **Step 5: Implement copy cycling and rerender**

```javascript
async function rerenderVisuals() {
  const value = await api(
    `/api/articles/${encodeURIComponent(state.articleId)}/visuals/render`,
    {
      method: "POST",
      body: JSON.stringify({
        version: state.version,
        template: visualTemplate.value,
        copy_index: state.visualCopyIndex,
      }),
    },
  );
  state.payload = value.payload;
  state.version = value.version;
  state.dirty = false;
  renderVisuals();
  schedulePreview();
  notify("图片新版本已生成，旧版本仍可恢复。");
}

nextCopyButton.addEventListener("click", async () => {
  state.visualCopyIndex = (state.visualCopyIndex + 1) % 3;
  await rerenderVisuals();
});
renderVisualsButton.addEventListener("click", rerenderVisuals);
```

Disable both buttons while a request is active and re-enable in `finally`.

- [ ] **Step 6: Add responsive styling**

Desktop uses two visual cards in a row; screens below 760 px stack them. Set `object-fit: contain`, a neutral checker-free background, visible focus styles, and `[hidden] { display: none !important; }`.

- [ ] **Step 7: Run review tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_review_api.py tests\ai_content_loop\test_review_rendering.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add ai_content_loop/review tests/ai_content_loop/test_review_api.py
git commit -m "feat: add visual controls to content review desk"
```

### Task 12: Safely upgrade existing review articles

**Files:**
- Modify: `ai_content_loop/generation.py`
- Modify: `ai_content_loop/cli.py`
- Modify: `tests/ai_content_loop/test_generation.py`
- Modify: `tests/ai_content_loop/test_cli.py`
- Modify: `deploy/content-review/README.md`

- [ ] **Step 1: Write a failing backfill success test**

```python
def test_backfill_upgrades_legacy_article_and_generates_assets(
    tmp_path, monkeypatch
):
    config_path, final_path = seed_legacy_review_article(tmp_path)
    monkeypatch.setattr(
        cli,
        "enrich_factual_payload",
        lambda **_kwargs: (enriched_payload(), 1),
    )

    cli.cmd_backfill_review_assets(
        argparse.Namespace(config=str(config_path), limit=10)
    )

    value = json.loads(final_path.read_text(encoding="utf-8"))
    assert value["editorial_profile"]["version"] == "tech_friend_v1"
    assert value["visual_assets"]["cover"] is not None
    assert len(value["visual_assets"]["body"]) == 1
```

- [ ] **Step 2: Write a failing preservation test**

```python
def test_backfill_failure_preserves_legacy_final(
    tmp_path, monkeypatch
):
    config_path, final_path = seed_legacy_review_article(tmp_path)
    before = final_path.read_bytes()
    monkeypatch.setattr(
        cli,
        "enrich_factual_payload",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    cli.cmd_backfill_review_assets(
        argparse.Namespace(config=str(config_path), limit=10)
    )

    assert final_path.read_bytes() == before
```

- [ ] **Step 3: Run and verify failure**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_cli.py -q
```

Expected: FAIL because the backfill command does not exist.

- [ ] **Step 4: Expose editorial-only enrichment**

Refactor the second pass from Task 3 into
`enrich_factual_payload(*, factual_payload, bundle,
editorial_prompt_path, hermes_command, timeout_seconds, retries,
runner=subprocess.run) -> tuple[dict[str, object], int]`.

It uses the same prompt limits, secret-safe failures, schema validation, and editorial-only retry behavior as normal generation.

- [ ] **Step 5: Add `backfill-review-assets`**

The command:

1. lists only `needs_human_review` articles;
2. selects `editorial_profile.version == "legacy"`;
3. loads the row's original bundle;
4. treats the current legacy final as the factual payload;
5. runs `enrich_factual_payload`;
6. renders assets;
7. saves through `ArticleRepository.save_article` with operation `editorial_upgrade`;
8. catches expected per-article errors and leaves the old file untouched;
9. stops after `--limit`.

Parser:

```python
backfill = sub.add_parser("backfill-review-assets")
backfill.add_argument("--limit", type=int, default=20)
backfill.set_defaults(func=cmd_backfill_review_assets)
```

Reject limits below 1.

- [ ] **Step 6: Add the one-time deployment command**

Document:

```bash
sudo -u agentuser /opt/ai-content-loop/venv/bin/python \
  -m ai_content_loop.cli \
  --config /opt/ai-content-loop/config.toml \
  backfill-review-assets --limit 20
```

Run it only after backing up `out/final`, `out/history`, `out/assets`, and SQLite.

- [ ] **Step 7: Run generation and CLI tests**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py tests\ai_content_loop\test_cli.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add ai_content_loop/generation.py ai_content_loop/cli.py tests/ai_content_loop deploy/content-review/README.md
git commit -m "feat: backfill human voice and visual assets"
```

### Task 13: Prove the complete local story and deploy it safely

**Files:**
- Create: `tests/ai_content_loop/test_phase1_end_to_end.py`
- Modify: `deploy/content-review/README.md`
- Modify: `docs/superpowers/specs/2026-07-04-human-editorial-and-visual-assets-design.md` only if implementation changed an approved contract

- [ ] **Step 1: Write the end-to-end regression test**

The test must use a temporary database/output tree and a fake Hermes runner:

```python
def test_legacy_article_to_reviewed_visual_history(
    tmp_path, monkeypatch
):
    app, config_path = seed_legacy_review_app(tmp_path)
    monkeypatch.setattr(
        cli,
        "enrich_factual_payload",
        lambda **_kwargs: (enriched_payload(), 1),
    )
    cli.cmd_backfill_review_assets(
        argparse.Namespace(config=str(config_path), limit=1)
    )

    client = app.test_client()
    csrf = login(client)
    article_id = first_article_id(client)
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    assert loaded["payload"]["visual_assets"]["cover"] is not None

    changed = client.post(
        f"/api/articles/{article_id}/visuals/render",
        json={
            "version": loaded["version"],
            "template": "boss_vs_worker",
            "copy_index": 1,
        },
        headers={"X-CSRF-Token": csrf},
    ).get_json()
    assert changed["payload"]["visual_assets"]["cover"]["copy_index"] == 1

    history = client.get(
        f"/api/articles/{article_id}/history"
    ).get_json()["history"]
    restored = client.post(
        f"/api/articles/{article_id}/restore/{history[0]['history_id']}",
        json={"version": changed["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert restored.status_code == 200
```

- [ ] **Step 2: Run the complete project test boundary**

Use an existing parent directory for `--basetemp`; run outside the workspace sandbox if Windows denies pytest cleanup:

```powershell
New-Item -ItemType Directory -Path D:\NR_Projects\pytest-runs -Force
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop -q -p no:cacheprovider --basetemp D:\NR_Projects\pytest-runs\human-visuals-phase1
```

Expected: all tests PASS with zero failures or errors.

- [ ] **Step 3: Run static and packaging checks**

```powershell
D:\Users\36997\anaconda3\python.exe -m compileall -q ai_content_loop
git diff --check
git status --short
```

Expected: compile exit 0, no whitespace errors, and only known unrelated user files remain.

- [ ] **Step 4: Perform local browser acceptance**

Start the review service with a temporary config and credentials. Verify:

1. login is required;
2. an enriched article shows cover and inline image;
3. the inline image appears at `{{asset:body-01}}`;
4. “换一句梗” produces copy index 1, then 2, then 0;
5. template switching creates a new revision;
6. old image URLs remain readable through history restore;
7. approval is rejected before assets exist and accepted afterward;
8. narrow mobile layout stacks both image cards;
9. browser console has no errors.

- [ ] **Step 5: Commit final test and runbook changes**

```powershell
git add tests/ai_content_loop/test_phase1_end_to_end.py deploy/content-review/README.md docs/superpowers/specs/2026-07-04-human-editorial-and-visual-assets-design.md
git commit -m "test: cover human editorial visual workflow"
```

If the design file did not change, do not add or amend it.

- [ ] **Step 6: Back up the server before deployment**

On the Lighthouse server:

```bash
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
sudo mkdir -p /opt/ai-content-loop/backups
sudo tar -C /opt/ai-content-loop -czf \
  "/opt/ai-content-loop/backups/pre-human-visuals-${STAMP}.tar.gz" \
  repo out data config.toml review.env
sudo stat "/opt/ai-content-loop/backups/pre-human-visuals-${STAMP}.tar.gz"
```

Expected: a non-empty backup owned by root or the deployment administrator.

- [ ] **Step 7: Upload the committed revision and install dependencies**

Transfer only tracked files. Then:

```bash
cd /opt/ai-content-loop/repo
sudo apt-get update
sudo apt-get install -y fonts-noto-cjk
sudo /opt/ai-content-loop/venv/bin/pip install -r requirements-review.txt
test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
```

Expected: dependency install succeeds and the font exists.

- [ ] **Step 8: Update config and restart services**

Add the approved font/concurrency settings to `/opt/ai-content-loop/config.toml`, copy both service units, then:

```bash
sudo systemd-analyze verify deploy/systemd/ai-content-loop.service
sudo systemd-analyze verify deploy/systemd/ai-content-review.service
sudo cp deploy/systemd/ai-content-loop.service /etc/systemd/system/
sudo cp deploy/systemd/ai-content-review.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart ai-content-review.service
sudo systemctl is-active ai-content-review.service
sudo systemctl is-enabled ai-content-review.service
sudo systemctl is-active ai-content-loop.timer
```

Expected: `active`, `enabled`, `active`.

- [ ] **Step 9: Backfill one canary, inspect it, then finish**

```bash
sudo -u agentuser /opt/ai-content-loop/venv/bin/python \
  -m ai_content_loop.cli \
  --config /opt/ai-content-loop/config.toml \
  backfill-review-assets --limit 1
find /opt/ai-content-loop/out/assets -type f -maxdepth 4 | sort
```

Log in through the public Funnel URL and inspect the canary's text, cover, inline image, warnings, history, and approval guard. Only after the canary passes:

```bash
sudo -u agentuser /opt/ai-content-loop/venv/bin/python \
  -m ai_content_loop.cli \
  --config /opt/ai-content-loop/config.toml \
  backfill-review-assets --limit 20
```

- [ ] **Step 10: Verify production and record the backup**

```bash
sudo journalctl -u ai-content-review.service -n 100 --no-pager
sudo journalctl -u ai-content-loop.service -n 100 --no-pager
tailscale funnel status
sudo ss -lntp '( sport = :8765 )'
```

Expected:

- no traceback, secret, or full prompt in logs;
- Funnel still proxies HTTPS to `127.0.0.1:8765`;
- Gunicorn listens only on loopback;
- daily timer remains active;
- current articles have two images and remain manual-review only.

## Specification coverage audit

| Approved requirement | Phase 1 coverage |
|---|---|
| “懂技术的损友”为主、“好奇实测派”为辅 | Tasks 1–4: schema, deterministic checks, two-pass prompts, evidence bundle |
| 轻幽默、强钩子、少 AI 腔，不虚构亲测 | Tasks 2–4: warnings, editorial-only retry, provenance and evidence constraints |
| 封面 900×383、正文图 1080×608 | Tasks 5–8: visual schema, font/runtime dependencies, six Pillow templates, immutable assets |
| 每篇一张封面和一张正文图 | Tasks 7–9: renderer, daily stage, marker-safe preview and authenticated serving |
| 三组可切换文案、六种原创梗图模板 | Tasks 5, 7, 10, 11: visual brief, renderer, rerender API, browser controls |
| 图片和正文版本可追溯、可恢复 | Tasks 8–11: content-addressed revisions, full-payload history, restore-safe URLs |
| 现有文章可安全升级 | Task 12: legacy-only backfill with atomic preservation |
| 前 30 天人工审核、不能误发 | Tasks 10 and 13: approval guard, no publishing endpoint, canary deployment |
| Lighthouse 4C8G 可稳定运行 | Tasks 6, 8, 13: managed venv, deterministic local rendering, bounded concurrency |
| Hunyuan、远程项目图、沙箱实测、COS、自动发布 | Explicitly deferred to Phase 2 after Phase 1 usage data validates the need |
