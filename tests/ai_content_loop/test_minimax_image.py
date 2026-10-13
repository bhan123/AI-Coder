from __future__ import annotations

import base64
from io import BytesIO
import json

import pytest
from PIL import Image

from ai_content_loop.visuals.minimax_image import (
    MiniMaxImageClient,
    MiniMaxImageError,
    build_cover_prompt,
    client_from_env,
    prepare_cover_background,
)
from ai_content_loop.visuals.renderer import COVER_SIZE


def _jpeg_bytes(size=(1344, 576), color=(26, 67, 91)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_minimax_client_requests_one_reproducible_base64_image():
    secret = "subscription-key-value"
    captured = []
    encoded = base64.b64encode(_jpeg_bytes()).decode("ascii")

    def transport(request):
        captured.append(request)
        return json.dumps(
            {
                "id": "safe-task-id",
                "data": {"image_base64": [encoded]},
                "metadata": {"failed_count": "0", "success_count": "1"},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            }
        ).encode("utf-8")

    client = MiniMaxImageClient(secret, transport=transport)
    prompt = "Editorial illustration without text"

    generated = client.generate(prompt)

    assert secret not in repr(client)
    assert generated == _jpeg_bytes()
    assert len(captured) == 1
    request = captured[0]
    assert request.full_url == "https://api.minimaxi.com/v1/image_generation"
    assert request.get_header("Authorization") == f"Bearer {secret}"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload == {
        "model": "image-01",
        "prompt": prompt,
        "aspect_ratio": "21:9",
        "response_format": "base64",
        "seed": client.identity_for_prompt(prompt)["seed"],
        "n": 1,
        "prompt_optimizer": True,
        "aigc_watermark": False,
    }


def test_minimax_client_requests_16_by_9_body_image():
    captured = []
    encoded = base64.b64encode(_jpeg_bytes()).decode("ascii")

    def transport(request):
        captured.append(request)
        return json.dumps(
            {
                "data": {"image_base64": [encoded]},
                "base_resp": {"status_code": 0},
            }
        ).encode("utf-8")

    client = MiniMaxImageClient("secret", transport=transport)
    prompt = "Full-frame body illustration without text"

    client.generate(prompt, aspect_ratio="16:9")

    payload = json.loads(captured[0].data.decode("utf-8"))
    assert payload["aspect_ratio"] == "16:9"
    assert payload["seed"] == client.identity_for_prompt(
        prompt,
        aspect_ratio="16:9",
    )["seed"]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.minimaxi.com",
        "https://user:pass@api.minimaxi.com",
        "https://api.minimaxi.com?key=value",
        "file:///tmp/minimax",
    ],
)
def test_minimax_client_rejects_unsafe_api_base_urls(base_url):
    with pytest.raises(ValueError, match="safe HTTPS"):
        MiniMaxImageClient("secret", api_base_url=base_url)


def test_client_from_env_requires_explicit_image_subscription_key():
    assert client_from_env({}) is None
    assert client_from_env({"MINIMAX_API_KEY": "ordinary-key"}) is None

    client = client_from_env(
        {
            "MINIMAX_IMAGE_API_KEY": "subscription-key",
            "MINIMAX_IMAGE_MODEL": "image-01",
        }
    )

    assert client is not None
    assert client.model == "image-01"


def test_minimax_errors_never_echo_key_prompt_or_remote_message():
    secret = "private-subscription-key"
    prompt = "private unpublished headline"

    def transport(_request):
        return json.dumps(
            {
                "base_resp": {
                    "status_code": 1004,
                    "status_msg": f"bad {secret} {prompt}",
                }
            }
        ).encode("utf-8")

    client = MiniMaxImageClient(secret, transport=transport)
    with pytest.raises(MiniMaxImageError) as caught:
        client.generate(prompt)

    assert caught.value.code == "image_api_error"
    assert str(caught.value) == "image_api_error"
    assert secret not in str(caught.value)
    assert prompt not in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        b"not-json",
        json.dumps({"data": {"image_base64": []}}).encode(),
        json.dumps({"data": {"image_base64": ["***"]}}).encode(),
    ],
)
def test_minimax_client_rejects_invalid_responses(response):
    client = MiniMaxImageClient("secret", transport=lambda _request: response)

    with pytest.raises(MiniMaxImageError) as caught:
        client.generate("safe prompt")

    assert caught.value.code == "invalid_image_response"


def test_prepare_cover_background_crops_and_strips_metadata():
    prepared = prepare_cover_background(_jpeg_bytes(size=(1344, 576)))
    try:
        assert prepared.mode == "RGB"
        assert prepared.size == COVER_SIZE
        assert prepared.info == {}
    finally:
        prepared.close()


@pytest.mark.parametrize(
    "raw",
    [b"", b"not-an-image"],
)
def test_prepare_cover_background_rejects_unsafe_image_bytes(raw):
    with pytest.raises(MiniMaxImageError) as caught:
        prepare_cover_background(raw)

    assert caught.value.code == "invalid_image_response"


def test_cover_prompt_is_bounded_and_forbids_generated_words():
    prompt = build_cover_prompt(
        {
            "template_hint": "ai_done_vs_tests",
            "cover_line": "AI 写完了，测试才刚开始",
            "cover_subline": "速度不能替代证据",
            "body_panels": [
                {"label": "生成代码", "reaction": "很快"},
                {"label": "运行测试", "reaction": "见真章"},
            ],
            "alternatives": [
                {
                    "cover_line": "先跑再说",
                    "cover_subline": "测试不会陪你演戏",
                    "body_panels": [
                        {"label": "生成代码", "reaction": "很快"},
                        {"label": "运行测试", "reaction": "见真章"},
                    ],
                },
                {
                    "cover_line": "代码只是开始",
                    "cover_subline": "结果需要验证",
                    "body_panels": [
                        {"label": "生成代码", "reaction": "很快"},
                        {"label": "运行测试", "reaction": "见真章"},
                    ],
                },
            ],
        }
    )

    assert "AI 写完了，测试才刚开始" in prompt
    assert "no text" in prompt.lower()
    assert len(prompt) <= 1500
