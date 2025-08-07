class TradingBotException(Exception):
    """Базовое исключение для торгового бота"""
    pass

class APIException(TradingBotException):
    """Ошибки API биржи"""
    pass

class DataValidationException(TradingBotException):
    """Ошибки валидации данных"""
    pass

class InsufficientFundsException(TradingBotException):
    """Недостаточно средств"""
    pass

class MLModelException(TradingBotException):
    """Ошибки ML модели"""
    pass