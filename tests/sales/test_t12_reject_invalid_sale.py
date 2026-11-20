from models import InventoryItem, Sale
from database.create_db import db


def test_t12_empty_invalid_and_insufficient_sales_do_not_change_stock(client, app, make_user, login_as, csrf, make_item):
    item_id = make_item(quantity=2)
    login_as(make_user("Employee"))
    token = csrf("/app/sales/new")
    base = {"csrf_token": token, "submission_token": "b" * 32}
    empty = client.post("/sales/create", data={**base, "item_id": [""], "quantity": [""]})
    assert empty.status_code == 302
    invalid = client.post("/sales/create", data={**base, "item_id": [str(item_id)], "quantity": ["-1"]})
    assert invalid.status_code == 400
    unavailable = client.post("/sales/create", data={**base, "item_id": [str(item_id)], "quantity": ["3"]})
    assert unavailable.status_code == 302
    with app.app_context():
        assert db.session.query(Sale).count() == 0
        assert db.session.get(InventoryItem, item_id).quantity == 2
