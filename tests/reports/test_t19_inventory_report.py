def test_t19_inventory_report_shows_stock_states(client, make_user, login_as, make_item):
    make_item(name="Available", sku="A", quantity=10, reorder_level=2)
    make_item(name="Low", sku="L", quantity=1, reorder_level=2)
    make_item(name="Empty", sku="E", quantity=0, reorder_level=2)
    login_as(make_user("Business"))
    response = client.get("/app/reports/inventory")
    assert response.status_code == 200
    assert b"Available" in response.data and b"Low" in response.data and b"Empty" in response.data
