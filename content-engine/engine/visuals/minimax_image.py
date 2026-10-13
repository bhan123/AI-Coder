from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import json
import re
from typing import Callable, Mapping
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps, UnidentifiedImageError

from engine.visuals.prompting import (
    build_body_image_prompt,
    build_image_prompt,
)
from engine.visuals.renderer import BODY_SIZE, COVER_SIZE


MAX_RESPONSE_BYTES = 24 * 1024 * 1024
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_PIXELS = 16_000_000
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ASPECT_RATIOS = {"21:9", "16:9"}


class MiniMaxImageError(RuntimeError):
    """A stable MiniMax image error that never includes secrets or copy."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


Transport = Callable[[Request], bytes]


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_transport(request: Request) -> bytes:
    opener = build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=60) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MiniMaxImageError("invalid_image_response")
    return raw


def _safe_base_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MiniMax image API base URL must be a safe HTTPS URL")
    return value.rstrip("/")


def build_cover_prompt(
    brief: object,
    *,
    article_layout: object | None = None,
) -> str:
    """Build the MiniMax prompt from the shared semantic illustration plan."""

    try:
        return build_image_prompt(brief, article_layout=article_layout)
    except ValueError:
        raise MiniMaxImageError("invalid_image_prompt") from None


def build_body_prompt(
    brief: object,
    *,
    panel_index: int,
    article_layout: object | None = None,
) -> str:
    try:
        return build_body_image_prompt(
            brief,
            panel_index=panel_index,
            article_layout=article_layout,
        )
    except ValueError:
        raise MiniMaxImageError("invalid_image_prompt") from None


def _prepare_image(raw: bytes, size: tuple[int, int]) -> Image.Image:
    """Decode an untrusted response into a metadata-free fixed-size RGB image."""

    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise MiniMaxImageError("invalid_image_response")
    source: Image.Image | None = None
    converted: Image.Image | None = None
    try:
        source = Image.open(BytesIO(raw))
        width, height = source.size
        if (
            width <= 0
            or height <= 0
            or width > MAX_IMAGE_SIDE
            or height > MAX_IMAGE_SIDE
            or width * height > MAX_IMAGE_PIXELS
            or source.format not in {"JPEG", "PNG", "WEBP"}
        ):
            raise MiniMaxImageError("invalid_image_response")
        source.load()
        converted = source.convert("RGB")
        prepared = ImageOps.fit(
            converted,
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        prepared.info.clear()
        return prepared
    except MiniMaxImageError:
        raise
    except (
        Image.DecompressionBombError,
        OSError,
        TypeError,
        UnidentifiedImageError,
        ValueError,
    ):
        raise MiniMaxImageError("invalid_image_response") from None
    finally:
        if converted is not None:
            converted.close()
        if source is not None:
            source.close()


def prepare_cover_background(raw: bytes) -> Image.Image:
    return _prepare_image(raw, COVER_SIZE)


def prepare_body_image(raw: bytes) -> Image.Image:
    return _prepare_image(raw, BODY_SIZE)


@dataclass(frozen=True)
class MiniMaxImageClient:
    _api_key: str = field(repr=False)
    api_base_url: str = "https://api.minimaxi.com"
    model: str = "image-01"
    transport: Transport | None = None

    def __post_init__(self) -> None:
        if not isinstance(self._api_key, str) or not self._api_key.strip():
            raise ValueError("MiniMax image API key must be non-empty")
        if self.model != "image-01":
            raise ValueError("MiniMax image model must be image-01")
        object.__setattr__(self, "_api_key", self._api_key.strip())
        object.__setattr__(self, "api_base_url", _safe_base_url(self.api_base_url))
        object.__setattr__(self, "transport", self.transport or _default_transport)

    def identity_for_prompt(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "21:9",
    ) -> dict[str, object]:
        if (
            not isinstance(prompt, str)
            or not prompt
            or len(prompt) > 1500
            or aspect_ratio not in _ASPECT_RATIOS
        ):
            raise MiniMaxImageError("invalid_image_prompt")
        digest = hashlib.sha256(
            f"{aspect_ratio}\0{prompt}".encode("utf-8")
        ).hexdigest()
        return {
            "provider": "minimax",
            "model": self.model,
            "prompt_sha256": digest,
            "seed": int(digest[:16], 16) & ((1 << 63) - 1),
        }

    def generate(self, prompt: str, *, aspect_ratio: str = "21:9") -> bytes:
        identity = self.identity_for_prompt(
            prompt,
            aspect_ratio=aspect_ratio,
        )
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "response_format": "base64",
                "seed": identity["seed"],
                "n": 1,
                "prompt_optimizer": True,
                "aigc_watermark": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            f"{self.api_base_url}/v1/image_generation",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            raw = self.transport(request)
        except MiniMaxImageError:
            raise
        except Exception:
            raise MiniMaxImageError("image_request_failed") from None
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
            raise MiniMaxImageError("invalid_image_response")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MiniMaxImageError("invalid_image_response") from None
        if not isinstance(value, dict):
            raise MiniMaxImageError("invalid_image_response")
        base_resp = value.get("base_resp")
        if isinstance(base_resp, dict) and base_resp.get("status_code") not in (
            None,
            0,
        ):
            raise MiniMaxImageError("image_api_error")
        data = value.get("data")
        images = data.get("image_base64") if isinstance(data, dict) else None
        if not isinstance(images, list) or len(images) != 1:
            raise MiniMaxImageError("invalid_image_response")
        encoded = images[0]
        if (
            not isinstance(encoded, str)
            or not encoded
            or len(encoded) > (MAX_IMAGE_BYTES * 4 // 3) + 8
        ):
            raise MiniMaxImageError("invalid_image_response")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise MiniMaxImageError("invalid_image_response") from None
        if not 0 < len(image) <= MAX_IMAGE_BYTES:
            raise MiniMaxImageError("invalid_image_response")
        return image


def client_from_env(
    environ: Mapping[str, str],
) -> MiniMaxImageClient | None:
    key = environ.get("MINIMAX_IMAGE_API_KEY", "").strip()
    if not key:
        return None
    return MiniMaxImageClient(
        key,
        api_base_url=environ.get(
            "MINIMAX_IMAGE_API_BASE_URL", "https://api.minimaxi.com"
        ),
        model=environ.get("MINIMAX_IMAGE_MODEL", "image-01"),
    )


def validate_image_source(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "provider",
        "model",
        "prompt_sha256",
        "seed",
    }:
        raise MiniMaxImageError("invalid_image_source")
    if (
        value.get("provider") != "minimax"
        or value.get("model") != "image-01"
        or not isinstance(value.get("prompt_sha256"), str)
        or _HASH_PATTERN.fullmatch(value["prompt_sha256"]) is None
        or type(value.get("seed")) is not int
        or not 0 <= value["seed"] < (1 << 63)
    ):
        raise MiniMaxImageError("invalid_image_source")
    return dict(value)
