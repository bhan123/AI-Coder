from __future__ import annotations

from datetime import timedelta
import hmac
from io import BytesIO
import os
from pathlib import Path

from flask import (
    Flask,
    current_app,
    g,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)

from engine.config import load_config
from engine.db import ContentStore
from engine.editorial.reader_feedback import evaluate_reader_feedback
from engine.review.auth import (
    LoginLimiter,
    auth,
    csrf_token,
    login_required,
    require_csrf,
)
from engine.review.rendering import render_markdown
from engine.review.rich_article import render_rich_article
from engine.review.repository import (
    ArticleConflict,
    ArticleNotFound,
    ArticleRepository,
    InvalidArticle,
    WechatDraftResultUnknown,
)
from engine.visuals.assets import AssetPublicationError
from engine.visuals.minimax_image import client_from_env
from engine.visuals.pipeline import generate_visual_assets
from engine.visuals.renderer import VisualRenderError
from engine.pack import active_pack, load_pack, set_active_pack
from engine.wechat.client import WechatApiError, WechatClient


REVIEW_STATUSES = {
    "needs_human_review",
    "approved",
    "revision_requested",
}
REVIEW_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
    "script-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)
WEB_EDITION_CSP = (
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
    "script-src 'none'; connect-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'none'"
)


def _minimal_visual_brief(payload: dict, template_name: str) -> dict:
    """Build deterministic local copy when the model visual brief was dropped."""

    title = str(payload.get("master_title") or "内容速览").strip()[:32]
    panels = [
        {"label": "核心信息", "reaction": "看重点"},
        {"label": "事实边界", "reaction": "看原文"},
    ]
    return {
        "template_hint": template_name,
        "cover_line": title or "内容速览",
        "cover_subline": "重点内容一图看懂",
        "body_panels": panels,
        "alternatives": [
            {
                "cover_line": title or "内容速览",
                "cover_subline": "先看重点，再看原文",
                "body_panels": panels,
            },
            {
                "cover_line": title or "内容速览",
                "cover_subline": "核心信息快速浏览",
                "body_panels": panels,
            },
        ],
    }


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=1_500_000,
        LOGIN_ATTEMPTS=5,
        LOGIN_WINDOW_SECONDS=300,
    )
    if test_config is None:
        config_path = os.environ.get(
            "CONTENT_ENGINE_CONFIG",
            "config.toml",
        )
        content_config = load_config(config_path)
        # The review desk validates visual templates and article layouts, so it
        # needs the same pack the generator ran with.
        set_active_pack(load_pack(content_config.pack_dir))
        app.config.update(
            SECRET_KEY=os.environ.get("AI_CONTENT_REVIEW_SECRET_KEY"),
            REVIEW_USERNAME=os.environ.get("AI_CONTENT_REVIEW_USERNAME"),
            REVIEW_PASSWORD_HASH=os.environ.get("AI_CONTENT_REVIEW_PASSWORD_HASH"),
            DATABASE_PATH=content_config.database_path,
            FINAL_DIR=content_config.output_dir / "final",
            HISTORY_DIR=content_config.output_dir / "history",
            OUTPUT_DIR=content_config.output_dir,
            ASSET_DIR=content_config.output_dir / "assets",
            VISUAL_FONT_PATH=content_config.visual_font_path,
            WECHAT_APP_ID=os.environ.get("WECHAT_APP_ID"),
            WECHAT_APP_SECRET=os.environ.get("WECHAT_APP_SECRET"),
            WECHAT_API_BASE_URL=os.environ.get(
                "WECHAT_API_BASE_URL", "https://api.weixin.qq.com"
            ),
        )
    else:
        app.config.update(test_config)
        app.config["SESSION_COOKIE_SECURE"] = False
        pack_dir = app.config.get("PACK_DIR")
        if pack_dir:
            set_active_pack(load_pack(pack_dir))
    if not app.config.get("OUTPUT_DIR") and app.config.get("FINAL_DIR"):
        app.config["OUTPUT_DIR"] = Path(app.config["FINAL_DIR"]).parent
    if not app.config.get("ASSET_DIR") and app.config.get("OUTPUT_DIR"):
        app.config["ASSET_DIR"] = Path(app.config["OUTPUT_DIR"]) / "assets"
    required = (
        "SECRET_KEY",
        "REVIEW_USERNAME",
        "REVIEW_PASSWORD_HASH",
        "DATABASE_PATH",
        "FINAL_DIR",
        "HISTORY_DIR",
        "OUTPUT_DIR",
        "ASSET_DIR",
    )
    if any(not app.config.get(name) for name in required):
        raise RuntimeError("review service configuration is incomplete")
    app.extensions["login_limiter"] = LoginLimiter(
        app.config["LOGIN_ATTEMPTS"],
        app.config["LOGIN_WINDOW_SECONDS"],
    )

    store = ContentStore(app.config["DATABASE_PATH"])
    store.initialize()
    repository = ArticleRepository(
        store=store,
        final_dir=Path(app.config["FINAL_DIR"]),
        history_dir=Path(app.config["HISTORY_DIR"]),
        assets_dir=Path(app.config["ASSET_DIR"]),
    )
    app.extensions["article_repository"] = repository
    wechat_client = app.config.get("WECHAT_CLIENT")
    if (
        wechat_client is None
        and app.config.get("WECHAT_APP_ID")
        and app.config.get("WECHAT_APP_SECRET")
    ):
        wechat_client = WechatClient(
            str(app.config["WECHAT_APP_ID"]),
            str(app.config["WECHAT_APP_SECRET"]),
            api_base_url=str(
                app.config.get("WECHAT_API_BASE_URL") or "https://api.weixin.qq.com"
            ),
        )
    app.extensions["wechat_client"] = wechat_client
    minimax_image_client = app.config.get("MINIMAX_IMAGE_CLIENT")
    if minimax_image_client is None and test_config is None:
        minimax_image_client = client_from_env(os.environ)
    app.extensions["minimax_image_client"] = minimax_image_client
    app.register_blueprint(auth)

    @app.errorhandler(ArticleNotFound)
    def article_not_found(_error):
        return jsonify(error="not_found"), 404

    @app.errorhandler(InvalidArticle)
    def invalid_article(error):
        return jsonify(error="invalid_article", detail=str(error)), 400

    @app.errorhandler(ArticleConflict)
    def article_conflict(_error):
        return jsonify(error="version_conflict"), 409

    @app.errorhandler(WechatApiError)
    def wechat_api_error(error):
        return (
            jsonify(
                error="wechat_api_error",
                detail=str(error),
                status="error",
            ),
            502,
        )

    @app.errorhandler(WechatDraftResultUnknown)
    def wechat_draft_result_unknown(error):
        return (
            jsonify(
                error="wechat_draft_result_unknown",
                detail=str(error),
                status="pending",
            ),
            502,
        )

    @app.get("/")
    @login_required
    def review_page():
        return render_template(
            "review.html",
            csrf_token=csrf_token(),
            username=current_app.config["REVIEW_USERNAME"],
        )

    @app.post("/api/preview")
    @login_required
    def preview():
        require_csrf()
        value = request.get_json(silent=True)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("article_id"), str)
            or not isinstance(value.get("markdown"), str)
        ):
            return jsonify(error="invalid_markdown"), 400
        article_id = value["article_id"]
        references = repository.asset_references(article_id)
        asset_urls = {
            asset_id: url_for(
                "article_asset",
                article_id=article_id,
                asset_id=asset_id,
                revision=reference["revision"],
            )
            for asset_id, reference in references.items()
        }
        return jsonify(
            html=render_markdown(
                value["markdown"],
                asset_urls=asset_urls,
            )
        )

    @app.post("/api/rich-preview")
    @login_required
    def rich_preview():
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("article_id"), str):
            return jsonify(error="invalid_request"), 400
        loaded = repository.load_article(value["article_id"])
        payload = loaded["payload"]
        if not isinstance(payload, dict):
            raise InvalidArticle("stored payload must be an object")
        references = repository.asset_references(value["article_id"])
        body_images = [
            (
                url_for(
                    "article_asset",
                    article_id=value["article_id"],
                    asset_id=asset_id,
                    revision=reference["revision"],
                ),
                f"正文配图 {index}",
            )
            for index, (asset_id, reference) in enumerate(
                (
                    item
                    for item in sorted(references.items())
                    if item[0].startswith("body-")
                ),
                start=1,
            )
        ]
        return jsonify(
            html=render_rich_article(
                payload.get("article_layout"),
                fallback_title=payload.get("master_title"),
                fallback_markdown=payload.get("master_markdown"),
                body_images=body_images,
            )
        )

    @app.post("/api/editorial-feedback")
    @login_required
    def editorial_feedback():
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            return jsonify(error="invalid_request"), 400
        title = value.get("title")
        markdown = value.get("markdown")
        if (
            not isinstance(title, str)
            or not isinstance(markdown, str)
            or len(title) > 200_000
            or len(markdown) > 200_000
        ):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            reader_feedback=evaluate_reader_feedback(title, markdown)
        )

    @app.get("/api/articles")
    @login_required
    def list_articles():
        status = request.args.get("status")
        if status is not None and status not in REVIEW_STATUSES:
            return jsonify(error="invalid_status"), 400
        return jsonify(articles=repository.list_articles(status=status))

    @app.get("/api/articles/<article_id>")
    @login_required
    def get_article(article_id: str):
        value = repository.load_article(article_id)
        payload = value.get("payload")
        if not isinstance(payload, dict):
            raise InvalidArticle("stored payload must be an object")
        value["reader_feedback"] = evaluate_reader_feedback(
            str(payload.get("master_title") or ""),
            str(payload.get("master_markdown") or ""),
        )
        value["gpt_polish"] = repository.gpt_polish_status(article_id)
        current = repository.wechat_draft_status(article_id)
        if current is not None and current["status"] == "success":
            value["wechat_draft"] = {
                "status": current["status"],
                "media_id": current["media_id"],
                "error": current["error"],
            }
        elif app.extensions.get("wechat_client") is None:
            value["wechat_draft"] = {"status": "not_configured"}
        elif current is None:
            value["wechat_draft"] = {"status": "not_synced"}
        else:
            value["wechat_draft"] = {
                "status": current["status"],
                "media_id": current["media_id"],
                "error": current["error"],
            }
        return jsonify(value)

    @app.get("/api/articles/<article_id>/assets/<asset_id>/<revision>")
    @login_required
    def article_asset(article_id: str, asset_id: str, revision: str):
        return send_file(
            repository.asset_path(article_id, asset_id, revision),
            conditional=True,
            max_age=31536000,
        )

    @app.put("/api/articles/<article_id>")
    @login_required
    def save_article(article_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            repository.save_article(
                article_id,
                value.get("payload"),
                value["version"],
                operation="edit",
            )
        )

    @app.post("/api/articles/<article_id>/gpt-polish")
    @login_required
    def request_gpt_polish(article_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            gpt_polish=repository.request_gpt_polish(
                article_id, value["version"]
            )
        )

    @app.get("/api/articles/<article_id>/gpt-polish")
    @login_required
    def gpt_polish_status(article_id: str):
        return jsonify(gpt_polish=repository.gpt_polish_status(article_id))

    @app.post("/api/articles/<article_id>/gpt-polish/<job_id>/apply")
    @login_required
    def apply_gpt_polish(article_id: str, job_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            repository.apply_gpt_polish(
                article_id, job_id, value["version"]
            )
        )

    @app.post("/api/articles/<article_id>/gpt-polish/<job_id>/discard")
    @login_required
    def discard_gpt_polish(article_id: str, job_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if value not in ({}, None):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            gpt_polish=repository.discard_gpt_polish(article_id, job_id)
        )

    @app.get("/api/articles/<article_id>/history")
    @login_required
    def list_history(article_id: str):
        return jsonify(history=repository.list_history(article_id))

    @app.post("/api/articles/<article_id>/restore/<history_id>")
    @login_required
    def restore_article(article_id: str, history_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            repository.restore_article(
                article_id,
                history_id,
                value["version"],
            )
        )

    @app.post("/api/articles/<article_id>/visuals/render")
    @login_required
    def render_article_visuals(article_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            return jsonify(error="invalid_request"), 400
        version = value.get("version")
        template = value.get("template")
        copy_index = value.get("copy_index")
        if (
            not isinstance(version, str)
            or len(version) != 64
            or template not in active_pack().visual_templates
            or type(copy_index) is not int
            or not 0 <= copy_index <= 2
        ):
            return jsonify(error="invalid_visual_options"), 400
        font_path = app.config.get("VISUAL_FONT_PATH")
        if not font_path:
            return jsonify(error="visual_font_unavailable"), 503
        loaded = repository.load_article(article_id)
        if not hmac.compare_digest(str(loaded["version"]), version):
            raise ArticleConflict(article_id)
        try:
            render_payload = loaded["payload"]
            if render_payload.get("visual_brief") is None:
                render_payload = dict(render_payload)
                render_payload["visual_brief"] = _minimal_visual_brief(
                    render_payload,
                    template,
                )
            updated = generate_visual_assets(
                payload=render_payload,
                output_dir=Path(app.config["OUTPUT_DIR"]),
                font_path=Path(font_path),
                template_name=template,
                copy_index=copy_index,
                image_client=app.extensions.get("minimax_image_client"),
            )
        except (AssetPublicationError, VisualRenderError, OSError, ValueError):
            return jsonify(error="visual_generation_failed"), 400
        return jsonify(
            repository.save_article(
                article_id,
                updated,
                version,
                operation="visual_edit",
            )
        )

    @app.post("/api/articles/<article_id>/status")
    @login_required
    def set_status(article_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        status = value.get("status") if isinstance(value, dict) else None
        if status not in REVIEW_STATUSES:
            return jsonify(error="invalid_status"), 400
        repository.set_status(article_id, status)
        return jsonify(status=status)

    @app.post("/api/articles/<article_id>/web-edition")
    @login_required
    def export_web_edition(article_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if value not in (None, {}):
            return jsonify(error="invalid_request"), 400
        repository.export_web_edition(article_id)
        return jsonify(
            view_url=url_for("web_edition", article_id=article_id),
            download_url=url_for(
                "web_edition",
                article_id=article_id,
                download="1",
            ),
        )

    @app.post("/api/articles/<article_id>/wechat/draft")
    @login_required
    def sync_wechat_draft(article_id: str):
        require_csrf()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            return jsonify(error="invalid_request"), 400
        client = app.extensions.get("wechat_client")
        if client is None:
            return (
                jsonify(
                    error="wechat_not_configured",
                    status="not_configured",
                    detail="公众号服务尚未配置",
                ),
                503,
            )
        return jsonify(
            repository.sync_wechat_draft(article_id, value["version"], client)
        )

    @app.get("/api/articles/<article_id>/web-edition")
    @login_required
    def web_edition(article_id: str):
        path = repository.web_edition_path(article_id)
        g.web_edition_response = True
        return send_file(
            BytesIO(path.read_bytes()),
            as_attachment=request.args.get("download") == "1",
            download_name=f"{article_id}.html",
            mimetype="text/html",
            conditional=True,
        )

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            WEB_EDITION_CSP if getattr(g, "web_edition_response", False) else REVIEW_CSP
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    return app
