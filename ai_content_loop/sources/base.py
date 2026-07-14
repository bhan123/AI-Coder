from __future__ import annotations

import json
from urllib.request import Request, urlopen


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20):
    req = Request(url, headers=headers or {"User-Agent": "ai-content-loop/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> str:
    req = Request(url, headers=headers or {"User-Agent": "ai-content-loop/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")
