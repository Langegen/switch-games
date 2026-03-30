import requests
from bs4 import BeautifulSoup
import json
import re
import time
import os

# Настройки
FORUM_ID = '1605'
BASE_URL = "https://rutracker.org/forum/"
JSON_FILE = 'switch_games.json'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def clean_title(title):
    """Удаляет [Nintendo Switch] и чистит спецсимволы"""
    # Удаляем префикс
    title = re.sub(r'^\[Nintendo Switch\]\s*', '', title, flags=re.IGNORECASE).strip()
    # На всякий случай заменяем специфические символы, которые могут "сломать" отображение
    return title.replace('"', "'")

def get_topic_data(session, topic_id):
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    data = {"magnet": None, "size": "Unknown"}
    try:
        resp = session.get(url, headers=HEADERS, timeout=10)
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        attach_div = soup.find('div', class_='attach_link')
        if attach_div:
            mag_link = attach_div.find('a', class_='magnet-link')
            if mag_link:
                data["magnet"] = mag_link.get('href')
            
            list_items = attach_div.find_all('li')
            if list_items:
                raw_size = list_items[-1].get_text(strip=True)
                data["size"] = raw_size.replace('\xa0', ' ').replace('&nbsp;', ' ')
        
        time.sleep(1.2) # Анти-бан пауза
    except:
        pass
    return data

def get_total_pages(session):
    url = f"{BASE_URL}viewforum.php?f={FORUM_ID}"
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        pages_nav = soup.select('a.pg')
        page_nums = [int(link.text) for link in pages_nav if link.text.isdigit()]
        return max(page_nums) if page_nums else 1
    except:
        return 1

def run_scraper():
    session = requests.Session()
    
    # 1. Загрузка базы
    existing_data = []
    existing_ids = set()
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                existing_ids = {str(item.get('topic_id')) for item in existing_data if item.get('topic_id')}
        except:
            print("(!) Ошибка файла. Создаем новый.")

    # 2. Определение режима
    if not existing_data:
        print("[*] Первый запуск: сканирую ВСЁ.")
        total_pages = get_total_pages(session)
    else:
        print(f"[*] В базе {len(existing_data)} игр. Проверяю 4 страницы обновлений.")
        total_pages = 4

    new_entries = []

    # 3. Парсинг страниц
    for p in range(total_pages):
        start = p * 50
        url = f"{BASE_URL}viewforum.php?f={FORUM_ID}&start={start}"
        print(f"--- Страница {p+1}/{total_pages} ---")
        
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            resp.encoding = 'windows-1251'
            soup = BeautifulSoup(resp.text, 'html.parser')
            rows = soup.select('tr.hl-tr')
            if p == 0: rows = rows[15:]

            for row in rows:
                link_tag = row.select_one('a.tt-text')
                if not link_tag: continue
                
                topic_id = link_tag['href'].split('=')[-1]
                if topic_id in existing_ids: continue 

                title = clean_title(link_tag.text)
                print(f"  > Найдено: {title[:50]}...")
                
                details = get_topic_data(session, topic_id)
                new_entries.append({
                    "title": title,
                    "size": details["size"],
                    "magnet": details["magnet"],
                    "topic_id": topic_id,
                    "url": f"{BASE_URL}viewtopic.php?t={topic_id}"
                })
        except:
            continue

    # 4. Сохранение (новые сверху)
    if new_entries:
        full_db = new_entries + existing_data
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            # ensure_ascii=False сохраняет русские буквы читаемыми в UTF-8
            json.dump(full_db, f, ensure_ascii=False, indent=4)
        print(f"[+] База обновлена. Добавлено: {len(new_entries)}")
    else:
        print("[=] Новых игр нет.")

if __name__ == "__main__":
    run_scraper()