import os
import json
import re
import time
from bs4 import BeautifulSoup
from curl_cffi import requests

# Заходим напрямую на официальное зеркало
BASE_URL = "https://rutracker.net/forum/"
FORUM_ID = '1605'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(BASE_DIR, 'switch_games.json')

def clean_title(title):
    title = re.sub(r'^\[Nintendo Switch\]\s*', '', title, flags=re.IGNORECASE).strip()
    return title.replace('"', "'")

def fetch_url(url, max_retries=3):
    """Выполняет прямой HTTP-запрос с подменой TLS-отпечатка Chrome 120"""
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url, 
                impersonate="chrome120", 
                timeout=20
            )
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 403:
                print(f"    [!] 403 Forbidden на попытке {attempt+1}")
        except Exception as e:
            print(f"    [!] Ошибка сети (попытка {attempt+1}): {e}")
        time.sleep(2)
    return None

def get_topic_data(topic_id):
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    data = {"magnet": None, "size": "Unknown"}
    
    html = fetch_url(url)
    if not html:
        return data

    soup = BeautifulSoup(html, 'html.parser')
    attach_div = soup.find('div', class_='attach_link')
    if attach_div:
        mag_link = attach_div.find('a', class_='magnet-link')
        if mag_link:
            data["magnet"] = mag_link.get('href')
        
        list_items = attach_div.find_all('li')
        if list_items:
            raw_size = list_items[-1].get_text(strip=True)
            data["size"] = raw_size.replace('\xa0', ' ').replace('&nbsp;', ' ')

    return data

def get_total_pages():
    url = f"{BASE_URL}viewforum.php?f={FORUM_ID}"
    html = fetch_url(url)
    if not html:
        return 1

    soup = BeautifulSoup(html, 'html.parser')
    pages_nav = soup.select('a.pg')
    page_nums = [int(link.text) for link in pages_nav if link.text.isdigit()]
    return max(page_nums) if page_nums else 1

def run_scraper():
    existing_data = []
    existing_ids = set()
    
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                if content:
                    existing_data = json.loads(content)
                    existing_ids = {str(item.get('topic_id')) for item in existing_data if item.get('topic_id')}
        except Exception as e:
            print(f"(!) Ошибка чтения базы: {e}")

    if not existing_data:
        print("[*] Первый запуск: сканирую весь раздел.")
        total_pages = get_total_pages()
    else:
        print(f"[*] В базе {len(existing_data)} игр. Проверяю 10 страниц обновлений.")
        total_pages = 10

    new_entries = []

    for p_num in range(total_pages):
        start = p_num * 50
        url = f"{BASE_URL}viewforum.php?f={FORUM_ID}&start={start}"
        print(f"--- Страница {p_num + 1}/{total_pages} ---")
        
        html = fetch_url(url)
        if not html:
            print(f"[!] Ошибка доступа к странице {p_num + 1}")
            continue

        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.select('tr.hl-tr')
        
        if not rows:
            print(f"[?] Не найдено тем на странице {p_num + 1}.")
            continue

        if p_num == 0 and len(rows) > 15:
            rows = rows[15:]

        for row in rows:
            link_tag = row.select_one('a.tt-text')
            if not link_tag:
                continue
            
            topic_id = link_tag['href'].split('=')[-1]
            if topic_id in existing_ids:
                continue

            title = clean_title(link_tag.text)
            print(f"  > Найдена НОВАЯ игра: {title[:50]}...")
            
            details = get_topic_data(topic_id)
            new_entries.append({
                "title": title,
                "size": details["size"],
                "magnet": details["magnet"],
                "topic_id": topic_id,
                "url": f"{BASE_URL}viewtopic.php?t={topic_id}"
            })

    if new_entries:
        full_db = new_entries + existing_data
        try:
            with open(JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(full_db, f, ensure_ascii=False, indent=4)
            print(f"[+] База обновлена. Добавлено: {len(new_entries)}. Всего: {len(full_db)}")
        except Exception as e:
            print(f"(!) Ошибка записи JSON: {e}")
    else:
        print("[=] Проверка завершена. Новых раздач нет.")

if __name__ == "__main__":
    run_scraper()
