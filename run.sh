#!/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd "$(dirname "$0")"

echo "[$(date)] Начало работы..."
git pull origin main

echo "[$(date)] Запуск парсера..."
./venv/bin/python3 scraper.py

echo "[$(date)] Отправка изменений в GitHub..."
git add switch_games.json scraper.py .gitignore
git commit -m "Auto-update: $(date +'%Y-%m-%d %H:%M:%S')"
git push origin main
echo "[$(date)] Завершено!"
