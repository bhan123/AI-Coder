import pytest

from engine.evidence import build_evidence_pack
from engine.pack import active_pack
from engine.quality import evaluate_draft
from engine.templates import build_master_brief, build_platform_skeletons, choose_column


GROUNDED_BODY = (
    "它能辅助截图和内容草稿，帮创作者快速生成初稿素材，"
    "上手门槛很低，完全不用学编程就能开始用。"
    "\n\n实际用下来能在三十秒左右出结果，效果远超预期。"
    "\n\n来源：https://github.com/owner/repo"
)

GENERIC_BODY = (
    "这是一段超过基础长度要求的正文，用具体场景说明工具改变了什么，"
    "也解释了它的限制和适用边界，让普通读者能够判断是否值得尝试。"
    "\n\n来源：https://example.com/source"
)


def make_evidence():
    return build_evidence_pack(
        {
            "dedupe_key": "github:owner/repo",
            "source": "github",
            "title": "AI Screenshot Agent",
            "url": "https://github.com/owner/repo",
            "summary": "An AI agent that helps generate screenshots and content drafts.",
            "raw": {"stars": 100},
            "total": 80.0,
            "reason": "clear and useful",
        }
    )


def test_templates_create_brief_and_platform_skeletons():
    evidence = make_evidence()
    pack = active_pack()
    skeletons = build_platform_skeletons(evidence, pack)
    brief = build_master_brief(evidence, pack)

    assert choose_column(evidence, pack) == "开源项目淘金"
    assert set(skeletons) == {"wechat", "xiaohongshu", "toutiao", "zhihu"}
    assert "不少于 600 字，不设上限" in skeletons["wechat"]
    assert all("不设上限" in skeleton for skeleton in skeletons.values())
    assert "只讲两个证据最充分的场景" in skeletons["wechat"]
    assert "信息覆盖清单，不是固定结构" in brief
    assert "顺序自定" in skeletons["wechat"]
    assert "场景一 → 场景二" not in brief
    assert "场景一 → 场景二" not in skeletons["wechat"]
    assert "无论你是" not in skeletons["wechat"]


def test_platform_skeletons_resolve_placeholders():
    """Skeleton placeholders must be substituted, not emitted literally."""
    skeletons = build_platform_skeletons(make_evidence(), active_pack())

    for skeleton in skeletons.values():
        assert "{title}" not in skeleton
        assert "{column}" not in skeleton
        assert "{min_chars}" not in skeleton
    assert "https://github.com/owner/repo" in skeletons["wechat"]


def test_quality_gate_rejects_missing_source_link():
    result = evaluate_draft(
        "这个 AI 工具有点离谱",
        "它很好用，但是没有链接。",
        "https://github.com/owner/repo",
        active_pack(),
    )

    assert result.passed is False
    assert "missing_source_link" in result.failures


def test_quality_gate_accepts_grounded_draft():
    result = evaluate_draft(
        "这个 AI 工具有点离谱，但别先急着吹",
        GROUNDED_BODY,
        "https://github.com/owner/repo",
        active_pack(),
    )

    assert result.passed is True
    assert result.failures == []


@pytest.mark.parametrize(
    "title",
    [
        "ChatGPT Sites 上线：一句话生成小网站",
        "Kimi K3 发布：全面解析这次升级",
        "一文看懂 AI 如何重新定义办公方式",
        "最强 AI 助手来了",
        "这个新模型真正值得关注的地方是什么？",
    ],
)
def test_quality_gate_rejects_synthetic_title_templates(title: str):
    result = evaluate_draft(
        title,
        GENERIC_BODY,
        "https://example.com/source",
        active_pack(),
    )

    assert "synthetic_title" in result.failures


@pytest.mark.parametrize(
    "title",
    [
        "老板把周报交给 AI，十分钟后先后悔了",
        "网站是做出来了，真正费时间的是改第三遍",
        "它省下半小时，也把返工提前到了上午",
    ],
)
def test_quality_gate_allows_specific_spoken_titles(title: str):
    result = evaluate_draft(
        title,
        GENERIC_BODY,
        "https://example.com/source",
        active_pack(),
    )

    assert "synthetic_title" not in result.failures


def test_quality_gate_thresholds_come_from_the_pack():
    """The length gate reads its threshold from the pack, not a constant."""
    pack = active_pack()
    source_url = "https://e.co/s"

    # Sits just under the pack's minimum once the source link is included.
    filler = "短" * (pack.body_min_chars - len(source_url) - 2)
    short_body = f"{filler}\n{source_url}"
    assert len(short_body) < pack.body_min_chars

    result = evaluate_draft(
        "一个足够长的正常标题写法",
        short_body,
        source_url,
        pack,
    )

    assert "body_too_short" in result.failures
