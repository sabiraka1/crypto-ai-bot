# \# Prometheus Monitoring Setup

# 

# \## Алерты

# \- `alerts.yml` - правила алертинга для Prometheus

# \- Интеграция с Alertmanager для уведомлений в Telegram

# 

# \## Метрики приложения

# Приложение экспортирует метрики на `/metrics`:

# \- `orders\_\*` - статистика ордеров

# \- `latency\_\*` - латентность операций  

# \- `risk\_\*` - срабатывания risk-менеджера

# \- `bus\_\*` - статистика event bus

# 

# \## Deployment

# ```bash

# \# Загрузить правила в Prometheus

# curl -X POST http://prometheus:9090/-/reload

