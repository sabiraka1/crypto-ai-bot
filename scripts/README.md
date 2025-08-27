\# scripts/ — утилиты-обёртки



Скрипты вызывают существующие CLI-команды пакета (`cab-maintenance`, `cab-smoke`, и т.п.) одинаково на Windows и Linux/macOS.



\- `backup\_db.py` — делает бэкап БД (`cab-maintenance backup`)

\- `rotate\_backups.py` — удаляет старые бэкапы (`cab-maintenance rotate --days N`)

\- `integrity\_check.py` — проверка целостности (`cab-maintenance integrity`)

\- `run\_server.sh` — запуск uvicorn (Linux/macOS), TRADER\_AUTOSTART=1

\- `run\_server.ps1` — запуск uvicorn (Windows), TRADER\_AUTOSTART=1



