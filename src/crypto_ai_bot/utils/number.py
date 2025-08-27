# Historical compatibility shim:
# оставляем старый модуль, но логика — из единственного источника.
try:
    from .decimal import dec, q_step, set_dec_context  # type: ignore
except Exception:
    # минимальные заглушки, если decimal-хелперы будут недоступны
    from decimal import Decimal, getcontext, ROUND_DOWN as _RD  # type: ignore

    def dec(x) -> Decimal:
        return Decimal(str(x))

    def q_step(x: Decimal, step_pow10: int) -> Decimal:
        q = Decimal(10) ** -step_pow10
        return x.quantize(q, rounding=_RD)

    def set_dec_context(prec: int = 28) -> None:
        getcontext().prec = prec
