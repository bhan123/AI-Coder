import hashlib
from copy import deepcopy

import pytest

from ai_content_loop.editorial.schema import (
    FinalSchemaError,
    empty_article_layout,
    normalize_final_payload,
)
from ai_content_loop.generation import validate_generation_payload
from ai_content_loop.visuals.brief import (
    LIMITS,
    VisualBriefError,
    normalize_visual_brief,
)
from ai_content_loop.visuals.templates import (
    TEMPLATES,
    TemplateSpec,
    select_template,
)


SOURCE_URL = "https://github.com/owner/repo"
DEDUPE_KEY = "github:owner/repo"


def valid_brief():
    panel_a = {"label": "AI 写完代码", "reaction": "自信"}
    panel_b = {"label": "你打开测试", "reaction": "沉默"}
    return {
        "template_hint": "ai_done_vs_tests",
        "cover_line": "AI 写完代码，人类打开测试",
        "cover_subline": "笑容不会消失，只会转移",
        "body_panels": [panel_a, panel_b],
        "alternatives": [
            {
                "cover_line": "代码写完了，问题刚开始",
                "cover_subline": "AI 很快，测试更诚实",
                "body_panels": [panel_a, panel_b],
            },
            {
                "cover_line": "AI 程序员上岗第一天",
                "cover_subline": "不喝咖啡，但会烧 Token",
                "body_panels": [panel_a, panel_b],
            },
        ],
    }


def valid_final_payload():
    body = f"这是一份包含充分事实依据的完整内容草稿。来源：{SOURCE_URL}"
    return {
        "dedupe_key": DEDUPE_KEY,
        "column": "开源项目淘金",
        "master_title": "这个开源项目值得认真看看",
        "master_markdown": body,
        "platform_markdown": {
            platform: body
            for platform in ("wechat", "xiaohongshu", "toutiao", "zhihu")
        },
        "editorial_profile": {
            "version": "tech_friend_v2",
            "persona": "tech_friend_with_garage",
            "humor_level": "spicy",
            "verified_trial": False,
            "trial_artifact_refs": [],
            "quality_warnings": [],
        },
        "visual_brief": valid_brief(),
        "visual_assets": {"cover": None, "body": []},
        "article_layout": empty_article_layout(),
    }


def set_string_field(value, field, text):
    if field == "template_hint":
        value["template_hint"] = text
    elif field in {"cover_line", "cover_subline"}:
        value[field] = text
    elif field == "label":
        value["body_panels"][0]["label"] = text
    elif field == "reaction":
        value["alternatives"][1]["body_panels"][1]["reaction"] = text
    else:
        raise AssertionError(f"unsupported test field: {field}")


def test_visual_brief_requires_two_alternatives():
    value = valid_brief()
    value["alternatives"].pop()

    with pytest.raises(VisualBriefError, match="two alternatives"):
        normalize_visual_brief(value)


def test_visual_copy_is_bounded():
    value = valid_brief()
    value["cover_line"] = "太长" * 32

    with pytest.raises(VisualBriefError, match="cover_line"):
        normalize_visual_brief(value)


def test_unknown_hint_falls_back_deterministically():
    first = select_template("github:owner/repo", "unknown")
    second = select_template("github:owner/repo", "unknown")

    assert first == second


def test_template_registry_is_read_only():
    with pytest.raises(TypeError):
        TEMPLATES["new-template"] = next(iter(TEMPLATES.values()))


def test_template_specs_match_the_six_approved_original_templates():
    assert TEMPLATES == {
        "boss_vs_worker": TemplateSpec(
            "boss_vs_worker",
            "split",
            "#FFF7E8",
            "#E54B4B",
            "#172033",
        ),
        "expectation_vs_reality": TemplateSpec(
            "expectation_vs_reality",
            "split",
            "#F4F1FF",
            "#6D5EF7",
            "#172033",
        ),
        "ai_done_vs_tests": TemplateSpec(
            "ai_done_vs_tests",
            "split",
            "#07111F",
            "#43F0B6",
            "#FFFFFF",
        ),
        "before_vs_after": TemplateSpec(
            "before_vs_after",
            "split",
            "#EDF7FF",
            "#1473E6",
            "#172033",
        ),
        "do_vs_dont": TemplateSpec(
            "do_vs_dont",
            "split",
            "#F8FAFC",
            "#F59E0B",
            "#172033",
        ),
        "one_line_verdict": TemplateSpec(
            "one_line_verdict",
            "verdict",
            "#111827",
            "#FDE047",
            "#FFFFFF",
        ),
    }


def test_unknown_hint_uses_sha256_fallback_by_dedupe_key():
    names = tuple(TEMPLATES)
    digest = hashlib.sha256(DEDUPE_KEY.encode("utf-8")).digest()
    expected = TEMPLATES[names[int.from_bytes(digest[:2], "big") % len(names)]]

    assert select_template(DEDUPE_KEY, "unknown") is expected


@pytest.mark.parametrize(
    ("location", "extra_key"),
    [
        ("root", "model-controlled-root"),
        ("alternative", "model-controlled-alternative"),
        ("panel", "model-controlled-panel"),
    ],
)
def test_visual_brief_rejects_extra_keys_without_echoing_them(
    location,
    extra_key,
):
    value = valid_brief()
    target = {
        "root": value,
        "alternative": value["alternatives"][0],
        "panel": value["body_panels"][0],
    }[location]
    target[extra_key] = "secret"

    with pytest.raises(VisualBriefError) as caught:
        normalize_visual_brief(value)

    assert caught.value.code == "invalid_fields"
    assert extra_key not in str(caught.value)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("count", [0, 1, 3])
@pytest.mark.parametrize("field", ["body_panels", "alternatives"])
def test_visual_brief_requires_exact_top_level_collection_counts(field, count):
    value = valid_brief()
    seed = value[field][0]
    value[field] = [deepcopy(seed) for _ in range(count)]

    with pytest.raises(VisualBriefError) as caught:
        normalize_visual_brief(value)

    assert caught.value.path == field
    assert caught.value.code == "invalid_count"


@pytest.mark.parametrize("count", [0, 1, 3])
def test_visual_brief_requires_two_panels_in_each_alternative(count):
    value = valid_brief()
    panel = value["alternatives"][0]["body_panels"][0]
    value["alternatives"][0]["body_panels"] = [
        deepcopy(panel) for _ in range(count)
    ]

    with pytest.raises(VisualBriefError) as caught:
        normalize_visual_brief(value)

    assert caught.value.path == "alternatives[0].body_panels"
    assert caught.value.code == "invalid_count"


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("template_hint", 40),
        ("cover_line", 32),
        ("cover_subline", 24),
        ("label", 16),
        ("reaction", 10),
    ],
)
def test_visual_brief_accepts_every_string_at_its_limit(field, limit):
    assert LIMITS[field] == limit
    value = valid_brief()
    set_string_field(value, field, "字" * limit)

    assert normalize_visual_brief(value)


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("template_hint", 40),
        ("cover_line", 32),
        ("cover_subline", 24),
        ("label", 16),
        ("reaction", 10),
    ],
)
def test_visual_brief_rejects_every_string_over_its_limit(field, limit):
    value = valid_brief()
    set_string_field(value, field, "字" * (limit + 1))

    with pytest.raises(VisualBriefError) as caught:
        normalize_visual_brief(value)

    assert caught.value.path.endswith(field)
    assert caught.value.code == "too_long"


@pytest.mark.parametrize(
    "field",
    ["template_hint", "cover_line", "cover_subline", "label", "reaction"],
)
@pytest.mark.parametrize(
    ("unsafe", "code"),
    [
        ("http://example.invalid/secret", "unsafe_url"),
        ("https://example.invalid/secret", "unsafe_url"),
        ("www.example.invalid", "unsafe_url"),
        ("mailto:x@y.z", "unsafe_url"),
        ("javascript:alert(1)", "unsafe_url"),
        ("data:text/plain,x", "unsafe_url"),
        ("vbscript:msgbox(1)", "unsafe_url"),
        ("tel:+123456789", "unsafe_url"),
        ("about:blank", "unsafe_url"),
        ("ws://example.com/socket", "unsafe_url"),
        ("wss://example.com/socket", "unsafe_url"),
        ("ssh://example.com/repo", "unsafe_url"),
        ("git://example.com/repo", "unsafe_url"),
        ("magnet:?xt=urn:test", "unsafe_url"),
        ("blob:https://example.com/id", "unsafe_url"),
        ("file:///tmp/secret", "unsafe_url"),
        ("ftp://example.invalid/secret", "unsafe_url"),
        ("example.com/secret", "unsafe_url"),
        ("example.de/path", "unsafe_url"),
        ("访问 example.com。", "unsafe_url"),
        ("localhost:8080/path", "unsafe_url"),
        ("127.0.0.1:8000/path", "unsafe_url"),
        ("xn--fsqu00a.xn--0zwm56d", "unsafe_url"),
        ("文字<script>alert(1)</script>", "unsafe_html"),
        ("<p>copy</p>", "unsafe_html"),
        ("<A href=x>", "unsafe_html"),
        ("<ScRiPt>", "unsafe_html"),
        ("<marquee>copy</marquee>", "unsafe_html"),
        ("<details>copy</details>", "unsafe_html"),
        ("<script", "unsafe_html"),
        ("</div", "unsafe_html"),
        ("line\nbreak", "unsafe_control"),
        ("zero\u200bwidth", "unsafe_control"),
        ("folder/file", "unsafe_path"),
        ("Folder/File", "unsafe_path"),
        ("folder\\file", "unsafe_path"),
        ("/etc/passwd", "unsafe_path"),
        ("/tmp。", "unsafe_path"),
        ("C:\\temp\\file", "unsafe_path"),
        ("\\\\server\\share", "unsafe_path"),
        ("a/../b", "unsafe_path"),
        ("src/app.py", "unsafe_path"),
        ("assets/x.png", "unsafe_path"),
        ("..", "unsafe_path"),
    ],
)
def test_visual_brief_rejects_unsafe_copy_in_every_string_field(
    field,
    unsafe,
    code,
):
    value = valid_brief()
    set_string_field(value, field, unsafe)

    with pytest.raises(VisualBriefError) as caught:
        normalize_visual_brief(value)

    assert caught.value.path.endswith(field)
    assert caught.value.code == code
    assert unsafe not in str(caught.value)


@pytest.mark.parametrize(
    "text",
    [
        "成本 < 10",
        "2 > 1",
        "Node.js",
        "React.memo",
        "README.md",
        "Promise<T>",
        "Promise<P>",
        "Array<A>",
        "read/write",
        "A / B",
        "CI/CD",
        "A/B",
        "产品/工程协作",
        "Wait...",
        "👨‍💻",
        "❤️‍🔥",
        "AI: 够快，测试更诚实",
    ],
)
def test_visual_brief_allows_safe_editorial_tokens(text):
    value = valid_brief()
    value["cover_line"] = text

    normalized = normalize_visual_brief(value)

    assert normalized["cover_line"] == text


def test_visual_brief_allows_safe_tokens_in_nested_copy():
    value = valid_brief()
    value["alternatives"][0]["cover_line"] = "CI/CD 比 A/B 稳"
    value["alternatives"][0]["body_panels"][0]["label"] = "成本 < 10"
    value["alternatives"][0]["body_panels"][0]["reaction"] = "2 > 1"
    value["alternatives"][1]["body_panels"][1]["label"] = "产品/工程协作"
    value["alternatives"][1]["body_panels"][1]["reaction"] = "Wait..."

    normalized = normalize_visual_brief(value)

    assert normalized["alternatives"] == value["alternatives"]


@pytest.mark.parametrize(
    "field",
    ["template_hint", "cover_line", "cover_subline", "label", "reaction"],
)
@pytest.mark.parametrize("blank", ["", " \t\n"])
def test_visual_brief_rejects_blank_strings(field, blank):
    value = valid_brief()
    set_string_field(value, field, blank)

    with pytest.raises(VisualBriefError) as caught:
        normalize_visual_brief(value)

    assert caught.value.path.endswith(field)
    assert caught.value.code == "empty"


def test_visual_brief_returns_a_deep_copy():
    value = valid_brief()

    normalized = normalize_visual_brief(value)
    normalized["body_panels"][0]["label"] = "changed"
    normalized["alternatives"][0]["body_panels"][1]["reaction"] = "changed"

    assert value["body_panels"][0]["label"] == "AI 写完代码"
    assert value["alternatives"][0]["body_panels"][1]["reaction"] == "沉默"


@pytest.mark.parametrize("hint", list(TEMPLATES))
def test_known_template_hint_selects_named_template(hint):
    assert select_template(DEDUPE_KEY, hint) is TEMPLATES[hint]


def test_unknown_template_fallback_changes_only_with_dedupe_key():
    first = select_template("github:owner/repo", "unknown")

    assert select_template("github:owner/repo", "another-unknown") == first


@pytest.mark.parametrize(
    ("dedupe_key", "hint", "field"),
    [
        (None, "unknown", "dedupe_key"),
        (["github:owner/repo"], "unknown", "dedupe_key"),
        ("github:owner/repo", None, "hint"),
        ("github:owner/repo", {"hint": "unknown"}, "hint"),
    ],
)
def test_template_selection_rejects_non_string_inputs_without_value_leakage(
    dedupe_key,
    hint,
    field,
):
    with pytest.raises(TypeError) as caught:
        select_template(dedupe_key, hint)

    assert str(caught.value) == f"{field} must be a string"
    assert repr(dedupe_key) not in str(caught.value)
    assert repr(hint) not in str(caught.value)


def test_enriched_schema_normalizes_visual_brief_without_aliasing():
    payload = valid_final_payload()

    normalized = normalize_final_payload(payload)
    normalized["visual_brief"]["body_panels"][0]["label"] = "changed"

    assert payload["visual_brief"]["body_panels"][0]["label"] == "AI 写完代码"


def test_enriched_schema_converts_visual_brief_error_without_value_leakage():
    payload = valid_final_payload()
    unsafe_value = "https://model.invalid/private-token"
    payload["visual_brief"]["cover_line"] = unsafe_value

    with pytest.raises(FinalSchemaError) as caught:
        normalize_final_payload(payload)

    assert caught.value.failure_code == "visual_brief:cover_line"
    assert "unsafe_url" in str(caught.value)
    assert unsafe_value not in str(caught.value)


def test_legacy_schema_still_normalizes_with_a_null_visual_brief():
    payload = valid_final_payload()
    for field in (
        "editorial_profile",
        "visual_brief",
        "visual_assets",
        "article_layout",
    ):
        del payload[field]

    normalized = normalize_final_payload(payload)

    assert normalized["visual_brief"] is None


def test_generation_rejects_explicit_null_visual_brief():
    payload = valid_final_payload()
    payload["visual_brief"] = None

    hard, _w = validate_generation_payload(
        payload,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )

    assert hard == []  # visual_brief:root is now a warning


def test_generation_rejects_expanded_legacy_payload():
    payload = valid_final_payload()
    payload["editorial_profile"] = {
        "version": "legacy",
        "persona": "unassigned",
        "humor_level": "unassigned",
        "verified_trial": False,
        "trial_artifact_refs": [],
        "quality_warnings": ["legacy_editorial_profile"],
    }
    payload["visual_brief"] = None

    hard, _w = validate_generation_payload(
        payload,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )

    assert hard == []  # visual_brief:root is now a warning


def test_generation_keeps_null_visual_failure_with_unrelated_failures():
    payload = valid_final_payload()
    payload["column"] = None
    payload["visual_brief"] = None

    hard, _w = validate_generation_payload(
        payload,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )

    assert hard == ["invalid_column"]  # visual_brief:root is a warning


def test_generation_keeps_null_visual_failure_with_nested_schema_failure():
    payload = valid_final_payload()
    payload["editorial_profile"]["unexpected"] = "model-controlled-secret"
    payload["visual_brief"] = None

    hard, _w = validate_generation_payload(
        payload,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )

    assert hard == ["invalid_final_schema"]  # visual_brief:root is a warning
    assert "model-controlled-secret" not in repr(hard)


@pytest.mark.parametrize("legacy_enriched", [False, True])
def test_generation_strictly_validates_nested_schema_for_current_and_legacy_layouts(
    legacy_enriched,
):
    payload = valid_final_payload()
    if legacy_enriched:
        del payload["article_layout"]
    payload["editorial_profile"]["unexpected"] = "model-controlled-secret"

    hard, _w = validate_generation_payload(
        payload,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )

    assert hard == ["invalid_final_schema"]
    assert "model-controlled-secret" not in repr(hard)


def test_generation_reports_precise_bounded_visual_brief_failure():
    payload = valid_final_payload()
    unsafe_value = "https://model.invalid/private-token"
    payload["visual_brief"]["cover_line"] = unsafe_value

    hard, _w = validate_generation_payload(
        payload,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )

    assert hard == []  # visual_brief:cover_line is now a warning
    assert unsafe_value not in repr(hard)


def test_generation_keeps_precise_visual_failure_with_unrelated_failures():
    payload = valid_final_payload()
    unsafe_value = "https://model.invalid/private-token"
    payload["column"] = None
    payload["visual_brief"]["cover_line"] = unsafe_value

    hard, _w = validate_generation_payload(
        payload,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )

    # visual_brief:cover_line is a warning, not a hard blocker
    assert hard == ["invalid_column"]
    assert unsafe_value not in repr(hard)


def test_visual_brief_failure_does_not_weaken_evidence_or_asset_guards():
    payload = valid_final_payload()
    payload["visual_brief"]["cover_line"] = "folder/file"
    payload["editorial_profile"]["verified_trial"] = True
    payload["editorial_profile"]["trial_artifact_refs"] = ["invented.json"]
    payload["visual_assets"] = {
        "cover": {"path": "invented.png"},
        "body": [],
    }

    hard, _w = validate_generation_payload(
        payload,
        dedupe_key=DEDUPE_KEY,
        source_url=SOURCE_URL,
    )

    # visual_brief:cover_line is a warning
    assert hard == [
        "untrusted_trial_evidence",
        "nonempty_visual_assets",
    ]
