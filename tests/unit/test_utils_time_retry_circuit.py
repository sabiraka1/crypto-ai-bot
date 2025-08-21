## `tests/unit/test_utils_time_retry_circuit.py`
import time
from crypto_ai_bot.utils.time import now_ms, bucket_ms, monotonic_ms
from crypto_ai_bot.utils.retry import retry
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker, State
from crypto_ai_bot.utils.exceptions import TransientError
def test_now_and_monotonic_increase():
    t1, m1 = now_ms(), monotonic_ms()
    time.sleep(0.01)
    t2, m2 = now_ms(), monotonic_ms()
    assert t2 >= t1 and m2 > m1
def test_bucket_ms_floor():
    b = bucket_ms(1_699_920_123_456, 60_000)
    assert b % 60_000 == 0
def test_retry_eventually_succeeds():
    calls = {"n": 0}
    @retry(attempts=3, backoff_base=0.01)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise TransientError("temp")
        return "ok"
    assert flaky() == "ok" and calls["n"] == 2
def test_circuit_breaker_states():
    br = CircuitBreaker(failures_threshold=1, open_timeout_ms=50, half_open_successes_to_close=1)
    assert br.state == State.CLOSED
    try:
        br.run(lambda: (_ for _ in ()).throw(TransientError("x")))
    except TransientError:
        pass
    assert br.state == State.OPEN
    assert br.allow() is False
    time.sleep(0.06)
    assert br.allow() is True and br.state == State.HALF_OPEN
    assert br.run(lambda: "ok") == "ok"
    assert br.state == State.CLOSED