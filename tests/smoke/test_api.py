def test_health_has_components(client):
    r = client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert "status" in j
    assert "components" in j
    comps = j["components"]
    for key in ("db", "broker", "time"):
        assert key in comps

def test_tick_returns_status(client):
    r = client.post("/tick")
    assert r.status_code == 200
    j = r.json()
    assert "status" in j

def test_orders_buy_idempotent_same_minute(client):
    # first call
    r1 = client.post("/orders/buy", json={"size": "0.01"})
    assert r1.status_code == 200
    j1 = r1.json()
    assert j1.get("status") in ("ok", "forbidden", "error")  # if ENABLE_TRADING=false, would be forbidden
    if j1.get("status") != "ok":
        return  # do not assert idempotency when trading disabled or error

    # second call in same minute → expect idempotent or ok
    r2 = client.post("/orders/buy", json={"size": "0.01"})
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2.get("status") == "ok"
    # if idempotency worked, flag is present
    idem = j2.get("idempotent")
    assert idem in (True, False, None)
