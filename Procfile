web: gunicorn -k uvicorn.workers.UvicornWorker --workers 1 --bind 0.0.0.0:$PORT --chdir src crypto_ai_bot.app.server:app
