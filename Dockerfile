# ---- Base image ----
FROM python:3.11-slim AS base

# Env для корректного логгинга и headless-графиков
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    TZ=UTC

# Системные библиотеки:
# - libfreetype6/libpng/jpeg/fonts → для matplotlib (Agg)
# - libgomp1 → для scikit-learn (OpenMP)
# - tzdata → таймзона, curl → healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 libpng16-16 libjpeg62-turbo fonts-dejavu-core \
    libgomp1 tzdata ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь
RUN useradd -m appuser
WORKDIR /app

# ---- Python deps (кешируем слой по requirements.txt) ----
ENV VENV_PATH=/opt/venv
RUN python -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# Сначала копируем только requirements.txt (лучший кеш)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Затем — исходники
COPY src ./src

# (опционально) Healthcheck: дергаем /health локально
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8080}/health || exit 1

# Понижаем привилегии
USER appuser

# ... твой верх Dockerfile без изменений ...

WORKDIR /app

# venv + зависимости как у тебя
ENV VENV_PATH=/opt/venv
RUN python -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Копируем код
COPY src ./src

# ✅ Создаём каталоги для данных/логов/моделей и отдаём их пользователю
RUN mkdir -p /app/data /app/logs /app/models \
    && chown -R appuser:appuser /app

# Healthcheck как было
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8080}/health || exit 1

# Понижаем привилегии
USER appuser

# CMD как у тебя (gunicorn/uvicorn)
CMD ["sh","-c","gunicorn -k uvicorn.workers.UvicornWorker --workers ${WEB_CONCURRENCY:-1} --threads 1 --timeout 90 --graceful-timeout 30 --keep-alive 75 --max-requests 1000 --max-requests-jitter 100 --bind 0.0.0.0:${PORT:-8080} --chdir src crypto_ai_bot.app.server:app"]

# ---- Запуск ----
# Railway выставляет $PORT автоматически.
# WEB_CONCURRENCY можно задавать через Variables.
CMD ["sh","-c","gunicorn -k uvicorn.workers.UvicornWorker --workers ${WEB_CONCURRENCY:-1} --threads 1 --timeout 90 --graceful-timeout 30 --keep-alive 75 --max-requests 1000 --max-requests-jitter 100 --bind 0.0.0.0:${PORT:-8080} --chdir src crypto_ai_bot.app.server:app"]
