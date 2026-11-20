def test_t03_logout_clears_session_and_protected_pages_redirect(client, app, make_user, login_as, csrf):
    user_id = make_user("Manager")
    login_as(user_id)
    token = csrf("/app/inventory")
    response = client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert client.get("/app/inventory").status_code == 302
    with client.session_transaction() as state:
        assert "_user_id" not in state

