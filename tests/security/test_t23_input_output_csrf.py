from models import Customer
from database.create_db import db


def test_t23_csrf_required_and_user_text_is_escaped(client, app, make_user, login_as, csrf):
    login_as(make_user("Employee"))
    no_token = client.post("/customers/save", data={"first_name": "Safe", "last_name": "Person", "email": "safe@example.test"})
    assert no_token.status_code == 400
    token = csrf("/app/customers")
    response = client.post("/customers/save", data={"first_name": "Safe", "last_name": "<script>alert(1)</script>", "email": "script@example.com", "csrf_token": token})
    assert response.status_code == 302
    listing = client.get("/app/customers")
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in listing.data
    with app.app_context():
        assert db.session.query(Customer).filter_by(email="script@example.com").count() == 1
