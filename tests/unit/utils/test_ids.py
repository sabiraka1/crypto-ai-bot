from crypto_ai_bot.utils.ids import make_client_order_id

def test_make_client_order_id():
    cid = make_client_order_id("gateio", "BTC/USDT:buy")
    assert cid.startswith("gateio-")
    assert "BTC-USDT-buy" in cid
    assert len(cid) < 64
    
def test_client_order_id_safe_chars():
    cid = make_client_order_id("test", "weird!@#$%chars")
    assert all(c.isalnum() or c == '-' for c in cid)