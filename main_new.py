# Main launcher for crypto trading bot 
from src.crypto_ai_bot.trading.bot import TradingBot 
 
if __name__ == "__main__": 
    bot = TradingBot() 
    bot.run() 
