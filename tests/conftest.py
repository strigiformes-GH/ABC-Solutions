# shared for tests


from models import Customer, InventoryItem, Role, User
from database.create_db import db
from app import app as flask_app
import pytest
from decimal import Decimal
from datetime import UTC, datetime
import os


os.environ.setdefault("SECRET_KEY", "test-only-secret-key-never-deploy")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["MFA_REQUIRED"] = "false"


@pytest.fixture(autouse=True)  # create db in-memory for each test
def isolated_database():
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        for name in ("Admin", "Manager", "Business", "Employee"):
            db.session.add(Role(name=name))
        db.session.commit()
    yield
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    def create(role="Employee", *, username=None, active=True, mfa=False):
        with app.app_context():
            role_row = db.session.query(Role).filter_by(name=role).one()
            user = User(
                first_name="Test", last_name="User",
                username=username or f"{role.lower()}user",
                email=f"{username or role.lower()}@example.test",
                password_hash="test-hash", role_id=role_row.role_id,
                is_active=active, mfa_enabled=mfa,
                mfa_secret="JBSWY3DPEHPK3PXP" if mfa else None,
                password_changed_at=datetime.now(UTC),
            )
            db.session.add(user)
            db.session.commit()
            return user.user_id
    return create


@pytest.fixture
def make_item(app):
    def create(*, name="Test item", sku="SKU-1", price="3.50", quantity=10,
               reorder_level=2, active=True):
        with app.app_context():
            item = InventoryItem(name=name, sku=sku, price=Decimal(price),
                                 quantity=quantity, reorder_level=reorder_level,
                                 is_active=active)
            db.session.add(item)
            db.session.commit()
            return item.item_id
    return create


@pytest.fixture
def make_customer(app):
    def create(*, name="Taylor Example", email="taylor@example.test", phone="0123456789", active=True):
        with app.app_context():
            customer = Customer(name=name, email=email,
                                phone=phone, is_active=active)
            db.session.add(customer)
            db.session.commit()
            return customer.customer_id
    return create


@pytest.fixture
def login_as(client, app):
    def login(user_id):
        with app.app_context():
            user = db.session.get(User, user_id)
            auth_at = user.password_changed_at.timestamp()
        with client.session_transaction() as state:
            state["_user_id"] = str(user_id)
            state["_fresh"] = True
            state["auth_at"] = auth_at
        return client
    return login


@pytest.fixture
def csrf(client):
    def token(path="/login"):
        client.get(path)
        with client.session_transaction() as state:
            return state["csrf_token"]
    return token
