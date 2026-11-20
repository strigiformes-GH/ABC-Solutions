from models import PasswordResetToken
from database.create_db import db


def test_t05_password_recovery_request_is_generic_and_creates_request(client, app, make_user, csrf):
    user_id = make_user("Employee", username="resetme")
    token = csrf("/password-reset/request")
    response = client.post("/password-reset/request", data={"username_or_email": "resetme", "csrf_token": token})
    assert response.status_code == 200
    with app.app_context():
        reset = db.session.query(PasswordResetToken).filter_by(user_id=user_id).one()
        assert reset.token_hash is None
    response = client.post("/password-reset/request", data={"username_or_email": "unknown", "csrf_token": token})
    assert response.status_code == 200
    assert b"If an account exists" in response.data
    assert b"resetme" not in response.data
    assert b"unknown" not in response.data
