import pytest

from ai_content_loop.editorial.schema import (
    FinalSchemaError,
    empty_visual_assets,
    legacy_editorial_profile,
    normalize_final_payload,
)


def legacy_payload():
    body = "正文内容足够长。来源：https://example.com/source"
    return {
        "dedupe_key": "github:owner/repo",
        "column": "开源项目淘金",
        "master_title": "一个值得关注的开源项目",
        "master_markdown": body,
        "platform_markdown": {
            name: body
            for name in ("wechat", "xiaohongshu", "toutiao", "zhihu")
        },
    }


def valid_visual_brief():
    panels = [
        {"label": "AI 写完代码", "reaction": "自信"},
        {"label": "你打开测试", "reaction": "沉默"},
    ]
    return {
        "template_hint": "ai_done_vs_tests",
        "cover_line": "AI 写完代码，人类打开测试",
        "cover_subline": "笑容只会转移",
        "body_panels": panels,
        "alternatives": [
            {
                "cover_line": "代码写完了，问题刚开始",
                "cover_subline": "测试更诚实",
                "body_panels": panels,
            },
            {
                "cover_line": "AI 程序员上岗第一天",
                "cover_subline": "会烧 Token",
                "body_panels": panels,
            },
        ],
    }


def enriched_payload():
    value = legacy_payload()
    value.update(
        {
            "editorial_profile": {
                "version": "tech_friend_v1",
                "persona": "tech_friend",
                "humor_level": "light",
                "verified_trial": False,
                "trial_artifact_refs": [],
                "quality_warnings": [],
            },
            "visual_brief": valid_visual_brief(),
            "visual_assets": {"cover": None, "body": []},
        }
    )
    return value


def test_normalize_legacy_payload_adds_safe_defaults():
    value = normalize_final_payload(legacy_payload())

    assert value["editorial_profile"]["version"] == "legacy"
    assert value["editorial_profile"]["quality_warnings"] == [
        "legacy_editorial_profile"
    ]
    assert value["visual_brief"] is None
    assert value["visual_assets"] == {"cover": None, "body": []}


def test_accepts_explicit_null_visual_brief_in_enriched_payload():
    payload = enriched_payload()
    payload["visual_brief"] = None

    normalized = normalize_final_payload(payload)

    assert normalized["visual_brief"] is None
    assert normalized["visual_assets"] == empty_visual_assets()


def expanded_legacy_payload():
    payload = legacy_payload()
    payload.update(
        {
            "editorial_profile": legacy_editorial_profile(),
            "visual_brief": None,
            "visual_assets": empty_visual_assets(),
        }
    )
    return payload


def test_expanded_legacy_payload_requires_explicit_compatibility_mode():
    payload = expanded_legacy_payload()

    with pytest.raises(FinalSchemaError) as caught:
        normalize_final_payload(payload)

    assert caught.value.failure_code == "visual_brief:root"
    assert normalize_final_payload(
        payload,
        allow_legacy_expanded=True,
    ) == payload


@pytest.mark.parametrize("tampering", ["refs", "assets"])
def test_legacy_compatibility_rejects_untrusted_expanded_markers(tampering):
    payload = expanded_legacy_payload()
    if tampering == "refs":
        payload["editorial_profile"]["trial_artifact_refs"] = [
            "model-controlled-secret"
        ]
    else:
        payload["visual_assets"]["body"] = [
            {"path": "model-controlled-secret"}
        ]

    with pytest.raises(FinalSchemaError) as caught:
        normalize_final_payload(
            payload,
            allow_legacy_expanded=True,
        )

    if tampering == "assets":
        assert caught.value.failure_code == "visual_brief:root"
    assert "model-controlled-secret" not in str(caught.value)


def test_rejects_unknown_top_level_field():
    payload = legacy_payload()
    payload["surprise"] = "model-controlled"

    with pytest.raises(FinalSchemaError, match="final fields"):
        normalize_final_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("column", ""),
        ("master_title", None),
        ("master_markdown", "x" * 200_001),
    ],
    ids=["empty-column", "non-text-title", "oversized-markdown"],
)
def test_rejects_invalid_bounded_text(field, value):
    payload = enriched_payload()
    payload[field] = value

    with pytest.raises(FinalSchemaError, match=field):
        normalize_final_payload(payload)


def test_rejects_platforms_other_than_the_exact_supported_set():
    payload = enriched_payload()
    payload["platform_markdown"]["instagram"] = "model-controlled"

    with pytest.raises(FinalSchemaError, match="platform_markdown"):
        normalize_final_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", False),
        ("verified_trial", "false"),
        ("trial_artifact_refs", "trial/run-1.json"),
        ("quality_warnings", [False]),
    ],
)
def test_rejects_invalid_editorial_profile_types(field, value):
    payload = enriched_payload()
    payload["editorial_profile"][field] = value

    with pytest.raises(FinalSchemaError, match=f"editorial_profile.{field}"):
        normalize_final_payload(payload)


def test_rejects_unknown_editorial_profile_field():
    payload = enriched_payload()
    payload["editorial_profile"]["surprise"] = "model-controlled"

    with pytest.raises(FinalSchemaError, match="editorial_profile fields"):
        normalize_final_payload(payload)


def test_rejects_unknown_visual_asset_field():
    payload = enriched_payload()
    payload["visual_assets"]["surprise"] = "model-controlled"

    with pytest.raises(FinalSchemaError, match="visual_assets fields"):
        normalize_final_payload(payload)


def test_normalization_returns_a_deep_copy():
    payload = enriched_payload()

    value = normalize_final_payload(payload)
    value["editorial_profile"]["quality_warnings"].append("changed")

    assert payload["editorial_profile"]["quality_warnings"] == []
