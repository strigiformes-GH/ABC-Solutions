def test_t21_business_can_view_reports_and_employee_is_denied(client, make_user, login_as):
    login_as(make_user("Business"))
    assert client.get("/app/reports/inventory").status_code == 200
    login_as(make_user("Employee"))
    assert client.get("/app/reports/inventory").status_code == 403
    assert not any(rule.rule.endswith("/export") for rule in client.application.url_map.iter_rules())
