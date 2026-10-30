# -*- coding: utf-8 -*-
"""
enrich_versions.py
Массовое дообогащение каталога switch_games.json полями update_version и version.

Поля:
- update_version (int): номер версии обновления Nintendo из имени файла раздачи
  (например [0100...800][v196608] -> 196608). Если апдейта нет - поле опускается.
- version (str): отображаемая версия (например "1.0.3"). Нормализуется без 'v'.
  Приоритет 1: "Версия игры:" из тела темы.
  Приоритет 2: из заголовка темы или имени файлов.
  Если версия не найдена - поле опускается.

Особенности:
- Защита от конфликтов с cron (run.sh) через flock /tmp/rutracker-scraper.lock.
- Сохранение прогресса в enrich_versions_state.json каждые SAVE_INTERVAL записей.
- Безопасное завершение по SIGINT/SIGTERM с мгновенным сбросом изменений.
- Возможность продолжения с места остановки.
"""

import os
import sys
import time
import json
import signal
import re
import argparse
from bs4 import BeautifulSoup

# Установка UTF-8 для консоли Windows при локальном запуске
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(BASE_DIR, 'switch_games.json')
STATE_FILE = os.path.join(BASE_DIR, 'enrich_versions_state.json')
LOCK_FILE = '/tmp/rutracker-scraper.lock'
SAVE_INTERVAL = 50

# Импортируем утилиты из основного парсера
sys.path.insert(0, BASE_DIR)
from scraper import (
    BASE_URL,
    fetch_url,
    fetch_torrent_metadata,
    clean_version_str,
    extract_fallback_version,
    _post_text,
    _save_json,
    close_driver,
)


class FileLocker:
    """Кроссплатформенная блокировка файла через fcntl (Linux) с fallback."""
    def __init__(self, lock_path):
        self.lock_path = lock_path
        self.fd = None

    def __enter__(self):
        try:
            import fcntl
            self.fd = open(self.lock_path, 'w')
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            self.fd = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd is not None:
            try:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
            except Exception:
                pass


def _load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Ошибка чтения файла состояния {STATE_FILE}: {e}")
    return {}


def _save_state(state):
    try:
        tmp_file = f"{STATE_FILE}.tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, STATE_FILE)
    except Exception as e:
        print(f"[!] Ошибка сохранения состояния: {e}")


def extract_topic_version(html):
    """Извлекает версию игры из HTML страницы темы (viewtopic.php)."""
    if not html:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    post_body = soup.find('div', class_='post_body')
    if not post_body:
        return None

    text = _post_text(post_body)
    m = re.search(r'(?:Версия(?:\s+игры)?|Game\s*Version)\s*:\s*([^\n\r<]+)', text, re.IGNORECASE)
    if m:
        ver = clean_version_str(m.group(1))
        if ver:
            return ver
    return None


def enrich_all_versions(limit=None, delay=0.15, force=False, push=False):
    """Основной цикл дообогащения всех записей switch_games.json."""
    if not os.path.exists(JSON_FILE):
        print(f"[!] Каталог {JSON_FILE} не найден.")
        return

    print(f"[*] Чтение каталога {JSON_FILE}...")
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            games = json.load(f)
    except Exception as e:
        print(f"[!] Не удалось загрузить JSON: {e}")
        return

    total_games = len(games)
    print(f"[*] Всего записей в каталоге: {total_games}")

    state = {} if force else _load_state()
    stop_requested = False

    def handle_signal(sig, frame):
        nonlocal stop_requested
        print(f"\n[~] Получен сигнал {sig}, сохранение состояния и корректная остановка...")
        stop_requested = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    processed_count = 0
    updated_updates = 0
    updated_versions = 0
    since_last_save = 0

    print("[*] Захват блокировки и старт обработки...")
    with FileLocker(LOCK_FILE):
        for idx, item in enumerate(games):
            if stop_requested:
                break
            if limit is not None and processed_count >= limit:
                print(f"[*] Достигнут лимит обработки ({limit} записей).")
                break

            tid = str(item.get('topic_id', '')).strip()
            if not tid:
                continue

            # Если запись уже обработана и не force
            if not force and state.get(tid):
                continue

            # Проверяем, нужны ли поля:
            has_update_version = 'update_version' in item and item['update_version'] is not None
            has_version = bool(item.get('version'))

            # Если уже оба поля есть, просто фиксируем в состоянии
            if has_update_version and has_version and not force:
                state[tid] = int(time.time())
                continue

            raw_title = item.get('raw_title') or item.get('title', '')
            changed = False

            # 1. Запрос viewtorrent.php (список файлов -> update_version, title_id, file_version)
            torrent_meta = fetch_torrent_metadata(tid)

            # Title ID (если отсутствовал)
            if not item.get('title_id') and torrent_meta.get('title_id'):
                item['title_id'] = torrent_meta['title_id']
                changed = True

            # update_version (максимальный vN из файлов апдейта ...800)
            if torrent_meta.get('update_version'):
                if item.get('update_version') != torrent_meta['update_version']:
                    item['update_version'] = torrent_meta['update_version']
                    updated_updates += 1
                    changed = True

            # 2. Определение version
            if item.get('version'):
                cleaned = clean_version_str(item['version'])
                if cleaned:
                    if item['version'] != cleaned:
                        item['version'] = cleaned
                        changed = True
                else:
                    item.pop('version', None)
                    changed = True

            if not item.get('version'):
                ver_found = None
                # Пробуем получить со страницы темы (viewtopic.php)
                topic_html = fetch_url(f"{BASE_URL}viewtopic.php?t={tid}")
                if topic_html:
                    ver_found = extract_topic_version(topic_html)

                # Fallback: из файлов торрента или названия темы
                if not ver_found:
                    ver_found = torrent_meta.get('version') or extract_fallback_version(raw_title)

                if ver_found:
                    item['version'] = ver_found
                    updated_versions += 1
                    changed = True

            state[tid] = int(time.time())
            processed_count += 1
            since_last_save += 1

            title_preview = str(item.get('title', f'Topic {tid}'))[:45]
            upd_str = f"upd:{item.get('update_version')}" if item.get('update_version') else "no-upd"
            ver_str = f"v:{item.get('version')}" if item.get('version') else "no-v"
            print(f"[{idx+1}/{total_games}] [{tid}] {upd_str} | {ver_str} | {title_preview}")

            # Периодическое сохранение
            if since_last_save >= SAVE_INTERVAL or changed and since_last_save >= 20:
                _save_json(games, JSON_FILE)
                _save_state(state)
                since_last_save = 0
                print(f"  [~] Сохранено: обработано {processed_count}, апдейтов {updated_updates}, версий {updated_versions}")

            if delay > 0:
                time.sleep(delay)

        # Финальное сохранение
        _save_json(games, JSON_FILE)
        _save_state(state)
        print(f"\n[+] Обработка завершена!")
        print(f"    Всего обработано тем: {processed_count}")
        print(f"    Проставлено update_version: {updated_updates}")
        print(f"    Проставлено version: {updated_versions}")

    if push:
        _git_push()


def _git_push():
    """Коммит и отправка изменений в Git-репозиторий."""
    import subprocess
    print("[*] Выгрузка изменений в Git...")
    try:
        subprocess.run(["git", "add", "switch_games.json", "scraper.py", "enrich_versions.py", ".gitignore"], check=True)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if status.stdout.strip():
            msg = f"Enrich versions: update_version & version metadata ({time.strftime('%Y-%m-%d %H:%M:%S')})"
            subprocess.run(["git", "commit", "-m", msg], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("[+] Изменения успешно отправлены в GitHub!")
        else:
            print("[*] Изменений в Git нет.")
    except Exception as e:
        print(f"[!] Ошибка Git push: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich switch_games.json with update_version & version fields")
    parser.add_argument("--limit", type=int, default=None, help="Лимит тем для обработки")
    parser.add_argument("--delay", type=float, default=0.15, help="Задержка между запросами в секундах (по умолч. 0.15)")
    parser.add_argument("--force", action="store_true", help="Принудительно перепроверить даже обработанные темы")
    parser.add_argument("--push", action="store_true", help="Выполнить git commit и push после завершения")
    args = parser.parse_args()

    try:
        enrich_all_versions(limit=args.limit, delay=args.delay, force=args.force, push=args.push)
    finally:
        close_driver()
