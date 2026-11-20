from models import Customer, DeletionRequest
from database.create_db import db


def test_t16_employee_customer_archive_requires_approval(client, app, make_user, login_as, csrf, make_customer):
    customer_id = make_customer()
    login_as(make_user("Employee"))
    assert client.post(f"/customers/{customer_id}/delete", data={"csrf_token": csrf("/app/customers")}).status_code == 302
    with app.app_context():
        request_id = db.session.query(DeletionRequest).filter_by(entity_type="CUSTOMER", entity_id=customer_id).one().request_id
        assert db.session.get(Customer, customer_id).is_active
    login_as(make_user("Manager"))
    assert client.post(f"/approvals/deletion/{request_id}/approve", data={"csrf_token": csrf("/app/approvals")}).status_code == 302
    with app.app_context():
        assert not db.session.get(Customer, customer_id).is_active
