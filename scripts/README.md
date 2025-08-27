# scripts/ — утилиты-обёртки

Скрипты вызывают существующие CLI-команды пакета (`cab-maintenance`, `cab-smoke`, и т.п.) одинаково на Windows и Linux/macOS.

- `backup_db.py` — делает бэкап БД (`cab-maintenance backup`)
- `rotate_backups.py` — удаляет старые бэкапы (`cab-maintenance rotate --days N`)
- `integrity_check.py` — проверка целостности (`cab-maintenance integrity`)
- `run_server.sh` — запуск uvicorn (Linux/macOS), TRADER_AUTOSTART=1
- `run_server.ps1` — запуск uvicorn (Windows), TRADER_AUTOSTART=1
