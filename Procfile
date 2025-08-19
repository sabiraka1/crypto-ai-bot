web: gunicorn -k uvicorn.workers.UvicornWorker crypto_ai_bot.app.server:app --bind 0.0.0.0:${PORT} --workers 1 --timeout 75 --access-logfile -
