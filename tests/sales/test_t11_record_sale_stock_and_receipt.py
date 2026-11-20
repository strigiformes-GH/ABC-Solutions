from models import InventoryItem, Sale, SaleItem
from database.create_db import db


def test_t11_sale_records_totals_receipt_and_reduces_stock(client, app, make_user, login_as, csrf, make_item):
    item_id = make_item(price="2.50", quantity=8)
    login_as(make_user("Employee"))
    token = csrf("/app/sales/new")
    form = {"csrf_token": token, "submission_token": "a" * 32, "item_id": [str(item_id)], "quantity": ["3"]}
    response = client.post("/sales/create", data=form)
    assert response.status_code == 302
    with app.app_context():
        sale = db.session.query(Sale).one()
        assert str(sale.total) == "7.50"
        assert db.session.get(InventoryItem, item_id).quantity == 5
        assert db.session.query(SaleItem).filter_by(sale_id=sale.sale_id, quantity=3).one()
    assert b"Test item" in client.get(response.location).data
