def get_trade_stats(path: str) -> dict:
    """
    Унифицированная статистика по трейдам из CSV.
    Возвращает: total_trades, win_trades, loss_trades, total_pnl, win_rate, last_ts
    (сохраняем обратную совместимость: если где-то ждут старые ключи — их можно собрать из этого словаря).
    """
    import csv, time

    total = wins = losses = 0
    total_pnl = 0.0
    last_ts = 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                total += 1
                pnl = float(row.get("pnl", "0") or 0)
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                ts = int(row.get("ts", "0") or 0)
                if ts > last_ts:
                    last_ts = ts
    except FileNotFoundError:
        pass

    win_rate = round(100.0 * wins / total, 2) if total else 0.0

    return dict(
        total_trades=total,
        win_trades=wins,
        loss_trades=losses,
        total_pnl=round(total_pnl, 2),
        win_rate=win_rate,
        last_ts=last_ts or int(time.time()),
    )


