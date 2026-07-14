# AI Content Review Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a password-protected browser review desk that renders, edits, versions, copies, and approves the existing multi-platform article JSON files.

**Architecture:** Add a small Flask application beside the existing batch workflow. A repository layer keeps `out/final/*.json` as the canonical article body, creates atomic history snapshots, and uses SQLite only for source metadata and review status. Gunicorn listens on loopback; Tailscale Funnel supplies the public HTTPS endpoint.

**Tech Stack:** Python 3.11+, Flask 3, Werkzeug, markdown-it-py, Gunicorn, SQLite, vanilla JavaScript/CSS, systemd, Tailscale Funnel

---

## File map

Create:

- `requirements-review.txt` — review-service-only Python dependencies.
- `ai_content_loop/review/__init__.py` — package exports.
- `ai_content_loop/review/rendering.py` — safe Markdown rendering.
- `ai_content_loop/review/repository.py` — article lookup, validation, atomic saves, history, restore, and review status.
- `ai_content_loop/review/auth.py` — login, logout, CSRF, session enforcement, and login throttling.
- `ai_content_loop/review/app.py` — Flask application factory, pages, JSON API, and security headers.
- `ai_content_loop/review/wsgi.py` — production application entrypoint.
- `ai_content_loop/review/templates/login.html` — login screen.
- `ai_content_loop/review/templates/review.html` — review desk shell.
- `ai_content_loop/review/static/review.css` — responsive layout and rendered-article styling.
- `ai_content_loop/review/static/review.js` — article loading, editing, previewing, saving, copy, status, and history UI.
- `tests/ai_content_loop/test_review_rendering.py` — renderer safety tests.
- `tests/ai_content_loop/test_review_repository.py` — persistence and history tests.
- `tests/ai_content_loop/test_review_auth.py` — authentication and CSRF tests.
- `tests/ai_content_loop/test_review_api.py` — API behavior tests.
- `deploy/systemd/ai-content-review.service` — long-running review service.
- `deploy/content-review/README.md` — server installation, credentials, Funnel, verification, and rollback.

Modify:

- `ai_content_loop/db.py` — fetch source URL and expose a constrained review-status update.
- `tests/ai_content_loop/test_db.py` — cover the new database methods.
- `.gitignore` — ignore local review secrets and generated history.

Do not modify:

- Hermes prompting or generation behavior.
- Existing daily timer semantics.
- Existing final JSON schema.

### Task 1: Add review dependencies and safe Markdown rendering

**Files:**

- Create: `requirements-review.txt`
- Create: `ai_content_loop/review/__init__.py`
- Create: `ai_content_loop/review/rendering.py`
- Create: `tests/ai_content_loop/test_review_rendering.py`

- [ ] **Step 1: Write the failing renderer tests**

```python
# tests/ai_content_loop/test_review_rendering.py
from ai_content_loop.review.rendering import render_markdown


def test_render_markdown_supports_article_structure():
    html = render_markdown(
        "# 标题\n\n> 结论\n\n- 第一项\n- 第二项\n\n[来源](https://example.com)"
    )

    assert "<h1>标题</h1>" in html
    assert "<blockquote>" in html
    assert "<li>第一项</li>" in html
    assert 'href="https://example.com"' in html


def test_render_markdown_disables_raw_html():
    html = render_markdown(
        '<script>alert("x")</script>\n\n<img src=x onerror=alert(1)>'
    )

    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
```

- [ ] **Step 2: Run the renderer tests and verify the import fails**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_rendering.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ai_content_loop.review'`.

- [ ] **Step 3: Add dependencies and the renderer**

```text
# requirements-review.txt
Flask>=3.1,<4
gunicorn>=23,<24
markdown-it-py>=3,<4
```

```python
# ai_content_loop/review/__init__.py
"""Browser review desk for generated content."""
```

```python
# ai_content_loop/review/rendering.py
from __future__ import annotations

from markdown_it import MarkdownIt


_MARKDOWN = MarkdownIt(
    "commonmark",
    {
        "html": False,
        "linkify": False,
        "typographer": False,
    },
)


def render_markdown(markdown: str) -> str:
    if not isinstance(markdown, str):
        raise TypeError("markdown must be a string")
    return _MARKDOWN.render(markdown)
```

- [ ] **Step 4: Run the renderer tests**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_rendering.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```powershell
git add requirements-review.txt ai_content_loop/review tests/ai_content_loop/test_review_rendering.py
git commit -m "feat: add safe article markdown rendering"
```

### Task 2: Add source lookup and constrained review states

**Files:**

- Modify: `ai_content_loop/db.py`
- Modify: `tests/ai_content_loop/test_db.py`

- [ ] **Step 1: Write failing database tests**

Append:

```python
def test_get_source_url_returns_url_for_known_item(tmp_path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    item = make_item(external_id="owner/repo")
    store.upsert_source_items([item])

    assert store.get_source_url(item.dedupe_key) == item.url
    assert store.get_source_url("missing") is None


def test_set_review_status_accepts_only_review_states(tmp_path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_publish_queue(
        "github:owner/repo",
        "Repo",
        "开源项目淘金",
        "needs_human_review",
        str(tmp_path / "draft.json"),
    )

    store.set_review_status("github:owner/repo", "approved")
    assert store.list_publish_queue()[0]["status"] == "approved"

    with pytest.raises(ValueError, match="unsupported review status"):
        store.set_review_status("github:owner/repo", "generating")
```

Use the existing `make_item` helper and imports in `test_db.py`; `pytest` is already imported.

- [ ] **Step 2: Run the two tests and verify they fail**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_db.py -q
```

Expected: FAIL because `get_source_url` and `set_review_status` do not exist.

- [ ] **Step 3: Implement the database methods**

Add inside `ContentStore`:

```python
    def get_source_url(self, dedupe_key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT url FROM source_items WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
        return None if row is None else str(row["url"])

    def set_review_status(self, dedupe_key: str, status: str) -> None:
        allowed = {"needs_human_review", "approved", "revision_requested"}
        if status not in allowed:
            raise ValueError(f"unsupported review status: {status}")
        self.update_publish_queue_status(dedupe_key, status)
```

- [ ] **Step 4: Run database and existing content-loop tests**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_db.py -q
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop -q
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai_content_loop/db.py tests/ai_content_loop/test_db.py
git commit -m "feat: add content review database operations"
```

### Task 3: Build atomic article persistence and history

**Files:**

- Create: `ai_content_loop/review/repository.py`
- Create: `tests/ai_content_loop/test_review_repository.py`

- [ ] **Step 1: Write repository test fixtures and failing tests**

Create a test file containing:

```python
from __future__ import annotations

import json

import pytest

from ai_content_loop.db import ContentStore
from ai_content_loop.models import SourceItem
from ai_content_loop.review.repository import (
    ArticleConflict,
    ArticleNotFound,
    ArticleRepository,
    InvalidArticle,
)


DEDUPE_KEY = "github:owner/repo"
SOURCE_URL = "https://github.com/owner/repo"


def article_payload(body: str = "正文内容足够长。" * 8) -> dict:
    platform_body = f"{body}\n\n来源：{SOURCE_URL}"
    return {
        "dedupe_key": DEDUPE_KEY,
        "column": "开源项目淘金",
        "master_title": "一个值得关注的开源项目",
        "master_markdown": platform_body,
        "platform_markdown": {
            "wechat": platform_body,
            "xiaohongshu": platform_body,
            "toutiao": platform_body,
            "zhihu": platform_body,
        },
    }


@pytest.fixture
def repository(tmp_path):
    final_dir = tmp_path / "out" / "final"
    final_dir.mkdir(parents=True)
    (final_dir / "repo.json").write_text(
        json.dumps(article_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    store.upsert_source_items(
        [
            SourceItem(
                source="github",
                external_id="owner/repo",
                title="Repo",
                url=SOURCE_URL,
                summary="Summary",
                published_at="2026-07-01T00:00:00+00:00",
                fetched_at="2026-07-01T01:00:00+00:00",
                raw={},
            )
        ]
    )
    store.upsert_publish_queue(
        DEDUPE_KEY,
        "Repo",
        "开源项目淘金",
        "needs_human_review",
        str(tmp_path / "draft.json"),
    )
    return ArticleRepository(
        store=store,
        final_dir=final_dir,
        history_dir=tmp_path / "out" / "history",
    )


def test_list_and_load_use_opaque_article_id(repository):
    rows = repository.list_articles()
    assert len(rows) == 1
    assert rows[0]["dedupe_key"] == DEDUPE_KEY
    assert "/" not in rows[0]["article_id"]

    loaded = repository.load_article(rows[0]["article_id"])
    assert loaded["payload"]["dedupe_key"] == DEDUPE_KEY
    assert len(loaded["version"]) == 64


def test_save_creates_snapshot_and_rejects_stale_version(repository):
    article = repository.list_articles()[0]
    loaded = repository.load_article(article["article_id"])
    changed = dict(loaded["payload"])
    changed["master_title"] = "修改后的标题"

    saved = repository.save_article(
        article["article_id"],
        payload=changed,
        expected_version=loaded["version"],
        operation="edit",
    )
    assert saved["payload"]["master_title"] == "修改后的标题"
    assert saved["version"] != loaded["version"]
    assert len(repository.list_history(article["article_id"])) == 1

    with pytest.raises(ArticleConflict):
        repository.save_article(
            article["article_id"],
            payload=loaded["payload"],
            expected_version=loaded["version"],
            operation="edit",
        )


def test_restore_creates_new_version_without_deleting_history(repository):
    article_id = repository.list_articles()[0]["article_id"]
    original = repository.load_article(article_id)
    changed = dict(original["payload"])
    changed["master_title"] = "第二版"
    second = repository.save_article(
        article_id,
        changed,
        original["version"],
        operation="edit",
    )
    historical = repository.list_history(article_id)[0]

    restored = repository.restore_article(
        article_id,
        history_id=historical["history_id"],
        expected_version=second["version"],
    )

    assert restored["payload"]["master_title"] == original["payload"]["master_title"]
    assert len(repository.list_history(article_id)) == 2


def test_rejects_unknown_article_and_invalid_payload(repository):
    with pytest.raises(ArticleNotFound):
        repository.load_article("../../etc/passwd")

    article = repository.list_articles()[0]
    loaded = repository.load_article(article["article_id"])
    invalid = dict(loaded["payload"])
    invalid["platform_markdown"] = {"wechat": "only one"}
    with pytest.raises(InvalidArticle):
        repository.save_article(
            article["article_id"],
            invalid,
            loaded["version"],
            operation="edit",
        )
```

- [ ] **Step 2: Run the repository tests and verify they fail**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_repository.py -q
```

Expected: FAIL because `repository.py` does not exist.

- [ ] **Step 3: Implement the repository**

```python
# ai_content_loop/review/repository.py
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from ai_content_loop.db import ContentStore
from ai_content_loop.generation import validate_generation_payload


PLATFORMS = ("wechat", "xiaohongshu", "toutiao", "zhihu")
EXPECTED_FIELDS = {
    "dedupe_key",
    "column",
    "master_title",
    "master_markdown",
    "platform_markdown",
}
MAX_FIELD_CHARS = 200_000


def _article_id(dedupe_key: str) -> str:
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:24]


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _version(payload: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


class ArticleNotFound(KeyError):
    """The requested opaque article or history identifier does not exist."""


class ArticleConflict(RuntimeError):
    """The article changed after the browser loaded its version."""


class InvalidArticle(ValueError):
    """The submitted article does not match the final article schema."""


def _atomic_json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidArticle(f"{field} must be a non-empty string")
    if len(value) > MAX_FIELD_CHARS:
        raise InvalidArticle(f"{field} exceeds {MAX_FIELD_CHARS} characters")
    return value


def _validate_payload(
    value: object,
    *,
    expected_dedupe_key: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != EXPECTED_FIELDS:
        raise InvalidArticle("article fields do not match the final schema")

    dedupe_key = _require_text(value.get("dedupe_key"), "dedupe_key")
    if expected_dedupe_key is not None and dedupe_key != expected_dedupe_key:
        raise InvalidArticle("dedupe_key cannot be changed")

    platform_value = value.get("platform_markdown")
    if not isinstance(platform_value, dict) or set(platform_value) != set(PLATFORMS):
        raise InvalidArticle("platform_markdown must contain exactly four platforms")
    platforms = {
        platform: _require_text(platform_value.get(platform), platform)
        for platform in PLATFORMS
    }
    return {
        "dedupe_key": dedupe_key,
        "column": _require_text(value.get("column"), "column"),
        "master_title": _require_text(value.get("master_title"), "master_title"),
        "master_markdown": _require_text(
            value.get("master_markdown"),
            "master_markdown",
        ),
        "platform_markdown": platforms,
    }


class ArticleRepository:
    def __init__(
        self,
        *,
        store: ContentStore,
        final_dir: Path,
        history_dir: Path,
    ) -> None:
        self.store = store
        self.final_dir = Path(final_dir)
        self.history_dir = Path(history_dir)
        self._write_lock = threading.RLock()

    def _scan(self) -> dict[str, tuple[Path, dict[str, Any]]]:
        articles: dict[str, tuple[Path, dict[str, Any]]] = {}
        if not self.final_dir.exists():
            return articles
        for path in sorted(self.final_dir.glob("*.json")):
            if not path.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                payload = _validate_payload(value)
            except (OSError, json.JSONDecodeError, InvalidArticle):
                continue
            articles[_article_id(payload["dedupe_key"])] = (path, payload)
        return articles

    def _find(self, article_id: str) -> tuple[Path, dict[str, Any]]:
        if not isinstance(article_id, str):
            raise ArticleNotFound(article_id)
        found = self._scan().get(article_id)
        if found is None:
            raise ArticleNotFound(article_id)
        return found

    def _warnings(self, payload: dict[str, Any]) -> list[str]:
        source_url = self.store.get_source_url(payload["dedupe_key"])
        if source_url is None:
            return ["missing_source_metadata"]
        return validate_generation_payload(
            payload,
            dedupe_key=payload["dedupe_key"],
            source_url=source_url,
        )

    def list_articles(
        self,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        queue = {
            row["dedupe_key"]: row
            for row in self.store.list_publish_queue(status=status)
        }
        rows: list[dict[str, object]] = []
        for article_id, (_, payload) in self._scan().items():
            queue_row = queue.get(payload["dedupe_key"])
            if status is not None and queue_row is None:
                continue
            rows.append(
                {
                    "article_id": article_id,
                    "dedupe_key": payload["dedupe_key"],
                    "title": payload["master_title"],
                    "column": payload["column"],
                    "status": (
                        queue_row["status"] if queue_row is not None else "untracked"
                    ),
                    "created_at": (
                        queue_row["created_at"] if queue_row is not None else None
                    ),
                }
            )
        rows.sort(key=lambda row: str(row["created_at"] or ""), reverse=True)
        return rows

    def load_article(self, article_id: str) -> dict[str, object]:
        _, payload = self._find(article_id)
        return {
            "article_id": article_id,
            "payload": payload,
            "version": _version(payload),
            "warnings": self._warnings(payload),
        }

    def save_article(
        self,
        article_id: str,
        payload: object,
        expected_version: str,
        *,
        operation: str,
    ) -> dict[str, object]:
        with self._write_lock:
            if operation not in {"edit", "restore"}:
                raise ValueError(f"unsupported history operation: {operation}")
            path, current = self._find(article_id)
            current_version = _version(current)
            if not isinstance(expected_version, str) or not hmac.compare_digest(
                current_version,
                expected_version,
            ):
                raise ArticleConflict(article_id)

            replacement = _validate_payload(
                payload,
                expected_dedupe_key=current["dedupe_key"],
            )
            now = datetime.now(UTC)
            history_id = (
                f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-"
                f"{operation}-{current_version[:12]}.json"
            )
            envelope = {
                "metadata": {
                    "saved_at": now.isoformat(),
                    "operation": operation,
                    "version": current_version,
                },
                "payload": current,
            }
            _atomic_json_write(self.history_dir / article_id / history_id, envelope)
            _atomic_json_write(path, replacement)
            return self.load_article(article_id)

    def list_history(self, article_id: str) -> list[dict[str, str]]:
        self._find(article_id)
        directory = self.history_dir / article_id
        rows: list[dict[str, str]] = []
        if not directory.exists():
            return rows
        for path in directory.glob("*.json"):
            if not path.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                metadata = value["metadata"]
                rows.append(
                    {
                        "history_id": path.name,
                        "saved_at": str(metadata["saved_at"]),
                        "operation": str(metadata["operation"]),
                        "version": str(metadata["version"]),
                    }
                )
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
        rows.sort(key=lambda row: row["saved_at"], reverse=True)
        return rows

    def restore_article(
        self,
        article_id: str,
        history_id: str,
        expected_version: str,
    ) -> dict[str, object]:
        known = {
            row["history_id"]
            for row in self.list_history(article_id)
        }
        if history_id not in known:
            raise ArticleNotFound(history_id)
        value = json.loads(
            (self.history_dir / article_id / history_id).read_text(encoding="utf-8")
        )
        return self.save_article(
            article_id,
            value["payload"],
            expected_version,
            operation="restore",
        )

    def set_status(self, article_id: str, status: str) -> None:
        _, payload = self._find(article_id)
        self.store.set_review_status(payload["dedupe_key"], status)
```

- [ ] **Step 4: Run repository and content-loop tests**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_repository.py -q
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop -q
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai_content_loop/review/repository.py tests/ai_content_loop/test_review_repository.py
git commit -m "feat: add versioned article repository"
```

### Task 4: Add login, session, CSRF, and login throttling

**Files:**

- Create: `ai_content_loop/review/auth.py`
- Create: `ai_content_loop/review/templates/login.html`
- Create: `tests/ai_content_loop/test_review_auth.py`

- [ ] **Step 1: Write failing authentication tests**

```python
# tests/ai_content_loop/test_review_auth.py
from werkzeug.security import generate_password_hash

from ai_content_loop.review.app import create_app


def make_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "REVIEW_USERNAME": "owner",
            "REVIEW_PASSWORD_HASH": generate_password_hash("correct horse"),
            "DATABASE_PATH": tmp_path / "content.sqlite3",
            "FINAL_DIR": tmp_path / "final",
            "HISTORY_DIR": tmp_path / "history",
            "LOGIN_ATTEMPTS": 2,
            "LOGIN_WINDOW_SECONDS": 300,
        }
    )


def csrf_from(client):
    with client.session_transaction() as session:
        return session["csrf_token"]


def test_login_and_logout(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    login_page = client.get("/login")
    assert login_page.status_code == 200
    token = csrf_from(client)

    response = client.post(
        "/login",
        data={
            "username": "owner",
            "password": "correct horse",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200

    response = client.post(
        "/logout",
        headers={"X-CSRF-Token": csrf_from(client)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert client.get("/").status_code == 302


def test_write_request_requires_csrf(tmp_path):
    client = make_app(tmp_path).test_client()
    client.get("/login")
    client.post(
        "/login",
        data={
            "username": "owner",
            "password": "correct horse",
            "csrf_token": csrf_from(client),
        },
    )

    response = client.post("/api/preview", json={"markdown": "# 标题"})
    assert response.status_code == 403


def test_login_is_throttled_after_repeated_failure(tmp_path):
    client = make_app(tmp_path).test_client()
    client.get("/login")
    for _ in range(2):
        response = client.post(
            "/login",
            data={
                "username": "owner",
                "password": "wrong",
                "csrf_token": csrf_from(client),
            },
        )
        assert response.status_code == 401

    response = client.post(
        "/login",
        data={
            "username": "owner",
            "password": "correct horse",
            "csrf_token": csrf_from(client),
        },
    )
    assert response.status_code == 429
```

- [ ] **Step 2: Run the auth tests and verify they fail**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_auth.py -q
```

Expected: FAIL because `review.app` and auth handlers do not exist.

- [ ] **Step 3: Implement authentication helpers**

In `auth.py`, implement:

```python
from __future__ import annotations

from collections import defaultdict, deque
from functools import wraps
import hmac
import secrets
import threading
import time

from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash


auth = Blueprint("auth", __name__)


class LoginLimiter:
    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def blocked(self, key: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            queue = self.failures[key]
            while queue and current - queue[0] >= self.window_seconds:
                queue.popleft()
            return len(queue) >= self.attempts

    def fail(self, key: str) -> None:
        with self._lock:
            self.failures[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self.failures.pop(key, None)


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_csrf() -> None:
    supplied = request.headers.get("X-CSRF-Token")
    if request.form:
        supplied = request.form.get("csrf_token", supplied)
    if not isinstance(supplied, str) or not hmac.compare_digest(
        supplied,
        csrf_token(),
    ):
        abort(403)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("authenticated") is not True:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def _client_key() -> str:
    remote = request.remote_addr or "unknown"
    if remote in {"127.0.0.1", "::1"}:
        forwarded = request.headers.get("X-Forwarded-For", "")
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    return remote


@auth.route("/login", methods=["GET", "POST"])
def login():
    error = None
    status = 200
    token = csrf_token()
    if request.method == "POST":
        require_csrf()
        limiter: LoginLimiter = current_app.extensions["login_limiter"]
        key = _client_key()
        if limiter.blocked(key):
            error = "登录尝试过多，请稍后再试。"
            status = 429
        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            username_ok = hmac.compare_digest(
                username,
                current_app.config["REVIEW_USERNAME"],
            )
            password_ok = check_password_hash(
                current_app.config["REVIEW_PASSWORD_HASH"],
                password,
            )
            if username_ok and password_ok:
                limiter.clear(key)
                session.clear()
                session["authenticated"] = True
                session.permanent = True
                csrf_token()
                return redirect(url_for("review_page"))
            limiter.fail(key)
            error = "用户名或密码错误。"
            status = 401
    return (
        render_template(
            "login.html",
            error=error,
            csrf_token=token,
        ),
        status,
    )


@auth.post("/logout")
@login_required
def logout():
    require_csrf()
    session.clear()
    return redirect(url_for("auth.login"))
```

- [ ] **Step 4: Add the minimum application factory needed by the tests**

```python
# ai_content_loop/review/app.py
from __future__ import annotations

from flask import Flask, jsonify, request

from ai_content_loop.review.auth import (
    LoginLimiter,
    auth,
    login_required,
    require_csrf,
)
from ai_content_loop.review.rendering import render_markdown


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        LOGIN_ATTEMPTS=5,
        LOGIN_WINDOW_SECONDS=300,
    )
    if test_config is not None:
        app.config.update(test_config)
    required = ("SECRET_KEY", "REVIEW_USERNAME", "REVIEW_PASSWORD_HASH")
    if any(not app.config.get(name) for name in required):
        raise RuntimeError("review service configuration is incomplete")
    app.config["SESSION_COOKIE_SECURE"] = not app.config.get("TESTING", False)
    app.extensions["login_limiter"] = LoginLimiter(
        app.config["LOGIN_ATTEMPTS"],
        app.config["LOGIN_WINDOW_SECONDS"],
    )
    app.register_blueprint(auth)

    @app.get("/")
    @login_required
    def review_page():
        return "review"

    @app.post("/api/preview")
    @login_required
    def preview():
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("markdown"), str):
            return jsonify(error="invalid_markdown"), 400
        return jsonify(html=render_markdown(value["markdown"]))

    return app
```

Create the minimal login template used by the tests:

```html
<!-- ai_content_loop/review/templates/login.html -->
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>登录 · AI 内容审阅台</title>
</head>
<body>
  <main>
    <h1>AI 内容审阅台</h1>
    {% if error %}<p role="alert">{{ error }}</p>{% endif %}
    <form method="post" action="{{ url_for('auth.login') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>用户名 <input name="username" autocomplete="username" required></label>
      <label>密码 <input name="password" type="password" autocomplete="current-password" required></label>
      <button type="submit">登录</button>
    </form>
  </main>
</body>
</html>
```

- [ ] **Step 5: Run authentication tests**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_auth.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```powershell
git add ai_content_loop/review/auth.py ai_content_loop/review/app.py ai_content_loop/review/templates/login.html tests/ai_content_loop/test_review_auth.py
git commit -m "feat: secure the content review service"
```

### Task 5: Add the authenticated article API

**Files:**

- Modify: `ai_content_loop/review/app.py`
- Create: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write API fixtures and failing tests**

```python
# tests/ai_content_loop/test_review_api.py
import json

import pytest
from werkzeug.security import generate_password_hash

from ai_content_loop.db import ContentStore
from ai_content_loop.models import SourceItem
from ai_content_loop.review.app import create_app


DEDUPE_KEY = "github:owner/repo"
SOURCE_URL = "https://github.com/owner/repo"


def make_payload():
    body = f"{'正文内容足够长。' * 8}\n\n来源：{SOURCE_URL}"
    return {
        "dedupe_key": DEDUPE_KEY,
        "column": "开源项目淘金",
        "master_title": "一个值得关注的开源项目",
        "master_markdown": body,
        "platform_markdown": {
            "wechat": body,
            "xiaohongshu": body,
            "toutiao": body,
            "zhihu": body,
        },
    }


@pytest.fixture
def review_app(tmp_path):
    database_path = tmp_path / "content.sqlite3"
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "repo.json").write_text(
        json.dumps(make_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store = ContentStore(database_path)
    store.initialize()
    store.upsert_source_items(
        [
            SourceItem(
                source="github",
                external_id="owner/repo",
                title="Repo",
                url=SOURCE_URL,
                summary="Summary",
                published_at="2026-07-01T00:00:00+00:00",
                fetched_at="2026-07-01T01:00:00+00:00",
                raw={},
            )
        ]
    )
    store.upsert_publish_queue(
        DEDUPE_KEY,
        "Repo",
        "开源项目淘金",
        "needs_human_review",
        str(tmp_path / "draft.json"),
    )
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "REVIEW_USERNAME": "owner",
            "REVIEW_PASSWORD_HASH": generate_password_hash("correct horse"),
            "DATABASE_PATH": database_path,
            "FINAL_DIR": final_dir,
            "HISTORY_DIR": tmp_path / "history",
        }
    )


def login(client):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["csrf_token"]
    response = client.post(
        "/login",
        data={
            "username": "owner",
            "password": "correct horse",
            "csrf_token": token,
        },
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        return session["csrf_token"]


def test_article_api_round_trip(review_app):
    client = review_app.test_client()
    csrf = login(client)

    listed = client.get("/api/articles").get_json()
    article_id = listed["articles"][0]["article_id"]
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    loaded["payload"]["master_title"] = "浏览器里修改的标题"

    response = client.put(
        f"/api/articles/{article_id}",
        json={
            "payload": loaded["payload"],
            "version": loaded["version"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.get_json()["payload"]["master_title"] == "浏览器里修改的标题"


def test_stale_save_returns_conflict(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    changed = loaded["payload"]
    changed["master_title"] = "第一次保存"

    first = client.put(
        f"/api/articles/{article_id}",
        json={"payload": changed, "version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert first.status_code == 200

    stale = client.put(
        f"/api/articles/{article_id}",
        json={"payload": loaded["payload"], "version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert stale.status_code == 409


def test_history_restore_and_status(review_app):
    client = review_app.test_client()
    csrf = login(client)
    article_id = client.get("/api/articles").get_json()["articles"][0]["article_id"]
    loaded = client.get(f"/api/articles/{article_id}").get_json()
    changed = loaded["payload"]
    changed["master_title"] = "新标题"
    saved = client.put(
        f"/api/articles/{article_id}",
        json={"payload": changed, "version": loaded["version"]},
        headers={"X-CSRF-Token": csrf},
    ).get_json()

    history = client.get(f"/api/articles/{article_id}/history").get_json()["history"]
    restored = client.post(
        f"/api/articles/{article_id}/restore/{history[0]['history_id']}",
        json={"version": saved["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert restored.status_code == 200

    status_response = client.post(
        f"/api/articles/{article_id}/status",
        json={"status": "approved"},
        headers={"X-CSRF-Token": csrf},
    )
    assert status_response.status_code == 200
```

The `review_app` fixture must construct the real `create_app` with temporary `DATABASE_PATH`, `FINAL_DIR`, and `HISTORY_DIR`, then insert one source item, queue row, and final JSON before yielding the app.

- [ ] **Step 2: Run the API tests and verify missing routes**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_api.py -q
```

Expected: FAIL with 404 responses for article routes.

- [ ] **Step 3: Wire the repository into the application**

```python
# ai_content_loop/review/app.py
from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request

from ai_content_loop.db import ContentStore
from ai_content_loop.review.auth import (
    LoginLimiter,
    auth,
    login_required,
    require_csrf,
)
from ai_content_loop.review.rendering import render_markdown
from ai_content_loop.review.repository import (
    ArticleConflict,
    ArticleNotFound,
    ArticleRepository,
    InvalidArticle,
)


REVIEW_STATUSES = {
    "needs_human_review",
    "approved",
    "revision_requested",
}


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        LOGIN_ATTEMPTS=5,
        LOGIN_WINDOW_SECONDS=300,
    )
    if test_config is not None:
        app.config.update(test_config)
    required = (
        "SECRET_KEY",
        "REVIEW_USERNAME",
        "REVIEW_PASSWORD_HASH",
        "DATABASE_PATH",
        "FINAL_DIR",
        "HISTORY_DIR",
    )
    if any(not app.config.get(name) for name in required):
        raise RuntimeError("review service configuration is incomplete")
    app.config["SESSION_COOKIE_SECURE"] = not app.config.get("TESTING", False)
    app.extensions["login_limiter"] = LoginLimiter(
        app.config["LOGIN_ATTEMPTS"],
        app.config["LOGIN_WINDOW_SECONDS"],
    )

    store = ContentStore(app.config["DATABASE_PATH"])
    store.initialize()
    repository = ArticleRepository(
        store=store,
        final_dir=Path(app.config["FINAL_DIR"]),
        history_dir=Path(app.config["HISTORY_DIR"]),
    )
    app.extensions["article_repository"] = repository
    app.register_blueprint(auth)

    @app.errorhandler(ArticleNotFound)
    def article_not_found(error):
        return jsonify(error="not_found"), 404

    @app.errorhandler(InvalidArticle)
    def invalid_article(error):
        return jsonify(error="invalid_article", detail=str(error)), 400

    @app.errorhandler(ArticleConflict)
    def article_conflict(error):
        return jsonify(error="version_conflict"), 409

    @app.get("/")
    @login_required
    def review_page():
        return "review"

    @app.post("/api/preview")
    @login_required
    def preview():
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("markdown"), str):
            return jsonify(error="invalid_markdown"), 400
        return jsonify(html=render_markdown(value["markdown"]))

    @app.get("/api/articles")
    @login_required
    def list_articles():
        status = request.args.get("status")
        if status is not None and status not in REVIEW_STATUSES:
            return jsonify(error="invalid_status"), 400
        return jsonify(articles=repository.list_articles(status=status))

    @app.get("/api/articles/<article_id>")
    @login_required
    def get_article(article_id: str):
        return jsonify(repository.load_article(article_id))

    @app.put("/api/articles/<article_id>")
    @login_required
    def save_article(article_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("version"), str)
        ):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            repository.save_article(
                article_id,
                value.get("payload"),
                value.get("version"),
                operation="edit",
            )
        )

    @app.get("/api/articles/<article_id>/history")
    @login_required
    def list_history(article_id: str):
        return jsonify(history=repository.list_history(article_id))

    @app.post("/api/articles/<article_id>/restore/<history_id>")
    @login_required
    def restore_article(article_id: str, history_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            repository.restore_article(
                article_id,
                history_id,
                value["version"],
            )
        )

    @app.post("/api/articles/<article_id>/status")
    @login_required
    def set_status(article_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        status = value.get("status") if isinstance(value, dict) else None
        if status not in REVIEW_STATUSES:
            return jsonify(error="invalid_status"), 400
        repository.set_status(article_id, status)
        return jsonify(status=status)

    return app
```

- [ ] **Step 4: Run API, auth, repository, and full tests**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_api.py tests/ai_content_loop/test_review_auth.py tests/ai_content_loop/test_review_repository.py -q
D:\Users\36997\anaconda3\python.exe -m pytest tests -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai_content_loop/review/app.py tests/ai_content_loop/test_review_api.py
git commit -m "feat: add the content review API"
```

### Task 6: Build the responsive review interface

**Files:**

- Modify: `ai_content_loop/review/templates/login.html`
- Create: `ai_content_loop/review/templates/review.html`
- Create: `ai_content_loop/review/static/review.css`
- Create: `ai_content_loop/review/static/review.js`
- Modify: `ai_content_loop/review/app.py`
- Modify: `tests/ai_content_loop/test_review_auth.py`
- Modify: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Add failing page-shell tests**

Add assertions:

```python
def test_review_page_contains_editor_shell(review_app):
    client = review_app.test_client()
    login(client)
    html = client.get("/").get_data(as_text=True)

    assert 'id="article-list"' in html
    assert 'id="markdown-editor"' in html
    assert 'id="article-preview"' in html
    assert 'id="save-button"' in html
    assert 'id="history-dialog"' in html
    assert 'data-platform="wechat"' in html
    assert 'data-platform="xiaohongshu"' in html
    assert 'data-platform="toutiao"' in html
    assert 'data-platform="zhihu"' in html


def test_login_page_does_not_echo_password_hash(tmp_path):
    app = make_app(tmp_path)
    html = app.test_client().get("/login").get_data(as_text=True)
    assert app.config["REVIEW_PASSWORD_HASH"] not in html
    assert 'name="csrf_token"' in html
```

- [ ] **Step 2: Run the page tests and verify they fail**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_auth.py tests/ai_content_loop/test_review_api.py -q
```

Expected: FAIL because the temporary page does not contain the review shell.

- [ ] **Step 3: Create the templates**

```html
<!-- ai_content_loop/review/templates/login.html -->
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>登录 · AI 内容审阅台</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='review.css') }}">
</head>
<body class="login-page">
  <main class="login-card">
    <p class="eyebrow">HERMES CONTENT LOOP</p>
    <h1>AI 内容审阅台</h1>
    <p class="muted">查看、修改并确认今天的待发布内容。</p>
    {% if error %}<p class="notice error" role="alert">{{ error }}</p>{% endif %}
    <form method="post" action="{{ url_for('auth.login') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>用户名
        <input name="username" autocomplete="username" required autofocus>
      </label>
      <label>密码
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <button class="primary wide" type="submit">登录</button>
    </form>
  </main>
</body>
</html>
```

```html
<!-- ai_content_loop/review/templates/review.html -->
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="csrf-token" content="{{ csrf_token }}">
  <title>AI 内容审阅台</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='review.css') }}">
  <script src="{{ url_for('static', filename='review.js') }}" defer></script>
</head>
<body>
  <header class="topbar">
    <button id="sidebar-button" class="icon-button mobile-only" type="button" aria-label="打开文章列表">☰</button>
    <div>
      <strong>AI 内容审阅台</strong>
      <span class="muted">Hermes 生成 · 人工把关</span>
    </div>
    <div class="topbar-user">
      <span>{{ username }}</span>
      <button id="logout-button" class="quiet" type="button">退出</button>
    </div>
  </header>

  <main class="review-layout">
    <aside id="article-sidebar" class="article-sidebar">
      <div class="sidebar-heading">
        <h1>文章</h1>
        <select id="status-filter" aria-label="审核状态">
          <option value="">全部</option>
          <option value="needs_human_review">待审核</option>
          <option value="approved">已通过</option>
          <option value="revision_requested">已退回</option>
        </select>
      </div>
      <div id="article-list" class="article-list" aria-live="polite"></div>
    </aside>

    <section class="workspace">
      <div id="empty-state" class="empty-state">
        <h2>选择一篇文章开始审阅</h2>
        <p>左侧是 Hermes 已经生成的待发布内容。</p>
      </div>

      <div id="editor-shell" class="editor-shell" hidden>
        <div class="article-fields">
          <label>标题
            <input id="article-title" maxlength="200000">
          </label>
          <label>栏目
            <input id="article-column" maxlength="200000">
          </label>
        </div>

        <nav class="platform-tabs" aria-label="内容版本">
          <button type="button" data-platform="master">母稿</button>
          <button type="button" data-platform="wechat">公众号</button>
          <button type="button" data-platform="xiaohongshu">小红书</button>
          <button type="button" data-platform="toutiao">今日头条</button>
          <button type="button" data-platform="zhihu">知乎</button>
        </nav>

        <div id="quality-warnings" class="quality-warnings" hidden></div>

        <div class="mobile-view-switch mobile-only">
          <button id="show-editor-button" class="selected" type="button">编辑</button>
          <button id="show-preview-button" type="button">预览</button>
        </div>

        <div id="content-panes" class="content-panes show-editor">
          <section class="editor-pane">
            <div class="pane-title">Markdown</div>
            <textarea id="markdown-editor" spellcheck="false" aria-label="Markdown 正文"></textarea>
          </section>
          <section class="preview-pane">
            <div class="pane-title">发布排版预览</div>
            <article id="article-preview" class="article-preview"></article>
          </section>
        </div>

        <footer class="actionbar">
          <div>
            <button id="history-button" class="quiet" type="button">历史版本</button>
            <button id="copy-button" class="quiet" type="button">复制正文</button>
          </div>
          <div>
            <button id="reject-button" class="danger" type="button">退回</button>
            <button id="approve-button" class="success" type="button">通过</button>
            <button id="save-button" class="primary" type="button">保存修改</button>
          </div>
        </footer>
      </div>
    </section>
  </main>

  <div id="notification" class="notification" role="status" aria-live="polite" hidden></div>

  <dialog id="history-dialog">
    <header>
      <h2>历史版本</h2>
      <button id="history-close-button" class="icon-button" type="button" aria-label="关闭">×</button>
    </header>
    <div id="history-list"></div>
  </dialog>
</body>
</html>
```

Update the imports in `app.py`:

```python
from flask import Flask, current_app, jsonify, render_template, request
from ai_content_loop.review.auth import (
    LoginLimiter,
    auth,
    csrf_token,
    login_required,
    require_csrf,
)
```

Replace the temporary page body with:

```python
    @app.get("/")
    @login_required
    def review_page():
        return render_template(
            "review.html",
            csrf_token=csrf_token(),
            username=current_app.config["REVIEW_USERNAME"],
        )
```

- [ ] **Step 4: Implement the browser state machine**

```javascript
// ai_content_loop/review/static/review.js
const state = {
  articles: [],
  articleId: null,
  payload: null,
  version: null,
  platform: "wechat",
  dirty: false,
  previewRequest: 0,
};

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const articleList = document.querySelector("#article-list");
const statusFilter = document.querySelector("#status-filter");
const emptyState = document.querySelector("#empty-state");
const editorShell = document.querySelector("#editor-shell");
const titleInput = document.querySelector("#article-title");
const columnInput = document.querySelector("#article-column");
const markdownEditor = document.querySelector("#markdown-editor");
const articlePreview = document.querySelector("#article-preview");
const warnings = document.querySelector("#quality-warnings");
const notification = document.querySelector("#notification");
const historyDialog = document.querySelector("#history-dialog");
const historyList = document.querySelector("#history-list");
const contentPanes = document.querySelector("#content-panes");

async function api(path, options = {}) {
  const request = {...options};
  request.headers = {
    Accept: "application/json",
    ...(request.headers || {}),
  };
  if (request.body !== undefined) {
    request.headers["Content-Type"] = "application/json";
    request.headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch(path, request);
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("登录已过期");
  }
  let value = {};
  try {
    value = await response.json();
  } catch {
    value = {};
  }
  if (!response.ok) {
    if (response.status === 409) {
      throw new Error("文章已在其他页面修改，请刷新后重试。");
    }
    throw new Error(value.detail || value.error || `请求失败（${response.status}）`);
  }
  return value;
}

function notify(message, kind = "success") {
  notification.textContent = message;
  notification.className = `notification ${kind}`;
  notification.hidden = false;
  window.setTimeout(() => {
    notification.hidden = true;
  }, 2600);
}

function bodyFor(platform) {
  if (platform === "master") {
    return state.payload.master_markdown;
  }
  return state.payload.platform_markdown[platform];
}

function setBody(platform, value) {
  if (platform === "master") {
    state.payload.master_markdown = value;
  } else {
    state.payload.platform_markdown[platform] = value;
  }
}

function readEditorIntoPayload() {
  if (!state.payload) return;
  state.payload.master_title = titleInput.value;
  state.payload.column = columnInput.value;
  setBody(state.platform, markdownEditor.value);
}

function renderWarnings(items) {
  warnings.replaceChildren();
  if (!items || items.length === 0) {
    warnings.hidden = true;
    return;
  }
  const strong = document.createElement("strong");
  strong.textContent = "质量提醒：";
  const text = document.createTextNode(items.join("、"));
  warnings.append(strong, text);
  warnings.hidden = false;
}

function schedulePreview() {
  const requestId = ++state.previewRequest;
  const markdown = markdownEditor.value;
  window.setTimeout(async () => {
    if (requestId !== state.previewRequest) return;
    try {
      const value = await api("/api/preview", {
        method: "POST",
        body: JSON.stringify({markdown}),
      });
      if (requestId === state.previewRequest) {
        articlePreview.innerHTML = value.html;
      }
    } catch (error) {
      notify(error.message, "error");
    }
  }, 250);
}

function renderArticleList() {
  articleList.replaceChildren();
  if (state.articles.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted sidebar-empty";
    empty.textContent = "当前筛选条件下没有文章。";
    articleList.append(empty);
    return;
  }
  for (const article of state.articles) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "article-item";
    button.dataset.articleId = article.article_id;
    if (article.article_id === state.articleId) button.classList.add("selected");

    const title = document.createElement("strong");
    title.textContent = article.title;
    const meta = document.createElement("span");
    meta.textContent = `${article.column} · ${article.status}`;
    button.append(title, meta);
    button.addEventListener("click", () => openArticle(article.article_id));
    articleList.append(button);
  }
}

async function loadArticles(status = "") {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const value = await api(`/api/articles${query}`);
  state.articles = value.articles;
  renderArticleList();
  if (!state.articleId && state.articles.length > 0) {
    await openArticle(state.articles[0].article_id);
  }
}

async function openArticle(articleId) {
  if (
    state.dirty &&
    !window.confirm("当前修改尚未保存，确定切换文章吗？")
  ) {
    return;
  }
  try {
    const value = await api(`/api/articles/${encodeURIComponent(articleId)}`);
    state.articleId = articleId;
    state.payload = value.payload;
    state.version = value.version;
    state.platform = "wechat";
    state.dirty = false;
    titleInput.value = state.payload.master_title;
    columnInput.value = state.payload.column;
    emptyState.hidden = true;
    editorShell.hidden = false;
    renderWarnings(value.warnings);
    selectPlatform("wechat", false);
    renderArticleList();
    document.querySelector("#article-sidebar").classList.remove("open");
  } catch (error) {
    notify(error.message, "error");
  }
}

function selectPlatform(platform, preserveCurrent = true) {
  if (!state.payload) return;
  if (preserveCurrent) setBody(state.platform, markdownEditor.value);
  state.platform = platform;
  markdownEditor.value = bodyFor(platform);
  for (const button of document.querySelectorAll("[data-platform]")) {
    button.classList.toggle("selected", button.dataset.platform === platform);
  }
  schedulePreview();
}

async function saveArticle() {
  if (!state.payload) return;
  readEditorIntoPayload();
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}`,
      {
        method: "PUT",
        body: JSON.stringify({
          payload: state.payload,
          version: state.version,
        }),
      },
    );
    state.payload = value.payload;
    state.version = value.version;
    state.dirty = false;
    renderWarnings(value.warnings);
    notify("修改已保存，并创建了历史版本。");
    await loadArticles(statusFilter.value);
  } catch (error) {
    notify(error.message, "error");
  }
}

async function copyCurrentBody() {
  try {
    await navigator.clipboard.writeText(markdownEditor.value);
    notify("正文已复制。");
  } catch {
    notify("复制失败，请手动选择正文复制。", "error");
  }
}

async function setStatus(status) {
  if (!state.articleId) return;
  try {
    await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/status`,
      {
        method: "POST",
        body: JSON.stringify({status}),
      },
    );
    notify(status === "approved" ? "文章已标记为通过。" : "文章已标记为退回。");
    await loadArticles(statusFilter.value);
  } catch (error) {
    notify(error.message, "error");
  }
}

async function showHistory() {
  if (!state.articleId) return;
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/history`,
    );
    historyList.replaceChildren();
    if (value.history.length === 0) {
      const empty = document.createElement("p");
      empty.textContent = "还没有历史版本。";
      historyList.append(empty);
    }
    for (const item of value.history) {
      const row = document.createElement("div");
      row.className = "history-row";
      const text = document.createElement("span");
      text.textContent = `${new Date(item.saved_at).toLocaleString()} · ${item.operation}`;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "恢复";
      button.addEventListener("click", () => restoreHistory(item.history_id));
      row.append(text, button);
      historyList.append(row);
    }
    historyDialog.showModal();
  } catch (error) {
    notify(error.message, "error");
  }
}

async function restoreHistory(historyId) {
  if (!window.confirm("恢复后仍会保留当前版本，确定继续吗？")) return;
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/restore/${encodeURIComponent(historyId)}`,
      {
        method: "POST",
        body: JSON.stringify({version: state.version}),
      },
    );
    state.payload = value.payload;
    state.version = value.version;
    state.dirty = false;
    titleInput.value = state.payload.master_title;
    columnInput.value = state.payload.column;
    markdownEditor.value = bodyFor(state.platform);
    renderWarnings(value.warnings);
    schedulePreview();
    historyDialog.close();
    notify("历史版本已恢复。");
  } catch (error) {
    notify(error.message, "error");
  }
}

for (const button of document.querySelectorAll("[data-platform]")) {
  button.addEventListener("click", () => selectPlatform(button.dataset.platform));
}
for (const input of [titleInput, columnInput, markdownEditor]) {
  input.addEventListener("input", () => {
    readEditorIntoPayload();
    state.dirty = true;
    if (input === markdownEditor) schedulePreview();
  });
}

document.querySelector("#save-button").addEventListener("click", saveArticle);
document.querySelector("#copy-button").addEventListener("click", copyCurrentBody);
document.querySelector("#approve-button").addEventListener("click", () => setStatus("approved"));
document.querySelector("#reject-button").addEventListener("click", () => setStatus("revision_requested"));
document.querySelector("#history-button").addEventListener("click", showHistory);
document.querySelector("#history-close-button").addEventListener("click", () => historyDialog.close());
document.querySelector("#sidebar-button").addEventListener("click", () => {
  document.querySelector("#article-sidebar").classList.toggle("open");
});
document.querySelector("#show-editor-button").addEventListener("click", () => {
  contentPanes.className = "content-panes show-editor";
});
document.querySelector("#show-preview-button").addEventListener("click", () => {
  contentPanes.className = "content-panes show-preview";
});
statusFilter.addEventListener("change", () => loadArticles(statusFilter.value));
document.querySelector("#logout-button").addEventListener("click", async () => {
  await fetch("/logout", {
    method: "POST",
    headers: {"X-CSRF-Token": csrfToken},
  });
  window.location.assign("/login");
});
window.addEventListener("beforeunload", (event) => {
  if (!state.dirty) return;
  event.preventDefault();
  event.returnValue = "";
});

loadArticles().catch((error) => notify(error.message, "error"));
```

- [ ] **Step 5: Add responsive CSS**

```css
/* ai_content_loop/review/static/review.css */
:root {
  color-scheme: light;
  font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  color: #18212f;
  background: #f4f6f8;
  --accent: #176b5b;
  --accent-soft: #e4f2ee;
  --border: #dce2e8;
  --muted: #667384;
  --surface: #ffffff;
  --danger: #b23a48;
  --success: #176b5b;
}

* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
button, input, textarea, select { font: inherit; }
button, select { min-height: 44px; }
button { cursor: pointer; }
.muted { color: var(--muted); }
.mobile-only { display: none; }

.topbar {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.topbar strong { margin-right: 10px; }
.topbar-user { display: flex; align-items: center; gap: 12px; }

.review-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  height: calc(100vh - 64px);
}
.article-sidebar {
  overflow: auto;
  padding: 16px;
  border-right: 1px solid var(--border);
  background: #f9fafb;
}
.sidebar-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.sidebar-heading h1 { margin: 0; font-size: 20px; }
.article-list { display: grid; gap: 8px; margin-top: 14px; }
.article-item {
  display: grid;
  gap: 7px;
  width: 100%;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  text-align: left;
}
.article-item span { color: var(--muted); font-size: 12px; }
.article-item:hover, .article-item.selected {
  border-color: #b9d8d0;
  background: var(--accent-soft);
}
.sidebar-empty { padding: 10px; }

.workspace { min-width: 0; overflow: hidden; background: var(--surface); }
.empty-state { display: grid; place-content: center; height: 100%; text-align: center; }
.empty-state h2 { margin-bottom: 4px; }
.editor-shell { display: grid; grid-template-rows: auto auto auto 1fr auto; height: 100%; }
.article-fields {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(180px, 1fr);
  gap: 12px;
  padding: 14px 18px 10px;
}
label { display: grid; gap: 6px; color: var(--muted); font-size: 13px; }
input, textarea, select {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: inherit;
}
input { min-height: 42px; padding: 8px 10px; }
input:focus, textarea:focus, select:focus { outline: 2px solid #7fc5b6; outline-offset: 1px; }

.platform-tabs {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  padding: 0 18px;
  border-bottom: 1px solid var(--border);
}
.platform-tabs button {
  padding: 0 14px;
  border: 0;
  border-bottom: 3px solid transparent;
  background: transparent;
  color: var(--muted);
  white-space: nowrap;
}
.platform-tabs button.selected { border-bottom-color: var(--accent); color: var(--accent); font-weight: 700; }

.quality-warnings { padding: 9px 18px; background: #fff7dc; color: #765a09; font-size: 13px; }
.content-panes { display: grid; grid-template-columns: 1fr 1fr; min-height: 0; }
.editor-pane, .preview-pane { display: grid; grid-template-rows: 36px 1fr; min-width: 0; min-height: 0; }
.editor-pane { border-right: 1px solid var(--border); }
.pane-title { padding: 9px 14px; background: #f7f8fa; color: var(--muted); font-size: 12px; }
#markdown-editor {
  width: 100%;
  height: 100%;
  resize: none;
  padding: 18px;
  border: 0;
  border-radius: 0;
  line-height: 1.7;
  font-family: "Cascadia Code", "SFMono-Regular", monospace;
}
.article-preview { overflow: auto; padding: 30px max(24px, calc((100% - 760px) / 2)); line-height: 1.8; }
.article-preview h1, .article-preview h2, .article-preview h3 { line-height: 1.35; }
.article-preview img { max-width: 100%; }
.article-preview blockquote { margin-left: 0; padding-left: 14px; border-left: 3px solid #73b7a8; color: #526171; }
.article-preview a { color: var(--accent); overflow-wrap: anywhere; }

.actionbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}
.actionbar > div { display: flex; gap: 8px; }
button { padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
button.primary { border-color: var(--accent); background: var(--accent); color: white; }
button.success { border-color: #78b9aa; color: var(--success); }
button.danger { border-color: #e1aab0; color: var(--danger); }
button.quiet, .icon-button { background: transparent; }
.wide { width: 100%; }

.notification {
  position: fixed;
  right: 22px;
  bottom: 76px;
  z-index: 20;
  max-width: 360px;
  padding: 12px 16px;
  border-radius: 9px;
  background: #163c35;
  color: white;
  box-shadow: 0 12px 30px #20304033;
}
.notification.error, .notice.error { background: #fff0f1; color: #8d2633; }
dialog { width: min(560px, calc(100vw - 32px)); border: 0; border-radius: 14px; box-shadow: 0 18px 60px #1c283855; }
dialog::backdrop { background: #17202d77; }
dialog header, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.history-row { padding: 10px 0; border-top: 1px solid var(--border); }

.login-page { display: grid; place-items: center; min-height: 100%; padding: 20px; background: linear-gradient(145deg, #edf5f2, #f4f6f8 55%); }
.login-card { width: min(420px, 100%); padding: 34px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); box-shadow: 0 18px 48px #28443918; }
.login-card form { display: grid; gap: 16px; margin-top: 24px; }
.eyebrow { color: var(--accent); font-size: 12px; font-weight: 800; letter-spacing: .12em; }
.notice { padding: 10px 12px; border-radius: 8px; }

@media (max-width: 800px) {
  .mobile-only { display: inline-flex; }
  .topbar .muted { display: none; }
  .review-layout { display: block; }
  .article-sidebar {
    position: fixed;
    inset: 64px auto 0 0;
    z-index: 10;
    width: min(88vw, 320px);
    transform: translateX(-105%);
    transition: transform .18s ease;
    box-shadow: 12px 0 30px #24313f28;
  }
  .article-sidebar.open { transform: translateX(0); }
  .article-fields { grid-template-columns: 1fr; padding: 10px 12px; }
  .platform-tabs { padding: 0 8px; }
  .mobile-view-switch { display: flex; padding: 8px 12px 0; gap: 8px; }
  .content-panes { display: block; }
  .content-panes.show-editor .preview-pane,
  .content-panes.show-preview .editor-pane { display: none; }
  .editor-pane, .preview-pane { height: 100%; }
  .actionbar { padding: 9px; overflow-x: auto; }
  .actionbar > div { flex-shrink: 0; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
}
```

- [ ] **Step 6: Run automated tests**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_auth.py tests/ai_content_loop/test_review_api.py -q
D:\Users\36997\anaconda3\python.exe -m pytest tests -q
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```powershell
git add ai_content_loop/review/templates ai_content_loop/review/static ai_content_loop/review/app.py tests/ai_content_loop
git commit -m "feat: add the browser content review desk"
```

### Task 7: Add production entrypoint and service hardening

**Files:**

- Create: `ai_content_loop/review/wsgi.py`
- Create: `deploy/systemd/ai-content-review.service`
- Modify: `.gitignore`
- Modify: `tests/ai_content_loop/test_review_api.py`

- [ ] **Step 1: Write a failing production-config test**

```python
def test_create_app_loads_production_environment(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'database_path = "data/content.sqlite3"\noutput_dir = "out"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_CONTENT_CONFIG", str(config_path))
    monkeypatch.setenv("AI_CONTENT_REVIEW_USERNAME", "owner")
    monkeypatch.setenv(
        "AI_CONTENT_REVIEW_PASSWORD_HASH",
        generate_password_hash("secret"),
    )
    monkeypatch.setenv("AI_CONTENT_REVIEW_SECRET_KEY", "production-secret")

    app = create_app()

    assert app.config["DATABASE_PATH"] == tmp_path / "data" / "content.sqlite3"
    assert app.config["FINAL_DIR"] == tmp_path / "out" / "final"
    assert app.config["SESSION_COOKIE_SECURE"] is True
```

- [ ] **Step 2: Run the production-config test**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests/ai_content_loop/test_review_api.py::test_create_app_loads_production_environment -q
```

Expected: FAIL because `create_app()` does not yet derive paths from `AI_CONTENT_CONFIG`.

- [ ] **Step 3: Complete production configuration**

Add imports:

```python
from datetime import timedelta
import os

from ai_content_loop.config import load_config
```

Replace the configuration block at the beginning of `create_app` with:

```python
    app.config.from_mapping(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=1_500_000,
        LOGIN_ATTEMPTS=5,
        LOGIN_WINDOW_SECONDS=300,
    )
    if test_config is None:
        config_path = os.environ.get(
            "AI_CONTENT_CONFIG",
            "ai_content_loop/config.example.toml",
        )
        content_config = load_config(config_path)
        app.config.update(
            SECRET_KEY=os.environ.get("AI_CONTENT_REVIEW_SECRET_KEY"),
            REVIEW_USERNAME=os.environ.get("AI_CONTENT_REVIEW_USERNAME"),
            REVIEW_PASSWORD_HASH=os.environ.get(
                "AI_CONTENT_REVIEW_PASSWORD_HASH"
            ),
            DATABASE_PATH=content_config.database_path,
            FINAL_DIR=content_config.output_dir / "final",
            HISTORY_DIR=content_config.output_dir / "history",
        )
    else:
        app.config.update(test_config)
        app.config["SESSION_COOKIE_SECURE"] = False
```

Keep the existing required-value check so missing secrets raise:

```python
RuntimeError("review service configuration is incomplete")
```

Add the response headers before `return app`:

```python
    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response
```

`wsgi.py` contains:

```python
from ai_content_loop.review.app import create_app

app = create_app()
```

- [ ] **Step 4: Add the systemd unit**

```ini
# deploy/systemd/ai-content-review.service
[Unit]
Description=AI content browser review desk
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=agentuser
Group=agentuser
WorkingDirectory=/opt/ai-content-loop/repo
EnvironmentFile=/opt/ai-content-loop/review.env
Environment=PYTHONUNBUFFERED=1
UMask=0077
ExecStart=/opt/ai-content-loop/venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8765 --access-logfile - --error-logfile - ai_content_loop.review.wsgi:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/ai-content-loop/out /opt/ai-content-loop/data

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Ignore secret and generated history paths**

Append only missing patterns:

```gitignore
review.env
ai_content_loop/out/history/
```

- [ ] **Step 6: Run tests and validate the unit**

Run locally:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests -q
git diff --check
```

Run on Ubuntu after upload:

```bash
systemd-analyze verify /etc/systemd/system/ai-content-review.service
```

Expected: tests PASS, no diff errors, and systemd verification exits 0.

- [ ] **Step 7: Start the local review service**

Set test credentials without committing them:

```powershell
$env:AI_CONTENT_CONFIG = 'ai_content_loop/config.example.toml'
$env:AI_CONTENT_REVIEW_USERNAME = 'owner'
$env:AI_CONTENT_REVIEW_PASSWORD_HASH = & D:\Users\36997\anaconda3\python.exe -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('local-review-only'))"
$env:AI_CONTENT_REVIEW_SECRET_KEY = & D:\Users\36997\anaconda3\python.exe -c "import secrets; print(secrets.token_hex(32))"
D:\Users\36997\anaconda3\python.exe -m flask --app ai_content_loop.review.wsgi run --host 127.0.0.1 --port 8765
```

Expected: Flask listens only on `http://127.0.0.1:8765`.

- [ ] **Step 8: Verify the full browser story**

Use the browser verification tool against `http://127.0.0.1:8765`:

1. Login failure stays on login page.
2. Correct login opens the article list.
3. Existing Claude Code and Langflow articles render.
4. All five content tabs switch.
5. Edit preview updates.
6. Copy button reports success.
7. Save changes the version.
8. History shows the old version.
9. Restore returns the old content.
10. Narrow viewport remains usable.
11. Browser console has no errors.

- [ ] **Step 9: Commit**

```powershell
git add ai_content_loop/review/wsgi.py deploy/systemd/ai-content-review.service .gitignore tests/ai_content_loop/test_review_api.py
git commit -m "chore: add the production review service"
```

### Task 8: Document and perform Lighthouse deployment

**Files:**

- Create: `deploy/content-review/README.md`

- [ ] **Step 1: Write the deployment runbook**

The runbook must contain the exact server procedure:

```bash
cd /opt/ai-content-loop/repo
python3 -m venv /opt/ai-content-loop/venv
/opt/ai-content-loop/venv/bin/pip install --upgrade pip
/opt/ai-content-loop/venv/bin/pip install -r requirements-review.txt

python3 -c 'import secrets; print(secrets.token_hex(32))'
/opt/ai-content-loop/venv/bin/python -c \
  'from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass()))'
```

Create `/opt/ai-content-loop/review.env` as root with mode `0600`:

```text
AI_CONTENT_CONFIG=/opt/ai-content-loop/config.toml
AI_CONTENT_REVIEW_USERNAME=owner
AI_CONTENT_REVIEW_PASSWORD_HASH=PASTE_THE_GENERATED_HASH_HERE
AI_CONTENT_REVIEW_SECRET_KEY=PASTE_THE_GENERATED_RANDOM_KEY_HERE
```

Install the unit:

```bash
sudo cp deploy/systemd/ai-content-review.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-content-review.service
sudo systemctl status ai-content-review.service --no-pager
curl -I http://127.0.0.1:8765/login
ss -lntp | grep 8765
```

The runbook must state that `ss` should show only `127.0.0.1:8765`, never `0.0.0.0:8765`.

Install and authenticate Tailscale using its current official Ubuntu instructions, then:

```bash
sudo tailscale funnel --bg 8765
tailscale funnel status
TAILSCALE_HOST="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo "https://$TAILSCALE_HOST"
```

Record the generated HTTPS URL. Do not open TCP 8765 in the Tencent Cloud firewall.

Include rollback:

```bash
sudo tailscale funnel reset
sudo systemctl disable --now ai-content-review.service
```

- [ ] **Step 2: Commit the runbook**

```powershell
git add deploy/content-review/README.md
git commit -m "docs: add content review deployment runbook"
```

- [ ] **Step 3: Run final local verification**

Run:

```powershell
D:\Users\36997\anaconda3\python.exe -m pytest tests -q
git diff --check
git status --short
```

Expected:

- All tests PASS.
- No whitespace errors.
- Only known unrelated user changes remain.

- [ ] **Step 4: Upload the committed revision**

From the local machine, transfer only tracked project files or pull the committed revision on the server. Do not upload local secrets, `.superpowers`, pytest scratch data, or unrelated workspace files.

Verify:

```bash
cd /opt/ai-content-loop/repo
git rev-parse --short HEAD
```

Expected: server revision matches the local feature revision.

- [ ] **Step 5: Deploy the service and pause only for Tailscale authorization**

Execute the runbook. If `tailscale up` returns an authorization URL, present that URL to the user and wait for authorization. Continue immediately after the server becomes connected.

- [ ] **Step 6: Verify the public HTTPS story**

Check:

```bash
TAILSCALE_HOST="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
REVIEW_URL="https://$TAILSCALE_HOST"
curl -I "$REVIEW_URL/login"
sudo systemctl is-active ai-content-review.service
sudo systemctl is-enabled ai-content-review.service
tailscale funnel status
```

Then verify in a browser:

1. HTTPS certificate is valid.
2. Login is required before any article content is returned.
3. Existing articles load.
4. Editing and saving creates a server-side history snapshot.
5. Restore works.
6. Approval status persists after refresh.
7. The daily generation timer remains active.

- [ ] **Step 7: Record the handoff**

Return:

- Final HTTPS review URL.
- Username, but never echo the password.
- Current Git revision.
- Service and timer status.
- Exact commands for logs:

```bash
journalctl -u ai-content-review.service -n 100 --no-pager
journalctl -u ai-content-loop.service -n 100 --no-pager
```

## Plan self-review

- Spec coverage: UI, online editing, manual save, version history, restore, status, safe Markdown, authentication, CSRF, throttling, HTTPS, loopback binding, systemd, Funnel fallback boundary, tests, and deployment are each assigned to a task.
- Scope: automatic platform publishing, multi-user roles, rich text, analytics, and pixel-perfect platform simulation remain excluded.
- Type consistency: routes use opaque `article_id`; saves and restores use the same 64-character `version`; review states are identical in repository, database, API, and UI.
- Placeholder scan: deployment secret markers are explicit copy destinations for values generated by the immediately preceding commands; no implementation body is deferred.
