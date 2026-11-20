from click.testing import CliRunner
from models import Customer, Log
from database.create_db import db


def test_t25_customer_anonymisation_preserves_record_and_removes_identifiers(app, make_customer):
    customer_id = make_customer()
    runner = CliRunner()
    result = runner.invoke(app.cli, ["features", "anonymise-customer", str(customer_id)])
    assert result.exit_code == 0
    with app.app_context():
        customer = db.session.get(Customer, customer_id)
        assert customer.name == "Anonymised customer"
        assert customer.email.endswith("@invalid.example")
        assert customer.phone is None and not customer.is_active
        assert db.session.query(Log).filter_by(action="CUSTOMER_ANONYMISED", entity_id=customer_id).one()
