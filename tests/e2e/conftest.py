import os
import pytest


@pytest.fixture(autouse=True, scope="session")
def disable_redis_e2e():
    """Отключаем Redis для e2e тестов."""
    os.environ["EVENT_BUS_URL"] = ""
    yield