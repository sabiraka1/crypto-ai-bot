from __future__ import annotations


class AppError(Exception):
    """Базовый класс для доменных исключений приложения."""


class ValidationError(AppError):
    """Ошибки валидации входных данных/конфигурации."""


class CircuitBreakerOpen(AppError):
    """Поднято, когда Circuit Breaker в состоянии OPEN и вызов заблокирован."""