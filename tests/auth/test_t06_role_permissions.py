import pytest


@pytest.mark.parametrize("role,path,expected", [
    ("Business", "/app/customers", 403), ("Employee", "/app/reports", 403),
    ("Employee", "/app/logs", 403), ("Business", "/app/reports", 200),
    ("Manager", "/app/reports", 200),
])
def test_t06_server_enforces_role_access(client, make_user, login_as, role, path, expected):
    login_as(make_user(role))
    assert client.get(path).status_code == expected
