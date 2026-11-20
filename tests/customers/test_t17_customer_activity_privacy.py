def test_t17_customer_activity_is_staff_only_and_business_cannot_identify_customer(client, make_user, login_as, csrf, make_customer):
    customer_id = make_customer()
    login_as(make_user("Manager"))
    assert b"Taylor Example" in client.get(f"/app/customers/activity?customer_id={customer_id}").data
    login_as(make_user("Business"))
    assert client.get(f"/app/customers/activity?customer_id={customer_id}").status_code == 403
