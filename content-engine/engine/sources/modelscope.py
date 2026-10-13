from __future__ import annotations

from urllib.request import Request, urlopen
import json

from engine.models import SourceItem


MODELSCOPE_API = "https://modelscope.cn/api/v1/models"


def parse_modelscope_models(
    payload: list[dict], fetched_at: str
) -> list[SourceItem]:
    items = []
    for model in payload:
        name = str(model.get("Name") or model.get("name") or "").strip()
        if not name:
            continue
        model_id = str(model.get("Path") or model.get("PathWithNamespace") or name)
        downloads = int(model.get("Downloads") or 0)
        stars = int(model.get("Stars") or model.get("StarCount") or 0)
        tags = model.get("Tags") or []
        task = str(model.get("Task") or model.get("task") or "")
        if task:
            tags = list(tags) + [task]
        items.append(
            SourceItem(
                source="modelscope",
                external_id=model_id,
                title=name,
                url=f"https://modelscope.cn/models/{model_id}",
                summary=", ".join(str(tag) for tag in tags[:8]),
                published_at=str(model.get("GmtModified") or model.get("gmt_modified") or ""),
                fetched_at=fetched_at,
                raw={
                    "downloads": downloads,
                    "stars": stars,
                    "tags": tags,
                },
            )
        )
    return items


def fetch_modelscope_models(
    limit: int, fetched_at: str, task: str = "text-generation"
) -> list[SourceItem]:
    """Fetch trending models from ModelScope by task type and download count.

    ModelScope's public API does not require authentication for listing
    models.  We filter by ``task`` and order by downloads descending to
    surface the most-used Chinese-ecosystem models.
    """
    url = (
        f"{MODELSCOPE_API}"
        f"?PageNumber=1&PageSize={limit}"
        f"&SortBy=Downloads&Target=asc"
        f"&Task={task}"
    )
    req = Request(
        url,
        headers={
            "User-Agent": "ai-content-loop/0.1",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    models = (
        data.get("Data", {}).get("Model", {}).get("Models", [])
        if isinstance(data, dict)
        else data
    )
    if not isinstance(models, list):
        return []
    return parse_modelscope_models(models[:limit], fetched_at=fetched_at)
