# Aggregated exports for repository implementations.
# Делайте try/except, чтобы импорт отдельных модулей не валил тесты, которым они не нужны.

__all__ = []

try:
    from .idempotency import SqliteIdempotencyRepository  # type: ignore
    __all__.append("SqliteIdempotencyRepository")
except Exception:
    pass

try:
    from .trades import SqliteTradeRepository  # type: ignore
    __all__.append("SqliteTradeRepository")
except Exception:
    pass

try:
    from .positions import SqlitePositionRepository  # type: ignore
    __all__.append("SqlitePositionRepository")
except Exception:
    pass

try:
    from .snapshots import SqliteSnapshotRepository  # type: ignore
    __all__.append("SqliteSnapshotRepository")
except Exception:
    pass
