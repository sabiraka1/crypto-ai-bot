# ---- Base image ----
FROM python:3.11-slim AS base

# Базовые ENV для логгинга и headless-графиков
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    TZ=UTC

# Системные библиотеки для matplotlib/sklearn + утилиты
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 libpng16-16 libjpeg62-turbo fonts-dejavu-core \
    libgomp1 tzdata ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь
RUN useradd -m appuser

# Рабочая директория
WORKDIR /app

# ---- Python deps (кеш по requirements.txt) ----
ENV VENV_PATH=/opt/venv
RUN python -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# Сначала только зависимости (лучший кеш слоёв)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Затем исходники
COPY src ./src

# ---- Writable dirs + права ----
# Выполняем под root, создаём директории и отдаём их appuser
USER root
# Создаём каталоги и сразу задаём владельца
RUN install -d -o appuser -g appuser /app/data /app/logs /app/models \
    && chown -R appuser:appuser /app

# Дефолтные пути для данных/журналов/моделей (Railway Variables перекроют при необходимости)
ENV DATA_DIR=/app/data \
    LOGS_DIR=/app/logs \
    MODEL_DIR=/app/models \
    PAPER_POSITIONS_FILE=/app/data/paper_positions.json \
    PAPER_ORDERS_FILE=/app/data/paper_orders.csv \
    PAPER_PNL_FILE=/app/data/paper_pnl.csv \
    PAPER_BALANCE_FILE=/app/data/paper_balance.json \
    CLOSED_TRADES_CSV=/app/data/closed_trades.csv \
    SIGNALS_CSV=/app/data/signals_snapshots.csv

# Healthcheck: локальный пинг /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8080}/health || exit 1

# Запуск под непривилегированным пользователем
USER appuser

# ---- Start ----
# Railway задаёт $PORT автоматически; WEB_CONCURRENCY можно управлять через Variables
CMD ["sh","-c","gunicorn -k uvicorn.workers.UvicornWorker --workers ${WEB_CONCURRENCY:-1} --threads 1 --timeout 90 --graceful-timeout 30 --keep-alive 75 --max-requests 1000 --max-requests-jitter 100 --bind 0.0.0.0:${PORT:-8080} --chdir src crypto_ai_bot.app.server:app"]
