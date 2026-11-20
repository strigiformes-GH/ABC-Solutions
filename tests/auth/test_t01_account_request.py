from models import User
from database.create_db import db


def test_t01_valid_account_request_is_pending_and_duplicates_are_rejected(client, app, csrf):
    form = {"first_name": "Katie", "last_name": "Example", "email": "katie@example.com",
            "username": "katieexample", "requested_role": "EMPLOYEE",
            "password": "A-long-test-password-1", "confirm_password": "A-long-test-password-1"}
    response = client.post("/register", data={**form, "csrf_token": csrf()})
    assert response.status_code == 302
    with app.app_context():
        user = db.session.query(User).filter_by(username="katieexample").one()
        assert user.is_active is False
    response = client.post("/register", data={**form, "csrf_token": csrf()})
    assert b"Cannot create an account" in response.data
    response = client.post("/register", data={**form, "email": "bad", "csrf_token": csrf()})
    assert b"Check and complete" in response.data
