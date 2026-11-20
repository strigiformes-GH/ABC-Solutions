from models import Sale
from database.create_db import db
from decimal import Decimal


def test_t18_sales_report_date_bounds_and_employee_access(client, app, make_user, login_as):
    manager_id = make_user("Manager")
    with app.app_context():
        db.session.add(Sale(user_id=manager_id, total=Decimal("12.00"), submission_token="d" * 32))
        db.session.commit()
    login_as(manager_id)
    assert client.get("/app/reports").status_code == 200
    assert client.get("/app/reports?from_date=not-a-date").status_code == 400
    assert client.get("/app/reports?from_date=2026-02-01&to_date=2026-01-01").status_code == 400
    login_as(make_user("Employee"))
    assert client.get("/app/reports").status_code == 403
