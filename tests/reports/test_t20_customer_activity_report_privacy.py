def test_t20_customer_report_aggregates_and_masks_small_business_groups(client, app, make_user, login_as):
    from services.reporting import hide_small
    assert hide_small(1, "Business") == "Fewer than 3"
    assert hide_small(3, "Business") == 3
    login_as(make_user("Business"))
    response = client.get("/app/reports/customers")
    assert response.status_code == 200
