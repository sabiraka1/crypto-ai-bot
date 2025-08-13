web: gunicorn -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:$PORT \
  --workers 1 \
  --timeout 60 \
  --keep-alive 15 \
  --graceful-timeout 30 \
  --preload \
  --log-level info \
  crypto_ai_bot.app.server:app --chdir src
