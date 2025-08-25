web: python -m uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
release: python -m scripts.smoke_migrations
worker: python -m crypto_ai_bot.core.orchestrator run