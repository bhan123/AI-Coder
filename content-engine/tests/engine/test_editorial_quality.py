from engine.editorial.quality import evaluate_editorial_voice


def profile(*, verified=False):
    return {
        "version": "tech_friend_v2",
        "persona": "tech_friend_with_garage",
        "humor_level": "spicy",
        "verified_trial": verified,
        "trial_artifact_refs": ["trial/run-1.json"] if verified else [],
        "quality_warnings": [],
    }


def test_flags_ai_cliches_and_audience_roll_call():
    text = (
        "在这个数字化时代，值得一提的是，这个工具可以赋能每个人。"
        "无论你是学生、职场人、创作者还是老板，都值得使用。"
    )
    result = evaluate_editorial_voice("这个工具值得关注吗", text, profile())
    assert result.failures == [
        "ai_cliche",
        "audience_roll_call",
        "body_too_short",
        "body_no_paragraphs",
    ]


def test_rejects_unverified_first_person_trial():
    result = evaluate_editorial_voice(
        "这个工具到底能不能干活",
        "我试了一下，实际使用后发现它很快。",
        profile(verified=False),
    )
    assert "unverified_first_person_trial" in result.failures


def test_allows_trial_language_with_artifact():
    result = evaluate_editorial_voice(
        "这个工具到底能不能干活",
        "我试了一下，实际使用后发现它很快。",
        profile(verified=True),
    )
    # Body is too short/has no paragraphs, so overall not passed,
    # but unverified_first_person_trial must NOT be raised (verified=True)
    assert "unverified_first_person_trial" not in result.failures
    assert not result.passed


def test_flags_cheap_clickbait_in_title_and_excess_exclamations_in_order():
    result = evaluate_editorial_voice(
        "震惊！这个工具彻底颠覆工作方式",
        "先看事实！！！",
        profile(),
    )

    assert result.failures == [
        "cheap_clickbait",
        "too_many_exclamations",
        "body_too_short",
        "body_no_paragraphs",
    ]
