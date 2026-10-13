"""板块匹配 + 归一化权重测试。"""
from __future__ import annotations

from analysis.board_matcher import BoardExtras, load_boards, load_extras, match_board


def test_no_match_returns_other() -> None:
    boards = load_boards("config/boards.json")
    extras = load_extras("config/boards_extra.json")
    hits = match_board("今天天气好", boards, extras)
    assert hits == [("其他", False, 0.0, [])]


def test_single_primary_match() -> None:
    boards = load_boards("config/boards.json")
    extras = load_extras("config/boards_extra.json")
    hits = match_board("看好半导体", boards, extras)
    names = [h[0] for h in hits]
    assert "半导体" in names


def test_alias_match_is_secondary() -> None:
    boards = load_boards("config/boards.json")
    extras = load_extras("config/boards_extra.json")
    # "封测" 是 半导体的 alias
    hits = match_board("封测景气度在回暖", boards, extras)
    sem = [h for h in hits if h[0] == "半导体"]
    assert sem, "应命中半导体（通过 alias 封测）"
    assert sem[0][1] is False  # alias 是次板块


def test_multiple_boards_normalized_le_one() -> None:
    boards = load_boards("config/boards.json")
    extras = load_extras("config/boards_extra.json")
    # 同时谈半导体 + 新能源（比亚迪也算新能源）
    text = "半导体景气度回暖，电池端比亚迪新能源也跟着起飞"
    hits = match_board(text, boards, extras)
    assert len(hits) >= 2
    total_weight = sum(h[2] for h in hits)
    # 4 位小数舍入 + 多板叠加可能略超 1.0；1e-3 容忍足够严格
    assert total_weight <= 1.0 + 1e-3


def test_excluded_keyword_skips_board() -> None:
    boards = load_boards("config/boards.json")
    extras = load_extras("config/boards_extra.json")
    # "银行" 板被 "银行卡" 排除
    hits = match_board("我用银行卡转账", boards, extras)
    names = [h[0] for h in hits if h[0] != "其他"]
    assert "银行" not in names
