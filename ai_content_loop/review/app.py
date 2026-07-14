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

from ai_content_loop.config import load_config
from ai_content_loop.db import ContentStore
from ai_content_loop.review.auth import (
    LoginLimiter,
    auth,
    csrf_token,
    login_required,
    require_csrf,
)
from ai_content_loop.review.rendering import render_markdown
from ai_content_loop.review.rich_article import render_rich_article
from ai_content_loop.review.repository import (
    ArticleConflict,
    ArticleNotFound,
    ArticleRepository,
    InvalidArticle,
)
from ai_content_loop.visuals.assets import AssetPublicationError
from ai_content_loop.visuals.pipeline import generate_visual_assets
from ai_content_loop.visuals.renderer import VisualRenderError
from ai_content_loop.visuals.templates import TEMPLATES


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
            "AI_CONTENT_CONFIG",
            "ai_content_loop/config.example.toml",
        )
        content_config = load_config(config_path)
        app.config.update(
            SECRET_KEY=os.environ.get("AI_CONTENT_REVIEW_SECRET_KEY"),
            REVIEW_USERNAME=os.environ.get("AI_CONTENT_REVIEW_USERNAME"),
            REVIEW_PASSWORD_HASH=os.environ.get(
                "AI_CONTENT_REVIEW_PASSWORD_HASH"
            ),
            DATABASE_PATH=content_config.database_path,
            FINAL_DIR=content_config.output_dir / "final",
            HISTORY_DIR=content_config.output_dir / "history",
            OUTPUT_DIR=content_config.output_dir,
            ASSET_DIR=content_config.output_dir / "assets",
            VISUAL_FONT_PATH=content_config.visual_font_path,
        )
    else:
        app.config.update(test_config)
        app.config["SESSION_COOKIE_SECURE"] = False
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
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("article_id"), str)
        ):
            return jsonify(error="invalid_request"), 400
        loaded = repository.load_article(value["article_id"])
        payload = loaded["payload"]
        if not isinstance(payload, dict):
            raise InvalidArticle("stored payload must be an object")
        return jsonify(
            html=render_rich_article(
                payload.get("article_layout"),
                fallback_title=payload.get("master_title"),
                fallback_markdown=payload.get("master_markdown"),
            )
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
        return jsonify(repository.load_article(article_id))

    @app.get(
        "/api/articles/<article_id>/assets/<asset_id>/<revision>"
    )
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
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("version"), str)
        ):
            return jsonify(error="invalid_request"), 400
        return jsonify(
            repository.save_article(
                article_id,
                value.get("payload"),
                value["version"],
                operation="edit",
            )
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
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("version"), str)
        ):
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
            or template not in TEMPLATES
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
            updated = generate_visual_assets(
                payload=loaded["payload"],
                output_dir=Path(app.config["OUTPUT_DIR"]),
                font_path=Path(font_path),
                template_name=template,
                copy_index=copy_index,
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
            WEB_EDITION_CSP
            if getattr(g, "web_edition_response", False)
            else REVIEW_CSP
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    return app
