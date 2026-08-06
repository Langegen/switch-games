#!/bin/bash
# Ежедневное обновление базы раздач: парсер -> коммит -> push на GitHub
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd "$(dirname "$0")"

# Куки RuTracker (RUTRACKER_COOKIES) из локального .env, если есть
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

echo "[$(date)] Обновление кода..."
git pull --rebase origin main

echo "[$(date)] Запуск парсера..."
# Chrome-fallback требует виртуальный дисплей (Cloudflare не проходится в headless)
if command -v xvfb-run >/dev/null 2>&1; then
    xvfb-run -a ./venv/bin/python3 scraper.py
else
    ./venv/bin/python3 scraper.py
fi

echo "[$(date)] Выгрузка изменений на GitHub..."
git add switch_games.json scraper.py .gitignore
if git diff --staged --quiet; then
    echo "[$(date)] Изменений нет - коммит не нужен."
else
    git commit -m "Auto-update: $(date +'%Y-%m-%d %H:%M:%S')"
    git pull --rebase origin main
    git push origin main
    echo "[$(date)] Завершено!"
fi
