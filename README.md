
# 🤖 Crypto AI Bot

A fully automated cryptocurrency trading bot using **AI-enhanced signal scoring**, **technical analysis**, and **Telegram integration**. This project is deployed on [Render](https://crypto-ai-bot-1t88.onrender.com) and supports 24/7 trading using **Gate.io API**, **machine learning**, and **candlestick pattern recognition**.

---

## 🚀 Features

- ✅ **Technical Indicators**: RSI, MACD, Bollinger Bands, EMA, ADX, OBV, Stochastic RSI
- ✅ **Candlestick Pattern Detection**: Advanced pattern recognition including Doji, Hammer, Engulfing, Harami, Morning Star, etc.
- ✅ **AI Signal Scoring**: Predictive model trained using scikit-learn and XGBoost
- ✅ **Signal-based Trade Execution**: Automated BUY/SELL orders on strong AI signals (score ≥ 0.7)
- ✅ **Telegram Bot Integration**: Sends signals, confidence, and charts to Telegram
- ✅ **Flask Webhook**: Processes incoming triggers and data updates
- ✅ **24/7 Deployment**: Hosted on Render with persistent webhook URL
- ✅ **Auto Model Retraining**: Triggers after each closed trade
- ✅ **Profit Tracking**: `closed_trades.csv` + graphical chart generation
- ✅ **Command Panel via Telegram**:
  - `/start` – Welcome message
  - `/status` – Shows current position and PnL
  - `/test` – Triggers test signal generation
  - `/train` – Manually retrains AI model
  - `/profit` – Shows accumulated trading profit
  - `/errors` – Displays recent error signals and analysis

---

## 🧠 Tech Stack

- **Language**: Python 3.13+
- **Libraries**:
  - `ccxt`, `ta`, `scikit-learn`, `xgboost`, `pandas`, `numpy`, `matplotlib`
  - `flask`, `gunicorn`, `apscheduler`, `pyTelegramBotAPI`, `dotenv`
- **ML Models**: RandomForestClassifier, XGBoost
- **Hosting**: Render.com

---

## 📁 Project Structure

```
├── app.py                     # Flask app with APScheduler and webhook
├── telegram_bot.py           # Telegram bot and command handling
├── trading_bot.py            # Real-time trade decision logic
├── sinyal_skorlayici.py      # AI-based signal scoring
├── data_logger.py            # Logs all signal data
├── grafik_olusturucu.py      # Generates charts for each signal
├── profit_chart.py           # Creates profit summary graphs
├── technical_analysis.py     # Core TA + candlestick detection logic
├── utils.py                  # Support/resistance levels, helpers
├── requirements.txt          # Python dependencies
├── .env                      # Secrets (Telegram token, API keys)
├── static/ & templates/      # For web interface (optional)
└── README.md                 # You are here!
```

---

## ✅ Deployment

Hosted at: [https://crypto-ai-bot-1t88.onrender.com](https://crypto-ai-bot-1t88.onrender.com)

To deploy:
1. Upload to GitHub
2. Connect GitHub repo to [Render](https://render.com)
3. Set environment variables (API keys, Telegram bot token)
4. Set build command: `pip install -r requirements.txt`
5. Set start command: `gunicorn app:app`

---

## 📊 Example Log Output

```
📈 RSI: 79.84, MACD: 326.59, EMA9/21: 115627/115233
📊 Bollinger: [114068, 116111], Stoch RSI: 93.52, ADX: 35.64
🕯️ Pattern: BEARISH_HARAMI (Score: 4.5, Dir: BEARISH)
💰 Support: 114851, Resistance: 116400
📢 Сигнал: BUY (Confidence: 60.0%)
🤖 AI Score: 0.64
```

---

## 🧪 Developed by Züleyha & Sabir | Last updated: 2025-08-07
