import time
from crypto_ai_bot.utils.time import now_ms, bucket_ms, iso_utc, check_sync

def test_now_ms():
    """Тест текущего времени в миллисекундах."""
    ts = now_ms()
    assert isinstance(ts, int)
    assert ts > 1600000000000  # После 2020 года
    assert ts < 2000000000000  # До 2033 года

def test_bucket_ms():
    """Тест округления времени к bucket."""
    ts = 1700000123456
    
    # Округление к минуте
    bucket_1m = bucket_ms(ts, 60000)
    assert bucket_1m == 1700000100000
    
    # Округление к 5 минутам
    bucket_5m = bucket_ms(ts, 300000)
    assert bucket_5m == 1700000100000
    
    # Округление к часу
    bucket_1h = bucket_ms(ts, 3600000)
    assert bucket_1h == 1699996800000

def test_iso_utc():
    """Тест преобразования в ISO формат."""
    ts = 1700000000000
    iso = iso_utc(ts)
    assert isinstance(iso, str)
    assert "2023-11" in iso  # Ноябрь 2023
    assert iso.endswith("+00:00")  # UTC

def test_check_sync():
    """Тест проверки синхронизации времени."""
    # Без remote provider
    drift = check_sync()
    assert drift is None
    
    # С mock remote
    def remote():
        return now_ms() - 1000  # Remote отстает на 1 секунду
    
    drift = check_sync(remote)
    assert drift is not None
    assert drift >= 900  # Примерно 1000ms разницы
    assert drift <= 1100