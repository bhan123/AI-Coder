from __future__ import annotations

from dataclasses import dataclass


# 禁用 AI 套话
AI_CLICHES = (
    "在这个数字化时代",
    "赋能",
    "值得一提的是",
    "总的来说",
    "随着人工智能技术的不断发展",
    "在当今时代",
    "众所周知",
    "不可否认",
)

# 禁用受众点名
AUDIENCE_ROLL_CALLS = (
    "无论你是学生",
    "学生、职场人、创作者",
    "职场人、学生、创作者",
    "不管你是",
    "无论你是做什么的",
)

# 需要验证才能使用的第一人称
FIRST_PERSON_TRIALS = (
    "我试了一下",
    "我实际使用",
    "实测下来",
    "我跑了一遍",
    "我亲自测试",
    "我上手用了",
    "我体验了",
)

# 廉价标题党
CHEAP_CLICKBAIT = ("震惊", "彻底颠覆", "人人都能月入过万", "疯了", "炸裂")

# 过度承诺
OVER_PROMISE = (
    "月入",
    "躺赚",
    "稳赚",
    "保证收入",
    "轻松赚钱",
    "日入",
    "年入百万",
)

# 小红书禁止内容
XIAOHONGSHU_BANNED = (
    "微信号",
    "二维码",
    "加微信",
    "扫码",
)


@dataclass(frozen=True)
class EditorialQualityResult:
    passed: bool
    failures: list[str]


def evaluate_editorial_voice(
    title: str,
    wechat_markdown: str,
    profile: dict[str, object],
) -> EditorialQualityResult:
    """编辑器质量门禁——检查语调、套话、格式等问题。"""
    combined = f"{title}\n{wechat_markdown}"
    failures: list[str] = []

    # AI 套话检测
    cliche_hits = [item for item in AI_CLICHES if item in combined]
    if cliche_hits:
        failures.append("ai_cliche")

    # 受众点名检测
    roll_call_hits = [item for item in AUDIENCE_ROLL_CALLS if item in combined]
    if roll_call_hits:
        failures.append("audience_roll_call")

    # 第一人称实测需验证
    verified = profile.get("verified_trial") is True
    refs = profile.get("trial_artifact_refs")
    trial_hits = [item for item in FIRST_PERSON_TRIALS if item in combined]
    if trial_hits and not (verified and isinstance(refs, list) and refs):
        failures.append("unverified_first_person_trial")

    # 廉价标题党
    clickbait_hits = [item for item in CHEAP_CLICKBAIT if item in title]
    if clickbait_hits:
        failures.append("cheap_clickbait")

    # 过度承诺
    over_promise_hits = [item for item in OVER_PROMISE if item in combined]
    if over_promise_hits:
        failures.append("over_promise")

    # 感叹号过多
    exclaim_count = combined.count("！") + combined.count("!")
    if exclaim_count > 3:
        failures.append("too_many_exclamations")

    # 标题过短或过长
    stripped_title = title.strip()
    if len(stripped_title) < 8:
        failures.append("title_too_short")
    if len(stripped_title) > 40:
        failures.append("title_too_long")

    # 正文过短
    if len(wechat_markdown.strip()) < 100:
        failures.append("body_too_short")

    # 缺少段落分隔（说明可能没有结构）
    if wechat_markdown.count("\n\n") < 2:
        failures.append("body_no_paragraphs")

    # 小红书平台合规检查（针对 xiaohongshu 平台内容）
    xhs_banned = [item for item in XIAOHONGSHU_BANNED if item in combined]
    if xhs_banned:
        failures.append("xiaohongshu_compliance")

    return EditorialQualityResult(not failures, failures)
