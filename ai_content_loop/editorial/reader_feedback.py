from __future__ import annotations

import re
from typing import Any


_SOURCE_LINE = re.compile(r"^(?:来源|source)\s*[:：]", re.IGNORECASE)
_HEADING_LINE = re.compile(r"^\s*#{1,6}\s+")
_ASSET_LINE = re.compile(r"^\s*\{\{asset:[^}]+\}\}\s*$")
_DIGIT = re.compile(r"\d")
_DECISION_RULE = re.compile(
    r"不是.{0,24}而是|先.{0,32}(?:再|然后)|如果.{0,36}(?:就|不要|别)|"
    r"真正|关键|成本|代价|边界|风险|别急|不要"
)

_GENERIC_OPENINGS = (
    "最近有个变化值得普通读者看一眼",
    "某公司发布了一项新研究",
    "AI 又有新进展",
    "随着人工智能",
    "在这个数字化时代",
)
_WEAK_ENDINGS = (
    "值得关注",
    "值得持续观察",
    "总的来说",
    "综上所述",
    "下一步很具体",
    "我的判断（个人观点）",
    "作者判断（个人观点）",
)
_JARGON = (
    "benchmark",
    "embedding",
    "rag",
    "agent",
    "api",
    "token",
    "prompt",
    "参数",
    "模型",
    "推理",
    "训练",
    "框架",
    "扩散模型",
    "多智能体",
    "工作流",
    "数据流",
)
_EXPLANATION_MARKERS = ("简单说", "换句话说", "也就是说", "相当于", "可以理解为")
_SCENE_MARKERS = (
    "你",
    "手里",
    "上午",
    "下午",
    "晚上",
    "凌晨",
    "上班",
    "下班",
    "客户",
    "老板",
    "团队",
    "日常",
    "一个人",
)
_VIVID_MARKERS = (
    "像",
    "仿佛",
    "泼冷水",
    "背景墙",
    "翻车",
    "没崩",
    "死在",
    "眼睛",
    "菜谱",
    "搬运",
    "剪到凌晨",
    "挪到了",
)
_CONVERSATIONAL_MARKERS = (
    "听起来",
    "别急",
    "说白了",
    "换句话说",
    "麻烦在",
    "想一想",
    "别",
)
_CONTRAST_MARKERS = ("但", "却", "反而", "不是", "而是", "究竟", "还是")
_ACTION_MARKERS = (
    "先",
    "再",
    "打开",
    "验证",
    "测试",
    "试用",
    "比较",
    "检查",
    "选择",
    "别",
    "不要",
)
_TRADEOFF_MARKERS = (
    "成本",
    "代价",
    "限制",
    "风险",
    "边界",
    "返工",
    "换成",
    "转移",
    "仍然需要",
    "不能",
)
_APPLICATION_MARKERS = (
    "工作",
    "业务",
    "团队",
    "客户",
    "流程",
    "任务",
    "人工时间",
    "接口支出",
    "部署",
    "上线",
)


def _score(value: float) -> float:
    return max(0.0, min(5.0, round(value * 2) / 2))


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _paragraphs(markdown: str) -> list[str]:
    paragraphs: list[str] = []
    for chunk in re.split(r"\n\s*\n", markdown):
        lines = [line for line in chunk.splitlines() if not _ASSET_LINE.fullmatch(line)]
        if lines and _HEADING_LINE.match(lines[0]):
            lines = lines[1:]
        text = "\n".join(lines).strip()
        if not text or _SOURCE_LINE.match(text):
            continue
        paragraphs.append(text)
    return paragraphs


def _dimension(
    key: str,
    label: str,
    score: float,
    evidence: str,
    suggestion: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": _score(score),
        "evidence": evidence,
        "suggestion": suggestion,
    }


def _hook_feedback(title: str, opening: str) -> dict[str, Any]:
    generic = next((item for item in _GENERIC_OPENINGS if item in opening), "")
    signals: list[str] = []
    score = 1.0
    if 8 <= len(title.strip()) <= 40:
        score += 0.5
        signals.append("标题长度合适")
    if 40 <= len(opening) <= 180:
        score += 0.5
        signals.append("首段长度合适")
    if _DIGIT.search(f"{title}{opening}"):
        score += 0.75
        signals.append("有具体数字")
    if _contains_any(opening, _SCENE_MARKERS):
        score += 1.0
        signals.append("有读者场景")
    if _contains_any(opening, _CONTRAST_MARKERS) or "？" in opening or "?" in opening:
        score += 0.75
        signals.append("有冲突或问题")
    if not generic:
        score += 0.5
    else:
        score -= 1.0
    evidence = (
        f"首段 {len(opening)} 字；" + ("、".join(signals) if signals else "缺少明确钩子")
    )
    if generic:
        evidence += f"；命中空泛开场“{generic}”"
    suggestion = (
        "保留当前开场，让前 100 字继续兑现标题承诺。"
        if _score(score) >= 4
        else "第一句先给画面、异常结果或现实损失，再补项目名和背景。"
    )
    return _dimension("hook", "虎头吸引力", score, evidence, suggestion)


def _comprehension_feedback(paragraphs: list[str], body: str) -> dict[str, Any]:
    lengths = [len(re.sub(r"\s+", "", item)) for item in paragraphs]
    if not lengths:
        return _dimension(
            "comprehension",
            "轻松理解",
            0.0,
            "没有可评分的正文段落。",
            "至少写出三个承担不同作用的正文段落。",
        )
    average = round(sum(lengths) / len(lengths))
    longest = max(lengths)
    jargon_hits = [item for item in _JARGON if item.casefold() in body.casefold()]
    score = 5.0
    if longest > 260:
        score -= 2.0
    elif longest > 220:
        score -= 1.5
    elif longest > 180:
        score -= 1.0
    if average > 180:
        score -= 1.0
    elif average > 140:
        score -= 0.5
    if len(jargon_hits) >= 8:
        score -= 1.0
    elif len(jargon_hits) >= 4:
        score -= 0.5
    if jargon_hits and _contains_any(body, _EXPLANATION_MARKERS):
        score += 0.5
    if len(paragraphs) < 3 and sum(lengths) > 360:
        score -= 0.5
    evidence = (
        f"{len(paragraphs)} 段，平均 {average} 字，最长段 {longest} 字；"
        f"识别到 {len(jargon_hits)} 个技术词。"
    )
    if longest > 180:
        suggestion = "优先把超过 180 字的段落按“事实—解释—判断”拆开。"
    elif len(jargon_hits) >= 4 and not _contains_any(body, _EXPLANATION_MARKERS):
        suggestion = "连续术语后补一句“简单说”式生活化解释。"
    else:
        suggestion = "段落负担可控；继续保持一段只完成一个表达任务。"
    return _dimension(
        "comprehension",
        "轻松理解",
        score,
        evidence,
        suggestion,
    )


def _emotion_feedback(body: str) -> dict[str, Any]:
    signals: list[str] = []
    score = 1.0
    if _contains_any(body, _SCENE_MARKERS):
        score += 1.0
        signals.append("生活或工作场景")
    if _contains_any(body, _VIVID_MARKERS):
        score += 1.0
        signals.append("画面或比喻")
    if _contains_any(body, _CONVERSATIONAL_MARKERS):
        score += 0.75
        signals.append("朋友式表达")
    if _contains_any(body, _CONTRAST_MARKERS):
        score += 0.75
        signals.append("事实反差")
    if "？" in body or "?" in body:
        score += 0.5
        signals.append("好奇问题")
    evidence = "识别到：" + ("、".join(signals) if signals else "尚无明显情绪触点") + "。"
    suggestion = (
        "情绪触点已经存在，避免继续加梗稀释可信度。"
        if _score(score) >= 4
        else "补一个来自事实的生活画面、反差或“终于少做一步”的被理解感。"
    )
    return _dimension("emotion", "乐趣/情绪价值", score, evidence, suggestion)


def _value_feedback(body: str, ending: str) -> dict[str, Any]:
    signals: list[str] = []
    score = 1.0
    if _contains_any(body, _ACTION_MARKERS):
        score += 1.25
        signals.append("有具体动作")
    if _contains_any(body, _TRADEOFF_MARKERS):
        score += 1.0
        signals.append("交代成本或边界")
    if _DECISION_RULE.search(body):
        score += 1.0
        signals.append("有可迁移判断")
    if _contains_any(body, _APPLICATION_MARKERS):
        score += 0.75
        signals.append("连接个人或业务场景")
    if _contains_any(ending, _ACTION_MARKERS):
        score += 0.5
        signals.append("结尾能指导下一步")
    evidence = "识别到：" + ("、".join(signals) if signals else "尚无明确读者回报") + "。"
    suggestion = (
        "已有可执行或可迁移价值；确保建议与正文事实边界一致。"
        if _score(score) >= 4
        else "明确告诉读者先验证什么、少做哪一步，或判断同类产品时先问什么。"
    )
    return _dimension("value", "提效/商业启发", score, evidence, suggestion)


def _ngrams(text: str, size: int = 3) -> set[str]:
    compact = re.sub(r"[^\w\u4e00-\u9fff]+", "", text.casefold())
    ignored = {"这个", "一个", "可以", "项目", "模型", "工具", "我们", "就是"}
    return {
        compact[index : index + size]
        for index in range(max(0, len(compact) - size + 1))
        if compact[index : index + size] not in ignored
    }


def _ending_feedback(opening: str, ending: str) -> dict[str, Any]:
    weak_hits = [item for item in _WEAK_ENDINGS if item in ending]
    callback_hits = _ngrams(opening) & _ngrams(ending)
    has_rule = _DECISION_RULE.search(ending) is not None
    score = 1.0
    signals: list[str] = []
    if 40 <= len(ending) <= 180:
        score += 0.75
        signals.append("长度利于收束")
    if has_rule:
        score += 1.5
        signals.append("有判断或行动规则")
    if len(callback_hits) >= 2:
        score += 1.0
        signals.append("回扣开头")
    if "？" in ending or "?" in ending:
        score += 0.5
        signals.append("留下具体问题")
    if len(ending) >= 18:
        score += 0.25
    if weak_hits:
        score -= 1.5
    else:
        score += 0.5
    evidence = (
        f"末段 {len(ending)} 字；"
        + ("、".join(signals) if signals else "缺少回扣、反转或判断规则")
    )
    if weak_hits:
        evidence += f"；弱收束词：{'、'.join(weak_hits)}"
    suggestion = (
        "结尾已经形成收束；再检查是否重复前文原句。"
        if _score(score) >= 4
        else "把最强判断留到最后，用回扣开头、决策规则或具体问题完成收束。"
    )
    return _dimension("ending", "豹尾回味", score, evidence, suggestion)


def evaluate_reader_feedback(title: str, markdown: str) -> dict[str, Any]:
    """Return deterministic, explainable reader-experience feedback.

    The feedback is advisory. It is intentionally separate from factual and
    publication gates so that heuristic scores never block an article.
    """

    safe_title = title if isinstance(title, str) else ""
    safe_markdown = markdown if isinstance(markdown, str) else ""
    paragraphs = _paragraphs(safe_markdown)
    opening = paragraphs[0] if paragraphs else ""
    ending = paragraphs[-1] if paragraphs else ""
    body = "\n".join(paragraphs)
    dimensions = [
        _hook_feedback(safe_title, opening),
        _comprehension_feedback(paragraphs, body),
        _emotion_feedback(body),
        _value_feedback(body, ending),
        _ending_feedback(opening, ending),
    ]
    overall = round(sum(item["score"] for item in dimensions) / len(dimensions), 1)
    if overall >= 4.2:
        verdict = "表现出色"
    elif overall >= 3.6:
        verdict = "基本达标"
    elif overall >= 3.0:
        verdict = "需要打磨"
    else:
        verdict = "优先重写"
    priority_dimension = min(dimensions, key=lambda item: item["score"])
    strongest = max(dimensions, key=lambda item: item["score"])
    return {
        "version": "reader-feedback-v1",
        "overall": overall,
        "verdict": verdict,
        "summary": (
            f"最强项是{strongest['label']}；优先改{priority_dimension['label']}。"
        ),
        "priority": {
            "key": priority_dimension["key"],
            "label": priority_dimension["label"],
            "suggestion": priority_dimension["suggestion"],
        },
        "dimensions": dimensions,
    }
