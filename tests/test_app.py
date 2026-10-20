import app as biashara


def test_password_recovery_pages_render():
    biashara.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SECRET_KEY="test-secret")
    client = biashara.app.test_client()
    assert client.get("/forgot-password").status_code == 200
    assert client.get("/reset-password").status_code == 200


def test_password_recovery_has_security_headers():
    biashara.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SECRET_KEY="test-secret")
    response = biashara.app.test_client().get("/forgot-password")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


def test_reset_form_has_one_time_code_fields():
    biashara.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SECRET_KEY="test-secret")
    response = biashara.app.test_client().get("/reset-password")
    assert b'name="code"' in response.data
    assert b'name="confirm_password"' in response.data
