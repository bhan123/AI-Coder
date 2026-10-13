"""板块匹配 + 多板块归一化权重（设计文档 §2.3）。

输入：`boards.json` + `boards_extra.json`
输出：每条文本 → [(board, is_primary, match_weight, matched_keywords), ...]
      全部归一化：Σweight ≤ 1.0；无任何命中 → [("其他", False, 0.0, [])]
"""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class BoardConfig:
    name: str
    keywords: tuple[str, ...]
    components: tuple[str, ...]
    aliases: tuple[str, ...]


def load_boards(path: str) -> dict[str, BoardConfig]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, BoardConfig] = {}
    for name, conf in raw.get("boards", {}).items():
        out[name] = BoardConfig(
            name=name,
            keywords=tuple(conf.get("keywords", [])),
            components=tuple(conf.get("components", [])),
            aliases=tuple(conf.get("aliases", [])),
        )
    return out


@dataclass(frozen=True)
class BoardExtras:
    aliases: dict[str, list[str]]  # board_name -> extra alias list
    exclude_keywords: dict[str, list[str]]  # board_name -> exclusions


def load_extras(path: str) -> BoardExtras:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return BoardExtras(
        aliases={k: list(v) for k, v in raw.get("aliases", {}).items()},
        exclude_keywords={k: list(v) for k, v in raw.get("exclude_keywords", {}).items()},
    )


def match_board(
    text: str,
    boards: dict[str, BoardConfig],
    extras: BoardExtras | None = None,
) -> list[tuple[str, bool, float, list[str]]]:
    """对一条文本做板块匹配，返回归一化后的命中列表。

    规则（设计文档 §2.3）：
      - 标题/正文直接命中 keywords 或 components → 主板块权重 1.0
      - 仅命中别名（aliases + extras.aliases）→ 次板块权重 0.3
      - 命中后再做归一化，使 Σweight ≤ 1.0
      - exclude_keywords 命中后该板被屏蔽
      - 无任何命中 → [("其他", False, 0.0, [])]
    """
    if not text:
        return [("其他", False, 0.0, [])]

    raw_hits: list[tuple[str, bool, list[str]]] = []  # (board, is_primary, keywords)

    # 把所有板块名作为关键词一并参与——这样帖子说"看好半导体"也算主板块命中
    extras = extras or BoardExtras(aliases={}, exclude_keywords={})

    for name, conf in boards.items():
        excluded = extras.exclude_keywords.get(name, [])
        if any(ex in text for ex in excluded):
            continue

        kws_hit = [w for w in conf.keywords if w and w in text]
        comp_hit = [w for w in conf.components if w and w in text]
        alias_hit = [w for w in conf.aliases if w and w in text]
        extra_alias_hit = [w for w in extras.aliases.get(name, []) if w and w in text]

        primary_words = list(set(kws_hit + comp_hit + [name] if name in text else []))
        is_primary = bool(primary_words)
        all_alias = list(set(alias_hit + extra_alias_hit))
        if is_primary or all_alias:
            raw_hits.append((name, is_primary, primary_words or all_alias))

    if not raw_hits:
        return [("其他", False, 0.0, [])]

    # 归一化权重
    primary_w = 1.0
    secondary_w = 0.3
    weights = [primary_w if is_p else secondary_w for _, is_p, _ in raw_hits]
    total = sum(weights)
    scale = 1.0 if total <= 1.0 else 1.0 / total

    out: list[tuple[str, bool, float, list[str]]] = []
    for (name, is_p, kws), raw_w in zip(raw_hits, weights):
        out.append((name, is_p, round(raw_w * scale, 4), kws))
    return out
