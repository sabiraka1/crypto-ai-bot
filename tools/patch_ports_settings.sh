#!/usr/bin/env bash
set -euo pipefail

echo "→ Проверяю, что вы в корне репозитория…"
test -f "pyproject.toml" || { echo "Не найден pyproject.toml. Запусти из корня проекта."; exit 1; }

backup_file () {
  local f="$1"
  if [[ -f "$f" && ! -f "$f.bak" ]]; then
    cp "$f" "$f.bak"
    echo "   • Бэкап: $f.bak"
  fi
}

# Найти файлы через git (внутри src/**)
PORTS_FILES=$(git ls-files 'src/**/ports.py' || true)
SETTINGS_FILES=$(git ls-files 'src/**/settings.py' || true)

if [[ -z "${PORTS_FILES}" ]]; then echo "⚠️ ports.py не найден — пропускаю"; fi
if [[ -z "${SETTINGS_FILES}" ]]; then echo "⚠️ settings.py не найден — пропускаю"; fi

# ── settings.py: bare 'except:' → 'except Exception:'
for f in $SETTINGS_FILES; do
  echo "→ Правки в $f"
  backup_file "$f"
  if grep -n -E '^\s*except:\s*$' "$f" >/dev/null 2>&1; then
    perl -0777 -pe 's/(\n[ \t]*)except:\s*\n/\1except Exception:\n/g' -i "$f"
    echo "   • Заменено 'except:' → 'except Exception:'"
  else
    echo "   • 'except:' не найден — ок"
  fi
done

# ── ports.py правки
for f in $PORTS_FILES; do
  echo "→ Правки в $f"
  backup_file "$f"

  # 1) удалить импорт ABC/abstractmethod (если есть)
  if grep -n 'from abc import ABC' "$f" >/dev/null 2>&1; then
    perl -0777 -pe 's/^\s*from\s+abc\s+import\s+ABC,\s*abstractmethod\s*\r?\n//mg' -i "$f"
    echo "   • Удалён неиспользуемый импорт ABC/abstractmethod"
  fi

  # 2) добавить Callable, Awaitable (если нет)
  if ! grep -E 'from typing import .*Callable.*' "$f" >/dev/null 2>&1; then
    if grep -n 'from typing import' "$f" >/dev/null 2>&1; then
      awk 'BEGIN{a=0} /from typing import/ && a==0 {print; print "from typing import Callable, Awaitable"; a=1; next} {print}' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    else
      { echo 'from typing import Callable, Awaitable'; cat "$f"; } > "$f.tmp" && mv "$f.tmp" "$f"
    fi
    echo "   • Добавлен импорт Callable/Awaitable"
  fi

  # 3) handler: callable → строгий тип
  if grep -n 'handler:\s*callable' "$f" >/dev/null 2>&1; then
    perl -0777 -pe 's/handler:\s*callable/handler: Callable\[\[dict\[str, Any\]\], Awaitable\[None\]\]/g' -i "$f"
    echo "   • Ужесточён тип handler"
  fi

  # 4) list[callable] → строгий тип
  if grep -n 'list\[callable\]' "$f" >/dev/null 2>&1; then
    perl -0777 -pe 's/list\[callable\]/list\[Callable\[\[dict\[str, Any\]\], Awaitable\[None\]\]\]/g' -i "$f"
    echo "   • Ужесточён тип словаря обработчиков"
  fi
done

echo "✅ Готово. Бэкапы *.bak лежат рядом с файлами."
echo "→ Теперь запусти: pre-commit run -a && pytest -q"
