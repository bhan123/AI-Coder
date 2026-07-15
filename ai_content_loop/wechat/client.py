from __future__ import annotations

import json
import mimetypes
from pathlib import Path
import secrets
from typing import Callable
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class WechatApiError(RuntimeError):
    """A credential-safe WeChat API failure."""


Transport = Callable[[Request], bytes]


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_transport(request: Request) -> bytes:
    opener = build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=30) as response:
        return response.read()


class WechatClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        api_base_url: str = "https://api.weixin.qq.com",
        transport: Transport | None = None,
    ) -> None:
        parsed_base = urlparse(api_base_url)
        if (
            parsed_base.scheme != "https"
            or not parsed_base.netloc
            or parsed_base.hostname is None
            or parsed_base.username is not None
            or parsed_base.password is not None
            or parsed_base.query
            or parsed_base.fragment
        ):
            raise ValueError("WeChat API base URL must be a safe HTTPS URL")
        self._app_id = app_id
        self._app_secret = app_secret
        self._base = api_base_url.rstrip("/")
        self._transport = transport or _default_transport

    def _call(self, request: Request) -> dict[str, object]:
        try:
            raw = self._transport(request)
            value = json.loads(raw.decode("utf-8"))
        except Exception as error:
            raise WechatApiError("WeChat API request failed") from error
        if not isinstance(value, dict):
            raise WechatApiError("WeChat API returned an invalid response")
        errcode = value.get("errcode")
        if errcode not in (None, 0):
            safe_code = errcode if isinstance(errcode, int) else "unknown"
            raise WechatApiError(f"WeChat API error (errcode={safe_code})")
        return value

    def _url(self, path: str, query: dict[str, str]) -> str:
        return f"{self._base}{path}?{urlencode(query)}"

    def get_access_token(self) -> str:
        request = Request(
            self._url(
                "/cgi-bin/token",
                {
                    "grant_type": "client_credential",
                    "appid": self._app_id,
                    "secret": self._app_secret,
                },
            ),
            method="GET",
        )
        token = self._call(request).get("access_token")
        if not isinstance(token, str) or not token:
            raise WechatApiError("WeChat API response is missing access_token")
        return token

    def _multipart_request(
        self,
        path: str,
        token: str,
        image_path: Path,
        *,
        extra_query: dict[str, str] | None = None,
    ) -> Request:
        boundary = "----ai-content-loop-" + secrets.token_hex(12)
        content_type = (
            mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        )
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="{image_path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + image_path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode("ascii")
        )
        query = {"access_token": token, **(extra_query or {})}
        return Request(
            self._url(path, query),
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

    def upload_permanent_image(self, token: str, image_path: Path) -> str:
        value = self._call(
            self._multipart_request(
                "/cgi-bin/material/add_material",
                token,
                image_path,
                extra_query={"type": "image"},
            )
        )
        media_id = value.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise WechatApiError("WeChat API response is missing media_id")
        return media_id

    def upload_body_image(self, token: str, image_path: Path) -> str:
        value = self._call(
            self._multipart_request("/cgi-bin/media/uploadimg", token, image_path)
        )
        url = value.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if (
            parsed is None
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise WechatApiError("WeChat API response is missing a safe image URL")
        return url

    def add_draft(
        self, token: str, *, title: str, content: str, thumb_media_id: str
    ) -> str:
        data = json.dumps(
            {
                "articles": [
                    {
                        "title": title,
                        "content": content,
                        "thumb_media_id": thumb_media_id,
                        "need_open_comment": 0,
                        "only_fans_can_comment": 0,
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            self._url("/cgi-bin/draft/add", {"access_token": token}),
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        media_id = self._call(request).get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise WechatApiError("WeChat API response is missing media_id")
        return media_id
