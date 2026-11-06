# -*- coding: utf-8 -*-
"""
cleanup_nsw2.py
Скрипт для разовой очистки базы данных от раздач Nintendo Switch 2 (NSW2) и формата NUP.
Удаляет раздачи из switch_games.json, switch_games_stats.json и файлов состояний.
"""

import os
import sys
import json
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(BASE_DIR, 'switch_games.json')
STATS_FILE = os.path.join(BASE_DIR, 'switch_games_stats.json')
VERSIONS_STATE = os.path.join(BASE_DIR, 'enrich_versions_state.json')
TITLES_STATE = os.path.join(BASE_DIR, 'enrich_titles_state.json')

sys.path.insert(0, BASE_DIR)
from scraper import is_nsw2_or_nup, _save_json

def cleanup():
    if not os.path.exists(JSON_FILE):
        print(f"[!] {JSON_FILE} не найден.")
        return

    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        games = json.load(f)

    initial_count = len(games)
    cleaned_games = []
    removed_ids = set()
    removed_details = []

    for item in games:
        t = item.get('title', '')
        rt = item.get('raw_title', '')
        fmt = item.get('image_format', '')
        tid = str(item.get('topic_id', '')).strip()

        if is_nsw2_or_nup(t, rt, fmt, item):
            removed_ids.add(tid)
            removed_details.append((tid, t, fmt))
        else:
            cleaned_games.append(item)

    print(f"[*] Всего записей в switch_games.json: {initial_count}")
    print(f"[*] Найдено раздач NSW2 / NUP для удаления: {len(removed_ids)}")

    for tid, t, fmt in removed_details:
        print(f"  - [{tid}] fmt={fmt:<5} | {t}")

    # Сохраняем очищенный switch_games.json
    _save_json(cleaned_games, JSON_FILE)
    print(f"[+] switch_games.json обновлен: осталось {len(cleaned_games)} записей.")

    # Очищаем switch_games_stats.json
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            stats_initial = len(stats)
            for tid in removed_ids:
                stats.pop(tid, None)
            _save_json(stats, STATS_FILE)
            print(f"[+] switch_games_stats.json обновлен: удалено {stats_initial - len(stats)} записей (осталось {len(stats)}).")
        except Exception as e:
            print(f"[!] Ошибка очистки stats: {e}")

    # Очищаем файлы состояний
    for state_path in (VERSIONS_STATE, TITLES_STATE):
        if os.path.exists(state_path):
            try:
                with open(state_path, 'r', encoding='utf-8') as f:
                    st = json.load(f)
                st_init = len(st)
                for tid in removed_ids:
                    st.pop(tid, None)
                with open(state_path, 'w', encoding='utf-8') as f:
                    json.dump(st, f, ensure_ascii=False, indent=2)
                print(f"[+] {os.path.basename(state_path)} обновлен: удалено {st_init - len(st)} записей.")
            except Exception as e:
                print(f"[!] Ошибка очистки {state_path}: {e}")

    print("\n[+] Очистка успешно завершена!")

if __name__ == "__main__":
    cleanup()
