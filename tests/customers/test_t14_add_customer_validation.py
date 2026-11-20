from models import Customer
from database.create_db import db


def test_t14_customer_create_validates_contact_fields(client, app, make_user, login_as, csrf):
    login_as(make_user("Employee"))
    token = csrf("/app/customers")
    form = {"first_name": "Sam", "last_name": "Example", "email": "sam@example.com", "phone": "+441234567890", "csrf_token": token}
    assert client.post("/customers/save", data=form).status_code == 302
    with app.app_context():
        assert db.session.query(Customer).filter_by(email="sam@example.com").count() == 1
    assert client.post("/customers/save", data={**form, "email": "invalid", "csrf_token": token}).status_code == 400
    login_as(make_user("Business"))
    assert client.get("/app/customers").status_code == 403
