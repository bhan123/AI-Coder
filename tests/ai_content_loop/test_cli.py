import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.error import URLError

import pytest
from PIL import Image

from ai_content_loop import cli, generation
from ai_content_loop.config import load_config
from ai_content_loop.db import ContentStore
from ai_content_loop.editorial.schema import article_id_for, empty_article_layout
from ai_content_loop.generation import GenerationOutcome
from ai_content_loop.models import CandidateScore, SourceItem
from ai_content_loop.visuals.renderer import BODY_SIZE, COVER_SIZE


def write_config(tmp_path: Path, *, publish_limit: int = 2) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
database_path = "content.sqlite3"
output_dir = "out"
publish_limit = {publish_limit}
hermes_command = "custom-hermes"
generation_timeout_seconds = 321
generation_retries = 2
""",
        encoding="utf-8",
    )
    return config_path


def write_visual_config(tmp_path: Path) -> tuple[Path, Path]:
    font_path = tmp_path / "fonts" / "local-font.ttc"
    font_path.parent.mkdir()
    font_path.write_bytes(b"configured-local-font")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
database_path = "content.sqlite3"
output_dir = "out"
visual_font_path = "fonts/local-font.ttc"
visual_render_concurrency = 1
""",
        encoding="utf-8",
    )
    return config_path, font_path


def visual_payload(dedupe_key: str = "github:owner/repo") -> dict:
    panels = [
        {"label": "AI writes code", "reaction": "confident"},
        {"label": "Tests run", "reaction": "quiet"},
    ]
    return {
        "dedupe_key": dedupe_key,
        "column": "AI discoveries",
        "master_title": "Useful article",
        "master_markdown": "Useful article body",
        "platform_markdown": {
            "wechat": (
                "Useful WeChat body\n\n"
                "{{asset:body-01}}\n"
                "来源：https://example.test"
            ),
            "xiaohongshu": "Useful Xiaohongshu body",
            "toutiao": "Useful Toutiao body",
            "zhihu": "Useful Zhihu body",
        },
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
            "cover_line": "AI writes, tests answer",
            "cover_subline": "Fast meets honest",
            "body_panels": panels,
            "alternatives": [
                {
                    "cover_line": "Code done, tests start",
                    "cover_subline": "Tests stay honest",
                    "body_panels": panels,
                },
                {
                    "cover_line": "Fast code meets tests",
                    "cover_subline": "Evidence wins",
                    "body_panels": panels,
                },
            ],
        },
        "visual_assets": {"cover": None, "body": []},
        "article_layout": empty_article_layout(),
    }


def write_test_visuals(**kwargs) -> None:
    Image.new("RGB", COVER_SIZE, "white").save(
        kwargs["cover_path"],
        format="JPEG",
    )
    Image.new("RGB", BODY_SIZE, "white").save(
        kwargs["body_path"],
        format="PNG",
    )


def rendered_visual_payload(
    dedupe_key: str = "github:owner/repo",
) -> dict:
    payload = visual_payload(dedupe_key)
    article_id = article_id_for(dedupe_key)
    revision = "a" * 64
    common = {
        "revision": revision,
        "template": "ai_done_vs_tests",
        "copy_index": 0,
        "ai_generated": False,
    }
    payload["visual_assets"] = {
        "cover": {
            "asset_id": "cover",
            "path": f"assets/{article_id}/{revision}/cover.jpg",
            **common,
        },
        "body": [
            {
                "asset_id": "body-01",
                "path": f"assets/{article_id}/{revision}/body.png",
                **common,
            }
        ],
    }
    return payload


def make_item(
    *,
    external_id: str = "owner/repo",
    title: str = "Useful AI Repo",
) -> SourceItem:
    return SourceItem(
        source="github",
        external_id=external_id,
        title=title,
        url=f"https://github.com/{external_id}",
        summary="A useful AI automation repo",
        published_at="2026-06-30T00:00:00Z",
        fetched_at="2026-06-30T08:00:00Z",
        raw={"stars": 10},
    )


def make_score(item: SourceItem, *, total: float = 78.0) -> CandidateScore:
    return CandidateScore(
        dedupe_key=item.dedupe_key,
        novelty=8,
        clarity=9,
        fun=7,
        usefulness=9,
        demo=6,
        heat=5,
        credibility=8,
        total=total,
        reason="Clear, useful, and credible.",
    )


def seed_candidates(store: ContentStore, *scored_items: tuple[SourceItem, float]) -> None:
    items = [item for item, _ in scored_items]
    store.upsert_source_items(items)
    store.upsert_scores(
        [make_score(item, total=total) for item, total in scored_items]
    )


def seed_queue_row(
    store: ContentStore,
    *,
    dedupe_key: str = "github:owner/repo",
    status: str = "needs_generation",
    bundle_path: str = "out/drafts/github-owner-repo.json",
) -> None:
    store.upsert_publish_queue(
        dedupe_key=dedupe_key,
        title="Useful AI Repo",
        column_name="AI discoveries",
        status=status,
        bundle_path=bundle_path,
    )


def run_generate_drafts(config_path: Path) -> None:
    cli.cmd_generate_drafts(argparse.Namespace(config=str(config_path)))


def test_safe_name_is_distinct_ascii_deterministic_and_bounded():
    dedupe_keys = [
        "a:b/c",
        "a-b-c",
        "rss:https://example.com/feed?topic=ai&lang=zh#latest",
        "github:缁勭粐/椤圭洰",
        "x" * 500,
    ]

    names = [cli._safe_name(key) for key in dedupe_keys]

    assert len(names) == len(set(names))
    assert names == [cli._safe_name(key) for key in dedupe_keys]
    for name in names:
        prefix, digest = name.rsplit("-", maxsplit=1)
        assert re.fullmatch(r"[A-Za-z0-9._-]+", name)
        assert len(prefix) <= 48
        assert re.fullmatch(r"[0-9a-f]{12,}", digest)
        assert len(f"{name}.json") <= 80


def test_ingest_continues_when_one_source_fails(tmp_path: Path, monkeypatch, capsys):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
database_path = "content.sqlite3"
output_dir = "out"

[source_limits]
github = 1
hackernews = 1
arxiv = 1
modelscope = 1
producthunt = 1
""",
        encoding="utf-8",
    )
    good_item = SourceItem(
        source="github",
        external_id="owner/repo",
        title="Useful AI Repo",
        url="https://github.com/owner/repo",
        summary="A useful AI repo",
        published_at="2026-06-30T00:00:00Z",
        fetched_at="2026-06-30T08:00:00Z",
        raw={"stars": 10},
    )

    monkeypatch.setattr(cli, "fetch_github_repositories", lambda limit, fetched_at: [good_item])
    monkeypatch.setattr(cli, "fetch_hackernews_show", lambda limit, fetched_at: [])
    monkeypatch.setattr(cli, "fetch_arxiv_ai", lambda limit, fetched_at: (_ for _ in ()).throw(URLError("cert fail")))
    monkeypatch.setattr(cli, "fetch_modelscope_models", lambda limit, fetched_at: [])
    monkeypatch.setattr(cli, "fetch_producthunt_posts", lambda limit, fetched_at, token: [])

    cli.main(["--config", str(config_path), "ingest"])

    rows = ContentStore(tmp_path / "content.sqlite3").list_source_items(limit=10)
    output = capsys.readouterr().out
    assert len(rows) == 1
    assert rows[0].dedupe_key == "github:owner/repo"
    assert "source arxiv failed" in output
    assert "ingested 1 source items" in output


def test_build_queue_marks_new_rows_as_needs_generation(
    tmp_path: Path, monkeypatch
):
    config_path = write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    item = make_item()
    seed_candidates(store, (item, 78.0))

    cli.main(["--config", config_path.name, "build-queue"])

    rows = store.list_publish_queue()
    assert len(rows) == 1
    assert rows[0]["status"] == "needs_generation"
    bundle_path = Path(rows[0]["bundle_path"])
    assert bundle_path.is_absolute()
    assert bundle_path == (
        tmp_path / "out" / "drafts" / f"{cli._safe_name(item.dedupe_key)}.json"
    ).resolve()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["facts"] == [
        "一手来源：https://github.com/owner/repo",
        "来源平台：github",
        "标题：Useful AI Repo",
        "摘要/描述：A useful AI automation repo",
        "GitHub Stars：10",
    ]
    assert "一手来源：https://github.com/owner/repo" in bundle["facts"]
    assert isinstance(bundle["risks"], list)
    assert isinstance(bundle["writing_angles"], list)


def test_build_queue_excludes_queued_item_without_rewriting_status(tmp_path: Path):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    queued_item = make_item()
    unqueued_item = make_item(
        external_id="owner/alternative",
        title="Alternative AI Repo",
    )
    seed_candidates(store, (queued_item, 90.0), (unqueued_item, 70.0))
    store.upsert_publish_queue(
        dedupe_key=queued_item.dedupe_key,
        title=queued_item.title,
        column_name="AI discoveries",
        status="generation_failed",
        bundle_path="existing/bundle.json",
    )

    cli.main(["--config", str(config_path), "build-queue"])

    rows = {
        row["dedupe_key"]: row
        for row in store.list_publish_queue()
    }
    assert rows[queued_item.dedupe_key]["status"] == "generation_failed"
    assert rows[queued_item.dedupe_key]["bundle_path"] == "existing/bundle.json"
    assert rows[unqueued_item.dedupe_key]["status"] == "needs_generation"


def test_generate_drafts_marks_generated_as_needs_human_review(
    tmp_path: Path, monkeypatch, capsys
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(store)
    monkeypatch.setattr(
        cli,
        "generate_draft",
        lambda **kwargs: GenerationOutcome(
            dedupe_key="github:owner/repo",
            status="generated",
            attempts=1,
            output_path=tmp_path / "out/final/github-owner-repo.json",
        ),
    )

    run_generate_drafts(config_path)

    assert store.list_publish_queue()[0]["status"] == "needs_human_review"
    assert capsys.readouterr().out == "generated 1, skipped 0, failed 0\n"


def test_generate_drafts_marks_skipped_existing_as_needs_human_review(
    tmp_path: Path, monkeypatch, capsys
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(store)
    monkeypatch.setattr(
        cli,
        "generate_draft",
        lambda **kwargs: GenerationOutcome(
            dedupe_key="github:owner/repo",
            status="skipped_existing",
            attempts=0,
            output_path=tmp_path / "out/final/github-owner-repo.json",
        ),
    )

    run_generate_drafts(config_path)

    assert store.list_publish_queue()[0]["status"] == "needs_human_review"
    assert capsys.readouterr().out == "generated 0, skipped 1, failed 0\n"


def test_generate_drafts_marks_failed_as_generation_failed(
    tmp_path: Path, monkeypatch, capsys
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(store)
    monkeypatch.setattr(
        cli,
        "generate_draft",
        lambda **kwargs: GenerationOutcome(
            dedupe_key="github:owner/repo",
            status="failed",
            attempts=3,
            output_path=tmp_path / "out/failures/github-owner-repo.json",
        ),
    )

    run_generate_drafts(config_path)

    assert store.list_publish_queue()[0]["status"] == "generation_failed"
    assert capsys.readouterr().out == "generated 0, skipped 0, failed 1\n"


def test_generate_drafts_processes_only_needs_generation_rows(
    tmp_path: Path, monkeypatch
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(
        store,
        dedupe_key="github:owner/pending",
        bundle_path="pending.json",
    )
    seed_queue_row(
        store,
        dedupe_key="github:owner/review",
        status="needs_human_review",
        bundle_path="review.json",
    )
    received_bundle_paths = []

    def fake_generate_draft(**kwargs):
        received_bundle_paths.append(kwargs["bundle_path"])
        return GenerationOutcome(
            dedupe_key="github:owner/pending",
            status="generated",
            attempts=1,
            output_path=tmp_path / "out/final/pending.json",
        )

    monkeypatch.setattr(cli, "generate_draft", fake_generate_draft)

    run_generate_drafts(config_path)

    assert received_bundle_paths == [Path("pending.json")]
    rows = {
        row["dedupe_key"]: row["status"]
        for row in store.list_publish_queue()
    }
    assert rows["github:owner/review"] == "needs_human_review"


def test_generate_drafts_passes_paths_and_config_values(
    tmp_path: Path, monkeypatch
):
    config_path = write_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    bundle_path = str(cfg.output_dir / "drafts" / "github-owner-repo.json")
    seed_queue_row(store, bundle_path=bundle_path)
    calls = []

    def fake_generate_draft(**kwargs):
        calls.append(kwargs)
        return GenerationOutcome(
            dedupe_key="github:owner/repo",
            status="generated",
            attempts=1,
            output_path=cfg.output_dir / "final" / "github-owner-repo.json",
        )

    monkeypatch.setattr(cli, "generate_draft", fake_generate_draft)

    run_generate_drafts(config_path)

    assert calls == [
        {
            "bundle_path": Path(bundle_path),
            "factual_prompt_path": (
                Path(cli.__file__).parent / "prompts" / "factual_draft.md"
            ),
            "editorial_prompt_path": (
                Path(cli.__file__).parent / "prompts" / "editorial_voice.md"
            ),
            "final_dir": cfg.output_dir / "final",
            "failure_dir": cfg.output_dir / "failures",
            "hermes_command": "custom-hermes",
            "timeout_seconds": 321,
            "retries": 2,
        }
    ]


def test_generate_drafts_passes_both_prompt_paths(
    tmp_path: Path, monkeypatch
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(store)
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
    run_generate_drafts(config_path)

    assert captured["factual_prompt_path"].name == "factual_draft.md"
    assert captured["editorial_prompt_path"].name == "editorial_voice.md"


@pytest.mark.parametrize(
    "expected_error",
    [
        OSError("secret filesystem detail"),
        ValueError("secret malformed bundle detail"),
        KeyError("secret missing field detail"),
    ],
)
def test_generate_drafts_isolates_expected_row_error_and_continues(
    tmp_path: Path, monkeypatch, capsys, expected_error
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(
        store,
        dedupe_key="github:owner/bad",
        bundle_path="bad.json",
    )
    seed_queue_row(
        store,
        dedupe_key="github:owner/good",
        bundle_path="good.json",
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-02T00:00:00Z", "github:owner/bad"),
        )
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-01T00:00:00Z", "github:owner/good"),
        )
    calls = []

    def fake_generate_draft(**kwargs):
        calls.append(kwargs["bundle_path"])
        if kwargs["bundle_path"] == Path("bad.json"):
            raise expected_error
        return GenerationOutcome(
            dedupe_key="github:owner/good",
            status="generated",
            attempts=1,
            output_path=tmp_path / "out/final/good.json",
        )

    monkeypatch.setattr(cli, "generate_draft", fake_generate_draft)

    run_generate_drafts(config_path)

    rows = {
        row["dedupe_key"]: row["status"]
        for row in store.list_publish_queue()
    }
    assert calls == [Path("bad.json"), Path("good.json")]
    assert rows == {
        "github:owner/bad": "generation_failed",
        "github:owner/good": "needs_human_review",
    }
    assert capsys.readouterr().out == "generated 1, skipped 0, failed 1\n"
    failure_paths = list((tmp_path / "out" / "failures").glob("*.json"))
    assert len(failure_paths) == 1
    failure_text = failure_paths[0].read_text(encoding="utf-8")
    assert "secret" not in failure_text
    assert json.loads(failure_text) == {
        "dedupe_key": "github:owner/bad",
        "bundle_path": "bad.json",
        "attempts": 0,
        "attempt_failures": [
            [f"generation_error:{type(expected_error).__name__}"]
        ],
    }


@pytest.mark.parametrize(
    "invalid_bundle",
    [
        [],
        {
            "dedupe_key": {"model-controlled-source-secret": True},
            "source_url": "https://github.com/owner/bad",
        },
        {
            "dedupe_key": "github:owner/bad",
            "source_url": ["model-controlled-source-secret"],
        },
    ],
)
def test_generate_drafts_isolates_invalid_bundle_and_continues(
    tmp_path: Path, monkeypatch, capsys, invalid_bundle
):
    config_path = write_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    bad_path = cfg.output_dir / "drafts" / "bad.json"
    good_path = cfg.output_dir / "drafts" / "good.json"
    bad_path.parent.mkdir(parents=True)
    bad_path.write_text(json.dumps(invalid_bundle), encoding="utf-8")
    good_url = "https://github.com/owner/good"
    good_title = "A sufficiently descriptive title"
    good_summary = "A sufficiently detailed grounded draft body with facts."
    good_path.write_text(
        json.dumps(
            {
                "dedupe_key": "github:owner/good",
                "source_url": good_url,
                "source_title": "Good source",
                "title": good_title,
                "facts": [good_summary],
            }
        ),
        encoding="utf-8",
    )
    seed_queue_row(
        store,
        dedupe_key="github:owner/bad",
        bundle_path=str(bad_path),
    )
    seed_queue_row(
        store,
        dedupe_key="github:owner/good",
        bundle_path=str(good_path),
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-02T00:00:00Z", "github:owner/bad"),
        )
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-01T00:00:00Z", "github:owner/good"),
        )
    real_generate_draft = generation.generate_draft
    good_payload = {
        "dedupe_key": "github:owner/good",
        "column": "AI discoveries",
        "master_title": good_title,
        "master_markdown": f"{good_summary} Source: {good_url}",
        "platform_markdown": {
            platform: (
                f"{good_summary} Source: {good_url}"
            )
            for platform in generation.PLATFORMS
        },
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
            "cover_line": "AI writes, tests answer",
            "cover_subline": "Fast meets honest",
            "body_panels": [
                {"label": "AI writes code", "reaction": "confident"},
                {"label": "Tests run", "reaction": "quiet"},
            ],
            "alternatives": [
                {
                    "cover_line": "Code done, tests start",
                    "cover_subline": "Tests stay honest",
                    "body_panels": [
                        {
                            "label": "AI writes code",
                            "reaction": "confident",
                        },
                        {"label": "Tests run", "reaction": "quiet"},
                    ],
                },
                {
                    "cover_line": "Fast code meets tests",
                    "cover_subline": "Evidence wins",
                    "body_panels": [
                        {
                            "label": "AI writes code",
                            "reaction": "confident",
                        },
                        {"label": "Tests run", "reaction": "quiet"},
                    ],
                },
            ],
        },
        "visual_assets": {"cover": None, "body": []},
        "article_layout": {
            "theme": "press",
            "structure": "briefing",
            "blocks": [
                {
                    "type": "hero",
                    "title": good_title,
                    "deck": good_summary,
                },
                {"type": "lead", "text": good_summary},
                {"type": "key_judgment", "text": good_summary},
                {
                    "type": "section",
                    "heading": good_title,
                    "paragraphs": [good_summary],
                },
                {"type": "callout", "text": good_summary},
                {
                    "type": "source_note",
                    "url": good_url,
                    "attribution": good_title,
                },
            ],
        },
    }
    good_factual_payload = {
        key: good_payload[key]
        for key in (
            "dedupe_key",
            "column",
            "master_title",
            "master_markdown",
            "platform_markdown",
        )
    }
    model_prompts: list[str] = []

    def staged_runner(argv, **_runner_kwargs):
        prompt = argv[-1]
        model_prompts.append(prompt)

        if "Prompt version: factual-v8" in prompt:
            if len(model_prompts) != 1:
                raise AssertionError(
                    "unexpected factual prompt call "
                    f"{len(model_prompts)}: {prompt[:300]!r}"
                )
            payload = good_factual_payload
        elif "Prompt version: editorial-v16" in prompt:
            if len(model_prompts) != 2:
                raise AssertionError(
                    "unexpected editorial prompt call "
                    f"{len(model_prompts)}: {prompt[:300]!r}"
                )
            assert '"source_title": "Good source"' in prompt
            assert '"facts": [' in prompt
            assert good_summary in prompt
            payload = good_payload
        else:
            raise AssertionError(
                "unexpected generation prompt stage/call "
                f"{len(model_prompts)}: {prompt[:300]!r}"
            )

        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    def run_real_generation(**kwargs):
        return real_generate_draft(
            **kwargs,
            runner=staged_runner,
        )

    monkeypatch.setattr(cli, "generate_draft", run_real_generation)
    monkeypatch.setattr(
        generation,
        "choose_article_layout",
        lambda: {"theme": "press", "structure": "briefing"},
    )

    run_generate_drafts(config_path)

    assert len(model_prompts) == 2
    assert "Prompt version: factual-v8" in model_prompts[0]
    assert "Prompt version: editorial-v16" in model_prompts[1]

    rows = {
        row["dedupe_key"]: row["status"]
        for row in store.list_publish_queue()
    }
    assert rows == {
        "github:owner/bad": "generation_failed",
        "github:owner/good": "needs_human_review",
    }
    assert capsys.readouterr().out == "generated 1, skipped 0, failed 1\n"
    failure_paths = list((cfg.output_dir / "failures").glob("*.json"))
    assert len(failure_paths) == 1
    failure_text = failure_paths[0].read_text(encoding="utf-8")
    assert "model-controlled-source-secret" not in failure_text
    assert json.loads(failure_text)["attempt_failures"] == [
        ["generation_error:ValueError"]
    ]


def test_generate_drafts_requeues_unexpected_error_and_next_run_processes_it(
    tmp_path: Path, monkeypatch
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(store, bundle_path="pending.json")
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("programming bug")
        return GenerationOutcome(
            dedupe_key="github:owner/repo",
            status="generated",
            attempts=1,
            output_path=tmp_path / "out/final/pending.json",
        )

    monkeypatch.setattr(cli, "generate_draft", fail_once)

    with pytest.raises(RuntimeError, match="programming bug"):
        run_generate_drafts(config_path)

    row = store.list_publish_queue()[0]
    assert row["status"] == "needs_generation"
    assert row["claimed_at"] is None

    run_generate_drafts(config_path)

    assert calls == 2
    row = store.list_publish_queue()[0]
    assert row["status"] == "needs_human_review"
    assert row["claimed_at"] is None


def test_generate_drafts_reclaims_stale_row_before_listing(
    tmp_path: Path, monkeypatch
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(
        store,
        dedupe_key="github:owner/stale",
        bundle_path="stale.json",
    )
    assert store.claim_publish_queue_item(
        "github:owner/stale", "stale-worker"
    ) is True
    with store.connect() as conn:
        conn.execute(
            """
            UPDATE publish_queue
            SET claimed_at = '2000-01-01 00:00:00'
            WHERE dedupe_key = 'github:owner/stale'
            """
        )
    calls = []

    def fake_generate_draft(**kwargs):
        calls.append(kwargs["bundle_path"])
        return GenerationOutcome(
            dedupe_key="github:owner/stale",
            status="generated",
            attempts=1,
            output_path=tmp_path / "out/final/stale.json",
        )

    monkeypatch.setattr(cli, "generate_draft", fake_generate_draft)

    run_generate_drafts(config_path)

    assert calls == [Path("stale.json")]
    row = store.list_publish_queue()[0]
    assert row["status"] == "needs_human_review"
    assert row["claimed_at"] is None
    assert row["claim_token"] is None


def test_generate_drafts_rejects_mismatched_outcome_identity_and_continues(
    tmp_path: Path, monkeypatch, capsys
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(
        store,
        dedupe_key="github:owner/mismatch",
        bundle_path="mismatch.json",
    )
    seed_queue_row(
        store,
        dedupe_key="github:owner/good",
        bundle_path="good.json",
    )
    with store.connect() as conn:
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-02T00:00:00Z", "github:owner/mismatch"),
        )
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-01T00:00:00Z", "github:owner/good"),
        )

    def fake_generate_draft(**kwargs):
        if kwargs["bundle_path"] == Path("mismatch.json"):
            return GenerationOutcome(
                dedupe_key="model-controlled-secret",
                status="generated",
                attempts=1,
                output_path=tmp_path / "out/final/mismatch.json",
            )
        return GenerationOutcome(
            dedupe_key="github:owner/good",
            status="generated",
            attempts=1,
            output_path=tmp_path / "out/final/good.json",
        )

    monkeypatch.setattr(cli, "generate_draft", fake_generate_draft)

    run_generate_drafts(config_path)

    rows = {
        row["dedupe_key"]: row["status"]
        for row in store.list_publish_queue()
    }
    assert rows == {
        "github:owner/mismatch": "generation_failed",
        "github:owner/good": "needs_human_review",
    }
    output = capsys.readouterr().out
    assert output == "generated 1, skipped 0, failed 1\n"
    assert "model-controlled-secret" not in output
    failure_paths = list((tmp_path / "out" / "failures").glob("*.json"))
    assert len(failure_paths) == 1
    failure_text = failure_paths[0].read_text(encoding="utf-8")
    assert "model-controlled-secret" not in failure_text
    assert json.loads(failure_text)["attempt_failures"] == [["identity_mismatch"]]


def test_generate_drafts_does_not_call_model_when_claim_fails(
    tmp_path: Path, monkeypatch, capsys
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(store, bundle_path="pending.json")
    monkeypatch.setattr(
        ContentStore,
        "claim_publish_queue_item",
        lambda self, dedupe_key, claim_token: False,
    )

    def model_must_not_run(**kwargs):
        raise AssertionError("generate_draft must not be called")

    monkeypatch.setattr(cli, "generate_draft", model_must_not_run)

    run_generate_drafts(config_path)

    assert store.list_publish_queue()[0]["status"] == "needs_generation"
    assert capsys.readouterr().out == "generated 0, skipped 0, failed 0\n"


def test_generate_drafts_stale_worker_cannot_overwrite_new_claim(
    tmp_path: Path, monkeypatch
):
    config_path = write_config(tmp_path)
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    seed_queue_row(store, bundle_path="pending.json")

    def reclaimed_while_generating(**kwargs):
        with store.connect() as conn:
            conn.execute(
                """
                UPDATE publish_queue
                SET claimed_at = '2000-01-01 00:00:00'
                WHERE dedupe_key = 'github:owner/repo'
                """
            )
        assert store.requeue_stale_generation_claims(3600) == 1
        assert store.claim_publish_queue_item(
            "github:owner/repo", "worker-b"
        ) is True
        return GenerationOutcome(
            dedupe_key="github:owner/repo",
            status="generated",
            attempts=1,
            output_path=tmp_path / "out/final/pending.json",
        )

    monkeypatch.setattr(cli, "generate_draft", reclaimed_while_generating)

    run_generate_drafts(config_path)

    row = store.list_publish_queue()[0]
    assert row["status"] == "generating"
    assert row["claim_token"] == "worker-b"
    assert store.transition_claimed_publish_queue_item(
        "github:owner/repo", "worker-b", "needs_human_review"
    ) is True


def test_generate_assets_requires_font_before_scanning_queue(monkeypatch):
    class StoreMustNotBeConstructed:
        def __init__(self, path):
            raise AssertionError("queue must not be scanned")

    monkeypatch.setattr(cli, "ContentStore", StoreMustNotBeConstructed)

    with pytest.raises(ValueError, match="visual_font_path is required"):
        cli.cmd_generate_assets(
            argparse.Namespace(config="missing-config.toml")
        )


def test_generate_assets_uses_safe_final_name_not_database_bundle_path(
    tmp_path: Path, monkeypatch, capsys
):
    config_path, font_path = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    dedupe_key = "github:owner/repo"
    seed_queue_row(
        store,
        dedupe_key=dedupe_key,
        status="needs_human_review",
        bundle_path=r"C:\outside\model-controlled.json",
    )
    seed_queue_row(
        store,
        dedupe_key="github:owner/pending",
        status="needs_generation",
        bundle_path="pending.json",
    )
    final_path = (
        cfg.output_dir / "final" / f"{cli._safe_name(dedupe_key)}.json"
    )
    final_path.parent.mkdir(parents=True)
    final_path.write_text(
        json.dumps(visual_payload(dedupe_key)),
        encoding="utf-8",
    )
    calls = []

    def fake_generate(*, final_path, **kwargs):
        calls.append((final_path, kwargs))
        return visual_payload(dedupe_key)

    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        fake_generate,
    )

    cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    assert calls == [
        (
            final_path,
            {
                "output_dir": cfg.output_dir,
                "font_path": font_path,
                    "template_name": None,
                    "copy_index": 0,
                    "expected_version": cli.payload_version(
                        cli.coerce_reviewable_final_payload(
                            visual_payload(dedupe_key)
                        )
                    ),
                },
        )
    ]
    assert capsys.readouterr().out == "generated 1, skipped 0, failed 0\n"


def test_generate_assets_skips_only_valid_published_revision(
    tmp_path: Path, monkeypatch, capsys
):
    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    seed_queue_row(store, status="needs_human_review")
    final_path = (
        cfg.output_dir
        / "final"
        / f"{cli._safe_name('github:owner/repo')}.json"
    )
    final_path.parent.mkdir(parents=True)
    final_path.write_text(
        json.dumps(rendered_visual_payload()),
        encoding="utf-8",
    )
    validations = []
    monkeypatch.setattr(
        cli,
        "validate_payload_revision",
        lambda payload, output_dir, font_path: validations.append(
            (payload["dedupe_key"], output_dir, font_path)
        ),
    )
    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        lambda *args, **kwargs: pytest.fail("must skip valid revision"),
    )

    cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    assert validations == [
        ("github:owner/repo", cfg.output_dir, cfg.visual_font_path)
    ]
    assert capsys.readouterr().out == "generated 0, skipped 1, failed 0\n"


def test_generate_assets_skips_legacy_articles_without_visual_brief(
    tmp_path: Path, monkeypatch, capsys
):
    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    seed_queue_row(store, status="needs_human_review")
    final_path = (
        cfg.output_dir
        / "final"
        / f"{cli._safe_name('github:owner/repo')}.json"
    )
    final_path.parent.mkdir(parents=True)
    legacy_payload = {
        key: value
        for key, value in visual_payload().items()
        if key not in {
            "editorial_profile",
            "visual_brief",
            "visual_assets",
            "article_layout",
        }
    }
    final_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "validate_payload_revision",
        lambda *args, **kwargs: pytest.fail("legacy article has no assets"),
    )
    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        lambda *args, **kwargs: pytest.fail("legacy article has no brief"),
    )

    cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    assert capsys.readouterr().out == "generated 0, skipped 1, failed 0\n"


def test_generate_assets_skips_legacy_named_final_articles(
    tmp_path: Path, monkeypatch, capsys
):
    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    seed_queue_row(store, status="needs_human_review")
    legacy_path = cfg.output_dir / "final" / "github-owner-repo.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_payload = {
        key: value
        for key, value in visual_payload().items()
        if key not in {
            "editorial_profile",
            "visual_brief",
            "visual_assets",
            "article_layout",
        }
    }
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        lambda *args, **kwargs: pytest.fail("legacy filename is skipped"),
    )

    cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    assert capsys.readouterr().out == "generated 0, skipped 1, failed 0\n"


@pytest.mark.parametrize(
    "wechat",
    [
        "Useful WeChat body\n\n来源：https://example.test",
        (
            "Useful WeChat body\n\n"
            "{{asset:body-01}}\n"
            "{{asset:body-01}}\n"
            "来源：https://example.test"
        ),
        (
            "Useful WeChat body\n\n"
            "来源：https://example.test\n"
            "{{asset:body-01}}"
        ),
    ],
    ids=["missing", "duplicate", "after-source"],
)
def test_generate_assets_rewrites_noncanonical_body_marker(
    tmp_path: Path, monkeypatch, capsys, wechat
):
    from ai_content_loop.visuals import pipeline

    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    seed_queue_row(store, status="needs_human_review")

    render_calls = []

    def fake_renderer(**kwargs):
        render_calls.append(kwargs)
        write_test_visuals(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    rendered = pipeline.generate_visual_assets(
        payload=visual_payload(),
        output_dir=cfg.output_dir,
        font_path=cfg.visual_font_path,
    )
    rendered["platform_markdown"]["wechat"] = wechat
    other_platforms = {
        name: rendered["platform_markdown"][name]
        for name in ("xiaohongshu", "toutiao", "zhihu")
    }
    final_path = (
        cfg.output_dir
        / "final"
        / f"{cli._safe_name('github:owner/repo')}.json"
    )
    final_path.parent.mkdir(parents=True)
    final_path.write_text(json.dumps(rendered), encoding="utf-8")

    cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    updated = json.loads(final_path.read_text(encoding="utf-8"))
    assert updated["platform_markdown"]["wechat"] == (
        "Useful WeChat body\n\n"
        "{{asset:body-01}}\n"
        "来源：https://example.test"
    )
    assert {
        name: updated["platform_markdown"][name]
        for name in other_platforms
    } == other_platforms
    assert len(render_calls) == 1
    assert capsys.readouterr().out == "generated 1, skipped 0, failed 0\n"


def test_generate_assets_repairs_overlong_visual_brief(
    tmp_path: Path, monkeypatch, capsys
):
    from ai_content_loop.visuals import pipeline

    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    seed_queue_row(store, status="needs_human_review")
    render_calls = []

    def fake_renderer(**kwargs):
        render_calls.append(kwargs)
        write_test_visuals(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    payload = visual_payload()
    payload["visual_brief"]["body_panels"].append(
        {"label": "Extra panel", "reaction": "noisy"}
    )
    payload["visual_brief"]["alternatives"][0]["body_panels"].append(
        {"label": "Extra alt", "reaction": "noisy"}
    )
    final_path = (
        cfg.output_dir
        / "final"
        / f"{cli._safe_name('github:owner/repo')}.json"
    )
    final_path.parent.mkdir(parents=True)
    final_path.write_text(json.dumps(payload), encoding="utf-8")

    cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    updated = json.loads(final_path.read_text(encoding="utf-8"))
    assert len(updated["visual_brief"]["body_panels"]) == 2
    assert len(updated["visual_brief"]["alternatives"][0]["body_panels"]) == 2
    assert updated["visual_assets"]["cover"]["asset_id"] == "cover"
    assert len(render_calls) == 1
    assert capsys.readouterr().out == "generated 1, skipped 0, failed 0\n"


def test_generate_assets_marker_repair_preserves_visual_selection(
    tmp_path: Path, monkeypatch, capsys
):
    from ai_content_loop.visuals import pipeline

    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    seed_queue_row(store, status="needs_human_review")
    render_calls = []

    def fake_renderer(**kwargs):
        render_calls.append(kwargs)
        write_test_visuals(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    rendered = pipeline.generate_visual_assets(
        payload=visual_payload(),
        output_dir=cfg.output_dir,
        font_path=cfg.visual_font_path,
        template_name="boss_vs_worker",
        copy_index=2,
    )
    original_cover = dict(rendered["visual_assets"]["cover"])
    rendered["platform_markdown"]["wechat"] = (
        "Useful WeChat body\n\n来源：https://example.test"
    )
    final_path = (
        cfg.output_dir
        / "final"
        / f"{cli._safe_name('github:owner/repo')}.json"
    )
    final_path.parent.mkdir(parents=True)
    final_path.write_text(json.dumps(rendered), encoding="utf-8")

    cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    updated = json.loads(final_path.read_text(encoding="utf-8"))
    assert updated["visual_assets"]["cover"] == original_cover
    assert updated["platform_markdown"]["wechat"] == (
        "Useful WeChat body\n\n"
        "{{asset:body-01}}\n"
        "来源：https://example.test"
    )
    assert len(render_calls) == 1
    assert capsys.readouterr().out == "generated 1, skipped 0, failed 0\n"


def test_generate_assets_mismatch_preserves_visual_selection(
    tmp_path: Path, monkeypatch, capsys
):
    from ai_content_loop.visuals import pipeline

    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    seed_queue_row(store, status="needs_human_review")
    render_calls = []

    def fake_renderer(**kwargs):
        render_calls.append(kwargs)
        write_test_visuals(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    rendered = pipeline.generate_visual_assets(
        payload=visual_payload(),
        output_dir=cfg.output_dir,
        font_path=cfg.visual_font_path,
        template_name="boss_vs_worker",
        copy_index=2,
    )
    final_path = (
        cfg.output_dir
        / "final"
        / f"{cli._safe_name('github:owner/repo')}.json"
    )
    final_path.parent.mkdir(parents=True)
    final_path.write_text(json.dumps(rendered), encoding="utf-8")
    body_path = cfg.output_dir / rendered["visual_assets"]["body"][0]["path"]
    body_path.write_bytes(b"tampered")
    real_generate = cli.generate_visual_assets_for_file
    calls = []

    def capture_generate(**kwargs):
        calls.append(kwargs)
        return real_generate(**kwargs)

    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        capture_generate,
    )

    with pytest.raises(SystemExit) as caught:
        cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    assert calls[0].get("template_name") == "boss_vs_worker"
    assert calls[0].get("copy_index") == 2
    assert len(render_calls) == 1
    unchanged = json.loads(final_path.read_text(encoding="utf-8"))
    assert unchanged["visual_assets"]["cover"]["template"] == "boss_vs_worker"
    assert unchanged["visual_assets"]["cover"]["copy_index"] == 2
    assert caught.value.code == 1
    assert capsys.readouterr().out == "generated 0, skipped 0, failed 1\n"


@pytest.mark.parametrize(
    ("field", "value"),
    [("template", "model-controlled-template"), ("copy_index", True)],
)
def test_generate_assets_isolates_malformed_nonempty_selection(
    tmp_path: Path, monkeypatch, capsys, field, value
):
    from ai_content_loop.visuals import pipeline

    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    seed_queue_row(store, status="needs_human_review")
    payload = rendered_visual_payload()
    payload["visual_assets"]["cover"][field] = value
    final_path = (
        cfg.output_dir
        / "final"
        / f"{cli._safe_name('github:owner/repo')}.json"
    )
    final_path.parent.mkdir(parents=True)
    final_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        pipeline,
        "render_visuals",
        lambda **kwargs: pytest.fail("renderer must not be called"),
    )
    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        lambda **kwargs: pytest.fail("file wrapper must not be called"),
    )

    with pytest.raises(SystemExit) as caught:
        cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    assert caught.value.code == 1
    assert capsys.readouterr().out == "generated 0, skipped 0, failed 1\n"


def test_generate_assets_isolates_expected_failures_without_leaking(
    tmp_path: Path, monkeypatch, capsys
):
    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    for dedupe_key in ("github:owner/bad", "github:owner/good"):
        seed_queue_row(
            store,
            dedupe_key=dedupe_key,
            status="needs_human_review",
        )
        final_path = (
            cfg.output_dir
            / "final"
            / f"{cli._safe_name(dedupe_key)}.json"
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(
            json.dumps(visual_payload(dedupe_key)),
            encoding="utf-8",
        )
    with store.connect() as conn:
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-02T00:00:00Z", "github:owner/bad"),
        )
        conn.execute(
            "UPDATE publish_queue SET created_at = ? WHERE dedupe_key = ?",
            ("2026-07-01T00:00:00Z", "github:owner/good"),
        )
    calls = []

    def generate(*, final_path, **kwargs):
        calls.append(final_path.name)
        if "bad" in final_path.name:
            raise cli.VisualRenderError("unsupported_glyph")
        return visual_payload("github:owner/good")

    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        generate,
    )

    with pytest.raises(SystemExit) as caught:
        cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    output = capsys.readouterr().out
    assert caught.value.code == 1
    assert len(calls) == 2
    assert output == "generated 1, skipped 0, failed 1\n"
    assert "unsupported_glyph" not in output


def test_generate_assets_persists_failure_continues_and_clears_on_success(
    tmp_path: Path, monkeypatch, capsys
):
    config_path, _ = write_visual_config(tmp_path)
    cfg = load_config(config_path)
    store = ContentStore(cfg.database_path)
    store.initialize()
    for dedupe_key in ("github:owner/bad", "github:owner/good"):
        seed_queue_row(
            store,
            dedupe_key=dedupe_key,
            status="needs_human_review",
        )
        final_path = (
            cfg.output_dir
            / "final"
            / f"{cli._safe_name(dedupe_key)}.json"
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(
            json.dumps(visual_payload(dedupe_key)),
            encoding="utf-8",
        )
    calls = []

    def fail_bad(*, final_path, **kwargs):
        calls.append(final_path.name)
        if "bad" in final_path.name:
            raise cli.VisualRenderError("unsupported_glyph")

    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        fail_bad,
    )

    with pytest.raises(SystemExit) as caught:
        cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    assert caught.value.code == 1
    assert len(calls) == 2
    output = capsys.readouterr().out
    assert output == "generated 1, skipped 0, failed 1\n"
    failure_path = (
        cfg.output_dir
        / "failures"
        / "assets"
        / f"{cli._safe_name('github:owner/bad')}.json"
    )
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert set(failure) == {"dedupe_key", "code", "timestamp"}
    assert failure["dedupe_key"] == "github:owner/bad"
    assert failure["code"] == "unsupported_glyph"
    assert "unsupported_glyph" not in output

    monkeypatch.setattr(
        cli,
        "generate_visual_assets_for_file",
        lambda **kwargs: None,
    )
    cli.cmd_generate_assets(argparse.Namespace(config=str(config_path)))

    assert not failure_path.exists()
    assert capsys.readouterr().out == "generated 2, skipped 0, failed 0\n"


def test_daily_propagates_asset_batch_failure_after_prior_stages(monkeypatch):
    calls = []

    for name in (
        "cmd_ingest",
        "cmd_score",
        "cmd_build_queue",
        "cmd_generate_drafts",
    ):
        monkeypatch.setattr(
            cli,
            name,
            lambda args, name=name: calls.append(name),
        )

    def fail_assets(args):
        calls.append("cmd_generate_assets")
        raise SystemExit(1)

    monkeypatch.setattr(cli, "cmd_generate_assets", fail_assets)

    with pytest.raises(SystemExit) as caught:
        cli.cmd_daily(argparse.Namespace(config="config.toml"))

    assert caught.value.code == 1
    assert calls == [
        "cmd_ingest",
        "cmd_score",
        "cmd_build_queue",
        "cmd_generate_drafts",
        "cmd_generate_assets",
    ]


def test_daily_runs_stages_in_order(monkeypatch):
    args = argparse.Namespace(config="config.toml")
    calls = []
    for name in (
        "cmd_ingest",
        "cmd_score",
        "cmd_build_queue",
        "cmd_generate_drafts",
        "cmd_generate_assets",
    ):
        monkeypatch.setattr(
            cli,
            name,
            lambda received_args, name=name: calls.append((name, received_args)),
        )

    cli.cmd_daily(args)

    assert calls == [
        ("cmd_ingest", args),
        ("cmd_score", args),
        ("cmd_build_queue", args),
        ("cmd_generate_drafts", args),
        ("cmd_generate_assets", args),
    ]


@pytest.mark.parametrize(
    ("failing_stage", "expected_calls"),
    [
        ("cmd_score", ["cmd_ingest", "cmd_score"]),
        ("cmd_build_queue", ["cmd_ingest", "cmd_score", "cmd_build_queue"]),
    ],
)
def test_daily_stops_after_deterministic_stage_error(
    failing_stage, expected_calls, monkeypatch
):
    calls = []

    def stage(name):
        def run(args):
            calls.append(name)
            if name == failing_stage:
                raise RuntimeError("stage failed")

        return run

    for name in (
        "cmd_ingest",
        "cmd_score",
        "cmd_build_queue",
        "cmd_generate_drafts",
        "cmd_generate_assets",
    ):
        monkeypatch.setattr(cli, name, stage(name))

    with pytest.raises(RuntimeError, match="stage failed"):
        cli.cmd_daily(argparse.Namespace(config="config.toml"))

    assert calls == expected_calls
    assert "cmd_generate_drafts" not in calls


def test_cli_help_lists_generation_and_daily_commands(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "generate-drafts" in output
    assert "generate-assets" in output
    assert "daily" in output
