from __future__ import annotations

from ai_content_loop.models import SourceItem
from ai_content_loop.sources.base import fetch_json


def parse_huggingface_models(payload: list[dict], fetched_at: str) -> list[SourceItem]:
    items = []
    for model in payload:
        model_id = str(model.get("modelId", "")).strip()
        if not model_id:
            continue
        tags = model.get("tags") or []
        items.append(
            SourceItem(
                source="huggingface",
                external_id=model_id,
                title=model_id,
                url=f"https://huggingface.co/{model_id}",
                summary=", ".join(str(tag) for tag in tags[:8]),
                published_at=str(model.get("lastModified") or ""),
                fetched_at=fetched_at,
                raw={
                    "likes": int(model.get("likes") or 0),
                    "downloads": int(model.get("downloads") or 0),
                    "tags": tags,
                },
            )
        )
    return items


def fetch_huggingface_models(limit: int, fetched_at: str) -> list[SourceItem]:
    url = f"https://huggingface.co/api/models?sort=likes&direction=-1&limit={limit}"
    return parse_huggingface_models(fetch_json(url), fetched_at=fetched_at)
