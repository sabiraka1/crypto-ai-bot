import pytest
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker, State
from crypto_ai_bot.utils.exceptions import CircuitOpenError, TransientError

def test_circuit_breaker_closed_state():
    """Тест закрытого состояния."""
    cb = CircuitBreaker(failures_threshold=3)
    
    assert cb.state == State.CLOSED
    assert cb.allow() is True
    
    # Успешный вызов
    result = cb.run(lambda: "success")
    assert result == "success"

def test_circuit_breaker_opens_on_failures():
    """Тест открытия при ошибках."""
    cb = CircuitBreaker(failures_threshold=2)
    
    def failing():
        raise TransientError("fail")
    
    # Первая ошибка
    with pytest.raises(TransientError):
        cb.run(failing)
    assert cb.state == State.CLOSED
    
    # Вторая ошибка - открывается
    with pytest.raises(TransientError):
        cb.run(failing)
    assert cb.state == State.OPEN
    
    # Теперь не разрешает вызовы
    with pytest.raises(CircuitOpenError):
        cb.run(lambda: "test")

@pytest.mark.asyncio
async def test_circuit_breaker_async():
    """Тест с async функциями."""
    cb = CircuitBreaker(failures_threshold=2)
    
    async def async_success():
        return "async_result"
    
    result = await cb.run_async(async_success)
    assert result == "async_result"
    
    async def async_fail():
        raise TransientError("async fail")
    
    with pytest.raises(TransientError):
        await cb.run_async(async_fail)

def test_circuit_breaker_half_open():
    """Тест half-open состояния."""
    cb = CircuitBreaker(
        failures_threshold=2,
        open_timeout_ms=100,
        half_open_successes_to_close=2
    )
    
    def failing():
        raise TransientError("fail")
    
    # Открываем circuit
    for _ in range(2):
        try:
            cb.run(failing)
        except:
            pass
    
    assert cb.state == State.OPEN
    
    # Ждем timeout
    import time
    time.sleep(0.15)
    
    # Должен перейти в half-open и разрешить попытку
    assert cb.allow() is True
    
    # Успешный вызов в half-open
    cb.run(lambda: "success")
    cb.on_success()  # Второй успех
    
    # Должен закрыться после 2 успехов
    assert cb.state == State.CLOSED