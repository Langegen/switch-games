#!/bin/bash
cd /root/switch-games
git pull
./venv/bin/python3 scraper.py
git add .
git commit -m "Auto-update: $(date +'%Y-%m-%d %H:%M:%S')"
git push
