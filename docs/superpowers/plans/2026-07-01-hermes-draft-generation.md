# Hermes Draft Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add idempotent Hermes-powered article generation, one retry with quality validation, atomic final/failure artifacts, and a daily 08:00 Asia/Shanghai systemd schedule.

**Architecture:** Deterministic Python owns queue state, prompt assembly, subprocess boundaries, validation, retries, and files. Hermes remains the writing engine and is invoked through its existing CLI configuration. A systemd timer runs the complete Python pipeline as `agentuser`; platform publishing remains manual.

**Tech Stack:** Python 3.11+ standard library, SQLite, pytest, Hermes CLI, TOML, JSON, systemd.

---

## File map

- Create `ai_content_loop/generation.py`: parse Hermes output, validate payloads, invoke Hermes, retry once, and atomically write final or failure JSON.
- Modify `ai_content_loop/config.py`: load Hermes command, timeout, and retry settings.
- Modify `ai_content_loop/config.example.toml`: document generation defaults.
- Modify `ai_content_loop/db.py`: filter queued topics and update queue status.
- Modify `ai_content_loop/cli.py`: add `generate-drafts` and `daily`; make new queue entries `needs_generation`.
- Modify `ai_content_loop/prompts/drafting.md`: strengthen strict-JSON and source-link requirements.
- Create `deploy/systemd/ai-content-loop.service`: run the daily pipeline as `agentuser`.
- Create `deploy/systemd/ai-content-loop.timer`: schedule daily at 08:00 Asia/Shanghai.
- Create `tests/ai_content_loop/test_generation.py`: parser, validation, retry, success, failure, and idempotency tests.
- Modify `tests/ai_content_loop/test_config.py`: generation config tests.
- Modify `tests/ai_content_loop/test_db.py`: queue filtering and lifecycle tests.
- Modify `tests/ai_content_loop/test_cli.py`: CLI generation and daily orchestration tests.
- Modify `docs/ai-content-loop/lighthouse-deployment.md`: deployment and systemd installation.
- Modify `docs/ai-content-loop/operator-runbook.md`: final/failure review instructions.

## Task 0: Preserve the already verified ingestion resilience fix

The main worktree currently contains the prior source-isolation fix as uncommitted changes. Preserve only these scoped files before creating the feature worktree.

- [ ] **Step 1: Verify the scoped diff**

Run:

```powershell
git diff -- .gitignore ai_content_loop/cli.py
git status --short -- .gitignore ai_content_loop/cli.py tests/ai_content_loop/test_cli.py
```

Expected: `.gitignore` ignores runtime output, `cmd_ingest` isolates each source failure, and `test_cli.py` contains the regression test.

- [ ] **Step 2: Run the AI content loop suite**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop -q --basetemp D:\NR_Projects\ITF_DATA\.pytest_tmp_ai_content_generation -p no:cacheprovider
```

Expected: `19 passed`.

- [ ] **Step 3: Commit only the scoped fix**

Run:

```powershell
git add -- .gitignore ai_content_loop/cli.py tests/ai_content_loop/test_cli.py
git commit -m "fix: isolate source ingestion failures"
```

Expected: unrelated deleted/untracked files remain unstaged.

## Task 1: Add generation configuration

**Files:**
- Modify: `ai_content_loop/config.py`
- Modify: `ai_content_loop/config.example.toml`
- Modify: `tests/ai_content_loop/test_config.py`

- [ ] **Step 1: Write failing config tests**

Add to `tests/ai_content_loop/test_config.py`:

```python
def test_load_config_uses_generation_defaults_when_file_missing(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.toml")

    assert cfg.hermes_command == "hermes"
    assert cfg.generation_timeout_seconds == 600
    assert cfg.generation_retries == 1


def test_load_config_reads_generation_values(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
hermes_command = "/home/agentuser/.local/bin/hermes"
generation_timeout_seconds = 420
generation_retries = 1
""",
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.hermes_command == "/home/agentuser/.local/bin/hermes"
    assert cfg.generation_timeout_seconds == 420
    assert cfg.generation_retries == 1
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_config.py -q
```

Expected: FAIL because `AppConfig` has no generation fields.

- [ ] **Step 3: Add minimal config fields**

Add to `AppConfig` in `ai_content_loop/config.py`:

```python
    hermes_command: str = "hermes"
    generation_timeout_seconds: int = 600
    generation_retries: int = 1
```

Add to the `AppConfig(...)` returned for an existing file:

```python
        hermes_command=str(data.get("hermes_command", "hermes")),
        generation_timeout_seconds=int(data.get("generation_timeout_seconds", 600)),
        generation_retries=int(data.get("generation_retries", 1)),
```

Add to `ai_content_loop/config.example.toml`:

```toml
hermes_command = "hermes"
generation_timeout_seconds = 600
generation_retries = 1
```

- [ ] **Step 4: Run config tests and confirm GREEN**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_config.py -q
```

Expected: all config tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- ai_content_loop/config.py ai_content_loop/config.example.toml tests/ai_content_loop/test_config.py
git commit -m "feat: configure Hermes draft generation"
```

## Task 2: Add queue lifecycle and exclude handled topics

**Files:**
- Modify: `ai_content_loop/db.py`
- Modify: `tests/ai_content_loop/test_db.py`

- [ ] **Step 1: Write failing queue tests**

Add helpers and tests to `tests/ai_content_loop/test_db.py` using the file's existing `SourceItem` and `CandidateScore` fixtures:

```python
def test_ranked_candidates_exclude_existing_queue_items(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    item = make_item()
    store.upsert_source_items([item])
    store.upsert_scores(
        [
            CandidateScore(
                dedupe_key=item.dedupe_key,
                novelty=8,
                clarity=9,
                fun=7,
                usefulness=9,
                demo=6,
                heat=5,
                credibility=8,
                total=78.0,
                reason="Clear, useful, and credible.",
            )
        ]
    )
    store.upsert_publish_queue(
        dedupe_key=item.dedupe_key,
        title=item.title,
        column_name="开源项目淘金",
        status="needs_generation",
        bundle_path="out/drafts/item.json",
    )

    assert store.list_ranked_candidates(limit=2, exclude_queued=True) == []


def test_publish_queue_can_filter_and_update_status(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        dedupe_key="github:owner/repo",
        title="Repo",
        column_name="开源项目淘金",
        status="needs_generation",
        bundle_path="out/drafts/repo.json",
    )

    assert len(store.list_publish_queue(status="needs_generation")) == 1
    store.update_publish_queue_status("github:owner/repo", "needs_human_review")
    assert store.list_publish_queue(status="needs_generation") == []
    assert store.list_publish_queue(status="needs_human_review")[0]["dedupe_key"] == "github:owner/repo"
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_db.py -q
```

Expected: FAIL because the methods do not accept filters and the status updater does not exist.

- [ ] **Step 3: Implement queue filtering**

Change the signature in `ai_content_loop/db.py`:

```python
    def list_ranked_candidates(
        self,
        limit: int,
        exclude_queued: bool = False,
    ) -> list[dict[str, Any]]:
```

Build the query deterministically:

```python
        exclusion = """
        WHERE NOT EXISTS (
            SELECT 1
            FROM publish_queue q
            WHERE q.dedupe_key = s.dedupe_key
        )
        """ if exclude_queued else ""
        query = f"""
            SELECT s.dedupe_key, s.source, s.title, s.url, s.summary, s.raw_json,
                   c.total, c.reason
            FROM source_items s
            JOIN candidate_scores c ON c.dedupe_key = s.dedupe_key
            {exclusion}
            ORDER BY c.total DESC, s.fetched_at DESC
            LIMIT ?
        """
```

The only interpolated value is the constant SQL fragment selected by the boolean; data remains parameterized.

- [ ] **Step 4: Implement status query and update**

Replace `list_publish_queue` with:

```python
    def list_publish_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE status = ?" if status is not None else ""
        params: tuple[Any, ...] = (status,) if status is not None else ()
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT dedupe_key, title, column_name, status, bundle_path, created_at
                FROM publish_queue
                {where}
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_publish_queue_status(self, dedupe_key: str, status: str) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE publish_queue SET status = ? WHERE dedupe_key = ?",
                (status, dedupe_key),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown publish queue item: {dedupe_key}")
```

- [ ] **Step 5: Run database tests and confirm GREEN**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_db.py -q
```

Expected: all database tests pass.

- [ ] **Step 6: Commit**

```powershell
git add -- ai_content_loop/db.py tests/ai_content_loop/test_db.py
git commit -m "feat: add draft queue lifecycle"
```

## Task 3: Parse and validate Hermes output

**Files:**
- Create: `ai_content_loop/generation.py`
- Create: `tests/ai_content_loop/test_generation.py`

- [ ] **Step 1: Write failing parser and validation tests**

Create `tests/ai_content_loop/test_generation.py`:

```python
import json

import pytest

from ai_content_loop.generation import parse_generation_output, validate_generation_payload


SOURCE_URL = "https://github.com/owner/repo"


def valid_payload():
    body = f"这是足够长的正文内容，用人话解释工具价值，并保留来源：{SOURCE_URL}"
    return {
        "dedupe_key": "github:owner/repo",
        "column": "开源项目淘金",
        "master_title": "这个 AI 工具很能干，但先别急着吹",
        "master_markdown": body,
        "platform_markdown": {
            "wechat": body,
            "xiaohongshu": body,
            "toutiao": body,
            "zhihu": body,
        },
    }


def test_parse_generation_output_accepts_json_code_fence():
    raw = "```json\n" + json.dumps(valid_payload(), ensure_ascii=False) + "\n```"

    assert parse_generation_output(raw)["dedupe_key"] == "github:owner/repo"


def test_validate_generation_payload_accepts_complete_grounded_content():
    assert validate_generation_payload(
        valid_payload(),
        dedupe_key="github:owner/repo",
        source_url=SOURCE_URL,
    ) == []


def test_validate_generation_payload_rejects_missing_platform_and_wrong_key():
    payload = valid_payload()
    payload["dedupe_key"] = "github:wrong/repo"
    del payload["platform_markdown"]["wechat"]

    failures = validate_generation_payload(
        payload,
        dedupe_key="github:owner/repo",
        source_url=SOURCE_URL,
    )

    assert "dedupe_key_mismatch" in failures
    assert "missing_platform:wechat" in failures


def test_validate_generation_payload_requires_source_in_every_body():
    payload = valid_payload()
    payload["platform_markdown"]["zhihu"] = "这是足够长但没有来源链接的知乎正文。"

    failures = validate_generation_payload(
        payload,
        dedupe_key="github:owner/repo",
        source_url=SOURCE_URL,
    )

    assert "zhihu:missing_source_link" in failures
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py -q
```

Expected: collection fails because `ai_content_loop.generation` does not exist.

- [ ] **Step 3: Implement parser and validator**

Create `ai_content_loop/generation.py`:

```python
from __future__ import annotations

from json import JSONDecodeError, JSONDecoder
from typing import Any

from ai_content_loop.quality import evaluate_draft


PLATFORMS = ("wechat", "xiaohongshu", "toutiao", "zhihu")


def parse_generation_output(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    if start < 0:
        raise ValueError("generation output contains no JSON object")
    try:
        payload, _ = JSONDecoder().raw_decode(raw[start:])
    except JSONDecodeError as exc:
        raise ValueError(f"invalid generation JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("generation output must be a JSON object")
    return payload


def validate_generation_payload(
    payload: dict[str, Any],
    *,
    dedupe_key: str,
    source_url: str,
) -> list[str]:
    failures: list[str] = []
    if payload.get("dedupe_key") != dedupe_key:
        failures.append("dedupe_key_mismatch")
    title = payload.get("master_title")
    master = payload.get("master_markdown")
    platforms = payload.get("platform_markdown")
    if not isinstance(title, str):
        failures.append("invalid_master_title")
        title = ""
    if not isinstance(master, str):
        failures.append("invalid_master_markdown")
        master = ""
    if not isinstance(payload.get("column"), str):
        failures.append("invalid_column")
    if not isinstance(platforms, dict):
        failures.append("invalid_platform_markdown")
        platforms = {}

    master_result = evaluate_draft(title, master, source_url)
    failures.extend(f"master:{failure}" for failure in master_result.failures)
    for platform in PLATFORMS:
        body = platforms.get(platform)
        if not isinstance(body, str):
            failures.append(f"missing_platform:{platform}")
            continue
        result = evaluate_draft(title, body, source_url)
        failures.extend(f"{platform}:{failure}" for failure in result.failures)
    return list(dict.fromkeys(failures))
```

- [ ] **Step 4: Run tests and confirm GREEN**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py -q
```

Expected: all four tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- ai_content_loop/generation.py tests/ai_content_loop/test_generation.py
git commit -m "feat: validate Hermes article payloads"
```

## Task 4: Add Hermes invocation, retry, and atomic artifacts

**Files:**
- Modify: `ai_content_loop/generation.py`
- Modify: `tests/ai_content_loop/test_generation.py`
- Modify: `ai_content_loop/prompts/drafting.md`

- [ ] **Step 1: Write failing generation tests**

Append to `tests/ai_content_loop/test_generation.py`:

```python
from pathlib import Path
from subprocess import CompletedProcess

from ai_content_loop.generation import generate_draft


def write_bundle(path: Path):
    path.write_text(
        json.dumps(
            {
                "dedupe_key": "github:owner/repo",
                "title": "owner/repo",
                "column": "开源项目淘金",
                "source_url": SOURCE_URL,
                "brief": "写一篇易懂有趣的文章。",
                "platform_skeletons": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_generate_draft_retries_once_then_writes_final(tmp_path: Path):
    bundle_path = tmp_path / "drafts" / "repo.json"
    bundle_path.parent.mkdir()
    write_bundle(bundle_path)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        stdout = "not json" if len(calls) == 1 else json.dumps(valid_payload(), ensure_ascii=False)
        return CompletedProcess(command, 0, stdout=stdout, stderr="")

    outcome = generate_draft(
        bundle_path=bundle_path,
        prompt_path=Path("ai_content_loop/prompts/drafting.md"),
        final_dir=tmp_path / "final",
        failure_dir=tmp_path / "failures",
        hermes_command="hermes",
        timeout_seconds=60,
        retries=1,
        runner=runner,
    )

    assert outcome.status == "generated"
    assert outcome.attempts == 2
    assert len(calls) == 2
    final_payload = json.loads(outcome.output_path.read_text(encoding="utf-8"))
    assert final_payload["dedupe_key"] == "github:owner/repo"


def test_generate_draft_records_failure_after_two_attempts(tmp_path: Path):
    bundle_path = tmp_path / "drafts" / "repo.json"
    bundle_path.parent.mkdir()
    write_bundle(bundle_path)

    def runner(command, **kwargs):
        return CompletedProcess(command, 0, stdout="not json", stderr="")

    outcome = generate_draft(
        bundle_path=bundle_path,
        prompt_path=Path("ai_content_loop/prompts/drafting.md"),
        final_dir=tmp_path / "final",
        failure_dir=tmp_path / "failures",
        hermes_command="hermes",
        timeout_seconds=60,
        retries=1,
        runner=runner,
    )

    assert outcome.status == "failed"
    assert outcome.attempts == 2
    failure = json.loads(outcome.output_path.read_text(encoding="utf-8"))
    assert failure["dedupe_key"] == "github:owner/repo"
    assert len(failure["attempt_failures"]) == 2


def test_generate_draft_skips_existing_valid_final(tmp_path: Path):
    bundle_path = tmp_path / "drafts" / "repo.json"
    bundle_path.parent.mkdir()
    write_bundle(bundle_path)
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "repo.json").write_text(
        json.dumps(valid_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    def runner(command, **kwargs):
        raise AssertionError("Hermes must not be called")

    outcome = generate_draft(
        bundle_path=bundle_path,
        prompt_path=Path("ai_content_loop/prompts/drafting.md"),
        final_dir=final_dir,
        failure_dir=tmp_path / "failures",
        hermes_command="hermes",
        timeout_seconds=60,
        retries=1,
        runner=runner,
    )

    assert outcome.status == "skipped_existing"
    assert outcome.attempts == 0
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py -q
```

Expected: FAIL because `generate_draft` does not exist.

- [ ] **Step 3: Implement prompt, subprocess, retry, and atomic writes**

Extend `ai_content_loop/generation.py` with:

```python
from dataclasses import dataclass
from pathlib import Path
import json
import os
import subprocess
import tempfile
from collections.abc import Callable


@dataclass(frozen=True)
class GenerationOutcome:
    dedupe_key: str
    status: str
    attempts: int
    output_path: Path


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _build_prompt(template: str, bundle: dict[str, Any], failures: list[str]) -> str:
    retry = ""
    if failures:
        retry = (
            "\n上一次输出未通过机器校验。请修复以下问题，并重新输出完整 JSON：\n- "
            + "\n- ".join(failures)
        )
    return (
        f"{template}\n\n"
        "下面是本次写作简报 JSON。只输出一个完整 JSON 对象，不要解释，不要使用 Markdown 代码围栏。\n"
        f"{json.dumps(bundle, ensure_ascii=False, indent=2)}"
        f"{retry}"
    )


def generate_draft(
    *,
    bundle_path: Path,
    prompt_path: Path,
    final_dir: Path,
    failure_dir: Path,
    hermes_command: str,
    timeout_seconds: int,
    retries: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> GenerationOutcome:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    dedupe_key = str(bundle["dedupe_key"])
    source_url = str(bundle["source_url"])
    final_path = final_dir / bundle_path.name
    if final_path.exists():
        existing = parse_generation_output(final_path.read_text(encoding="utf-8"))
        if not validate_generation_payload(existing, dedupe_key=dedupe_key, source_url=source_url):
            return GenerationOutcome(dedupe_key, "skipped_existing", 0, final_path)

    template = prompt_path.read_text(encoding="utf-8")
    attempt_failures: list[list[str]] = []
    total_attempts = retries + 1
    for attempt in range(1, total_attempts + 1):
        prompt = _build_prompt(template, bundle, attempt_failures[-1] if attempt_failures else [])
        failures: list[str] = []
        try:
            result = runner(
                [hermes_command, "chat", "-Q", "-q", prompt],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                failures = [f"hermes_exit:{result.returncode}", result.stderr.strip()[:500]]
            else:
                payload = parse_generation_output(result.stdout)
                failures = validate_generation_payload(
                    payload,
                    dedupe_key=dedupe_key,
                    source_url=source_url,
                )
                if not failures:
                    _atomic_write_json(final_path, payload)
                    return GenerationOutcome(dedupe_key, "generated", attempt, final_path)
        except (subprocess.TimeoutExpired, ValueError) as exc:
            failures = [f"{type(exc).__name__}:{exc}"]
        attempt_failures.append([failure for failure in failures if failure])

    failure_path = failure_dir / bundle_path.name
    _atomic_write_json(
        failure_path,
        {
            "dedupe_key": dedupe_key,
            "bundle_path": str(bundle_path),
            "attempts": total_attempts,
            "attempt_failures": attempt_failures,
        },
    )
    return GenerationOutcome(dedupe_key, "failed", total_attempts, failure_path)
```

- [ ] **Step 4: Strengthen the drafting prompt**

Add to `ai_content_loop/prompts/drafting.md`:

```markdown
- 只输出一个合法 JSON 对象，不要补充解释，不要使用 Markdown 代码围栏。
- `dedupe_key` 必须与写作简报完全一致。
- 母稿和四个平台版本都必须原样保留写作简报中的 `source_url`。
```

- [ ] **Step 5: Run generation tests and confirm GREEN**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_generation.py -q
```

Expected: all generation tests pass.

- [ ] **Step 6: Commit**

```powershell
git add -- ai_content_loop/generation.py ai_content_loop/prompts/drafting.md tests/ai_content_loop/test_generation.py
git commit -m "feat: generate validated Hermes drafts"
```

## Task 5: Add CLI generation and daily orchestration

**Files:**
- Modify: `ai_content_loop/cli.py`
- Modify: `tests/ai_content_loop/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/ai_content_loop/test_cli.py`:

```python
from ai_content_loop.config import load_config
from ai_content_loop.generation import GenerationOutcome
from ai_content_loop.models import CandidateScore


def write_test_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
database_path = "content.sqlite3"
output_dir = "out"
publish_limit = 1
hermes_command = "hermes"
generation_timeout_seconds = 60
generation_retries = 1
""",
        encoding="utf-8",
    )
    return config_path


def seed_ranked_candidate(config_path: Path) -> None:
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    item = SourceItem(
        source="github",
        external_id="owner/repo",
        title="Useful AI Repo",
        url="https://github.com/owner/repo",
        summary="A useful AI repo",
        published_at="2026-06-30T00:00:00Z",
        fetched_at="2026-06-30T08:00:00Z",
        raw={"stars": 10},
    )
    store.upsert_source_items([item])
    store.upsert_scores(
        [
            CandidateScore(
                dedupe_key=item.dedupe_key,
                novelty=8,
                clarity=9,
                fun=7,
                usefulness=9,
                demo=6,
                heat=5,
                credibility=8,
                total=78.0,
                reason="Clear, useful, and credible.",
            )
        ]
    )


def test_build_queue_marks_new_items_for_generation(monkeypatch, tmp_path, capsys):
    config_path = write_test_config(tmp_path)
    seed_ranked_candidate(config_path)

    cli.main(["--config", str(config_path), "build-queue"])

    cfg = load_config(config_path)
    queue = ContentStore(cfg.database_path).list_publish_queue()
    assert queue[0]["status"] == "needs_generation"


def test_generate_drafts_updates_queue_status(monkeypatch, tmp_path, capsys):
    config_path = write_test_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    bundle_path = cfg.output_dir / "drafts" / "repo.json"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text("{}", encoding="utf-8")
    store.upsert_publish_queue(
        dedupe_key="github:owner/repo",
        title="Repo",
        column_name="开源项目淘金",
        status="needs_generation",
        bundle_path=str(bundle_path),
    )

    monkeypatch.setattr(
        "ai_content_loop.cli.generate_draft",
        lambda **kwargs: GenerationOutcome(
            "github:owner/repo",
            "generated",
            1,
            cfg.output_dir / "final" / "repo.json",
        ),
    )

    cli.main(["--config", str(config_path), "generate-drafts"])

    assert store.list_publish_queue(status="needs_human_review")[0]["dedupe_key"] == "github:owner/repo"


def test_daily_runs_stages_in_order(monkeypatch, tmp_path):
    config_path = write_test_config(tmp_path)
    calls = []
    monkeypatch.setattr("ai_content_loop.cli.cmd_ingest", lambda args: calls.append("ingest"))
    monkeypatch.setattr("ai_content_loop.cli.cmd_score", lambda args: calls.append("score"))
    monkeypatch.setattr("ai_content_loop.cli.cmd_build_queue", lambda args: calls.append("build-queue"))
    monkeypatch.setattr("ai_content_loop.cli.cmd_generate_drafts", lambda args: calls.append("generate-drafts"))

    cli.main(["--config", str(config_path), "daily"])

    assert calls == ["ingest", "score", "build-queue", "generate-drafts"]
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_cli.py -q
```

Expected: FAIL for missing command and old queue status.

- [ ] **Step 3: Exclude queued topics and use lifecycle state**

In `cmd_build_queue`:

```python
    candidates = store.list_ranked_candidates(
        limit=cfg.publish_limit,
        exclude_queued=True,
    )
```

Change the inserted status to:

```python
            status="needs_generation",
```

- [ ] **Step 4: Add `cmd_generate_drafts`**

Import:

```python
from pathlib import Path
from ai_content_loop.generation import generate_draft
```

Add:

```python
def cmd_generate_drafts(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    prompt_path = Path(__file__).parent / "prompts" / "drafting.md"
    rows = store.list_publish_queue(status="needs_generation")
    generated = failed = skipped = 0
    for row in rows:
        outcome = generate_draft(
            bundle_path=Path(row["bundle_path"]),
            prompt_path=prompt_path,
            final_dir=cfg.output_dir / "final",
            failure_dir=cfg.output_dir / "failures",
            hermes_command=cfg.hermes_command,
            timeout_seconds=cfg.generation_timeout_seconds,
            retries=cfg.generation_retries,
        )
        if outcome.status in {"generated", "skipped_existing"}:
            store.update_publish_queue_status(row["dedupe_key"], "needs_human_review")
            generated += outcome.status == "generated"
            skipped += outcome.status == "skipped_existing"
        else:
            store.update_publish_queue_status(row["dedupe_key"], "generation_failed")
            failed += 1
    print(f"generated {generated}, skipped {skipped}, failed {failed}")
```

- [ ] **Step 5: Add `daily` command**

Add:

```python
def cmd_daily(args: argparse.Namespace) -> None:
    cmd_ingest(args)
    cmd_score(args)
    cmd_build_queue(args)
    cmd_generate_drafts(args)
```

Register parsers:

```python
    generate = sub.add_parser("generate-drafts")
    generate.set_defaults(func=cmd_generate_drafts)

    daily = sub.add_parser("daily")
    daily.set_defaults(func=cmd_daily)
```

- [ ] **Step 6: Run CLI tests and confirm GREEN**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop\test_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 7: Run the full suite**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop -q --basetemp D:\NR_Projects\ITF_DATA\.pytest_tmp_ai_content_generation -p no:cacheprovider
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add -- ai_content_loop/cli.py tests/ai_content_loop/test_cli.py
git commit -m "feat: add Hermes generation commands"
```

## Task 6: Add systemd deployment files

**Files:**
- Create: `deploy/systemd/ai-content-loop.service`
- Create: `deploy/systemd/ai-content-loop.timer`
- Modify: `docs/ai-content-loop/lighthouse-deployment.md`
- Modify: `docs/ai-content-loop/operator-runbook.md`

- [ ] **Step 1: Create the service**

Create `deploy/systemd/ai-content-loop.service`:

```ini
[Unit]
Description=AI content collection and Hermes draft generation
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=agentuser
Group=agentuser
WorkingDirectory=/opt/ai-content-loop/repo
Environment=HOME=/home/agentuser
Environment=PYTHONUNBUFFERED=1
UMask=0027
ExecStart=/usr/bin/python3 -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml daily
TimeoutStartSec=45min
```

- [ ] **Step 2: Create the timer**

Create `deploy/systemd/ai-content-loop.timer`:

```ini
[Unit]
Description=Run AI content loop every day at 08:00 Asia/Shanghai

[Timer]
OnCalendar=*-*-* 08:00:00 Asia/Shanghai
Persistent=true
Unit=ai-content-loop.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Update deployment documentation**

Add exact install commands to `docs/ai-content-loop/lighthouse-deployment.md`:

```bash
sudo install -o root -g root -m 0644 \
  /opt/ai-content-loop/repo/deploy/systemd/ai-content-loop.service \
  /etc/systemd/system/ai-content-loop.service
sudo install -o root -g root -m 0644 \
  /opt/ai-content-loop/repo/deploy/systemd/ai-content-loop.timer \
  /etc/systemd/system/ai-content-loop.timer
sudo systemctl daemon-reload
sudo systemctl enable --now ai-content-loop.timer
systemctl list-timers ai-content-loop.timer
```

Document:

```bash
sudo systemctl start ai-content-loop.service
sudo journalctl -u ai-content-loop.service -n 100 --no-pager
```

- [ ] **Step 4: Update operator runbook**

Document:

- review `out/final/*.json`;
- read the appropriate `platform_markdown` field;
- inspect `out/failures/*.json` when generation fails;
- never publish `generation_failed`;
- keep platform posting manual for the first 30 days.

- [ ] **Step 5: Validate unit syntax locally**

Run:

```powershell
rg -n "User=agentuser|UMask=0027|OnCalendar=.*Asia/Shanghai|Persistent=true" deploy/systemd
```

Expected: all four settings are present.

- [ ] **Step 6: Commit**

```powershell
git add -- deploy/systemd/ai-content-loop.service deploy/systemd/ai-content-loop.timer docs/ai-content-loop/lighthouse-deployment.md docs/ai-content-loop/operator-runbook.md
git commit -m "ops: schedule daily AI content generation"
```

## Task 7: Local verification and integration

- [ ] **Step 1: Run the full suite**

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests\ai_content_loop -q --basetemp D:\NR_Projects\ITF_DATA\.pytest_tmp_ai_content_generation -p no:cacheprovider
```

Expected: zero failures.

- [ ] **Step 2: Run syntax and CLI checks**

```powershell
D:\Users\36997\anaconda3\python.exe -m compileall -q ai_content_loop
D:\Users\36997\anaconda3\python.exe -m ai_content_loop.cli --help
```

Expected: help includes `generate-drafts` and `daily`.

- [ ] **Step 3: Request code review**

Use `superpowers:requesting-code-review` against the feature branch diff. Resolve any correctness issues, then rerun Steps 1 and 2.

- [ ] **Step 4: Merge the feature branch**

Use `superpowers:finishing-a-development-branch`. Select local merge after verification, rerun the full suite on `main`, and remove only the feature worktree created for this implementation.

## Task 8: Deploy and perform real Hermes generation

- [ ] **Step 1: Upload the verified package and systemd files**

Upload current `ai_content_loop/` and `deploy/systemd/` to the existing `/opt/ai-content-loop/repo` tree through the already verified SSH key. Before replacing files, create:

```bash
sudo tar -C /opt -czf /opt/ai-content-loop-backup-$(date +%Y%m%d-%H%M%S).tar.gz ai-content-loop
```

Keep the backup until real generation and timer verification pass.

- [ ] **Step 2: Install production generation config**

Ensure `/opt/ai-content-loop/config.toml` contains:

```toml
hermes_command = "/home/agentuser/.local/bin/hermes"
generation_timeout_seconds = 600
generation_retries = 1
```

Retain the deployed absolute `database_path`, `output_dir`, and `hackernews = 10`.

- [ ] **Step 3: Migrate the two legacy queue rows**

Run a bounded Python/SQLite migration that updates only rows with missing final files:

```python
from pathlib import Path
import sqlite3

root = Path("/opt/ai-content-loop")
with sqlite3.connect(root / "data" / "ai_content_loop.sqlite3") as connection:
    rows = connection.execute(
        "SELECT dedupe_key, bundle_path FROM publish_queue WHERE status = 'needs_human_review'"
    ).fetchall()
    for dedupe_key, bundle_path in rows:
        final_path = root / "out" / "final" / Path(bundle_path).name
        if not final_path.exists():
            connection.execute(
                "UPDATE publish_queue SET status = 'needs_generation' WHERE dedupe_key = ?",
                (dedupe_key,),
            )
```

Expected: exactly the two existing GitHub topics become `needs_generation`.

- [ ] **Step 4: Run real generation**

As `agentuser`:

```bash
cd /opt/ai-content-loop/repo
python3 -m ai_content_loop.cli \
  --config /opt/ai-content-loop/config.toml \
  generate-drafts
```

Expected: `generated 2, skipped 0, failed 0`. A model or content failure may produce one automatic retry, but no item receives more than two calls.

- [ ] **Step 5: Validate final artifacts**

Verify:

- exactly two JSON files exist in `/opt/ai-content-loop/out/final`;
- each parses as JSON;
- each contains all four platform keys;
- each platform body contains the original source URL;
- queue statuses are `needs_human_review`;
- no private key or model credential appears in final/failure files.

- [ ] **Step 6: Install and verify timer**

```bash
sudo install -o root -g root -m 0644 \
  /opt/ai-content-loop/repo/deploy/systemd/ai-content-loop.service \
  /etc/systemd/system/ai-content-loop.service
sudo install -o root -g root -m 0644 \
  /opt/ai-content-loop/repo/deploy/systemd/ai-content-loop.timer \
  /etc/systemd/system/ai-content-loop.timer
sudo systemd-analyze verify /etc/systemd/system/ai-content-loop.service
sudo systemd-analyze verify /etc/systemd/system/ai-content-loop.timer
sudo systemctl daemon-reload
sudo systemctl enable --now ai-content-loop.timer
systemctl list-timers ai-content-loop.timer --no-pager
```

Expected: timer is active and the next trigger is 08:00 Asia/Shanghai.

- [ ] **Step 7: Final read-only verification**

Check:

```bash
systemctl is-enabled ai-content-loop.timer
systemctl is-active ai-content-loop.timer
sudo -iu agentuser hermes cron status
find /opt/ai-content-loop/out/final -maxdepth 1 -type f -name '*.json' -print
```

Expected: systemd timer is enabled and active; Hermes gateway remains running; two final files are present.
