from models import Sale
from database.create_db import db
from decimal import Decimal


def test_t13_sales_history_access_and_search_validation(client, app, make_user, login_as, csrf):
    manager_id = make_user("Manager")
    login_as(manager_id)
    token = csrf("/app/sales/new")
    with app.app_context():
        sale = Sale(user_id=manager_id, total=Decimal("1.00"), submission_token="c" * 32)
        db.session.add(sale); db.session.commit(); sale_id = sale.sale_id
    assert str(sale_id).encode() in client.get(f"/app/sales/history?sale_id={sale_id}").data
    assert client.get("/app/sales/history?sale_id=invalid").status_code == 400
    login_as(make_user("Employee"))
    assert client.get("/app/sales/history").status_code == 403
