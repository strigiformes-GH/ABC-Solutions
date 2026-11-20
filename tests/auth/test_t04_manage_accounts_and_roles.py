from models import Log, User
from database.create_db import db


def test_t04_admin_can_create_user_but_cannot_deactivate_self(client, app, make_user, login_as, csrf):
    admin_id = make_user("Admin", username="admin")
    login_as(admin_id)
    token = csrf("/app/users/create")
    response = client.post("/admin/users/create", data={"csrf_token": token, "first_name": "New", "last_name": "Staff",
        "username": "newstaff", "email": "newstaff@example.com", "role": "Employee", "password": "Long-password-123"})
    assert response.status_code == 302
    with app.app_context():
        created = db.session.query(User).filter_by(username="newstaff").one()
        assert created.is_active
        assert db.session.query(Log).filter_by(action="USER_REGISTERED", entity_id=created.user_id).one()
    token = csrf("/app/users")
    response = client.post(
        f"/admin/users/{admin_id}/deactivate",
        data={"csrf_token": token},
    )
    assert response.status_code == 403
    with app.app_context():
        assert db.session.get(User, admin_id).is_active
