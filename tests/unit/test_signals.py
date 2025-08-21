from decimal import Decimal
from crypto_ai_bot.core.brokers.base import TickerDTO
from crypto_ai_bot.core.signals._build import build_features
from crypto_ai_bot.core.signals._fusion import fuse_score
from crypto_ai_bot.core.signals.policy import decide

def test_build_and_decide(container):
    sym = container.settings.SYMBOL
    # Наполняем несколько снапшотов
    for p in [Decimal("100"), Decimal("101"), Decimal("102")]:
        t = TickerDTO(
            symbol=sym,
            last=p,
            bid=p - Decimal("0.1"),
            ask=p + Decimal("0.1"),
            timestamp=0
        )
        container.storage.market_data.store_ticker(t)
    feats = build_features(symbol=sym, storage=container.storage, n=3)
    assert float(feats["spread_pct"]) >= 0
    score, explain = fuse_score(feats)
    action, score2, _ = decide(feats)
    assert 0.0 <= score <= 1.0 and abs(score - score2) < 1e-9
    assert action in {"buy", "sell", "hold"}
