"""板块匹配的归一化权重测试。

设计文档 §2.3 验收点 6：单条文本多板块命中时，match_weight 总和 <= 1，
且必须有单元测试覆盖。
"""
from __future__ import annotations

import pytest

from analysis.board_matcher import match_board

pytestmark = pytest.mark.skip(reason="stub: 待 match_board 实现")  # 跳过直到实现


def test_no_match_returns_other() -> None:
    # TODO: 输入与板块词典毫无交集的文本 → 返回 ("其他", False, 0.0, [])
    ...


def test_single_primary_match() -> None:
    # TODO: 标题中出现板块名 → 单一主板块命中
    ...


def test_multiple_boards_normalized_le_one() -> None:
    # TODO: 同一文本命中多个板块时，Σ match_weight <= 1.0
    ...


def test_alias_match_is_secondary() -> None:
    # TODO: 仅命中别名时被记为次板块（is_primary=False, weight=0.3）
    ...
