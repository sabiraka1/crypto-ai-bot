from __future__ import annotations
from typing import Any, Dict, Optional
from decimal import Decimal
from uuid import uuid4

from . import _build, _fusion
from crypto_ai_bot.core.risk import manager as risk_manager

def _as_decimal(x) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal('0')

def decide(cfg, broker, *, symbol: Optional[str], timeframe: Optional[str], limit: Optional[int]) -> Dict[str, Any]:
    """Public decision point. Returns dict with full explain-schema.
    Structure:
      {
        action, size, sl, tp, trail, score, symbol, timeframe, ts, decision_id,
        explain: {signals, blocks, weights, thresholds, context}
      }
    """
    feats = _build.build(cfg, broker, symbol=symbol, timeframe=timeframe, limit=limit)
    # signals come from features.indicators etc.
    signals = feats.get('indicators', {}) | (feats.get('signals', {}) or {})

    # simple rule score from a couple of indicators (example logic)
    # you can replace by your more advanced scoring inside _build
    rule_score = feats.get('rule_score')
    ai_score = feats.get('ai_score')
    score = _fusion.fuse(rule_score, ai_score, cfg)

    # basic thresholds
    buy_thr = getattr(cfg, 'THRESHOLD_BUY', 0.55)
    sell_thr = getattr(cfg, 'THRESHOLD_SELL', 0.45)

    action: str = 'hold'
    size = Decimal('0')
    if score >= Decimal(str(buy_thr)):
        action = 'buy'
        size = _as_decimal(getattr(cfg, 'DEFAULT_ORDER_SIZE', '0.01'))
    elif score <= Decimal(str(sell_thr)):
        action = 'sell'
        size = _as_decimal(getattr(cfg, 'DEFAULT_ORDER_SIZE', '0.01'))

    decision = {
        'action': action,
        'size': str(size),
        'sl': None,
        'tp': None,
        'trail': None,
        'score': float(score),
        'symbol': symbol or getattr(cfg, 'SYMBOL', 'BTC/USDT'),
        'timeframe': timeframe or getattr(cfg, 'TIMEFRAME', '1h'),
        'ts': int(feats.get('market', {}).get('ts') or 0),
        'decision_id': uuid4().hex,
        'explain': {
            'signals': signals,
            'blocks': feats.get('blocks', {}),
            'weights': {
                'rule': getattr(cfg, 'SCORE_RULE_WEIGHT', 0.5),
                'ai': getattr(cfg, 'SCORE_AI_WEIGHT', 0.5),
            },
            'thresholds': {
                'buy': buy_thr,
                'sell': sell_thr,
            },
            'context': {
                'price': float(feats.get('market', {}).get('price') or 0),
                'atr': float(signals.get('atr') or 0),
                'atr_pct': float(signals.get('atr_pct') or 0),
            }
        }
    }

    # risk pre-check right here is optional; main check happens in use-case
    ok, reason = risk_manager.check(decision, cfg)
    if not ok:
        # keep action but annotate
        decision['explain']['blocks']['risk'] = reason

    return decision
