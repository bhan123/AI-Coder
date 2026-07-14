from ai_content_loop.evidence import build_evidence_pack
from ai_content_loop.quality import evaluate_draft
from ai_content_loop.templates import build_master_brief, build_platform_skeletons, choose_column


def make_pack():
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
    pack = make_pack()
    skeletons = build_platform_skeletons(pack)
    brief = build_master_brief(pack)

    assert choose_column(pack) == "开源项目淘金"
    assert "普通读者" in brief
    assert set(skeletons) == {"wechat", "xiaohongshu", "toutiao", "zhihu"}
    assert "适合 1200–2200 字" in skeletons["wechat"]
    assert "只讲两个证据最充分的场景" in skeletons["wechat"]
    assert "信息覆盖清单，不是固定结构" in brief
    assert "顺序自定" in skeletons["wechat"]
    assert "场景一 → 场景二" not in brief
    assert "场景一 → 场景二" not in skeletons["wechat"]
    assert "无论你是" not in skeletons["wechat"]


def test_quality_gate_rejects_missing_source_link():
    result = evaluate_draft(
        title="这个 AI 工具有点离谱",
        markdown="它很好用，但是没有链接。",
        source_url="https://github.com/owner/repo",
    )

    assert result.passed is False
    assert "missing_source_link" in result.failures


def test_quality_gate_accepts_grounded_draft():
    result = evaluate_draft(
        title="这个 AI 工具有点离谱，但别先急着吹",
        markdown=(
            "它能辅助截图和内容草稿，帮创作者快速生成初稿素材，"
            "上手门槛很低，完全不用学编程就能开始用。"
            "\n\n实际用下来能在三十秒左右出结果，效果远超预期。"
            "\n\n来源：https://github.com/owner/repo"
        ),
        source_url="https://github.com/owner/repo",
    )

    assert result.passed is True
    assert result.failures == []
