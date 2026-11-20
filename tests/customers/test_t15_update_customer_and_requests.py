from models import Customer, CustomerChangeRequest
from database.create_db import db


def test_t15_employee_edit_request_waits_for_authorized_approval(client, app, make_user, login_as, csrf, make_customer):
    customer_id = make_customer()
    login_as(make_user("Employee"))
    token = csrf("/app/customers/edit-request")
    form = {"first_name": "Taylor", "last_name": "Updated", "email": "updated@example.com", "phone": "0123456789", "csrf_token": token}
    assert client.post(f"/customers/{customer_id}/edit-request", data=form).status_code == 302
    with app.app_context():
        change = db.session.query(CustomerChangeRequest).filter_by(customer_id=customer_id).one()
        request_id = change.request_id
        assert db.session.get(Customer, customer_id).email == "taylor@example.test"
    login_as(make_user("Manager"))
    assert client.post(f"/approvals/customer-edit/{request_id}/approve", data={"csrf_token": csrf("/app/approvals")}).status_code == 302
    with app.app_context():
        assert db.session.get(Customer, customer_id).email == "updated@example.com"
