from models import InventoryItem
from database.create_db import db


def test_t08_add_item_validates_fields_and_role(client, app, make_user, login_as, csrf):
    login_as(make_user("Manager"))
    token = csrf("/app/inventory/edit")
    form = {"sku": "NEW-1", "name": "New item", "price": "4.25", "quantity": "5", "reorder_level": "1", "csrf_token": token}
    assert client.post("/inventory/save", data=form).status_code == 302
    with app.app_context():
        assert db.session.query(InventoryItem).filter_by(sku="NEW-1").one().quantity == 5
    response = client.post("/inventory/save", data={**form, "sku": "NEW-2", "price": "-1", "csrf_token": token})
    assert response.status_code == 400
    assert client.post("/inventory/save", data={**form, "csrf_token": token}).status_code == 302
    login_as(make_user("Business"))
    assert client.post("/inventory/save", data={**form, "sku": "BIZ-1", "csrf_token": csrf("/app/inventory")}).status_code == 403
