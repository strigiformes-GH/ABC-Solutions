from datetime import UTC, datetime, timedelta
from models import User
from database.create_db import db


def test_t02_inactive_and_locked_accounts_are_denied(client, app, make_user, csrf):
    inactive_id = make_user("Employee", username="inactive", active=False)
    locked_id = make_user("Employee", username="locked")
    with app.app_context():
        locked = db.session.get(User, locked_id)
        locked.locked_until = datetime.now(UTC) + timedelta(minutes=5)
        db.session.commit()
    token = csrf()
    for username in ("inactive", "locked", "missing"):
        response = client.post("/login", data={"username": username, "password": "wrong", "csrf_token": token})
        assert response.status_code == 401
        assert b"Sign in failed" in response.data
    assert inactive_id != locked_id
