"""РЈР»СѓС‡С€РµРЅРЅС‹Рµ С‚РµСЃС‚С‹ РґР»СЏ РєР»Р°СЃСЃР° StateManager."""
import tempfile
import os
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, mock_open
import pytest

from core.state_manager import StateManager, TradingState


class TestStateManager:
    """РљРѕРјРїР»РµРєСЃРЅС‹Рµ С‚РµСЃС‚С‹ StateManager СЃ СЂР°Р·Р»РёС‡РЅС‹РјРё СЃС†РµРЅР°СЂРёСЏРјРё."""

    def test_set_and_get_calls_atomic_write(self, tmp_path):
        """РџСЂРѕРІРµСЂСЏРµРј Р°С‚РѕРјР°СЂРЅСѓСЋ Р·Р°РїРёСЃСЊ РїСЂРё СѓСЃС‚Р°РЅРѕРІРєРµ Р·РЅР°С‡РµРЅРёСЏ."""
        state_file = tmp_path / "state.json"
        sm = StateManager(str(state_file))
        
        with patch.object(sm, "_atomic_write") as mock_write:
            sm.set("key", "value")
            mock_write.assert_called_once()
        
        assert sm.get("key") == "value"

    def test_cooldown_logic(self, tmp_path):
        """РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ СЂР°Р±РѕС‚С‹ РєСѓР»РґР°СѓРЅР°."""
        state_file = tmp_path / "state.json"
        sm = StateManager(str(state_file))
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        with patch("core.state_manager.datetime") as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            
            # Р—Р°РїСѓСЃРєР°РµРј РєСѓР»РґР°СѓРЅ РЅР° 60 СЃРµРєСѓРЅРґ
            sm.start_cooldown(seconds=60)
            
            # Р§РµСЂРµР· 30 СЃРµРєСѓРЅРґ - РІСЃРµ РµС‰Рµ РІ РєСѓР»РґР°СѓРЅРµ
            mock_dt.now.return_value = base_time + timedelta(seconds=30)
            assert sm.is_in_cooldown() is True
            
            # Р§РµСЂРµР· 120 СЃРµРєСѓРЅРґ - РєСѓР»РґР°СѓРЅ Р·Р°РєРѕРЅС‡РёР»СЃСЏ
            mock_dt.now.return_value = base_time + timedelta(seconds=120)
            assert sm.is_in_cooldown() is False

    def test_atomic_write_file_creation(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј СЃРѕР·РґР°РЅРёРµ С„Р°Р№Р»Р° С‡РµСЂРµР· Р°С‚РѕРјР°СЂРЅСѓСЋ Р·Р°РїРёСЃСЊ."""
        state_file = tmp_path / "new_state.json"
        assert not state_file.exists()
        
        sm = StateManager(str(state_file))
        sm.set("test_key", "test_value")
        
        # Р¤Р°Р№Р» РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СЃРѕР·РґР°РЅ
        assert state_file.exists()
        
        # РЎРѕРґРµСЂР¶РёРјРѕРµ РґРѕР»Р¶РЅРѕ Р±С‹С‚СЊ РєРѕСЂСЂРµРєС‚РЅС‹Рј JSON
        with open(state_file, 'r') as f:
            data = json.load(f)
        assert data["test_key"] == "test_value"

    def test_corrupted_json_recovery(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёРµ РїСЂРё РїРѕРІСЂРµР¶РґРµРЅРЅРѕРј JSON."""
        state_file = tmp_path / "corrupted.json"
        
        # РЎРѕР·РґР°РµРј РїРѕРІСЂРµР¶РґРµРЅРЅС‹Р№ JSON С„Р°Р№Р»
        with open(state_file, 'w') as f:
            f.write("{ invalid json }")
        
        # StateManager РґРѕР»Р¶РµРЅ СЃРѕР·РґР°С‚СЊ Р±СЌРєР°Рї Рё Р·Р°РіСЂСѓР·РёС‚СЊ РґРµС„РѕР»С‚С‹
        with patch.object(StateManager, '_backup_file') as mock_backup:
            mock_backup.return_value = str(state_file) + ".backup"
            sm = StateManager(str(state_file))
            
            # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ СЃРѕР·РґР°РЅ Р±СЌРєР°Рї
            mock_backup.assert_called_once()
            
            # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ Р·Р°РіСЂСѓР¶РµРЅС‹ РґРµС„РѕР»С‚РЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ
            assert sm.get("trading_state") == TradingState.WAITING.value

    def test_trading_state_enum_handling(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј СЂР°Р±РѕС‚Сѓ СЃ enum TradingState."""
        state_file = tmp_path / "trading_state.json"
        sm = StateManager(str(state_file))
        
        # РЈСЃС‚Р°РЅРѕРІРєР° Рё РїРѕР»СѓС‡РµРЅРёРµ С‡РµСЂРµР· enum
        sm.set_trading_state(TradingState.IN_POSITION)
        assert sm.get_trading_state() == TradingState.IN_POSITION
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІ С„Р°Р№Р»Рµ СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ СЃС‚СЂРѕРєРѕРІРѕРµ Р·РЅР°С‡РµРЅРёРµ
        with open(state_file, 'r') as f:
            data = json.load(f)
        assert data["trading_state"] == "in_position"

    def test_position_management(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј СѓРїСЂР°РІР»РµРЅРёРµ РїРѕР·РёС†РёРµР№."""
        state_file = tmp_path / "position.json"
        sm = StateManager(str(state_file))
        
        # РР·РЅР°С‡Р°Р»СЊРЅРѕ РїРѕР·РёС†РёСЏ РЅРµР°РєС‚РёРІРЅР°
        assert not sm.is_position_active()
        
        # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј РїРѕР·РёС†РёСЋ
        sm.set("in_position", True)
        sm.set("symbol", "BTC/USDT")
        sm.set("entry_price", 50000.0)
        
        assert sm.is_position_active()
        
        # РџРѕР»СѓС‡Р°РµРј РёРЅС„РѕСЂРјР°С†РёСЋ Рѕ РїРѕР·РёС†РёРё
        pos_info = sm.get_position_info()
        assert pos_info["active"] is True
        assert pos_info["symbol"] == "BTC/USDT"
        assert pos_info["entry_price"] == 50000.0
        
        # РЎР±СЂР°СЃС‹РІР°РµРј РїРѕР·РёС†РёСЋ
        sm.reset_position()
        assert not sm.is_position_active()

    def test_statistics_tracking(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј РѕС‚СЃР»РµР¶РёРІР°РЅРёРµ СЃС‚Р°С‚РёСЃС‚РёРєРё."""
        state_file = tmp_path / "stats.json"
        sm = StateManager(str(state_file))
        
        # РР·РЅР°С‡Р°Р»СЊРЅРѕ СЃС‚Р°С‚РёСЃС‚РёРєР° РїСѓСЃС‚Р°СЏ
        stats = sm.get_statistics()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0
        
        # Р”РѕР±Р°РІР»СЏРµРј РЅРµСЃРєРѕР»СЊРєРѕ СЃРґРµР»РѕРє
        sm.increment_trade_count()
        sm.add_profit(100.0)  # РџСЂРёР±С‹Р»СЊРЅР°СЏ СЃРґРµР»РєР°
        
        sm.increment_trade_count()
        sm.add_profit(-50.0)  # РЈР±С‹С‚РѕС‡РЅР°СЏ СЃРґРµР»РєР°
        
        sm.increment_trade_count()
        sm.add_profit(75.0)   # Р•С‰Рµ РѕРґРЅР° РїСЂРёР±С‹Р»СЊРЅР°СЏ
        
        # РџСЂРѕРІРµСЂСЏРµРј СЃС‚Р°С‚РёСЃС‚РёРєСѓ
        stats = sm.get_statistics()
        assert stats["total_trades"] == 3
        assert stats["win_trades"] == 2
        assert stats["lose_trades"] == 1
        assert stats["win_rate"] == 66.67
        assert stats["total_profit"] == 125.0

    def test_cooldown_edge_cases(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј РіСЂР°РЅРёС‡РЅС‹Рµ СЃР»СѓС‡Р°Рё РєСѓР»РґР°СѓРЅР°."""
        state_file = tmp_path / "cooldown.json"
        sm = StateManager(str(state_file))
        
        # РљСѓР»РґР°СѓРЅ Р±РµР· РїР°СЂР°РјРµС‚СЂРѕРІ (РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ 60 РјРёРЅСѓС‚)
        with patch("core.state_manager.datetime") as mock_dt:
            base_time = datetime.now(timezone.utc)
            mock_dt.now.return_value = base_time
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            
            sm.start_cooldown()  # Р‘РµР· РїР°СЂР°РјРµС‚СЂРѕРІ
            
            # Р§РµСЂРµР· 30 РјРёРЅСѓС‚ - РµС‰Рµ РІ РєСѓР»РґР°СѓРЅРµ
            mock_dt.now.return_value = base_time + timedelta(minutes=30)
            assert sm.is_in_cooldown() is True
            
            # Р§РµСЂРµР· 61 РјРёРЅСѓС‚Сѓ - РєСѓР»РґР°СѓРЅ Р·Р°РєРѕРЅС‡РёР»СЃСЏ
            mock_dt.now.return_value = base_time + timedelta(minutes=61)
            assert sm.is_in_cooldown() is False
        
        # РћС‡РёСЃС‚РєР° РєСѓР»РґР°СѓРЅР°
        sm.clear_cooldown()
        assert not sm.is_in_cooldown()

    def test_concurrent_access_simulation(self, tmp_path):
        """РРјРёС‚Р°С†РёСЏ РєРѕРЅРєСѓСЂРµРЅС‚РЅРѕРіРѕ РґРѕСЃС‚СѓРїР°."""
        import threading
        import random
        
        state_file = tmp_path / "concurrent.json"
        sm = StateManager(str(state_file))
        
        results = []
        errors = []
        
        def worker(worker_id):
            try:
                for i in range(10):
                    # РЎР»СѓС‡Р°Р№РЅС‹Рµ РѕРїРµСЂР°С†РёРё
                    if random.choice([True, False]):
                        sm.set(f"worker_{worker_id}_key_{i}", f"value_{i}")
                    else:
                        value = sm.get(f"worker_{worker_id}_key_{i}", "default")
                        results.append(value)
                    time.sleep(0.001)  # РќРµР±РѕР»СЊС€Р°СЏ РїР°СѓР·Р°
            except Exception as e:
                errors.append(e)
        
        # Р—Р°РїСѓСЃРєР°РµРј РЅРµСЃРєРѕР»СЊРєРѕ РїРѕС‚РѕРєРѕРІ
        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Р–РґРµРј Р·Р°РІРµСЂС€РµРЅРёСЏ
        for t in threads:
            t.join()
        
        # РќРµ РґРѕР»Р¶РЅРѕ Р±С‹С‚СЊ РѕС€РёР±РѕРє
        assert len(errors) == 0

    def test_data_persistence_across_instances(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј СЃРѕС…СЂР°РЅРµРЅРёРµ РґР°РЅРЅС‹С… РјРµР¶РґСѓ СЌРєР·РµРјРїР»СЏСЂР°РјРё."""
        state_file = tmp_path / "persistence.json"
        
        # РџРµСЂРІС‹Р№ СЌРєР·РµРјРїР»СЏСЂ
        sm1 = StateManager(str(state_file))
        sm1.set("persistent_key", "persistent_value")
        sm1.set("total_trades", 5)
        sm1.set_trading_state(TradingState.IN_POSITION)
        
        # РЎРѕР·РґР°РµРј РІС‚РѕСЂРѕР№ СЌРєР·РµРјРїР»СЏСЂ (РёРјРёС‚Р°С†РёСЏ РїРµСЂРµР·Р°РїСѓСЃРєР°)
        sm2 = StateManager(str(state_file))
        
        # Р”Р°РЅРЅС‹Рµ РґРѕР»Р¶РЅС‹ СЃРѕС…СЂР°РЅРёС‚СЊСЃСЏ
        assert sm2.get("persistent_key") == "persistent_value"
        assert sm2.get("total_trades") == 5
        assert sm2.get_trading_state() == TradingState.IN_POSITION

    def test_update_multiple_values(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј РѕР±РЅРѕРІР»РµРЅРёРµ РЅРµСЃРєРѕР»СЊРєРёС… Р·РЅР°С‡РµРЅРёР№ РѕРґРЅРѕРІСЂРµРјРµРЅРЅРѕ."""
        state_file = tmp_path / "update.json"
        sm = StateManager(str(state_file))
        
        # РђС‚РѕРјР°СЂРЅРѕРµ РѕР±РЅРѕРІР»РµРЅРёРµ РЅРµСЃРєРѕР»СЊРєРёС… Р·РЅР°С‡РµРЅРёР№
        update_data = {
            "symbol": "ETH/USDT",
            "entry_price": 3000.0,
            "quantity": 1.5,
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        with patch.object(sm, "_atomic_write") as mock_write:
            sm.update(update_data)
            mock_write.assert_called_once()
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІСЃРµ Р·РЅР°С‡РµРЅРёСЏ СѓСЃС‚Р°РЅРѕРІР»РµРЅС‹
        for key, value in update_data.items():
            assert sm.get(key) == value

    def test_invalid_trading_state_handling(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј РѕР±СЂР°Р±РѕС‚РєСѓ РЅРµРєРѕСЂСЂРµРєС‚РЅС‹С… СЃРѕСЃС‚РѕСЏРЅРёР№ С‚РѕСЂРіРѕРІР»Рё."""
        state_file = tmp_path / "invalid_state.json"
        sm = StateManager(str(state_file))
        
        # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј РЅРµРєРѕСЂСЂРµРєС‚РЅРѕРµ СЃРѕСЃС‚РѕСЏРЅРёРµ РЅР°РїСЂСЏРјСѓСЋ РІ С„Р°Р№Р»
        sm.set("trading_state", "invalid_state")
        
        # get_trading_state РґРѕР»Р¶РЅРѕ РІРµСЂРЅСѓС‚СЊ РґРµС„РѕР»С‚РЅРѕРµ Р·РЅР°С‡РµРЅРёРµ
        assert sm.get_trading_state() == TradingState.WAITING

    def test_position_reset_completeness(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј РїРѕР»РЅРѕС‚Сѓ СЃР±СЂРѕСЃР° РїРѕР·РёС†РёРё."""
        state_file = tmp_path / "reset.json"
        sm = StateManager(str(state_file))
        
        # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј РІСЃРµ РїРѕР»СЏ РїРѕР·РёС†РёРё
        position_fields = {
            "in_position": True,
            "opening": True,
            "symbol": "BTC/USDT",
            "entry_price": 50000.0,
            "qty_usd": 1000.0,
            "qty_base": 0.02,
            "buy_score": 0.8,
            "ai_score": 0.9,
            "tp_price_pct": 0.02,
            "sl_price_pct": 0.01
        }
        
        for key, value in position_fields.items():
            sm.set(key, value)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РїРѕР·РёС†РёСЏ Р°РєС‚РёРІРЅР°
        assert sm.is_position_active()
        
        # РЎР±СЂР°СЃС‹РІР°РµРј РїРѕР·РёС†РёСЋ
        sm.reset_position()
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІСЃРµ РїРѕР»СЏ РїРѕР·РёС†РёРё СЃР±СЂРѕС€РµРЅС‹ Рє РґРµС„РѕР»С‚Р°Рј
        defaults = sm._default_state()
        pos_keys = sm._derive_position_keys()
        
        for key in pos_keys:
            expected = defaults.get(key)
            actual = sm.get(key)
            assert actual == expected, f"Field {key}: expected {expected}, got {actual}"

    def test_file_permissions_error_handling(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј РѕР±СЂР°Р±РѕС‚РєСѓ РѕС€РёР±РѕРє РґРѕСЃС‚СѓРїР° Рє С„Р°Р№Р»Сѓ."""
        state_file = tmp_path / "readonly.json"
        
        # РЎРѕР·РґР°РµРј С„Р°Р№Р» Рё РґРµР»Р°РµРј РµРіРѕ С‚РѕР»СЊРєРѕ РґР»СЏ С‡С‚РµРЅРёСЏ
        sm = StateManager(str(state_file))
        sm.set("test", "value")
        
        os.chmod(state_file, 0o444)  # РўРѕР»СЊРєРѕ С‡С‚РµРЅРёРµ
        
        try:
            # РџРѕРїС‹С‚РєР° Р·Р°РїРёСЃРё РґРѕР»Р¶РЅР° Р±С‹С‚СЊ РѕР±СЂР°Р±РѕС‚Р°РЅР° gracefully
            sm.set("another_key", "another_value")
            # Р•СЃР»Рё РґРѕС€Р»Рё СЃСЋРґР°, Р·РЅР°С‡РёС‚ РѕС€РёР±РєР° Р±С‹Р»Р° РѕР±СЂР°Р±РѕС‚Р°РЅР°
        except Exception as e:
            # РР»Рё РїСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ СЌС‚Рѕ РѕР¶РёРґР°РµРјР°СЏ РѕС€РёР±РєР°
            assert ("Permission denied" in str(e) or "Read-only" in str(e) or 
                    "EriЕџim engellendi" in str(e) or "WinError 5" in str(e))
        finally:
            # Р’РѕСЃСЃС‚Р°РЅР°РІР»РёРІР°РµРј РїСЂР°РІР° РґР»СЏ cleanup
            os.chmod(state_file, 0o644)

    def test_large_data_handling(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј СЂР°Р±РѕС‚Сѓ СЃ Р±РѕР»СЊС€РёРјРё РѕР±СЉРµРјР°РјРё РґР°РЅРЅС‹С…."""
        state_file = tmp_path / "large_data.json"
        sm = StateManager(str(state_file))
        
        # Р‘РѕР»СЊС€РѕР№ РѕР±СЉРµРєС‚ РґР°РЅРЅС‹С…
        large_data = {
            f"key_{i}": f"value_{i}" * 100 for i in range(1000)
        }
        
        # Р”РѕР»Р¶РЅРѕ СЂР°Р±РѕС‚Р°С‚СЊ Р±РµР· РѕС€РёР±РѕРє
        sm.update(large_data)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РґР°РЅРЅС‹Рµ СЃРѕС…СЂР°РЅРёР»РёСЃСЊ
        for key, value in list(large_data.items())[:10]:  # РџСЂРѕРІРµСЂСЏРµРј РїРµСЂРІС‹Рµ 10
            assert sm.get(key) == value

    def test_export_import_state(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј СЌРєСЃРїРѕСЂС‚ Рё РёРјРїРѕСЂС‚ СЃРѕСЃС‚РѕСЏРЅРёСЏ."""
        state_file = tmp_path / "export_import.json"
        sm = StateManager(str(state_file))
        
        # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј РЅРµРєРѕС‚РѕСЂС‹Рµ РґР°РЅРЅС‹Рµ
        test_data = {
            "symbol": "BTC/USDT",
            "entry_price": 45000.0,
            "total_trades": 10
        }
        sm.update(test_data)
        
        # Р­РєСЃРїРѕСЂС‚РёСЂСѓРµРј СЃРѕСЃС‚РѕСЏРЅРёРµ
        exported = sm.export_state()
        assert isinstance(exported, dict)
        for key, value in test_data.items():
            assert exported[key] == value
        
        # РЎРѕР·РґР°РµРј РЅРѕРІС‹Р№ СЌРєР·РµРјРїР»СЏСЂ Рё РёРјРїРѕСЂС‚РёСЂСѓРµРј
        sm2 = StateManager(str(tmp_path / "import.json"))
        success = sm2.import_state(exported)
        assert success is True
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РґР°РЅРЅС‹Рµ РёРјРїРѕСЂС‚РёСЂРѕРІР°Р»РёСЃСЊ
        for key, value in test_data.items():
            assert sm2.get(key) == value

    def test_import_invalid_data(self, tmp_path):
        """РўРµСЃС‚РёСЂСѓРµРј РёРјРїРѕСЂС‚ РЅРµРєРѕСЂСЂРµРєС‚РЅС‹С… РґР°РЅРЅС‹С…."""
        state_file = tmp_path / "import_invalid.json"
        sm = StateManager(str(state_file))
        
        # РџРѕРїС‹С‚РєР° РёРјРїРѕСЂС‚Р° РЅРµ-СЃР»РѕРІР°СЂСЏ
        with pytest.raises(ValueError):
            sm.import_state("not a dict")
        
        # РџРѕРїС‹С‚РєР° РёРјРїРѕСЂС‚Р° None
        with pytest.raises(ValueError):
            sm.import_state(None)
        
        # РџРѕРїС‹С‚РєР° РёРјРїРѕСЂС‚Р° СЃРїРёСЃРєР°
        with pytest.raises(ValueError):
            sm.import_state([1, 2, 3])

    @pytest.mark.parametrize("cooldown_seconds", [0, 1, 60, 3600, 86400])
    def test_cooldown_various_durations(self, tmp_path, cooldown_seconds):
        """РџР°СЂР°РјРµС‚СЂРёР·РѕРІР°РЅРЅС‹Р№ С‚РµСЃС‚ СЂР°Р·Р»РёС‡РЅС‹С… РґР»РёС‚РµР»СЊРЅРѕСЃС‚РµР№ РєСѓР»РґР°СѓРЅР°."""
        state_file = tmp_path / f"cooldown_{cooldown_seconds}.json"
        sm = StateManager(str(state_file))
        
        with patch("core.state_manager.datetime") as mock_dt:
            base_time = datetime.now(timezone.utc)
            mock_dt.now.return_value = base_time
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            
            sm.start_cooldown(seconds=cooldown_seconds)
            
            # РЎСЂР°Р·Сѓ РїРѕСЃР»Рµ СѓСЃС‚Р°РЅРѕРІРєРё РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РІ РєСѓР»РґР°СѓРЅРµ (РµСЃР»Рё > 0)
            if cooldown_seconds > 0:
                assert sm.is_in_cooldown() is True
            
            # РџРѕСЃР»Рµ РёСЃС‚РµС‡РµРЅРёСЏ РІСЂРµРјРµРЅРё РєСѓР»РґР°СѓРЅР°
            mock_dt.now.return_value = base_time + timedelta(seconds=cooldown_seconds + 1)
            assert sm.is_in_cooldown() is False



