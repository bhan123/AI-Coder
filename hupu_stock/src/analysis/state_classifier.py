"""状态判定（设计文档 §3）。

判定顺序：
  样本不足 → 低置信观察 → 新热启动 / 亢奋拥挤 / 恐慌拥挤 / 噪音争吵 → 无强信号
"""
from __future__ import annotations


def compute_confidence(history_days: int) -> str:
    if history_days < 20:
        return "冷启动"
    if history_days < 60:
        return "低置信"
    if history_days < 120:
        return "中置信"
    return "正式"


def classify_state(
    *,
    hot_score: float,
    sent_score: float,
    crowding_score: float,
    heat_momentum: float,
    price_extension: float,
    is_top_board: bool,
    coverage_score: float,
    history_days: int,
    effective_item_count: float,
    unique_authors: int,
) -> str:
    """返回 §3 表格中的状态标签。"""
    if not is_top_board or effective_item_count < 10 or unique_authors < 5 or history_days < 20:
        return "样本不足"
    if history_days < 60:
        return "低置信观察"

    # 噪音争吵（分裂很大）
    if hot_score > 70 and abs(sent_score - 50) < 10:
        return "噪音争吵"

    # 亢奋拥挤（多头）
    if hot_score > 90 and sent_score > 75 and crowding_score > 80:
        return "亢奋拥挤"

    # 恐慌拥挤（空头）
    if hot_score > 85 and sent_score < 25 and crowding_score > 70:
        return "恐慌拥挤"

    # 新热启动（题材扩散初期）
    if (
        70 <= hot_score <= 90
        and heat_momentum > 1.5
        and 55 <= sent_score <= 70
        and crowding_score < 60
        and price_extension < 60
    ):
        return "新热启动"

    return "无强信号"
