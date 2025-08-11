# Crypto AI Bot

Crypto AI Bot автоматизирует торговлю на Gate.io, используя технический анализ, ML-оценку и Telegram-уведомления.

## Features

- **StateManager** с атомарным сохранением состояния (`core/state_manager.py`).
- **UnifiedCacheManager** для централизованного кэширования (`utils/unified_cache.py`).
- Интеграция с Telegram и Flask-вебхуком.

## Requirements

- Python 3.10+
- Зависимости из `requirements.txt`

## Installation

```bash
git clone <repo_url>
cd crypto-ai-bot
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
```

## Environment Setup

```bash
cp env.example .env
```

Ключевые переменные окружения:

- `BOT_TOKEN`, `CHAT_ID`, `ADMIN_CHAT_IDS`
- `GATE_API_KEY`, `GATE_API_SECRET`
- `SYMBOL`, `TIMEFRAME`, `TRADE_AMOUNT`, `SAFE_MODE`, `ENABLE_TRADING` и др.

## Running

- Запуск торгового бота: `python main.py`
- Запуск Flask-сервиса с вебхуками: `python app.py`
- При деплое можно использовать `Procfile`.

## Testing

```bash
pytest
```

## Project Structure

- `analysis/` — скрипты и исследования рынка
- `core/` — основные компоненты бота
- `trading/` — стратегии и логика торговли
- `telegram/` — Telegram-интеграция
- `utils/` — вспомогательные утилиты
- `ml/` — модули машинного обучения
- `config/` — конфигурационные файлы

## Disclaimer

Торговля криптовалютой связана с рисками. Используйте бота на свой страх и риск.

## License

MIT License
