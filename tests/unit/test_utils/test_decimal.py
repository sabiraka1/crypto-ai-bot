import pytest
from decimal import Decimal
from crypto_ai_bot.utils.decimal import dec

def test_decimal_basic_operations():
    '''Test basic decimal operations'''
    assert dec('100.50') * dec('0.1') == dec('10.05')
    assert dec('1.1') + dec('2.2') == dec('3.3')
    assert dec('10') - dec('3') == dec('7')
    assert dec('10') / dec('2') == dec('5')

def test_decimal_precision():
    '''Test decimal precision handling'''
    result = dec('0.1') + dec('0.2')
    assert result == dec('0.3')
    assert isinstance(result, Decimal)

def test_decimal_string_conversion():
    '''Test conversion from string'''
    assert dec('123.456') == Decimal('123.456')
    assert dec('0.001') == Decimal('0.001')
