from pathlib import Path
import threading

import pytest

from ai_content_loop.article_lock import ArticleLockError, article_lock


def test_article_lock_times_out_with_stable_error_and_persists_lock_file(
    tmp_path: Path,
):
    article_id = "a" * 24
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock():
        with article_lock(output_dir=tmp_path, article_id=article_id):
            acquired.set()
            assert release.wait(timeout=10)

    worker = threading.Thread(target=hold_lock)
    worker.start()
    assert acquired.wait(timeout=10)

    with pytest.raises(ArticleLockError) as caught:
        with article_lock(
            output_dir=tmp_path,
            article_id=article_id,
            timeout_seconds=0.05,
        ):
            pytest.fail("contended lock must not be acquired")

    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert caught.value.code == "article_lock_timeout"
    assert str(caught.value) == "article_lock_timeout"
    assert (tmp_path / ".locks" / f"{article_id}.lock").is_file()
