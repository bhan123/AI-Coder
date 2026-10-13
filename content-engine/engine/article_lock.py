from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import time
from typing import BinaryIO, Iterator


_ARTICLE_ID_PATTERN = re.compile(r"[0-9a-f]{24}\Z")
DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
LOCK_POLL_SECONDS = 0.05


class ArticleLockError(RuntimeError):
    """A stable lock failure that never includes local paths or content."""

    def __init__(self, code: str = "article_lock_timeout") -> None:
        self.code = code
        super().__init__(code)


def _trusted_article_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or _ARTICLE_ID_PATTERN.fullmatch(value) is None
    ):
        raise ArticleLockError("invalid_article_lock")
    return value


def _is_link_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction is not None and is_junction())
    except OSError:
        raise ArticleLockError("invalid_article_lock") from None


def _acquire(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def article_lock(
    *,
    output_dir: str | Path,
    article_id: str,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire the persistent cross-process lock for one opaque article."""

    trusted_id = _trusted_article_id(article_id)
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 0
    ):
        raise ArticleLockError("invalid_article_lock")
    root = Path(output_dir)
    lock_dir = root / ".locks"
    if _is_link_or_junction(root) or _is_link_or_junction(lock_dir):
        raise ArticleLockError("invalid_article_lock")
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        if _is_link_or_junction(lock_dir) or not lock_dir.is_dir():
            raise ArticleLockError("invalid_article_lock")
        handle = (lock_dir / f"{trusted_id}.lock").open("a+b")
    except OSError:
        raise ArticleLockError("article_lock_unavailable") from None

    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + float(timeout_seconds)
        while True:
            try:
                _acquire(handle)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ArticleLockError("article_lock_timeout") from None
                time.sleep(LOCK_POLL_SECONDS)
        yield
    finally:
        if acquired:
            try:
                _release(handle)
            except OSError:
                pass
        handle.close()
