from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont

import ai_content_loop.visuals.renderer as renderer
from ai_content_loop.visuals.brief import VisualBriefError
from ai_content_loop.visuals.renderer import (
    BODY_SIZE,
    COVER_SIZE,
    VisualRenderError,
    _fit_font,
    _wrap_text,
    render_visuals,
)
from ai_content_loop.visuals.templates import TEMPLATES, TemplateSpec


def local_chinese_font() -> Path:
    candidates = (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    )
    for path in candidates:
        if path.exists():
            return path
    pytest.skip("Chinese test font unavailable")


@pytest.fixture
def valid_brief():
    panel_a = {"label": "AI 写完代码", "reaction": "自信"}
    panel_b = {"label": "人类打开测试", "reaction": "沉默"}
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


def _render(tmp_path, brief, template, *, stem="visual"):
    cover = tmp_path / stem / "cover.jpg"
    body = tmp_path / stem / "body.png"
    render_visuals(
        brief=brief,
        template=template,
        font_path=local_chinese_font(),
        cover_path=cover,
        body_path=body,
    )
    return cover, body


def _color_distance(left, right):
    return sum(abs(a - b) for a, b in zip(left[:3], right[:3], strict=True))


def _count_near_color(image, color, *, tolerance=0, box=None):
    target = ImageColor.getrgb(color)
    region = image.crop(box) if box else image
    try:
        return sum(
            _color_distance(pixel, target) <= tolerance
            for pixel in region.getdata()
        )
    finally:
        if region is not image:
            region.close()


def _assert_background_corners(image, color, *, tolerance):
    target = ImageColor.getrgb(color)
    width, height = image.size
    for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        assert _color_distance(image.getpixel(point), target) <= tolerance


def _assert_color_is_bounded(image, color, allowed_boxes):
    target = ImageColor.getrgb(color)
    pixels = image.load()
    matched = 0
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y] != target:
                continue
            matched += 1
            assert any(
                left <= x <= right and top <= y <= bottom
                for left, top, right, bottom in allowed_boxes
            )
    assert matched > 100


def test_renderer_exports_fixed_image_sizes():
    assert COVER_SIZE == (900, 383)
    assert BODY_SIZE == (1080, 608)


def test_generated_cover_keeps_original_image_and_adds_text_without_color_panel(
    tmp_path, valid_brief
):
    background = Image.new("RGB", COVER_SIZE, (65, 105, 180))
    cover = tmp_path / "generated-cover.jpg"
    body = tmp_path / "generated-body.png"
    try:
        render_visuals(
            brief=valid_brief,
            template=TEMPLATES["before_vs_after"],
            font_path=local_chinese_font(),
            cover_path=cover,
            body_path=body,
            cover_background=background,
        )
        assert background.getpixel((100, 200)) == (65, 105, 180)
    finally:
        background.close()

    with Image.open(cover) as image:
        assert image.size == COVER_SIZE
        right_pixel = image.convert("RGB").getpixel((850, 200))
        assert all(abs(actual - expected) <= 5 for actual, expected in zip(
            right_pixel, (65, 105, 180)
        ))
        left_pixel = image.convert("RGB").getpixel((20, 200))
        assert all(abs(actual - expected) <= 5 for actual, expected in zip(
            left_pixel, (65, 105, 180)
        ))


def test_generated_body_images_are_preserved_without_template_redraw(
    tmp_path, valid_brief
):
    cover_background = Image.new("RGB", COVER_SIZE, (65, 105, 180))
    first_body = Image.new("RGB", BODY_SIZE, (120, 40, 30))
    second_body = Image.new("RGB", BODY_SIZE, (20, 130, 70))
    cover = tmp_path / "cover.jpg"
    body = tmp_path / "body.png"
    second = tmp_path / "body-02.png"
    try:
        render_visuals(
            brief=valid_brief,
            template=TEMPLATES["before_vs_after"],
            font_path=local_chinese_font(),
            cover_path=cover,
            body_path=body,
            secondary_body_path=second,
            cover_background=cover_background,
            body_backgrounds=(first_body, second_body),
        )
    finally:
        cover_background.close()
        first_body.close()
        second_body.close()

    with Image.open(body) as image:
        assert image.getpixel((540, 304)) == (120, 40, 30)
    with Image.open(second) as image:
        assert image.getpixel((540, 304)) == (20, 130, 70)


@pytest.mark.parametrize(
    "structure",
    ["comparison", "pipeline", "hub", "editorial_metaphor"],
)
def test_local_cover_supports_semantic_material_motifs(
    tmp_path, valid_brief, structure
):
    cover = tmp_path / f"{structure}.jpg"
    body = tmp_path / f"{structure}.png"

    render_visuals(
        brief=valid_brief,
        template=TEMPLATES["ai_done_vs_tests"],
        font_path=local_chinese_font(),
        cover_path=cover,
        body_path=body,
        illustration_structure=structure,
    )

    assert cover.stat().st_size > 0
    assert body.stat().st_size > 0


def test_renderer_rejects_unknown_illustration_structure(
    tmp_path, valid_brief
):
    with pytest.raises(
        VisualRenderError,
        match="invalid_illustration_structure",
    ):
        render_visuals(
            brief=valid_brief,
            template=TEMPLATES["ai_done_vs_tests"],
            font_path=local_chinese_font(),
            cover_path=tmp_path / "cover.jpg",
            body_path=tmp_path / "body.png",
            illustration_structure="unknown",
        )


def test_renderer_can_emit_a_distinct_second_body_illustration(
    tmp_path, valid_brief
):
    cover = tmp_path / "cover.jpg"
    body_one = tmp_path / "body-01.png"
    body_two = tmp_path / "body-02.png"

    render_visuals(
        brief=valid_brief,
        template=TEMPLATES["ai_done_vs_tests"],
        font_path=local_chinese_font(),
        cover_path=cover,
        body_path=body_one,
        secondary_body_path=body_two,
        illustration_structure="pipeline",
    )

    with Image.open(body_one) as first, Image.open(body_two) as second:
        assert first.size == BODY_SIZE
        assert second.size == BODY_SIZE
        assert ImageChops.difference(first, second).getbbox() is not None


@pytest.mark.parametrize("template_name", tuple(TEMPLATES))
def test_each_template_renders_bounded_images_with_original_palette(
    tmp_path, valid_brief, template_name
):
    template = TEMPLATES[template_name]
    brief = deepcopy(valid_brief)
    brief["template_hint"] = template_name

    cover, body = _render(
        tmp_path,
        brief,
        template,
        stem=template_name,
    )

    with Image.open(cover) as image:
        assert image.size == COVER_SIZE
        assert image.format == "JPEG"
        _assert_background_corners(image, template.background, tolerance=4)
        assert _count_near_color(image, template.accent, tolerance=18) > 500
    with Image.open(body) as image:
        assert image.size == BODY_SIZE
        assert image.format == "PNG"
        _assert_background_corners(image, template.background, tolerance=0)
        assert _count_near_color(image, template.accent) > 500
    assert cover.stat().st_size < 1_000_000
    assert body.stat().st_size < 2_000_000


def test_cover_draws_both_approved_copy_fields_inside_bounded_regions(
    tmp_path, valid_brief
):
    template = TEMPLATES["ai_done_vs_tests"]
    cover, _ = _render(tmp_path, valid_brief, template)

    with Image.open(cover) as image:
        assert _count_near_color(
            image,
            template.foreground,
            tolerance=18,
            box=(60, 40, 670, 245),
        ) > 100
        assert _count_near_color(
            image,
            template.foreground,
            tolerance=18,
            box=(60, 250, 670, 345),
        ) > 50


@pytest.mark.parametrize(
    "template_name",
    [
        name
        for name, template in TEMPLATES.items()
        if template.layout == "split"
    ],
)
def test_split_templates_have_distinct_panels_and_circle_line_faces(
    tmp_path, valid_brief, template_name
):
    template = TEMPLATES[template_name]
    _, body_path = _render(
        tmp_path,
        valid_brief,
        template,
        stem=template_name,
    )

    with Image.open(body_path) as image:
        left = image.crop((50, 70, 520, 538))
        right = image.crop((560, 70, 1030, 538))
        try:
            assert ImageChops.difference(left, right).getbbox() is not None
        finally:
            left.close()
            right.close()
        for face_box in ((210, 215, 360, 375), (720, 215, 870, 375)):
            assert _count_near_color(
                image,
                template.accent,
                box=face_box,
            ) > 100
            assert _count_near_color(
                image,
                template.foreground,
                box=face_box,
            ) > 20


def test_split_layout_uses_both_labels_and_both_reactions(
    tmp_path, valid_brief
):
    template = TEMPLATES["before_vs_after"]
    changed = deepcopy(valid_brief)
    changed["body_panels"] = [
        {"label": "老板要求今天上线", "reaction": "非常乐观"},
        {"label": "我看完测试报告", "reaction": "重新排期"},
    ]

    _, first_path = _render(
        tmp_path,
        valid_brief,
        template,
        stem="first",
    )
    _, second_path = _render(
        tmp_path,
        changed,
        template,
        stem="second",
    )

    with Image.open(first_path) as first, Image.open(second_path) as second:
        for box in (
            (80, 90, 490, 210),
            (590, 90, 1000, 210),
            (80, 410, 490, 515),
            (590, 410, 1000, 515),
        ):
            first_region = first.crop(box)
            second_region = second.crop(box)
            try:
                assert (
                    ImageChops.difference(first_region, second_region).getbbox()
                    is not None
                )
            finally:
                first_region.close()
                second_region.close()


def test_verdict_has_central_accent_and_uses_headline_and_subline(
    tmp_path, valid_brief
):
    template = TEMPLATES["one_line_verdict"]
    changed = deepcopy(valid_brief)
    changed["cover_line"] = "测试通过之前，完成度都是幻觉"
    changed["cover_subline"] = "证据比速度更重要"

    _, first_path = _render(
        tmp_path,
        valid_brief,
        template,
        stem="verdict-first",
    )
    _, second_path = _render(
        tmp_path,
        changed,
        template,
        stem="verdict-second",
    )

    with Image.open(first_path) as first, Image.open(second_path) as second:
        assert _count_near_color(
            first,
            template.accent,
            box=(100, 40, 980, 568),
        ) > 1_000
        central_accent = _count_near_color(
            first,
            template.accent,
            box=(350, 60, 730, 390),
        )
        left_accent = _count_near_color(
            first,
            template.accent,
            box=(100, 60, 300, 390),
        )
        right_accent = _count_near_color(
            first,
            template.accent,
            box=(780, 60, 980, 390),
        )
        assert central_accent > 2 * max(left_accent, right_accent)
        for box in ((150, 160, 930, 350), (160, 395, 920, 505)):
            first_region = first.crop(box)
            second_region = second.crop(box)
            try:
                assert (
                    ImageChops.difference(first_region, second_region).getbbox()
                    is not None
                )
            finally:
                first_region.close()
                second_region.close()


@pytest.mark.parametrize(
    "template_name",
    ["boss_vs_worker", "one_line_verdict"],
)
def test_contract_maximum_copy_renders_without_leaving_canvas(
    tmp_path, valid_brief, template_name
):
    brief = deepcopy(valid_brief)
    brief["cover_line"] = "测" * 30
    brief["cover_subline"] = "试" * 20
    brief["body_panels"] = [
        {"label": "甲" * 16, "reaction": "左" * 10},
        {"label": "乙" * 16, "reaction": "右" * 10},
    ]

    cover, body = _render(
        tmp_path,
        brief,
        TEMPLATES[template_name],
        stem=f"maximum-{template_name}",
    )

    with Image.open(cover) as image:
        assert image.size == COVER_SIZE
        _assert_background_corners(
            image,
            TEMPLATES[template_name].background,
            tolerance=4,
        )
    with Image.open(body) as image:
        assert image.size == BODY_SIZE
        _assert_background_corners(
            image,
            TEMPLATES[template_name].background,
            tolerance=0,
        )
        if TEMPLATES[template_name].layout == "split":
            allowed_foreground_boxes = (
                (80, 90, 490, 210),
                (210, 215, 360, 375),
                (80, 410, 490, 515),
                (590, 90, 1000, 210),
                (720, 215, 870, 375),
                (590, 410, 1000, 515),
            )
        else:
            allowed_foreground_boxes = ((150, 165, 930, 350),)
        _assert_color_is_bounded(
            image,
            TEMPLATES[template_name].foreground,
            allowed_foreground_boxes,
        )


def test_fit_font_decrements_through_declared_minimum_and_validates_bounds():
    font_path = local_chinese_font()
    image = Image.new("RGB", (800, 300))
    draw = ImageDraw.Draw(image)
    text = "宽度测试" * 4
    minimum = ImageFont.truetype(str(font_path), size=24)
    min_box = draw.multiline_textbbox(
        (0, 0),
        text,
        font=minimum,
        spacing=4,
    )
    max_width = min_box[2] - min_box[0]
    max_height = min_box[3] - min_box[1]

    fitted = _fit_font(
        draw,
        text,
        font_path,
        max_width=max_width,
        max_height=max_height,
        start_size=36,
        min_size=24,
    )

    fitted_box = draw.multiline_textbbox(
        (0, 0),
        text,
        font=fitted,
        spacing=max(4, fitted.size // 5),
    )
    assert fitted.size == 24
    assert fitted_box[2] - fitted_box[0] <= max_width
    assert fitted_box[3] - fitted_box[1] <= max_height
    image.close()


def test_fit_font_raises_stable_text_overflow_when_minimum_does_not_fit():
    image = Image.new("RGB", (100, 100))
    draw = ImageDraw.Draw(image)

    with pytest.raises(VisualRenderError) as caught:
        _fit_font(
            draw,
            "W",
            local_chinese_font(),
            max_width=1,
            max_height=1,
            start_size=18,
            min_size=12,
        )

    assert caught.value.code == "text_overflow"
    assert str(caught.value) == "text_overflow"
    image.close()


def test_wrap_text_measures_chinese_incrementally_without_overwide_lines():
    image = Image.new("RGB", (300, 200))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(local_chinese_font()), size=32)
    two_glyph_box = draw.textbbox((0, 0), "中文", font=font)
    max_width = two_glyph_box[2] - two_glyph_box[0]

    wrapped = _wrap_text(draw, "中文测试换行", font, max_width=max_width)

    assert "".join(wrapped.splitlines()) == "中文测试换行"
    assert len(wrapped.splitlines()) >= 3
    for line in wrapped.splitlines():
        box = draw.textbbox((0, 0), line, font=font)
        assert box[2] - box[0] <= max_width
    image.close()


def test_wrap_text_preserves_explicit_newlines():
    image = Image.new("RGB", (500, 200))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(local_chinese_font()), size=24)

    wrapped = _wrap_text(
        draw,
        "第一行\n第二行\n",
        font,
        max_width=400,
    )

    assert wrapped == "第一行\n第二行\n"
    image.close()


@pytest.mark.parametrize(
    "cluster",
    [
        "👩\u200d💻",
        "❤️\u200d🔥",
        "👍🏽",
        "e\u0301",
        "🇨🇳",
    ],
)
def test_wrap_text_never_splits_extended_graphemes_at_a_width_boundary(
    cluster,
):
    image = Image.new("RGB", (500, 200))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(local_chinese_font()), size=32)

    prefix_box = draw.textbbox((0, 0), "A", font=font)
    cluster_box = draw.textbbox((0, 0), cluster, font=font)
    prefix_width = prefix_box[2] - prefix_box[0]
    cluster_width = cluster_box[2] - cluster_box[0]
    max_width = max(prefix_width, cluster_width)
    combined_box = draw.textbbox((0, 0), f"A{cluster}", font=font)
    assert combined_box[2] - combined_box[0] > max_width

    wrapped = _wrap_text(
        draw,
        f"A{cluster}",
        font,
        max_width=max_width,
    )

    assert wrapped == f"A\n{cluster}"
    image.close()


def test_wrap_text_keeps_clusters_intact_next_to_explicit_newline():
    image = Image.new("RGB", (500, 200))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(local_chinese_font()), size=32)
    text = "👩\u200d💻\ne\u0301"

    wrapped = _wrap_text(draw, text, font, max_width=400)

    assert wrapped == text
    image.close()


def test_wrap_text_rejects_one_overwide_extended_grapheme():
    image = Image.new("RGB", (500, 200))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(local_chinese_font()), size=32)
    cluster = "👩\u200d💻"
    box = draw.textbbox((0, 0), cluster, font=font)
    cluster_width = box[2] - box[0]

    with pytest.raises(VisualRenderError) as caught:
        _wrap_text(
            draw,
            cluster,
            font,
            max_width=cluster_width - 1,
        )

    assert caught.value.code == "text_overflow"
    image.close()


def test_wrap_text_rejects_a_single_glyph_wider_than_the_box():
    image = Image.new("RGB", (100, 100))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(local_chinese_font()), size=32)

    with pytest.raises(VisualRenderError) as caught:
        _wrap_text(draw, "宽", font, max_width=1)

    assert caught.value.code == "text_overflow"
    image.close()


class _FakeMask:
    size = (2, 2)

    def __init__(self, value):
        self.value = value

    def __bytes__(self):
        return self.value * 4


class _FakeCoverageFont:
    def __init__(self, supported=None):
        self.calls = []
        self.supported = {"A", "中"} if supported is None else supported

    def getmask(self, text, mode):
        self.calls.append((text, mode))
        if text in self.supported:
            return _FakeMask(b"\x01")
        return _FakeMask(b"\x00")


def test_glyph_coverage_raises_secret_safe_error_for_missing_base():
    font = _FakeCoverageFont()
    private_missing_glyph = "🚫"

    with pytest.raises(VisualRenderError) as caught:
        renderer._ensure_supported_text(font, f"A{private_missing_glyph}")

    assert caught.value.code == "unsupported_glyph"
    assert str(caught.value) == "unsupported_glyph"
    assert private_missing_glyph not in str(caught.value)


def test_glyph_coverage_rejects_missing_combining_mark():
    font = _FakeCoverageFont()

    with pytest.raises(VisualRenderError) as caught:
        renderer._ensure_supported_text(font, "A\u0301")

    assert caught.value.code == "unsupported_glyph"


def test_glyph_coverage_rejects_missing_emoji_modifier():
    base_emoji = "\U0001f44d"
    font = _FakeCoverageFont(supported={base_emoji})

    with pytest.raises(VisualRenderError) as caught:
        renderer._ensure_supported_text(font, f"{base_emoji}\U0001f3fd")

    assert caught.value.code == "unsupported_glyph"


def test_glyph_coverage_ignores_only_non_rendering_controls_and_whitespace():
    font = _FakeCoverageFont()

    renderer._ensure_supported_text(font, "A \n\u200d\ufe0f")

    checked_values = {text for text, _mode in font.calls}
    assert "\u200d" not in checked_values
    assert "\ufe0f" not in checked_values
    assert " " not in checked_values
    assert "\n" not in checked_values


def test_glyph_coverage_accepts_supported_chinese_text():
    font = ImageFont.truetype(str(local_chinese_font()), size=32)

    renderer._ensure_supported_text(font, "中文")


def test_fit_font_rejects_a_guaranteed_unassigned_codepoint():
    image = Image.new("RGB", (200, 100))
    draw = ImageDraw.Draw(image)

    with pytest.raises(VisualRenderError) as caught:
        _fit_font(
            draw,
            "\u0378",
            local_chinese_font(),
            max_width=180,
            max_height=80,
            start_size=24,
            min_size=18,
        )

    assert caught.value.code == "unsupported_glyph"
    image.close()


@pytest.mark.parametrize("font_kind", ["missing", "corrupt"])
def test_fit_font_reports_non_leaking_font_unavailable(
    tmp_path, font_kind
):
    font_path = tmp_path / f"private-{font_kind}.ttc"
    if font_kind == "corrupt":
        font_path.write_bytes(b"not a font")
    image = Image.new("RGB", (200, 100))
    draw = ImageDraw.Draw(image)

    with pytest.raises(VisualRenderError) as caught:
        _fit_font(
            draw,
            "文字",
            font_path,
            max_width=180,
            max_height=80,
            start_size=24,
            min_size=18,
        )

    assert caught.value.code == "font_unavailable"
    assert str(caught.value) == "font_unavailable"
    assert font_path.name not in str(caught.value)
    image.close()


def test_equal_registered_template_is_canonicalized_and_accepted(
    tmp_path, valid_brief
):
    approved = TEMPLATES["do_vs_dont"]
    equal_copy = TemplateSpec(
        approved.name,
        approved.layout,
        approved.background,
        approved.accent,
        approved.foreground,
    )

    cover, body = _render(
        tmp_path,
        valid_brief,
        equal_copy,
        stem="equal-template",
    )

    assert cover.is_file()
    assert body.is_file()


def test_arbitrary_template_is_rejected_without_rendering_or_leaking(
    tmp_path, valid_brief
):
    private_value = "private-model-color"
    arbitrary = TemplateSpec(
        "unregistered",
        "split",
        "#000000",
        private_value,
        "#FFFFFF",
    )
    cover = tmp_path / "cover.jpg"
    body = tmp_path / "body.png"

    with pytest.raises(VisualRenderError) as caught:
        render_visuals(
            brief=valid_brief,
            template=arbitrary,
            font_path=local_chinese_font(),
            cover_path=cover,
            body_path=body,
        )

    assert caught.value.code == "invalid_template"
    assert str(caught.value) == "invalid_template"
    assert private_value not in str(caught.value)
    assert not cover.exists()
    assert not body.exists()


def test_render_normalizes_brief_before_creating_outputs(
    tmp_path, valid_brief
):
    invalid = deepcopy(valid_brief)
    invalid["unexpected"] = "model-controlled"
    cover = tmp_path / "nested" / "cover.jpg"
    body = tmp_path / "nested" / "body.png"

    with pytest.raises(VisualBriefError):
        render_visuals(
            brief=invalid,
            template=TEMPLATES["ai_done_vs_tests"],
            font_path=local_chinese_font(),
            cover_path=cover,
            body_path=body,
        )

    assert not cover.exists()
    assert not body.exists()


def test_render_rejects_same_output_path_with_stable_code(
    tmp_path, valid_brief
):
    output = tmp_path / "same-image"

    with pytest.raises(VisualRenderError) as caught:
        render_visuals(
            brief=valid_brief,
            template=TEMPLATES["ai_done_vs_tests"],
            font_path=local_chinese_font(),
            cover_path=output,
            body_path=output,
        )

    assert caught.value.code == "invalid_output"
    assert str(caught.value) == "invalid_output"
    assert not output.exists()
