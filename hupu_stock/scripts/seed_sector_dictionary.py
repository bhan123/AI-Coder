"""从 akshare（同花顺版）拉取全板块列表，初始化 config/boards.json。

设计文档 §4.2：动态拉取 → 第一版暂只生成板块骨架（无成分股）；
第二版可加上东方财富成分股 fallback。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# 把 src/ 加入 path，让 market.akshare_loader 可 import
SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import warnings

warnings.filterwarnings("ignore")


def fetch_ths_industries() -> list[dict]:
    """返回 [{name, code}, ...]."""
    import akshare as ak
    df = ak.stock_board_industry_name_ths()
    return [{"name": str(r["name"]), "code": str(r["code"])} for _, r in df.iterrows()]


def fetch_components_best_effort(name: str) -> list[str]:
    """从东方财富或同花顺拿成分股；拿不到返回空列表。"""
    try:
        from market.akshare_loader import fetch_sector_components_em
        comp = fetch_sector_components_em(name)
        if comp:
            return comp
    except Exception:
        pass
    return []


def build_boards_json(
    industries: list[dict],
    version_tag: str,
    extras_path: str = "config/boards_extra.json",
    with_components: bool = False,
) -> dict:
    """组装 boards.json 结构 + 自动合并 boards_extra.json 里的 aliases / exclude_keywords。

    with_components=True 时为每个板块尝试拉成分股（EM 接口可能被代理拦截）。
    """
    extras: dict = {}
    try:
        extras = json.loads(Path(extras_path).read_text(encoding="utf-8"))
    except Exception:
        pass
    alias_map = extras.get("aliases", {})
    exclude_map = extras.get("exclude_keywords", {})

    boards: dict[str, dict] = {}
    for ind in industries:
        name = ind["name"]
        comps = fetch_components_best_effort(name)[:30] if with_components else []
        extra_alias = alias_map.get(name, [])
        extras_excl = exclude_map.get(name, [])
        # 板块名本身就是主关键词，加上别名避免重复
        seen = {name}
        kws = [name]
        for c in comps:
            if c not in seen:
                kws.append(c); seen.add(c)
        # 别名作为"次关键词"放入 aliases（match_board 命中后算 secondary）
        aliases = []
        for a in extra_alias:
            if a not in seen:
                aliases.append(a); seen.add(a)
        boards[name] = {
            "keywords": kws,
            "components": comps,
            "aliases": aliases,
            "exclude_keywords": extras_excl,
            "code": ind["code"],
        }
    return {"version": version_tag, "source": "akshare-ths+extras", "boards": boards}


def main() -> None:
    parser = argparse.ArgumentParser(description="从 akshare 拉取同花顺全板块，覆盖 config/boards.json")
    parser.add_argument("--output", default="config/boards.json")
    parser.add_argument("--version-tag", default=f"ths-{datetime.now().strftime('%Y-%m-%d')}")
    parser.add_argument("--with-components", action="store_true",
                        help="尝试为每个板块拉成分股（EM 接口可能受网络限制）")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="每板块请求间隔（防 akshare 限速）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    industries = fetch_ths_industries()
    print(f"[seed] 同花顺板块数 = {len(industries)}", flush=True)

    payload = build_boards_json(
        industries, args.version_tag, with_components=args.with_components,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[seed] wrote {out_path} with {len(payload['boards'])} boards (含 aliases 自动合并)")


if __name__ == "__main__":
    main()
