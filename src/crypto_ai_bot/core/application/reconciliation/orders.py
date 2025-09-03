from __future__ import annotations

from dataclasses import dataclass

from crypto_ai_bot.core.application.ports import BrokerPort


@dataclass
class OrdersReconciler:
    broker: BrokerPort
    symbol: str

    async def run_once(self) -> None:
        # ДћвЂ™ ДћВ±ДћВ°ДћВ·ДћВѕДћВІДћВѕДћВ№ ДћВІДћВµГ‘в‚¬Г‘ВЃДћВёДћВё ДћВЅДћВёГ‘вЂЎДћВµДћВіДћВѕ ДћВЅДћВµ Г‘вЂљГ‘ВЏДћВЅДћВµДћВј ДћВёДћВ· infrastructure ДћВЅДћВ°ДћВїГ‘в‚¬Г‘ВЏДћВјГ‘Ж’Г‘ВЋ.
        # ДћВћГ‘ВЃГ‘вЂљДћВ°ДћВІДћВ»Г‘ВЏДћВµДћВј ДћВ·ДћВ°ДћВіДћВ»Г‘Ж’Г‘Л†ДћВєГ‘Ж’ ДћВґДћВ»Г‘ВЏ ДћВїДћВѕГ‘ВЃДћВ»ДћВµДћВґГ‘Ж’Г‘ВЋГ‘вЂ°ДћВёГ‘вЂ¦ Г‘в‚¬ДћВ°Г‘ВЃГ‘Л†ДћВёГ‘в‚¬ДћВµДћВЅДћВёДћВ№ (Г‘ВЃДћВІДћВµГ‘в‚¬ДћВєДћВ° Г‘ВЃГ‘вЂљДћВ°Г‘вЂљГ‘Ж’Г‘ВЃДћВѕДћВІ ДћВѕГ‘в‚¬ДћВґДћВµГ‘в‚¬ДћВѕДћВІ ДћВїДћВѕ ДћВ±ДћВёГ‘в‚¬ДћВ¶ДћВµ)
        return None
