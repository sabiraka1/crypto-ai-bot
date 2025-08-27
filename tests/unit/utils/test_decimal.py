from decimal import Decimal
import pytest
from crypto_ai_bot.utils.decimal import dec, q_step

def test_dec_conversion():
    assert dec("100.50") == Decimal("100.50")
    assert dec(100.5) == Decimal("100.5")
    assert dec(None) == Decimal("0")
    assert dec(Decimal("42")) == Decimal("42")

def test_q_step():
    assert q_step(Decimal("100.12345"), 2) == Decimal("100.12")
    assert q_step(Decimal("0.00123456"), 8) == Decimal("0.00123456")
    assert q_step(Decimal("999.999"), 0) == Decimal("999")