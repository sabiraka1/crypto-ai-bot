import time
import logging
from functools import wraps
from typing import Callable, Any

def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Р”РµРєРѕСЂР°С‚РѕСЂ РґР»СЏ РїРѕРІС‚РѕСЂРЅС‹С… РїРѕРїС‹С‚РѕРє РІС‹РїРѕР»РЅРµРЅРёСЏ С„СѓРЅРєС†РёРё"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            attempts = 0
            current_delay = delay
            
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if attempts == max_attempts:
                        logging.error(f"Failed after {max_attempts} attempts: {e}")
                        raise
                    
                    logging.warning(f"Attempt {attempts} failed: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
            
        return wrapper
    return decorator

def log_execution(func: Callable) -> Callable:
    """Р”РµРєРѕСЂР°С‚РѕСЂ РґР»СЏ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ РІС‹РїРѕР»РЅРµРЅРёСЏ С„СѓРЅРєС†РёР№"""
    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        start_time = time.time()
        logging.info(f"рџ”„ Executing {func.__name__}")
        
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            logging.info(f"вњ… {func.__name__} completed in {execution_time:.2f}s")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logging.error(f"вќЊ {func.__name__} failed after {execution_time:.2f}s: {e}")
            raise
    
    return wrapper
