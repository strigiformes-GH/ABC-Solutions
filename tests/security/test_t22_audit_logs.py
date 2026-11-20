from models import Log
from database.create_db import db


def test_t22_only_admin_can_review_audit_logs(client, app, make_user, login_as):
    admin_id = make_user("Admin")
    with app.app_context():
        db.session.add(Log(user_id=admin_id, action="TEST_EVENT", entity_type="USER", entity_id=admin_id))
        db.session.commit()
    login_as(admin_id)
    assert client.get("/app/logs").status_code == 200
    assert b"TEST_EVENT" in client.get("/app/logs").data
    login_as(make_user("Manager"))
    assert client.get("/app/logs").status_code == 403
