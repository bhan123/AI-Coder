from __future__ import annotations

from collections import defaultdict, deque
from functools import wraps
import hmac
import secrets
import threading
import time

from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash


auth = Blueprint("auth", __name__)


class LoginLimiter:
    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def blocked(self, key: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            queue = self.failures[key]
            while queue and current - queue[0] >= self.window_seconds:
                queue.popleft()
            return len(queue) >= self.attempts

    def fail(self, key: str) -> None:
        with self._lock:
            self.failures[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self.failures.pop(key, None)


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_csrf() -> None:
    supplied = request.headers.get("X-CSRF-Token")
    if request.form:
        supplied = request.form.get("csrf_token", supplied)
    if not isinstance(supplied, str) or not hmac.compare_digest(
        supplied,
        csrf_token(),
    ):
        abort(403)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("authenticated") is not True:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def _client_key() -> str:
    remote = request.remote_addr or "unknown"
    if remote in {"127.0.0.1", "::1"}:
        forwarded = request.headers.get("X-Forwarded-For", "")
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    return remote


@auth.route("/login", methods=["GET", "POST"])
def login():
    error = None
    status = 200
    token = csrf_token()
    if request.method == "POST":
        require_csrf()
        limiter: LoginLimiter = current_app.extensions["login_limiter"]
        key = _client_key()
        if limiter.blocked(key):
            error = "登录尝试过多，请稍后再试。"
            status = 429
        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            username_ok = hmac.compare_digest(
                username,
                current_app.config["REVIEW_USERNAME"],
            )
            password_ok = check_password_hash(
                current_app.config["REVIEW_PASSWORD_HASH"],
                password,
            )
            if username_ok and password_ok:
                limiter.clear(key)
                session.clear()
                session["authenticated"] = True
                session.permanent = True
                csrf_token()
                return redirect(url_for("review_page"))
            limiter.fail(key)
            error = "用户名或密码错误。"
            status = 401
    return (
        render_template(
            "login.html",
            error=error,
            csrf_token=token,
        ),
        status,
    )


@auth.post("/logout")
@login_required
def logout():
    require_csrf()
    session.clear()
    return redirect(url_for("auth.login"))
