from models import InventoryItem
from database.create_db import db


def test_t07_inventory_search_filter_and_empty_state(client, app, make_user, login_as, make_item):
    low_id = make_item(name="Tea", sku="TEA-1", quantity=2, reorder_level=3)
    make_item(name="Coffee", sku="COF-1", quantity=20)
    login_as(make_user("Employee"))
    assert b"Tea" in client.get("/app/inventory?q=tea").data
    assert b"Coffee" not in client.get("/app/inventory?q=tea").data
    assert b"Tea" in client.get("/app/inventory?low=1").data
    assert b"No items match the filters" in client.get("/app/inventory?q=not-found").data
    with app.app_context():
        assert db.session.get(InventoryItem, low_id).quantity == 2
