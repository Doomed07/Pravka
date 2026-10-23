#!/bin/bash
# Двойной щелчок в Finder запускает «Правки» в браузере. Окно Терминала не закрывайте, пока работаете.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  echo "Первый запуск: устанавливаю зависимости (один раз)…"
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || { echo "Не удалось установить зависимости"; read -r; exit 1; }
fi
.venv/bin/python -m pravki web
