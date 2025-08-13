Microsoft Windows [Version 10.0.26100.4770]
(c) Microsoft Corporation. Tüm hakları saklıdır.

C:\Users\Sabir ŞAHBAZ>cd "C:\Users\Sabir ŞAHBAZ\Documents\GitHub\crypto-ai-bot"

C:\Users\Sabir ŞAHBAZ\Documents\GitHub\crypto-ai-bot>python -m uvicorn --app-dir src crypto_ai_bot.app.server:app --reload --port 8000
INFO:     Will watch for changes in these directories: ['C:\\Users\\Sabir ŞAHBAZ\\Documents\\GitHub\\crypto-ai-bot']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [1472] using StatReload
WARNING:root:📊 Technical Indicators: Unified Cache not available, using fallback: No module named 'utils'
Process SpawnProcess-1:
Traceback (most recent call last):
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.1776.0_x64__qbz5n2kfra8p0\Lib\multiprocessing\process.py", line 313, in _bootstrap
    self.run()
    ~~~~~~~~^^
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.1776.0_x64__qbz5n2kfra8p0\Lib\multiprocessing\process.py", line 108, in run
    self._target(*self._args, **self._kwargs)
    ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Sabir ŞAHBAZ\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\uvicorn\_subprocess.py", line 80, in subprocess_started
    target(sockets=sockets)
    ~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\Users\Sabir ŞAHBAZ\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\uvicorn\server.py", line 67, in run
    return asyncio.run(self.serve(sockets=sockets))
           ~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.1776.0_x64__qbz5n2kfra8p0\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
           ~~~~~~~~~~^^^^^^
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.1776.0_x64__qbz5n2kfra8p0\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.1776.0_x64__qbz5n2kfra8p0\Lib\asyncio\base_events.py", line 725, in run_until_complete
    return future.result()
           ~~~~~~~~~~~~~^^
  File "C:\Users\Sabir ŞAHBAZ\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\uvicorn\server.py", line 71, in serve
    await self._serve(sockets)
  File "C:\Users\Sabir ŞAHBAZ\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\uvicorn\server.py", line 78, in _serve
    config.load()
    ~~~~~~~~~~~^^
  File "C:\Users\Sabir ŞAHBAZ\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\uvicorn\config.py", line 436, in load
    self.loaded_app = import_from_string(self.app)
                      ~~~~~~~~~~~~~~~~~~^^^^^^^^^^
  File "C:\Users\Sabir ŞAHBAZ\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\uvicorn\importer.py", line 19, in import_from_string
    module = importlib.import_module(module_str)
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.1776.0_x64__qbz5n2kfra8p0\Lib\importlib\__init__.py", line 88, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 1026, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "C:\Users\Sabir ŞAHBAZ\Documents\GitHub\crypto-ai-bot\src\crypto_ai_bot\app\server.py", line 13, in <module>
    from crypto_ai_bot.trading.bot import TradingBot, Deps
  File "C:\Users\Sabir ŞAHBAZ\Documents\GitHub\crypto-ai-bot\src\crypto_ai_bot\trading\bot.py", line 40, in <module>
    from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features
  File "C:\Users\Sabir ŞAHBAZ\Documents\GitHub\crypto-ai-bot\src\crypto_ai_bot\trading\signals\signal_aggregator.py", line 15, in <module>
    from crypto_ai_bot.context.snapshot import ContextSnapshot
ImportError: cannot import name 'ContextSnapshot' from 'crypto_ai_bot.context.snapshot' (C:\Users\Sabir ŞAHBAZ\Documents\GitHub\crypto-ai-bot\src\crypto_ai_bot\context\snapshot.py)
