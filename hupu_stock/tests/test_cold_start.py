"""冷启动与置信度行为测试。

设计文档 §11 验收点 8：
- history_days < 20 强制"样本不足"
- 20-59 日"低置信观察"，不输出强信号
- 60+ 日才允许进入强状态候选
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="stub: 集成测试，待指标与状态判定实现")


def test_below_20_days_always_insufficient() -> None:
    # TODO: history_days=10 + 任意 is_top_board → state="样本不足"
    ...


def test_between_20_and_59_no_strong_signal() -> None:
    # TODO: 即使指标满足亢奋拥挤，也只能得到"低置信观察"
    ...


def test_top_n_filter_blocks_long_tail() -> None:
    # TODO: is_top_board=False 时永不输出"亢奋拥挤/恐慌拥挤/新热启动/噪音争吵"
    ...
