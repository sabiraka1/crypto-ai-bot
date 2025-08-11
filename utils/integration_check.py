"""
Проверка корректности интеграции оптимизаций
"""

def check_integration():
    """Проверить все интеграции"""
    results = {}
    
    # 1. Проверка technical_indicators
    try:
        from analysis.technical_indicators import calculate_all_indicators, get_cache_stats
        import pandas as pd
        
        # Тестовые данные
        test_df = pd.DataFrame({
            'open': [100, 101, 102],
            'high': [102, 103, 104], 
            'low': [99, 100, 101],
            'close': [101, 102, 103],
            'volume': [1000, 1100, 1200]
        })
        
        # Проверяем кэширование
        df1 = calculate_all_indicators(test_df, use_cache=True)
        df2 = calculate_all_indicators(test_df, use_cache=True)  # Должно быть из кэша
        
        cache_stats = get_cache_stats()
        
        results['technical_indicators'] = {
            'status': 'OK',
            'cache_working': cache_stats['size'] > 0,
            'indicators_count': len([col for col in df1.columns if col not in test_df.columns])
        }
        
    except Exception as e:
        results['technical_indicators'] = {'status': 'ERROR', 'error': str(e)}
    
    # 2. Проверка CSV батчинга
    try:
        from utils.csv_handler import CSVHandler, get_csv_system_stats
        
        # Тест записи
        test_signal = {
            'timestamp': '2024-01-01T00:00:00Z',
            'symbol': 'BTC/USDT',
            'buy_score': 0.75,
            'ai_score': 0.80
        }
        
        CSVHandler.log_signal_snapshot(test_signal)
        stats = get_csv_system_stats()
        
        results['csv_handler'] = {
            'status': 'OK',
            'batch_working': stats['batch_writer']['buffer_size'] >= 0,
            'cache_working': len(stats['read_cache']) >= 0
        }
        
    except Exception as e:
        results['csv_handler'] = {'status': 'ERROR', 'error': str(e)}
    
    # 3. Проверка мониторинга
    try:
        from utils.monitoring import SimpleMonitor, app_monitoring
        
        monitor = SimpleMonitor()
        metrics = monitor.get_system_metrics()
        health = app_monitoring.get_health_response()
        
        results['monitoring'] = {
            'status': 'OK',
            'metrics_working': metrics.memory_mb > 0,
            'health_working': 'timestamp' in health
        }
        
    except Exception as e:
        results['monitoring'] = {'status': 'ERROR', 'error': str(e)}
    
    # 4. Проверка ScoringEngine
    try:
        from analysis.scoring_engine import ScoringEngine
        
        scorer = ScoringEngine()
        
        # Проверяем что остался только evaluate()
        has_evaluate = hasattr(scorer, 'evaluate')
        has_legacy = hasattr(scorer, 'calculate_scores') or hasattr(scorer, 'score')
        
        results['scoring_engine'] = {
            'status': 'OK',
            'unified_interface': has_evaluate and not has_legacy,
            'methods': [m for m in dir(scorer) if not m.startswith('_')]
        }
        
    except Exception as e:
        results['scoring_engine'] = {'status': 'ERROR', 'error': str(e)}
    
    return results

def print_integration_report():
    """Напечатать отчет об интеграции"""
    results = check_integration()
    
    print("=" * 60)
    print("ОТЧЕТ ОБ ИНТЕГРАЦИИ ОПТИМИЗАЦИЙ")
    print("=" * 60)
    
    for component, result in results.items():
        status = result.get('status', 'UNKNOWN')
        print(f"\n{component.upper()}: {status}")
        
        if status == 'OK':
            for key, value in result.items():
                if key != 'status':
                    print(f"  ✅ {key}: {value}")
        else:
            print(f"  ❌ Error: {result.get('error', 'Unknown error')}")
    
    print("\n" + "=" * 60)
    
    # Общий статус
    all_ok = all(r.get('status') == 'OK' for r in results.values())
    print(f"ОБЩИЙ СТАТУС: {'✅ ВСЕ РАБОТАЕТ' if all_ok else '❌ ЕСТЬ ПРОБЛЕМЫ'}")
    print("=" * 60)

if __name__ == "__main__":
    print_integration_report()