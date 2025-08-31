# Процесс для платформ вроде Heroku/Render/Fly.
# Использует gunicorn + uvicorn worker. Настраивается через WEB_CONCURRENCY и PORT.
web: gunicorn -w ${WEB_CONCURRENCY:-2} -k uvicorn.workers.UvicornWorker crypto_ai_bot.app.server:app --bind 0.0.0.0:${PORT:-8000}
