from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import threading

import pytest
from PIL import Image

from ai_content_loop.editorial import schema
from ai_content_loop.editorial.schema import (
    FinalSchemaError,
    empty_article_layout,
)
from ai_content_loop.visuals.renderer import BODY_SIZE, COVER_SIZE


@pytest.fixture(autouse=True)
def local_test_font(tmp_path: Path) -> None:
    (tmp_path / "font.ttc").write_bytes(b"test-font-v1")


def valid_payload() -> dict[str, object]:
    panels = [
        {"label": "AI writes code", "reaction": "confident"},
        {"label": "Tests run", "reaction": "quiet"},
    ]
    return {
        "dedupe_key": "github:owner/repo",
        "column": "AI discoveries",
        "master_title": "A useful article",
        "master_markdown": "# A useful article\n\nBody",
        "platform_markdown": {
            "wechat": "Opening\n\n来源：https://example.test/source",
            "xiaohongshu": "Xiaohongshu copy",
            "toutiao": "Toutiao copy",
            "zhihu": "Zhihu copy",
        },
        "editorial_profile": {
            "version": "tech_friend_v1",
            "persona": "tech_friend",
            "humor_level": "light",
            "verified_trial": False,
            "trial_artifact_refs": [],
            "quality_warnings": [],
        },
        "visual_brief": {
            "template_hint": "ai_done_vs_tests",
            "cover_line": "AI writes code",
            "cover_subline": "Tests tell truth",
            "body_panels": panels,
            "alternatives": [
                {
                    "cover_line": "Code is only step one",
                    "cover_subline": "Run the tests",
                    "body_panels": panels,
                },
                {
                    "cover_line": "Fast code, honest tests",
                    "cover_subline": "Check the result",
                    "body_panels": panels,
                },
            ],
        },
        "visual_assets": {"cover": None, "body": []},
        "article_layout": empty_article_layout(),
    }


def rendered_payload() -> dict[str, object]:
    payload = valid_payload()
    article_id = schema.article_id_for(payload["dedupe_key"])
    revision = "a" * 64
    base = f"assets/{article_id}/{revision}"
    shared = {
        "revision": revision,
        "template": "ai_done_vs_tests",
        "copy_index": 0,
        "ai_generated": False,
    }
    payload["visual_assets"] = {
        "cover": {
            "asset_id": "cover",
            "path": f"{base}/cover.jpg",
            **shared,
        },
        "body": [
            {
                "asset_id": "body-01",
                "path": f"{base}/body.png",
                **shared,
            }
        ],
    }
    return payload


def fake_renderer(**kwargs) -> None:
    Image.new("RGB", COVER_SIZE, "white").save(
        kwargs["cover_path"],
        format="JPEG",
    )
    Image.new("RGB", BODY_SIZE, "white").save(
        kwargs["body_path"],
        format="PNG",
    )
    secondary = kwargs.get("secondary_body_path")
    if secondary is not None:
        Image.new("RGB", BODY_SIZE, "gray").save(
            secondary,
            format="PNG",
        )


def test_article_id_for_is_stable_opaque_and_secret_safe():
    dedupe_key = "github:owner/repo"

    article_id = schema.article_id_for(dedupe_key)

    assert article_id == hashlib.sha256(
        dedupe_key.encode("utf-8")
    ).hexdigest()[:24]
    assert len(article_id) == 24
    with pytest.raises(ValueError) as caught:
        schema.article_id_for("")
    assert dedupe_key not in str(caught.value)


@pytest.mark.parametrize("invalid", [None, False, 1, "", "   "])
def test_article_id_for_rejects_invalid_input_without_echoing_it(invalid):
    with pytest.raises(ValueError) as caught:
        schema.article_id_for(invalid)
    assert str(caught.value) == "dedupe_key must be a non-empty string"


def test_schema_accepts_exact_rendered_asset_references():
    normalized = schema.normalize_final_payload(rendered_payload())

    assert normalized["visual_assets"] == rendered_payload()["visual_assets"]


def test_schema_accepts_server_generated_hybrid_revision_references():
    payload = rendered_payload()
    payload["visual_assets"]["cover"]["ai_generated"] = True

    normalized = schema.normalize_final_payload(payload)

    assert normalized["visual_assets"]["cover"]["ai_generated"] is True
    assert normalized["visual_assets"]["body"][0]["ai_generated"] is False


def test_schema_accepts_ai_generated_body_reference():
    payload = rendered_payload()
    payload["visual_assets"]["body"][0]["ai_generated"] = True

    normalized = schema.normalize_final_payload(payload)

    assert normalized["visual_assets"]["body"][0]["ai_generated"] is True


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        ("cover", "asset_id", "body-01"),
        ("body", "asset_id", "cover"),
        ("cover", "revision", "A" * 64),
        ("cover", "revision", "a" * 63),
        ("cover", "path", "/assets/opaque/revision/cover.jpg"),
        ("cover", "path", "../assets/opaque/revision/cover.jpg"),
        ("cover", "path", r"assets\opaque\revision\cover.jpg"),
        ("cover", "path", "https://example.test/cover.jpg"),
        ("cover", "template", "model-controlled-template"),
        ("cover", "copy_index", True),
        ("cover", "copy_index", 3),
        ("cover", "ai_generated", "yes"),
    ],
)
def test_schema_rejects_invalid_asset_reference(location, field, value):
    payload = rendered_payload()
    reference = (
        payload["visual_assets"]["cover"]
        if location == "cover"
        else payload["visual_assets"]["body"][0]
    )
    reference[field] = value

    with pytest.raises(FinalSchemaError, match="visual_assets"):
        schema.normalize_final_payload(payload)


def test_schema_rejects_extra_asset_reference_keys_and_partial_render_state():
    extra = rendered_payload()
    extra["visual_assets"]["cover"]["model_value"] = "secret"
    with pytest.raises(FinalSchemaError) as caught:
        schema.normalize_final_payload(extra)
    assert "secret" not in str(caught.value)

    partial = rendered_payload()
    partial["visual_assets"]["body"] = []
    with pytest.raises(FinalSchemaError, match="visual_assets"):
        schema.normalize_final_payload(partial)


def test_insert_body_asset_marker_is_idempotent_and_platform_scoped():
    from ai_content_loop.visuals.pipeline import insert_body_asset_marker

    payload = valid_payload()
    original_other_platforms = {
        name: payload["platform_markdown"][name]
        for name in ("xiaohongshu", "toutiao", "zhihu")
    }

    once = insert_body_asset_marker(payload)
    twice = insert_body_asset_marker(once)

    wechat = twice["platform_markdown"]["wechat"]
    assert wechat.count("{{asset:body-01}}") == 1
    assert wechat.index("{{asset:body-01}}") < wechat.index("来源：")
    assert {
        name: twice["platform_markdown"][name]
        for name in original_other_platforms
    } == original_other_platforms
    assert payload["platform_markdown"]["wechat"].count(
        "{{asset:body-01}}"
    ) == 0


def test_insert_body_asset_marker_falls_back_to_end_and_removes_duplicates():
    from ai_content_loop.visuals.pipeline import insert_body_asset_marker

    payload = valid_payload()
    payload["platform_markdown"]["wechat"] = (
        "Opening\n{{asset:body-01}}\nBody\n{{asset:body-01}}"
    )

    normalized = insert_body_asset_marker(payload)

    assert normalized["platform_markdown"]["wechat"] == (
        "Opening\n{{asset:body-01}}\nBody\n{{asset:body-02}}"
    )


@pytest.mark.parametrize(
    "wechat",
    [
        (
            "Opening\n{{asset:body-01}}\n{{asset:body-02}}\n"
            "来源：https://example.test"
        ),
        "Opening\n{{asset:body-01}}\n{{asset:body-02}}",
    ],
    ids=["before-source", "fallback-at-end"],
)
def test_canonical_body_marker_check_is_nonmutating(wechat):
    from ai_content_loop.visuals.pipeline import (
        has_canonical_body_asset_marker,
    )

    payload = valid_payload()
    payload["platform_markdown"]["wechat"] = wechat
    before = deepcopy(payload)

    assert has_canonical_body_asset_marker(payload) is True
    assert payload == before


def test_canonical_body_marker_keeps_legacy_single_body_article_valid():
    from ai_content_loop.visuals.pipeline import (
        has_canonical_body_asset_marker,
        insert_body_asset_marker,
    )

    payload = rendered_payload()
    payload["platform_markdown"]["wechat"] = "Opening\nBody"
    normalized = insert_body_asset_marker(payload)

    assert normalized["platform_markdown"]["wechat"].count(
        "{{asset:body-01}}"
    ) == 1
    assert "{{asset:body-02}}" not in normalized["platform_markdown"]["wechat"]
    assert has_canonical_body_asset_marker(normalized) is True


def test_generate_visual_assets_publishes_immutable_revisions(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    payload = valid_payload()

    first = pipeline.generate_visual_assets(
        payload=payload,
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )
    second_payload = deepcopy(payload)
    second_payload["visual_brief"]["cover_line"] = "Changed selected copy"
    second = pipeline.generate_visual_assets(
        payload=second_payload,
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )

    first_revision = first["visual_assets"]["cover"]["revision"]
    second_revision = second["visual_assets"]["cover"]["revision"]
    article_id = schema.article_id_for(payload["dedupe_key"])
    assert first_revision != second_revision
    for revision in (first_revision, second_revision):
        revision_dir = tmp_path / "assets" / article_id / revision
        with Image.open(revision_dir / "cover.jpg") as cover:
            assert cover.format == "JPEG"
            assert cover.size == COVER_SIZE
        with Image.open(revision_dir / "body.png") as body:
            assert body.format == "PNG"
            assert body.size == BODY_SIZE
        manifest = json.loads(
            (revision_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["revision"] == revision
        assert manifest["article_id"] == article_id
    assert first["platform_markdown"]["wechat"].count(
        "{{asset:body-01}}"
    ) == 1
    assert payload["visual_assets"] == {"cover": None, "body": []}


def test_generate_visual_assets_uses_minimax_cover_once_and_marks_revision(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    calls = []
    aspect_ratios = []
    rendered_backgrounds = []
    rendered_body_backgrounds = []
    rendered_structures = []

    class FakeImageClient:
        model = "image-01"

        def identity_for_prompt(self, prompt, *, aspect_ratio="21:9"):
            return {
                "provider": "minimax",
                "model": self.model,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "seed": 42,
            }

        def generate(self, prompt, *, aspect_ratio="21:9"):
            calls.append(prompt)
            aspect_ratios.append(aspect_ratio)
            buffer = BytesIO()
            Image.new("RGB", (1344, 576), "navy").save(
                buffer, format="JPEG"
            )
            return buffer.getvalue()

    def renderer(**kwargs):
        rendered_backgrounds.append(kwargs.get("cover_background"))
        rendered_body_backgrounds.append(kwargs.get("body_backgrounds"))
        rendered_structures.append(kwargs.get("illustration_structure"))
        fake_renderer(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", renderer)
    client = FakeImageClient()

    first = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
        image_client=client,
    )
    second = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
        image_client=client,
    )

    assert first == second
    assert len(calls) == 3
    assert len(set(calls)) == 3
    assert aspect_ratios == ["21:9", "16:9", "16:9"]
    assert rendered_backgrounds[0].size == COVER_SIZE
    assert tuple(image.size for image in rendered_body_backgrounds[0]) == (
        BODY_SIZE,
        BODY_SIZE,
    )
    assert rendered_structures == ["hub"]
    reference = first["visual_assets"]["cover"]
    assert reference["ai_generated"] is True
    assert all(
        reference["ai_generated"] is True
        for reference in first["visual_assets"]["body"]
    )
    article_id = schema.article_id_for(first["dedupe_key"])
    manifest = json.loads(
        (
            tmp_path
            / "assets"
            / article_id
            / reference["revision"]
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["version"] == 4
    assert manifest["source_kind"] == "minimax_image_set"
    assert manifest["ai_generated"] is True
    assert manifest["image_source"]["model"] == "image-01"
    from ai_content_loop.visuals.assets import validate_payload_revision

    expected_source = pipeline.expected_image_source(
        payload=first,
        image_client=client,
        copy_index=0,
    )
    validated = validate_payload_revision(
        first,
        tmp_path,
        tmp_path / "font.ttc",
        image_source=expected_source,
    )
    assert validated["image_source"] == manifest["image_source"]
    with pytest.raises(
        pipeline.AssetPublicationError,
        match="asset_source_mismatch",
    ):
        validate_payload_revision(
            first,
            tmp_path,
            tmp_path / "font.ttc",
        )


def test_generate_visual_assets_falls_back_when_minimax_fails(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.minimax_image import MiniMaxImageError

    backgrounds = []

    class FailingImageClient:
        def identity_for_prompt(self, prompt, *, aspect_ratio="21:9"):
            return {
                "provider": "minimax",
                "model": "image-01",
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "seed": 7,
            }

        def generate(self, _prompt, *, aspect_ratio="21:9"):
            raise MiniMaxImageError("image_request_failed")

    def renderer(**kwargs):
        backgrounds.append(kwargs.get("cover_background"))
        fake_renderer(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", renderer)

    rendered = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
        image_client=FailingImageClient(),
    )

    assert backgrounds == [None]
    assert rendered["visual_assets"]["cover"]["ai_generated"] is False
    article_id = schema.article_id_for(rendered["dedupe_key"])
    revision = rendered["visual_assets"]["cover"]["revision"]
    manifest = json.loads(
        (tmp_path / "assets" / article_id / revision / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["version"] == 2
    assert manifest["source_kind"] == "original_template"


def test_generate_visual_assets_falls_back_per_image_without_discarding_successes(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.minimax_image import MiniMaxImageError

    rendered = []

    class PartiallyFailingImageClient:
        model = "image-01"

        def identity_for_prompt(self, prompt, *, aspect_ratio="21:9"):
            digest = hashlib.sha256(prompt.encode()).hexdigest()
            return {
                "provider": "minimax",
                "model": self.model,
                "prompt_sha256": digest,
                "seed": int(digest[:16], 16) & ((1 << 63) - 1),
            }

        def generate(self, prompt, *, aspect_ratio="21:9"):
            if "focuses only on: AI writes code" in prompt:
                raise MiniMaxImageError("image_request_failed")
            buffer = BytesIO()
            Image.new("RGB", (1344, 576), "navy").save(buffer, format="JPEG")
            return buffer.getvalue()

    def renderer(**kwargs):
        rendered.append(kwargs)
        fake_renderer(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", renderer)
    client = PartiallyFailingImageClient()
    result = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
        image_client=client,
    )

    assert result["visual_assets"]["cover"]["ai_generated"] is True
    assert [item["ai_generated"] for item in result["visual_assets"]["body"]] == [
        False,
        True,
    ]
    assert rendered[0]["body_backgrounds"][0] is None
    assert rendered[0]["body_backgrounds"][1].size == BODY_SIZE
    expected_source = pipeline.expected_image_source(
        payload=result,
        image_client=client,
        copy_index=0,
    )
    from ai_content_loop.visuals.assets import validate_payload_revision

    validate_payload_revision(
        result,
        tmp_path,
        tmp_path / "font.ttc",
        image_source=expected_source,
    )


def test_generate_visual_assets_selects_canonical_copy_and_override(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    calls = []

    def capture_renderer(**kwargs):
        calls.append(kwargs)
        fake_renderer(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", capture_renderer)
    payload = valid_payload()

    rendered = pipeline.generate_visual_assets(
        payload=payload,
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
        template_name="one_line_verdict",
        copy_index=1,
    )

    assert calls[0]["brief"]["cover_line"] == (
        payload["visual_brief"]["alternatives"][0]["cover_line"]
    )
    assert calls[0]["template"].name == "one_line_verdict"
    assert rendered["visual_assets"]["cover"]["copy_index"] == 1
    assert rendered["visual_brief"] == payload["visual_brief"]


@pytest.mark.parametrize("copy_index", [False, True, -1, 3, "0", None])
def test_generate_visual_assets_rejects_invalid_copy_index(copy_index):
    from ai_content_loop.visuals.pipeline import generate_visual_assets

    with pytest.raises(ValueError, match="copy_index"):
        generate_visual_assets(
            payload=valid_payload(),
            output_dir=Path("unused-output"),
            font_path=Path("unused-font.ttc"),
            copy_index=copy_index,
        )


@pytest.mark.parametrize(
    "template_name",
    ["unknown", "", False, "../one_line_verdict"],
)
def test_generate_visual_assets_rejects_noncanonical_override(template_name):
    from ai_content_loop.visuals.pipeline import generate_visual_assets

    with pytest.raises(ValueError, match="template"):
        generate_visual_assets(
            payload=valid_payload(),
            output_dir=Path("unused-output"),
            font_path=Path("unused-font.ttc"),
            template_name=template_name,
        )


def test_visual_asset_public_apis_are_keyword_only(tmp_path: Path):
    from ai_content_loop.visuals.pipeline import (
        generate_visual_assets,
        generate_visual_assets_for_file,
    )

    with pytest.raises(TypeError):
        generate_visual_assets(
            valid_payload(),
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )
    with pytest.raises(TypeError):
        generate_visual_assets_for_file(
            tmp_path / "final" / "article.json",
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )


def test_identical_generation_reuses_valid_revision(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    calls = []

    def renderer(**kwargs):
        calls.append(kwargs)
        fake_renderer(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", renderer)
    first = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )
    second = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )

    assert second == first
    assert len(calls) == 1


def test_font_bytes_and_render_contract_change_revision(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    font_path = tmp_path / "font.ttc"
    first = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=font_path,
    )
    font_path.write_bytes(b"test-font-v2")
    second = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=font_path,
    )
    monkeypatch.setattr(
        pipeline,
        "current_render_contract",
        lambda: {
            "renderer_contract_version": "changed-contract",
            "pillow_version": "test",
            "jpeg_version": "test",
            "zlib_version": "test",
        },
        raising=False,
    )
    third = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=font_path,
    )

    revisions = {
        result["visual_assets"]["cover"]["revision"]
        for result in (first, second, third)
    }
    assert len(revisions) == 3
    article_id = schema.article_id_for("github:owner/repo")
    manifest = json.loads(
        (
            tmp_path
            / "assets"
            / article_id
            / second["visual_assets"]["cover"]["revision"]
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["font_sha256"] == hashlib.sha256(
        b"test-font-v2"
    ).hexdigest()
    assert set(manifest["render_contract"]) == {
        "renderer_contract_version",
        "pillow_version",
        "jpeg_version",
        "zlib_version",
    }


def test_identical_selected_copy_reuses_revision_across_copy_indexes(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    calls = []

    def renderer(**kwargs):
        calls.append(kwargs)
        fake_renderer(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", renderer)
    payload = valid_payload()
    payload["visual_brief"]["alternatives"][0] = {
        field: deepcopy(payload["visual_brief"][field])
        for field in ("cover_line", "cover_subline", "body_panels")
    }

    primary = pipeline.generate_visual_assets(
        payload=payload,
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
        copy_index=0,
    )
    alternative = pipeline.generate_visual_assets(
        payload=payload,
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
        copy_index=1,
    )

    assert (
        alternative["visual_assets"]["cover"]["revision"]
        == primary["visual_assets"]["cover"]["revision"]
    )
    assert alternative["visual_assets"]["cover"]["copy_index"] == 1
    assert len(calls) == 1


def test_tampered_existing_revision_is_never_overwritten(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    result = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )
    cover = tmp_path / result["visual_assets"]["cover"]["path"]
    cover.write_bytes(b"tampered")

    with pytest.raises(
        AssetPublicationError, match="existing_revision_mismatch"
    ):
        pipeline.generate_visual_assets(
            payload=valid_payload(),
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )
    assert cover.read_bytes() == b"tampered"


def test_render_failure_leaves_no_published_or_temporary_revision(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    payload = valid_payload()

    def fail_renderer(**kwargs):
        kwargs["cover_path"].write_bytes(b"partial")
        raise pipeline.VisualRenderError("invalid_output")

    monkeypatch.setattr(pipeline, "render_visuals", fail_renderer)
    with pytest.raises(pipeline.VisualRenderError):
        pipeline.generate_visual_assets(
            payload=payload,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    article_root = (
        tmp_path / "assets" / schema.article_id_for(payload["dedupe_key"])
    )
    assert not article_root.exists() or list(article_root.iterdir()) == []


@pytest.mark.parametrize(
    "failure",
    ["corrupt", "wrong-cover-format", "wrong-cover-dimensions"],
)
def test_rendered_assets_require_valid_format_and_dimensions(
    tmp_path: Path, monkeypatch, failure
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    def invalid_renderer(**kwargs):
        if failure == "corrupt":
            kwargs["cover_path"].write_bytes(b"not-an-image")
        elif failure == "wrong-cover-format":
            Image.new("RGB", COVER_SIZE).save(
                kwargs["cover_path"],
                format="PNG",
            )
        else:
            Image.new("RGB", (10, 10)).save(
                kwargs["cover_path"],
                format="JPEG",
            )
        Image.new("RGB", BODY_SIZE).save(
            kwargs["body_path"],
            format="PNG",
        )

    monkeypatch.setattr(pipeline, "render_visuals", invalid_renderer)

    with pytest.raises(
        AssetPublicationError, match="invalid_rendered_asset"
    ):
        pipeline.generate_visual_assets(
            payload=valid_payload(),
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

def test_render_failure_preserves_preexisting_empty_asset_parents(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    payload = valid_payload()
    article_root = (
        tmp_path / "assets" / schema.article_id_for(payload["dedupe_key"])
    )
    article_root.mkdir(parents=True)

    def fail_renderer(**kwargs):
        raise pipeline.VisualRenderError("invalid_output")

    monkeypatch.setattr(pipeline, "render_visuals", fail_renderer)
    with pytest.raises(pipeline.VisualRenderError):
        pipeline.generate_visual_assets(
            payload=payload,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    assert (tmp_path / "assets").is_dir()
    assert article_root.is_dir()
    assert list(article_root.iterdir()) == []


def test_render_failure_preserves_concurrent_sibling_directory(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    payload = valid_payload()
    article_root = (
        tmp_path / "assets" / schema.article_id_for(payload["dedupe_key"])
    )
    sibling = article_root / ".concurrent-worker.tmp"
    sibling.mkdir(parents=True)
    (sibling / "owned.txt").write_text("keep", encoding="utf-8")

    def fail_renderer(**kwargs):
        raise pipeline.VisualRenderError("invalid_output")

    monkeypatch.setattr(pipeline, "render_visuals", fail_renderer)
    with pytest.raises(pipeline.VisualRenderError):
        pipeline.generate_visual_assets(
            payload=payload,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    assert (sibling / "owned.txt").read_text(encoding="utf-8") == "keep"
    assert list(article_root.iterdir()) == [sibling]


@pytest.mark.parametrize("failure_stage", ["manifest", "publication"])
def test_manifest_or_publication_failure_leaves_no_partial_revision(
    tmp_path: Path, monkeypatch, failure_stage
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    payload = valid_payload()
    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    if failure_stage == "manifest":
        monkeypatch.setattr(
            pipeline,
            "atomic_json_write",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                OSError("private manifest detail")
            ),
        )
        expected = OSError
    else:
        monkeypatch.setattr(
            pipeline,
            "publish_revision",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssetPublicationError("revision_publication_failed")
            ),
        )
        expected = AssetPublicationError

    with pytest.raises(expected):
        pipeline.generate_visual_assets(
            payload=payload,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    article_root = (
        tmp_path / "assets" / schema.article_id_for(payload["dedupe_key"])
    )
    assert not article_root.exists() or list(article_root.iterdir()) == []


def test_publication_race_refuses_mismatched_winner_and_cleans_own_temp(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)

    def mismatched_winner(temporary: Path, final: Path) -> None:
        final.mkdir()
        (final / "intruder.txt").write_text("keep", encoding="utf-8")
        raise FileExistsError("simulated Windows rename race")

    monkeypatch.setattr(pipeline, "publish_revision", mismatched_winner)
    payload = valid_payload()

    with pytest.raises(
        AssetPublicationError, match="existing_revision_mismatch"
    ):
        pipeline.generate_visual_assets(
            payload=payload,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    article_root = (
        tmp_path / "assets" / schema.article_id_for(payload["dedupe_key"])
    )
    assert len(list(article_root.iterdir())) == 1
    winner = next(article_root.iterdir())
    assert (winner / "intruder.txt").read_text(encoding="utf-8") == "keep"
    assert not any(path.name.endswith(".tmp") for path in article_root.iterdir())


def test_generate_visual_assets_for_file_preserves_original_on_failure(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    final_dir = tmp_path / "final"
    final_dir.mkdir()
    final_path = final_dir / "article.json"
    original = json.dumps(valid_payload(), ensure_ascii=False).encode("utf-8")
    final_path.write_bytes(original)

    def fail_renderer(**kwargs):
        raise pipeline.VisualRenderError("invalid_output")

    monkeypatch.setattr(pipeline, "render_visuals", fail_renderer)
    with pytest.raises(pipeline.VisualRenderError):
        pipeline.generate_visual_assets_for_file(
            final_path=final_path,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    assert final_path.read_bytes() == original
    article_root = (
        tmp_path / "assets" / schema.article_id_for("github:owner/repo")
    )
    assert not article_root.exists() or list(article_root.iterdir()) == []


@pytest.mark.parametrize("failure_stage", ["manifest", "publication"])
def test_file_wrapper_preserves_json_on_manifest_or_publication_failure(
    tmp_path: Path, monkeypatch, failure_stage
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    final_dir = tmp_path / "final"
    final_dir.mkdir()
    final_path = final_dir / "article.json"
    original = json.dumps(valid_payload(), ensure_ascii=False).encode("utf-8")
    final_path.write_bytes(original)
    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    if failure_stage == "manifest":
        monkeypatch.setattr(
            pipeline,
            "atomic_json_write",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                OSError("private manifest detail")
            ),
        )
        expected = OSError
    else:
        monkeypatch.setattr(
            pipeline,
            "publish_revision",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssetPublicationError("revision_publication_failed")
            ),
        )
        expected = AssetPublicationError

    with pytest.raises(expected):
        pipeline.generate_visual_assets_for_file(
            final_path=final_path,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    assert final_path.read_bytes() == original
    article_root = (
        tmp_path / "assets" / schema.article_id_for("github:owner/repo")
    )
    assert not article_root.exists() or list(article_root.iterdir()) == []


def test_file_wrapper_preserves_json_when_final_atomic_write_fails(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    rendered = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    final_path = final_dir / "article.json"
    original = json.dumps(rendered, ensure_ascii=False).encode("utf-8")
    final_path.write_bytes(original)
    monkeypatch.setattr(
        pipeline,
        "atomic_json_write",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("private final write detail")
        ),
    )

    with pytest.raises(OSError):
        pipeline.generate_visual_assets_for_file(
            final_path=final_path,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    assert final_path.read_bytes() == original


def test_file_wrapper_cas_preserves_concurrent_repository_edit(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.db import ContentStore
    from ai_content_loop.review.repository import ArticleRepository
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    output_dir = tmp_path / "out"
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True)
    final_path = final_dir / "article.json"
    final_path.write_text(
        json.dumps(valid_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    repository_a = ArticleRepository(
        store=store,
        final_dir=final_dir,
        history_dir=output_dir / "history",
    )
    repository_b = ArticleRepository(
        store=store,
        final_dir=final_dir,
        history_dir=output_dir / "history",
    )
    article_id = repository_a.list_articles()[0]["article_id"]
    render_started = threading.Event()
    continue_render = threading.Event()
    errors = []

    def blocking_renderer(**kwargs):
        render_started.set()
        assert continue_render.wait(timeout=10)
        fake_renderer(**kwargs)

    monkeypatch.setattr(pipeline, "render_visuals", blocking_renderer)

    def run_assets():
        try:
            pipeline.generate_visual_assets_for_file(
                final_path=final_path,
                output_dir=output_dir,
                font_path=tmp_path / "font.ttc",
            )
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=run_assets)
    worker.start()
    assert render_started.wait(timeout=10)

    concurrent = repository_b.load_article(article_id)
    edited = concurrent["payload"]
    edited["master_title"] = "Concurrent human edit"
    repository_b.save_article(
        article_id,
        edited,
        concurrent["version"],
        operation="edit",
    )
    continue_render.set()
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], AssetPublicationError)
    assert errors[0].code == "article_conflict"
    assert repository_a.load_article(article_id)["payload"]["master_title"] == (
        "Concurrent human edit"
    )
    assert len(repository_a.list_history(article_id)) == 1


def test_generate_visual_assets_for_file_rejects_outside_and_symlink(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals.pipeline import generate_visual_assets_for_file

    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(valid_payload()), encoding="utf-8")
    with pytest.raises(ValueError, match="final_path"):
        generate_visual_assets_for_file(
            final_path=outside,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )

    final_dir = tmp_path / "final"
    final_dir.mkdir()
    linked = final_dir / "linked.json"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="final_path"):
        generate_visual_assets_for_file(
            final_path=linked,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )


def test_generate_visual_assets_for_file_rejects_symlinked_final_directory(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals.pipeline import generate_visual_assets_for_file

    final_dir = tmp_path / "final"
    final_dir.mkdir()
    final_path = final_dir / "article.json"
    final_path.write_text(json.dumps(valid_payload()), encoding="utf-8")
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == final_dir or real_is_symlink(path),
    )

    with pytest.raises(ValueError, match="final_path"):
        generate_visual_assets_for_file(
            final_path=final_path,
            output_dir=tmp_path,
            font_path=tmp_path / "font.ttc",
        )


def test_generate_visual_assets_rejects_junction_in_output_ancestry(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    output_dir = tmp_path / "out"
    real_is_junction = getattr(Path, "is_junction", None)

    def fake_is_junction(path: Path) -> bool:
        if path == tmp_path:
            return True
        return real_is_junction(path) if real_is_junction else False

    monkeypatch.setattr(Path, "is_junction", fake_is_junction, raising=False)
    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)

    with pytest.raises(AssetPublicationError, match="invalid_asset_root"):
        pipeline.generate_visual_assets(
            payload=valid_payload(),
            output_dir=output_dir,
            font_path=tmp_path / "font.ttc",
        )


def test_output_descendant_validation_rejects_lexical_escape(tmp_path: Path):
    from ai_content_loop.visuals.assets import (
        AssetPublicationError,
        validate_output_descendant,
    )

    output_dir = tmp_path / "out"

    with pytest.raises(AssetPublicationError, match="invalid_asset_root"):
        validate_output_descendant(output_dir, tmp_path / "outside")


def test_file_wrapper_rejects_junction_output_root(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    output_dir = tmp_path / "out"
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True)
    final_path = final_dir / "article.json"
    final_path.write_text(json.dumps(valid_payload()), encoding="utf-8")
    real_is_junction = getattr(Path, "is_junction", None)

    def fake_is_junction(path: Path) -> bool:
        if path == output_dir:
            return True
        return real_is_junction(path) if real_is_junction else False

    monkeypatch.setattr(Path, "is_junction", fake_is_junction, raising=False)
    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)

    with pytest.raises(AssetPublicationError, match="invalid_asset_root"):
        pipeline.generate_visual_assets_for_file(
            final_path=final_path,
            output_dir=output_dir,
            font_path=tmp_path / "font.ttc",
        )


def test_generate_visual_assets_rejects_symlinked_output_root(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import AssetPublicationError

    target = tmp_path / "real-output"
    target.mkdir()
    linked_output = tmp_path / "linked-output"
    try:
        linked_output.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)

    with pytest.raises(AssetPublicationError, match="invalid_asset_root"):
        pipeline.generate_visual_assets(
            payload=valid_payload(),
            output_dir=linked_output,
            font_path=tmp_path / "font.ttc",
        )


def test_manifest_hash_and_size_validation_detects_tampering(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import (
        AssetPublicationError,
        validate_payload_revision,
    )

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    result = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )
    validate_payload_revision(result, tmp_path, tmp_path / "font.ttc")
    body = tmp_path / result["visual_assets"]["body"][0]["path"]
    body.write_bytes(body.read_bytes() + b"tamper")

    with pytest.raises(
        AssetPublicationError, match="existing_revision_mismatch"
    ):
        validate_payload_revision(result, tmp_path, tmp_path / "font.ttc")


@pytest.mark.parametrize("tampering", ["extra_file", "manifest_metadata"])
def test_revision_validation_rejects_extra_files_and_metadata(
    tmp_path: Path, monkeypatch, tampering
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import (
        AssetPublicationError,
        validate_payload_revision,
    )

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    result = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )
    revision_dir = (
        tmp_path / result["visual_assets"]["cover"]["path"]
    ).parent
    if tampering == "extra_file":
        (revision_dir / "unexpected.txt").write_text("extra", encoding="utf-8")
    else:
        manifest_path = revision_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["assets"]["cover"]["content_type"] = "image/png"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        AssetPublicationError, match="existing_revision_mismatch"
    ):
        validate_payload_revision(result, tmp_path, tmp_path / "font.ttc")


def test_payload_revision_validation_rejects_stale_selected_copy(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline
    from ai_content_loop.visuals.assets import (
        AssetPublicationError,
        validate_payload_revision,
    )

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    result = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )
    result["visual_brief"]["cover_line"] = "A different current cover"

    with pytest.raises(
        AssetPublicationError, match="asset_identity_mismatch"
    ):
        validate_payload_revision(result, tmp_path, tmp_path / "font.ttc")


def test_real_renderer_pipeline_integration(tmp_path: Path):
    from ai_content_loop.visuals.pipeline import generate_visual_assets

    font = Path(r"C:\Windows\Fonts\msyh.ttc")
    if not font.is_file():
        pytest.skip("local Chinese font unavailable")
    payload = valid_payload()
    payload["visual_brief"]["cover_line"] = "AI 写完代码"
    payload["visual_brief"]["cover_subline"] = "测试说真话"
    payload["visual_brief"]["body_panels"] = [
        {"label": "AI 写代码", "reaction": "自信"},
        {"label": "运行测试", "reaction": "沉默"},
    ]

    result = generate_visual_assets(
        payload=payload,
        output_dir=tmp_path,
        font_path=font,
    )

    cover_path = tmp_path / result["visual_assets"]["cover"]["path"]
    body_path = tmp_path / result["visual_assets"]["body"][0]["path"]
    with Image.open(cover_path) as cover:
        assert cover.size == COVER_SIZE
    with Image.open(body_path) as body:
        assert body.size == BODY_SIZE


def test_new_visual_revision_contains_two_distributed_body_images(
    tmp_path: Path, monkeypatch
):
    from ai_content_loop.visuals import pipeline

    monkeypatch.setattr(pipeline, "render_visuals", fake_renderer)
    result = pipeline.generate_visual_assets(
        payload=valid_payload(),
        output_dir=tmp_path,
        font_path=tmp_path / "font.ttc",
    )

    assert [item["asset_id"] for item in result["visual_assets"]["body"]] == [
        "body-01",
        "body-02",
    ]
    wechat = result["platform_markdown"]["wechat"]
    assert wechat.count("{{asset:body-01}}") == 1
    assert wechat.count("{{asset:body-02}}") == 1
    revision = result["visual_assets"]["cover"]["revision"]
    article_id = schema.article_id_for(result["dedupe_key"])
    revision_dir = tmp_path / "assets" / article_id / revision
    assert (revision_dir / "body.png").is_file()
    assert (revision_dir / "body-02.png").is_file()
