from models import InventoryItem, Log
from database.create_db import db


def test_t09_update_item_changes_saved_and_invalid_values_rejected(client, app, make_user, login_as, csrf, make_item):
    item_id = make_item()
    login_as(make_user("Manager"))
    token = csrf("/app/inventory/edit")
    form = {"item_id": str(item_id), "sku": "SKU-1", "name": "Updated name", "price": "4.00", "quantity": "10", "reorder_level": "2", "csrf_token": token}
    assert client.post("/inventory/save", data=form).status_code == 302
    with app.app_context():
        assert db.session.get(InventoryItem, item_id).name == "Updated name"
        assert db.session.query(Log).filter_by(action="INVENTORY_UPDATED", entity_id=item_id).one()
    assert client.post("/inventory/save", data={**form, "price": "NaN", "csrf_token": token}).status_code == 400
