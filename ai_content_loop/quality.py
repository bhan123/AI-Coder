from __future__ import annotations

from dataclasses import dataclass


BANNED_PROMISES = (
    "保证赚钱", "躺赚", "稳赚", "替代所有", "100%",
    "月入", "日入", "年入百万", "轻松赚钱",
)
RISKY_TOPICS = ("诊断疾病", "投资建议", "法律意见")

# 标题党检测
CLICKBAIT_PATTERNS = (
    "震惊", "疯了", "炸裂", "彻底改变", "颠覆",
    "你绝对想不到", "99%的人不知道",
)


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    failures: list[str]


def evaluate_draft(title: str, markdown: str, source_url: str) -> QualityResult:
    """基础质量门禁——事实链接、长度、违禁词、标题党检测。"""
    failures: list[str] = []
    combined = f"{title}\n{markdown}"

    # 来源链接检查
    if source_url not in markdown:
        failures.append("missing_source_link")

    # 长度检查（阈值提高）
    if len(title.strip()) < 8:
        failures.append("title_too_short")
    if len(title.strip()) > 40:
        failures.append("title_too_long")
    if len(markdown.strip()) < 100:
        failures.append("body_too_short")

    # 违禁承诺
    if any(phrase in combined for phrase in BANNED_PROMISES):
        failures.append("overpromise")

    # 高风险话题
    if any(topic in combined for topic in RISKY_TOPICS):
        failures.append("high_risk_advice")

    # 标题党检测
    clickbait_hits = [p for p in CLICKBAIT_PATTERNS if p in title]
    if clickbait_hits:
        failures.append("clickbait_title")

    # 感叹号过多（全角+半角）
    exclaim_count = combined.count("！") + combined.count("!")
    if exclaim_count > 5:
        failures.append("too_many_exclamations")

    # 全角问号过多
    if title.count("？") > 2:
        failures.append("too_many_question_marks")

    return QualityResult(passed=not failures, failures=failures)
