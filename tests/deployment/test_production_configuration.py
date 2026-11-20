import pytest
from config import validate_production


def production_config():
    return dict(APP_ENV="production", SECRET_KEY="a" * 64,
                SQLALCHEMY_DATABASE_URI="postgresql+psycopg://user:pass@db/app",
                SESSION_COOKIE_SECURE=True, MFA_REQUIRED=True,
                TRUSTED_HOSTS=["app.example.com"], AUTO_INIT_DB=False)


@pytest.mark.parametrize("key,value", [  # pass unsafe config to ensure it is rejected
    ("SECRET_KEY", "short"), ("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:"),
    ("SESSION_COOKIE_SECURE", False), ("MFA_REQUIRED", False),
    ("TRUSTED_HOSTS", None), ("AUTO_INIT_DB", True),
])
def test_unsafe_production_configuration_is_rejected(key, value):
    settings = production_config()
    settings[key] = value
    with pytest.raises(RuntimeError):
        validate_production(settings)


def test_valid_production_configuration_is_accepted():
    validate_production(production_config())
