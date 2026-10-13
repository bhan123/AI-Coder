from __future__ import annotations

from engine.models import EvidencePack
from engine.sources.web_content import enrich_source_content


def build_evidence_pack(
    candidate: dict,
    *,
    deep_research: bool = False,
) -> EvidencePack:
    """构建证据包。

    Args:
        candidate: 数据库候选行（含 raw 字段）
        deep_research: 是否抓取源内容补充证据
    """
    source = str(candidate.get("source", ""))
    external_id = str(candidate.get("external_id", ""))
    url = str(candidate.get("url", ""))
    title = str(candidate.get("title", ""))
    summary = str(candidate.get("summary", ""))
    raw = candidate.get("raw", {})
    if not isinstance(raw, dict):
        raw = {}

    # ---- 基础事实 ----
    facts = [
        f"一手来源：{url}",
        f"来源平台：{source}",
        f"标题：{title}",
    ]
    if summary:
        facts.append(f"摘要/描述：{summary}")

    if source == "github":
        stars = raw.get("stars", 0)
        forks = raw.get("forks", 0)
        language = raw.get("language", "")
        topics = raw.get("topics", [])
        if stars:
            facts.append(f"GitHub Stars：{stars}")
        if forks:
            facts.append(f"Forks：{forks}")
        if language:
            facts.append(f"主要语言：{language}")
        if topics:
            facts.append(f"Topics：{', '.join(str(t) for t in topics[:10])}")

    if source == "hackernews":
        score = raw.get("score", 0)
        comments = raw.get("comments", 0)
        if score:
            facts.append(f"HN 得分：{score}")
        if comments:
            facts.append(f"评论数：{comments}")

    if source == "modelscope":
        downloads = raw.get("downloads", 0)
        stars = raw.get("stars", 0)
        if downloads:
            facts.append(f"ModelScope 下载量：{downloads}")
        if stars:
            facts.append(f"ModelScope Stars：{stars}")

    if source == "producthunt":
        votes = raw.get("votes", 0)
        if votes:
            facts.append(f"Product Hunt 投票数：{votes}")

    # ---- 深度研究：抓取源内容 ----
    if deep_research:
        extra = enrich_source_content(source, external_id, url)
        if extra:
            if source == "github":
                label = "GitHub README 摘要"
            elif source == "hackernews":
                label = "Hacker News 热评摘要"
            elif source == "modelscope":
                label = "ModelScope 模型卡摘要"
            elif source == "huggingface":
                label = "HuggingFace 模型卡摘要"
            elif source.startswith("official_rss"):
                label = "原文内容摘要"
            else:
                label = "补充源内容"
            facts.append(
                f"{label}：{extra[:500]}{'…' if len(extra) > 500 else ''}"
            )
        else:
            facts.append("补充源内容：未获取（源平台无额外内容或抓取失败）")

    # ---- 风险 ----
    risks: list[str] = [
        "不要承诺收益或替代人工结果，只描述可能用途。",
        "标题可以有钩子，但正文必须回到证据。",
    ]
    if not summary:
        risks.append("摘要为空，发布前需要人工补充项目实际用途。")
    if not url:
        risks.append("缺少来源链接，事实无法核验。")
    if source == "hackernews":
        risks.append("HN 来源：确认该项目非争议性内容。")
    if source == "producthunt":
        risks.append("Product Hunt 来源：投票可能包含营销水分。")

    # ---- 写作角度（按栏目差异化） ----
    column = candidate.get("column", "")
    writing_angles = _build_writing_angles(column, title)

    return EvidencePack(
        dedupe_key=str(candidate.get("dedupe_key", "")),
        title=title,
        url=url,
        source=source,
        summary=summary,
        score_total=float(candidate.get("total", 0)),
        score_reason=str(candidate.get("reason", "")),
        facts=facts,
        risks=risks,
        writing_angles=writing_angles,
    )


def _build_writing_angles(column: str, title: str) -> list[str]:
    """按栏目生成差异化的写作角度。"""
    angles_by_column = {
        "AI 神器发现": [
            f"普通读者：{title}到底是什么，为什么值得花 5 分钟了解。重点讲「能帮你做什么」和「上手有多简单」。",
            f"职场人/学生/创作者：{title}怎么帮你省时间、提高产出。给出 1 个具体的日常使用场景。",
            f"小老板/个体户：{title}能不能帮你获客、做内容、提效率。讲清楚成本和收益。",
        ],
        "开源项目淘金": [
            f"技术人：这个项目解决了什么痛点，技术路线有什么亮点，和现有方案比有什么优势。",
            f"产品人/创业者：这个开源项目能封装成什么产品，目标用户是谁，商业化方向在哪。",
            f"普通读者：这个项目背后是什么趋势，即使不懂代码也值得知道的 2 个原因。",
        ],
        "AI 副业/生意灵感": [
            f"想试的人：这个模式怎么操作，投入多少（时间+钱），预期产出多少，第一步怎么做。",
            f"在观望的人：已经有人做成了吗，案例和数据是什么，风险在哪里。",
            f"小老板/个体户：这个方向和你的现有业务怎么结合，最低成本验证方法是什么。",
        ],
        "普通人也看得懂的 AI 趋势": [
            f"泛读者：这件事为什么会发生，它对你的工作/生活会有什么影响（即使很间接）。",
            f"关注趋势的人：这件事和 AI 平民化/Agent 化/多模态化趋势怎么关联。",
            f"行动派：知道这件事后，你今天或这周可以做什么。不给空洞建议，给具体行动。",
        ],
    }
    default = [
        "普通读者：这个东西到底有什么用，为什么值得看一眼。",
        "职场/学生/创作者：它能不能节省时间、提高表达或辅助学习。",
        "小老板/个体户：它是否能辅助获客、客服、内容生产或交付。",
    ]
    return angles_by_column.get(column, default)
