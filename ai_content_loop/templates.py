from __future__ import annotations

from ai_content_loop.models import EvidencePack


PLATFORMS = ("wechat", "xiaohongshu", "toutiao", "zhihu")


def choose_column(pack: EvidencePack, *, llm_column: str = "") -> str:
    """基于关键词的确定性栏目分配（供预筛使用，LLM 可覆盖）。"""
    if llm_column and llm_column.strip():
        return llm_column.strip()
    text = f"{pack.title} {pack.summary}".lower()
    source = pack.source.lower()

    # 论文 → 趋势
    if "arxiv" in source:
        return "普通人也看得懂的 AI 趋势"
    if "paper" in text or "论文" in text or "研究" in text:
        return "普通人也看得懂的 AI 趋势"

    # 开源项目
    if "github" in source and ("repo" in text or "开源" in text or "代码" in text):
        return "开源项目淘金"
    if "github" in source:
        return "开源项目淘金"

    # 商业/副业
    if any(w in text for w in ("business", "sales", "customer", "营销", "获客", "副业",
                                  "赚钱", "变现", "产品", "startup")):
        return "AI 副业/生意灵感"

    return "AI 神器发现"


def build_master_brief(pack: EvidencePack, *, llm_angle: str = "") -> str:
    """构建按栏目差异化的写作简报。"""
    column = choose_column(pack)
    facts = "\n".join(f"- {fact}" for fact in pack.facts)
    risks = "\n".join(f"- {risk}" for risk in pack.risks)
    angles = "\n".join(f"- {angle}" for angle in pack.writing_angles)

    column_guide = _column_specific_guide(column, pack.title)
    llm_angle_block = ""
    if llm_angle and llm_angle.strip():
        llm_angle_block = (
            "## LLM 推荐写作角度\n\n"
            f"{llm_angle.strip()}\n\n"
        )

    return f"""# 写作简报：{pack.title}

栏目：{column}
来源：{pack.source}
链接：{pack.url}
评分：{pack.score_total}
评分理由：{pack.score_reason}

## 一句话任务

写一篇好懂、有趣、重点前置的 AI 内容，让泛读者先看懂，再让高频受益人群看到用法。

{llm_angle_block}## 栏目写作指南

{column_guide}

## 证据

{facts}

## 可写角度

{angles}

## 风险

{risks}

## 信息覆盖清单，不是固定结构

- 前 100 字给出结果、反差、边界或工作流变化，并接住标题。
- 用人话解释它是什么；参数只作为证据，不作为开头。
- 选择 1-2 个证据最充分的场景写透，不凑功能清单。
- 回答一个核心价值：提效、商业可能、学习或情绪价值。
- 给出基于证据的作者判断，并说明事实边界。
- 写清具体限制和一个可执行的下一步。
- 保留来源链接。

以上是必须覆盖的信息，不规定出现顺序，也不要使用固定的“场景一/场景二”小标题。
"""


def _column_specific_guide(column: str, title: str) -> str:
    """每个栏目的差异化写作指南。"""
    guides = {
        "AI 神器发现": f"""- 核心问题："这个工具能帮我做什么？"
- 必答：免费吗？上手门槛多高？比现在用的好在哪？
- 找最吸引人的一个功能深入写，不要列功能清单
- 语气：朋友安利好物，"你可以试试这个" """,
        "开源项目淘金": f"""- 核心问题："为什么这个项目值得关注？"
- 必答：解决了什么痛点？比现有方案好在哪？部署难度如何？
- 不要只写技术参数，写"这个项目如果做成产品会是什么样"
- 语气：技术买手，"这个项目值得关注因为..." """,
        "AI 副业/生意灵感": f"""- 核心问题："这个模式我能复制吗？"
- 必答：目标用户是谁？怎么赚钱？投入多少？风险在哪？
- 必须有风险提示，不能画饼
- 语气：务实分析，"如果你有 X 技能，可以考虑 Y，但注意 Z" """,
        "普通人也看得懂的 AI 趋势": f"""- 核心问题："这跟我有什么关系？"
- 必答：为什么发生？对普通人意味着什么？3 个月后会怎样？
- 不高谈阔论，不写技术原理，写影响和变化
- 语气：趋势解释者，"这件事值得关注因为..." """,
    }
    return guides.get(column, guides["AI 神器发现"])


def build_platform_skeletons(pack: EvidencePack, *, llm_column: str = "") -> dict[str, str]:
    """构建各平台差异化起始骨架。"""
    column = choose_column(pack, llm_column=llm_column)
    return {
        "wechat": (
            f"# {pack.title}\n\n栏目：{column}\n\n"
            f"适合 1200–2200 字，只讲两个证据最充分的场景，写清流程、变化、限制，保留来源链接：{pack.url}\n\n"
            "覆盖要素：标题承接、核心判断、具体场景、差异、限制和下一步；顺序自定，不使用固定场景编号。"
        ),
        "xiaohongshu": (
            f"# {pack.title}\n\n栏目：{column}\n\n"
            "适合 500-900 字，拆成 4-6 张卡片，第一屏直接讲结果和反差。\n"
            "Emoji 点缀但不过度。不要写微信号、二维码、外链描述。\n\n"
            "覆盖亮点、用法、证据和注意事项；顺序自定，避免固定卡片话术。"
        ),
        "toutiao": (
            f"# {pack.title}\n\n栏目：{column}\n\n"
            "适合 1000-1800 字，标题直接，信息密度高，少玩梗。\n"
            "前 50 字决定推荐量，必须最吸引人。\n\n"
            "覆盖核心价值、场景、数据证据和观点；顺序自定，保持信息密度。"
        ),
        "zhihu": (
            f"# {pack.title}\n\n栏目：{column}\n\n"
            "适合 1200-2200 字，用问答口吻解释为什么值得关注。\n"
            "允许适度的个人观点和判断（标注是个人观点）。\n\n"
            "覆盖问题、证据、重要性、用法或判断；顺序自定，论证完整。"
        ),
    }
