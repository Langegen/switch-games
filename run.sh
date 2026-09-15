#!/bin/bash
# Ежедневное обновление базы раздач: парсер -> коммит -> push на GitHub
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd "$(dirname "$0")"

# Взаимная блокировка (оба бота не должны работать одновременно)
LOCK_FILE="/tmp/rutracker-scraper.lock"
exec 200>"$LOCK_FILE"
if ! flock -w 7200 200; then
    echo "[$(date)] Другой парсер всё ещё активен спустя 2 часа ожидания. Выход."
    exit 1
fi

if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

echo "[$(date)] Обновление кода..."
git pull --rebase origin main

echo "[$(date)] Запуск парсера..."
# Таймаут на выполнение 2 часа (защита от зависаний)
if command -v xvfb-run >/dev/null 2>&1; then
    timeout 7200 xvfb-run -a ./venv/bin/python3 scraper.py
else
    timeout 7200 ./venv/bin/python3 scraper.py
fi

echo "[$(date)] Выгрузка изменений на GitHub..."
git add switch_games.json changes.txt scraper.py run.sh .gitignore
if git diff --staged --quiet; then
    echo "[$(date)] Изменений нет - коммит не нужен."
else
    git commit -m "Auto-update: $(date +'%Y-%m-%d %H:%M:%S')"
    git pull --rebase origin main
    git push origin main
    echo "[$(date)] Завершено!"
fi

# Ротация лога: оставляем последние 3000 строк
LOG_FILE="$(pwd)/cron_log.txt"
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 4000 ]; then
    tail -n 3000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi
