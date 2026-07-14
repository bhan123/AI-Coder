from werkzeug.security import generate_password_hash

from ai_content_loop.review.app import create_app


def make_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "REVIEW_USERNAME": "owner",
            "REVIEW_PASSWORD_HASH": generate_password_hash("correct horse"),
            "DATABASE_PATH": tmp_path / "content.sqlite3",
            "FINAL_DIR": tmp_path / "final",
            "HISTORY_DIR": tmp_path / "history",
            "LOGIN_ATTEMPTS": 2,
            "LOGIN_WINDOW_SECONDS": 300,
        }
    )


def csrf_from(client):
    with client.session_transaction() as session:
        return session["csrf_token"]


def login(client):
    client.get("/login")
    return client.post(
        "/login",
        data={
            "username": "owner",
            "password": "correct horse",
            "csrf_token": csrf_from(client),
        },
        follow_redirects=False,
    )


def test_login_and_logout(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    login_page = client.get("/login")
    assert login_page.status_code == 200
    token = csrf_from(client)

    response = client.post(
        "/login",
        data={
            "username": "owner",
            "password": "correct horse",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200

    response = client.post(
        "/logout",
        headers={"X-CSRF-Token": csrf_from(client)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert client.get("/").status_code == 302


def test_write_request_requires_csrf(tmp_path):
    client = make_app(tmp_path).test_client()
    login(client)

    response = client.post("/api/preview", json={"markdown": "# 标题"})

    assert response.status_code == 403


def test_login_is_throttled_after_repeated_failure(tmp_path):
    client = make_app(tmp_path).test_client()
    client.get("/login")
    for _ in range(2):
        response = client.post(
            "/login",
            data={
                "username": "owner",
                "password": "wrong",
                "csrf_token": csrf_from(client),
            },
        )
        assert response.status_code == 401

    response = client.post(
        "/login",
        data={
            "username": "owner",
            "password": "correct horse",
            "csrf_token": csrf_from(client),
        },
    )
    assert response.status_code == 429


def test_api_requires_authentication_without_redirecting_to_html(tmp_path):
    client = make_app(tmp_path).test_client()

    response = client.post("/api/preview", json={"markdown": "# 标题"})

    assert response.status_code == 401


def test_login_rejects_missing_csrf(tmp_path):
    client = make_app(tmp_path).test_client()

    response = client.post(
        "/login",
        data={"username": "owner", "password": "correct horse"},
    )

    assert response.status_code == 403


def test_login_page_does_not_echo_password_hash(tmp_path):
    app = make_app(tmp_path)

    html = app.test_client().get("/login").get_data(as_text=True)

    assert app.config["REVIEW_PASSWORD_HASH"] not in html
    assert 'name="csrf_token"' in html
