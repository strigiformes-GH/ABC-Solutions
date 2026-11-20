from models import DeletionRequest, InventoryItem
from database.create_db import db


def test_t10_employee_archive_is_request_and_manager_can_archive(client, app, make_user, login_as, csrf, make_item):
    item_id = make_item()
    login_as(make_user("Employee"))
    token = csrf(f"/app/inventory/archive?item_id={item_id}")
    assert client.post(f"/inventory/{item_id}/delete", data={"csrf_token": token}).status_code == 302
    with app.app_context():
        assert db.session.get(InventoryItem, item_id).is_active
        request_id = db.session.query(DeletionRequest).filter_by(
            entity_type="INVENTORY",
            entity_id=item_id,
            status="PENDING",
        ).one().request_id
    login_as(make_user("Manager"))
    assert client.post(
        f"/approvals/deletion/{request_id}/approve",
        data={"csrf_token": csrf("/app/approvals")},
    ).status_code == 302
    with app.app_context():
        assert not db.session.get(InventoryItem, item_id).is_active
