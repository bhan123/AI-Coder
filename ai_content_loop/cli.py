from __future__ import annotations

from datetime import UTC, datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import uuid

from ai_content_loop.config import load_config
from ai_content_loop.db import ContentStore
from ai_content_loop.durability import fsync_directory
from ai_content_loop.evidence import build_evidence_pack
from ai_content_loop.editorial.schema import (
    FinalSchemaError,
    coerce_reviewable_final_payload,
    normalize_final_payload,
    payload_version,
)
from ai_content_loop.generation import generate_draft, write_failure_artifact
from ai_content_loop.gpt_polish import (
    GptPolishProposalError,
    validate_gpt_polish_proposal,
)
from ai_content_loop.metrics import import_metrics_csv, weekly_summary
from ai_content_loop.scoring import llm_score_items, score_items
from ai_content_loop.sources.arxiv import fetch_arxiv_ai
from ai_content_loop.sources.github import fetch_github_repositories
from ai_content_loop.sources.hackernews import fetch_hackernews_show
from ai_content_loop.sources.modelscope import fetch_modelscope_models
from ai_content_loop.sources.producthunt import fetch_producthunt_posts
from ai_content_loop.sources.rss import fetch_rss_feed
from ai_content_loop.templates import build_master_brief, build_platform_skeletons, choose_column
from ai_content_loop.visuals.assets import (
    AssetPublicationError,
    atomic_json_write,
    validate_payload_revision,
)
from ai_content_loop.visuals.pipeline import (
    expected_image_source,
    generate_visual_assets_for_file,
    has_canonical_body_asset_marker,
)
from ai_content_loop.visuals.minimax_image import client_from_env
from ai_content_loop.visuals.renderer import VisualRenderError


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(dedupe_key: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", dedupe_key).strip("._-")
    prefix = sanitized[:48].rstrip("._-") or "item"
    digest = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def cmd_init(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    ContentStore(cfg.database_path).initialize()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"initialized {cfg.database_path}")


def cmd_score(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    items = store.list_source_items(
        limit=cfg.daily_raw_limit,
        llm_eligible_only=cfg.scoring_llm_limit > 0,
    )
    scores = score_items(items)
    store.upsert_scores(scores)
    print(f"keyword-scored {len(scores)} candidates")

    # 混合打分：LLM 精选层
    if cfg.scoring_llm_limit > 0 and scores:
        items_dict = {i.dedupe_key: i for i in items}
        queued_keys = {
            str(row["dedupe_key"])
            for row in store.list_publish_queue()
        }
        reviewed_keys = store.list_llm_reviewed_dedupe_keys()
        eligible_scores = [
            score
            for score in scores
            if score.dedupe_key not in queued_keys
            and score.dedupe_key not in reviewed_keys
        ]
        top_n = min(cfg.scoring_llm_limit, len(eligible_scores))
        candidates_for_llm = [
            {
                "dedupe_key": s.dedupe_key,
                "source": items_dict[s.dedupe_key].source if s.dedupe_key in items_dict else "",
                "title": items_dict[s.dedupe_key].title if s.dedupe_key in items_dict else "",
                "summary": items_dict[s.dedupe_key].summary if s.dedupe_key in items_dict else "",
                "url": items_dict[s.dedupe_key].url if s.dedupe_key in items_dict else "",
                "total": s.total,
                "reason": s.reason,
                "raw": items_dict[s.dedupe_key].raw if s.dedupe_key in items_dict else {},
            }
            for s in eligible_scores[:top_n]
        ]
        skipped_queued = sum(
            score.dedupe_key in queued_keys for score in scores
        )
        skipped_reviewed = sum(
            score.dedupe_key not in queued_keys
            and score.dedupe_key in reviewed_keys
            for score in scores
        )
        if skipped_queued:
            print(f"llm-skipped {skipped_queued} candidates already in publish queue")
        if skipped_reviewed:
            print(f"llm-skipped {skipped_reviewed} candidates already reviewed")
        if not candidates_for_llm:
            print("LLM scoring skipped; no unqueued candidate is eligible")
            return
        prompt_dir = Path(__file__).parent / "prompts"
        successful_candidates: list[dict[str, Any]] = []
        llm_scores: list[dict[str, Any]] = []
        failed_batches = 0
        for start in range(0, len(candidates_for_llm), cfg.scoring_llm_batch_size):
            if len(llm_scores) >= cfg.publish_limit:
                break
            batch = candidates_for_llm[
                start : start + cfg.scoring_llm_batch_size
            ]
            batch_scores = llm_score_items(
                batch,
                hermes_command=cfg.hermes_command,
                prompt_path=prompt_dir / "scoring.md",
                timeout_seconds=cfg.scoring_llm_timeout_seconds,
            )
            if batch_scores is None:
                failed_batches += 1
                continue
            successful_candidates.extend(batch)
            llm_scores.extend(batch_scores)

        candidates_for_llm = successful_candidates
        if not successful_candidates:
            llm_scores = None
        if llm_scores is not None:
            # 用 LLM 打分更新数据库中的分数
            from ai_content_loop.models import CandidateScore
            reviewed_keys = [
                candidate["dedupe_key"] for candidate in candidates_for_llm
            ]
            reviewed_set = set(reviewed_keys)
            updated = []
            for ls in llm_scores:
                if ls.get("dedupe_key") not in reviewed_set:
                    continue
                scores_detail = ls.get("scores", {})
                updated.append(CandidateScore(
                    dedupe_key=ls["dedupe_key"],
                    novelty=int(scores_detail.get("novelty", 5)),
                    clarity=int(scores_detail.get("clarity", 5)),
                    fun=int(scores_detail.get("fun", 5)),
                    usefulness=int(scores_detail.get("usefulness", 5)),
                    demo=int(scores_detail.get("demo", 4)),
                    heat=int(scores_detail.get("heat", 5)),
                    credibility=int(scores_detail.get("credibility", 5)),
                    total=float(ls.get("total_score", 50)),
                    reason=f"llm: {ls.get('reason', '')} | angle: {ls.get('angle', '')} | column: {ls.get('column', '')}",
                    llm_column=str(ls.get("column", "")),
                    llm_angle=str(ls.get("angle", "")),
                ))
            if updated:
                store.upsert_scores(updated)
            recommended_keys = [
                score["dedupe_key"]
                for score in llm_scores
                if score.get("dedupe_key") in reviewed_set
            ]
            store.record_llm_recommendations(
                reviewed_keys=reviewed_keys,
                recommended_keys=recommended_keys,
            )
            print(
                f"llm-reviewed {len(reviewed_keys)} candidates, "
                f"recommended {len(recommended_keys)}"
            )
            if failed_batches:
                print(
                    f"LLM scoring had {failed_batches} failed batch(es); "
                    "previous successful recommendations were preserved"
                )
        else:
            print("LLM scoring failed for every batch; previous recommendations were preserved")


def cmd_ingest(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    fetched_at = _now()
    collected = []

    def collect_source(name: str, fetcher) -> None:
        try:
            collected.extend(fetcher())
        except Exception as exc:
            print(f"source {name} failed: {exc}")

    limits = cfg.source_limits

    def collect_limited_source(name: str, default: int, fetcher) -> None:
        limit = int(limits.get(name, default))
        if limit > 0:
            collect_source(name, lambda: fetcher(limit))

    collect_limited_source(
        "github",
        30,
        lambda limit: fetch_github_repositories(limit, fetched_at=fetched_at),
    )
    collect_limited_source(
        "hackernews",
        30,
        lambda limit: fetch_hackernews_show(limit, fetched_at=fetched_at),
    )
    collect_limited_source(
        "arxiv",
        30,
        lambda limit: fetch_arxiv_ai(limit, fetched_at=fetched_at),
    )
    collect_limited_source(
        "modelscope",
        30,
        lambda limit: fetch_modelscope_models(limit, fetched_at=fetched_at),
    )
    collect_limited_source(
        "producthunt",
        20,
        lambda limit: fetch_producthunt_posts(
            limit,
            fetched_at=fetched_at,
            token=cfg.producthunt_token,
        ),
    )
    for index, feed_url in enumerate(cfg.official_rss_feeds):
        collect_source(
            f"official_rss_{index}",
            lambda feed_url=feed_url, index=index: fetch_rss_feed(
                feed_url,
                source_name=f"official_rss_{index}",
                fetched_at=fetched_at,
                limit=limits.get("official_rss", 10),
            ),
        )
    for feed in cfg.rss_feeds:
        collect_source(
            feed.name,
            lambda feed=feed: fetch_rss_feed(
                feed.url,
                source_name=feed.name,
                fetched_at=fetched_at,
                include_keywords=feed.include_keywords,
                limit=feed.limit,
            ),
        )

    store.upsert_source_items(collected[: cfg.daily_raw_limit])
    print(f"ingested {min(len(collected), cfg.daily_raw_limit)} source items")


RESEARCH_SOURCES = {"arxiv", "modelscope", "huggingface"}
PRACTICAL_SOURCES = {"producthunt", "huggingface_spaces"}
PRACTICAL_RSS_PREFIXES = (
    "rss_sspai",
    "rss_appinn",
    "rss_ifanr",
    "rss_zapier",
)


def _is_practical_source(source: str) -> bool:
    return source in PRACTICAL_SOURCES or source.startswith(PRACTICAL_RSS_PREFIXES)


def select_balanced_candidates(
    candidates: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    selected: list[dict[str, Any]] = []
    practical = next(
        (
            candidate
            for candidate in candidates
            if _is_practical_source(str(candidate.get("source", "")))
        ),
        None,
    )
    if practical is not None:
        selected.append(practical)

    research_count = sum(
        str(candidate.get("source", "")) in RESEARCH_SOURCES
        for candidate in selected
    )
    selected_keys = {candidate["dedupe_key"] for candidate in selected}
    for candidate in candidates:
        if len(selected) >= limit:
            break
        if candidate["dedupe_key"] in selected_keys:
            continue
        source = str(candidate.get("source", ""))
        if source in RESEARCH_SOURCES and research_count >= 1:
            continue
        selected.append(candidate)
        selected_keys.add(candidate["dedupe_key"])
        if source in RESEARCH_SOURCES:
            research_count += 1
    return selected


def cmd_build_queue(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    drafts_dir = cfg.output_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    ranked = store.list_ranked_candidates(
        limit=max(50, cfg.publish_limit * 10),
        exclude_queued=True,
        recommended_only=cfg.scoring_llm_limit > 0,
    )
    candidates = select_balanced_candidates(ranked, limit=cfg.publish_limit)
    for candidate in candidates:
        pack = build_evidence_pack(candidate, deep_research=cfg.deep_research_enabled)
        llm_column = str(candidate.get("llm_column", "") or "")
        llm_angle = str(candidate.get("llm_angle", "") or "")
        payload = {
            "dedupe_key": pack.dedupe_key,
            "title": pack.title,
            "column": choose_column(pack, llm_column=llm_column),
            "source_url": pack.url,
            "facts": list(pack.facts),
            "risks": list(pack.risks),
            "writing_angles": list(pack.writing_angles),
            "brief": build_master_brief(pack, llm_angle=llm_angle),
            "platform_skeletons": build_platform_skeletons(pack, llm_column=llm_column),
        }
        bundle_path = (
            drafts_dir / f"{_safe_name(pack.dedupe_key)}.json"
        ).resolve()
        bundle_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        store.upsert_publish_queue(
            dedupe_key=pack.dedupe_key,
            title=pack.title,
            column_name=payload["column"],
            status="needs_generation",
            bundle_path=str(bundle_path),
        )
    print(f"queued {len(candidates)} draft bundles")


def cmd_generate_drafts(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    prompt_dir = Path(__file__).parent / "prompts"
    counts = {"generated": 0, "skipped_existing": 0, "failed": 0}
    store.requeue_stale_generation_claims()

    for row in store.list_publish_queue(status="needs_generation"):
        dedupe_key = row["dedupe_key"]
        claim_token = uuid.uuid4().hex
        if not store.claim_publish_queue_item(dedupe_key, claim_token):
            continue

        transitioned = False
        try:
            bundle_path = Path(row["bundle_path"])
            try:
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
            except (OSError, ValueError, KeyError) as error:
                write_failure_artifact(
                    failure_dir=cfg.output_dir / "failures",
                    dedupe_key=dedupe_key,
                    bundle_path=bundle_path,
                    error_code=f"generation_error:{type(error).__name__}",
                )
                transitioned = store.transition_claimed_publish_queue_item(
                    dedupe_key, claim_token, "generation_failed"
                )
                if transitioned:
                    counts["failed"] += 1
                continue

            if outcome.dedupe_key != dedupe_key:
                write_failure_artifact(
                    failure_dir=cfg.output_dir / "failures",
                    dedupe_key=dedupe_key,
                    bundle_path=bundle_path,
                    error_code="identity_mismatch",
                )
                transitioned = store.transition_claimed_publish_queue_item(
                    dedupe_key, claim_token, "generation_failed"
                )
                if transitioned:
                    counts["failed"] += 1
                continue

            status = (
                "needs_human_review"
                if outcome.status in {"generated", "skipped_existing"}
                else "generation_failed"
            )
            transitioned = store.transition_claimed_publish_queue_item(
                dedupe_key, claim_token, status
            )
            if transitioned:
                counts[outcome.status] += 1
        finally:
            if not transitioned:
                store.transition_claimed_publish_queue_item(
                    dedupe_key, claim_token, "needs_generation"
                )

    print(
        f"generated {counts['generated']}, "
        f"skipped {counts['skipped_existing']}, "
        f"failed {counts['failed']}"
    )


def _configured_visual_font(cfg) -> Path:
    font_path = cfg.visual_font_path
    if font_path is None:
        raise ValueError("visual_font_path is required")
    path = Path(font_path)
    try:
        valid = not path.is_symlink() and path.is_file()
    except OSError:
        valid = False
    if not valid:
        raise ValueError(
            "visual_font_path must be a regular non-symlink file"
        )
    return path


def _final_path_for_dedupe(output_dir: Path, dedupe_key: str) -> Path:
    return (
        Path(output_dir)
        / "final"
        / f"{_safe_name(dedupe_key)}.json"
    )


def _legacy_final_path_for_dedupe(output_dir: Path, dedupe_key: str) -> Path:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", dedupe_key).strip("._-")
    filename = sanitized[:96].rstrip("._-") or "item"
    return Path(output_dir) / "final" / f"{filename}.json"


def _load_asset_candidate(
    final_path: Path,
    *,
    expected_dedupe_key: str,
) -> dict[str, Any]:
    if final_path.is_symlink() or not final_path.is_file():
        raise ValueError("final article is unavailable")
    try:
        value = json.loads(final_path.read_text(encoding="utf-8"))
        try:
            payload = normalize_final_payload(value)
        except FinalSchemaError:
            payload = coerce_reviewable_final_payload(value)
            atomic_json_write(final_path, payload)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        FinalSchemaError,
    ):
        raise ValueError("final article is invalid") from None
    if payload["dedupe_key"] != expected_dedupe_key:
        raise ValueError("final article identity mismatch")
    return payload


def _asset_generation_selection(
    payload: dict[str, Any],
) -> tuple[str | None, int]:
    """Extract only a selection already trusted by final-schema validation."""

    cover = payload["visual_assets"]["cover"]
    if cover is None:
        return None, 0
    return cover["template"], cover["copy_index"]


def _asset_failure_path(output_dir: Path, dedupe_key: str) -> Path:
    return (
        Path(output_dir)
        / "failures"
        / "assets"
        / f"{_safe_name(dedupe_key)}.json"
    )


def _asset_failure_code(error: Exception) -> str:
    if isinstance(error, (AssetPublicationError, VisualRenderError)):
        code = error.code
        if re.fullmatch(r"[a-z0-9_]{1,64}", code):
            return code
        return "asset_error"
    if isinstance(error, OSError):
        return "asset_io_error"
    return "invalid_asset_input"


def _write_asset_failure(
    *,
    output_dir: Path,
    dedupe_key: str,
    error: Exception,
) -> None:
    atomic_json_write(
        _asset_failure_path(output_dir, dedupe_key),
        {
            "dedupe_key": dedupe_key[:512],
            "code": _asset_failure_code(error),
            "timestamp": _now(),
        },
    )


def _clear_asset_failure(output_dir: Path, dedupe_key: str) -> None:
    path = _asset_failure_path(output_dir, dedupe_key)
    path.unlink(missing_ok=True)
    if path.parent.exists():
        fsync_directory(path.parent)


def cmd_generate_assets(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    font_path = _configured_visual_font(cfg)
    image_client = client_from_env(os.environ)
    if cfg.visual_render_concurrency != 1:
        raise ValueError("visual_render_concurrency must be the integer 1")

    store = ContentStore(cfg.database_path)
    store.initialize()
    counts = {"generated": 0, "skipped": 0, "failed": 0}
    for row in store.list_publish_queue(status="needs_human_review"):
        dedupe_key = None
        try:
            dedupe_key = row["dedupe_key"]
            if not isinstance(dedupe_key, str) or not dedupe_key.strip():
                raise ValueError("invalid queue identity")
            final_path = _final_path_for_dedupe(
                cfg.output_dir,
                dedupe_key,
            )
            legacy_final_path = _legacy_final_path_for_dedupe(
                cfg.output_dir,
                dedupe_key,
            )
            if (
                not final_path.exists()
                and legacy_final_path.is_file()
                and not legacy_final_path.is_symlink()
            ):
                counts["skipped"] += 1
                _clear_asset_failure(cfg.output_dir, dedupe_key)
                continue
            payload = _load_asset_candidate(
                final_path,
                expected_dedupe_key=dedupe_key,
            )
            if (
                payload["visual_brief"] is None
                and payload["visual_assets"]["cover"] is None
                and payload["visual_assets"]["body"] == []
            ):
                counts["skipped"] += 1
                _clear_asset_failure(cfg.output_dir, dedupe_key)
                continue
            template_name, copy_index = _asset_generation_selection(payload)
            expected_version = payload_version(payload)

            def generate_assets() -> None:
                generate_visual_assets_for_file(
                    final_path=final_path,
                    output_dir=cfg.output_dir,
                    font_path=font_path,
                    template_name=template_name,
                    copy_index=copy_index,
                    expected_version=expected_version,
                    image_client=image_client,
                )

            try:
                validate_payload_revision(
                    payload,
                    cfg.output_dir,
                    font_path,
                    image_source=expected_image_source(
                        payload=payload,
                        image_client=image_client,
                        copy_index=copy_index,
                    ),
                )
            except AssetPublicationError:
                generate_assets()
                counts["generated"] += 1
            else:
                if has_canonical_body_asset_marker(payload):
                    counts["skipped"] += 1
                else:
                    generate_assets()
                    counts["generated"] += 1
            _clear_asset_failure(cfg.output_dir, dedupe_key)
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AssetPublicationError,
            VisualRenderError,
        ) as error:
            counts["failed"] += 1
            if isinstance(dedupe_key, str) and dedupe_key.strip():
                try:
                    _write_asset_failure(
                        output_dir=cfg.output_dir,
                        dedupe_key=dedupe_key,
                        error=error,
                    )
                except OSError:
                    pass
    print(
        f"generated {counts['generated']}, "
        f"skipped {counts['skipped']}, "
        f"failed {counts['failed']}"
    )
    if counts["failed"]:
        raise SystemExit(1)


def cmd_daily(args: argparse.Namespace) -> None:
    cmd_ingest(args)
    cmd_score(args)
    cmd_build_queue(args)
    cmd_generate_drafts(args)
    cmd_generate_assets(args)


def cmd_import_metrics(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    count = import_metrics_csv(store, args.csv)
    print(f"imported {count} metric rows")


def cmd_weekly_summary(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    summary = weekly_summary(store, since_date=args.since)
    output = cfg.output_dir / "weekly-summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output}")


def cmd_gpt_polish_claim(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    job = store.claim_next_gpt_polish_job(args.worker)
    print(json.dumps({"job": job}, ensure_ascii=False, separators=(",", ":")))


def _read_gpt_polish_proposal(path: str) -> dict[str, Any]:
    if path == "-":
        raw = sys.stdin.read(1_500_001)
    else:
        candidate = Path(path)
        if not candidate.is_file() or candidate.is_symlink():
            raise SystemExit("proposal file is unavailable")
        if candidate.stat().st_size > 1_500_000:
            raise SystemExit("proposal file is too large")
        raw = candidate.read_text(encoding="utf-8")
    if len(raw.encode("utf-8")) > 1_500_000:
        raise SystemExit("proposal is too large")
    try:
        value = json.loads(raw)
        return validate_gpt_polish_proposal(value)
    except (json.JSONDecodeError, UnicodeError, GptPolishProposalError):
        raise SystemExit("proposal is invalid") from None


def cmd_gpt_polish_submit(args: argparse.Namespace) -> None:
    proposal = _read_gpt_polish_proposal(args.proposal_file)
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    if not store.submit_gpt_polish_proposal(
        args.job_id, args.worker, proposal
    ):
        raise SystemExit("GPT polish job cannot accept this proposal")
    print(json.dumps({"job_id": args.job_id, "status": "ready"}))


def cmd_gpt_polish_fail(args: argparse.Namespace) -> None:
    if re.fullmatch(r"[a-z][a-z0-9_]{0,79}", args.error) is None:
        raise SystemExit("error must be a stable code")
    cfg = load_config(args.config)
    store = ContentStore(cfg.database_path)
    store.initialize()
    if not store.fail_gpt_polish_job(args.job_id, args.worker, args.error):
        raise SystemExit("GPT polish job cannot be failed by this worker")
    print(json.dumps({"job_id": args.job_id, "status": "failed"}))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI content loop MVP")
    parser.add_argument("--config", default="ai_content_loop/config.example.toml")
    sub = parser.add_subparsers(required=True)

    init = sub.add_parser("init")
    init.set_defaults(func=cmd_init)

    ingest = sub.add_parser("ingest")
    ingest.set_defaults(func=cmd_ingest)

    score = sub.add_parser("score")
    score.set_defaults(func=cmd_score)

    queue = sub.add_parser("build-queue")
    queue.set_defaults(func=cmd_build_queue)

    generate = sub.add_parser("generate-drafts")
    generate.set_defaults(func=cmd_generate_drafts)

    assets = sub.add_parser("generate-assets")
    assets.set_defaults(func=cmd_generate_assets)

    daily = sub.add_parser("daily")
    daily.set_defaults(func=cmd_daily)

    metrics = sub.add_parser("import-metrics")
    metrics.add_argument("csv")
    metrics.set_defaults(func=cmd_import_metrics)

    weekly = sub.add_parser("weekly-summary")
    weekly.add_argument("--since", required=True)
    weekly.set_defaults(func=cmd_weekly_summary)

    polish_claim = sub.add_parser("gpt-polish-claim")
    polish_claim.add_argument("--worker", required=True)
    polish_claim.set_defaults(func=cmd_gpt_polish_claim)

    polish_submit = sub.add_parser("gpt-polish-submit")
    polish_submit.add_argument("--job-id", required=True)
    polish_submit.add_argument("--worker", required=True)
    polish_submit.add_argument("--proposal-file", required=True)
    polish_submit.set_defaults(func=cmd_gpt_polish_submit)

    polish_fail = sub.add_parser("gpt-polish-fail")
    polish_fail.add_argument("--job-id", required=True)
    polish_fail.add_argument("--worker", required=True)
    polish_fail.add_argument("--error", required=True)
    polish_fail.set_defaults(func=cmd_gpt_polish_fail)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
