import os
import json
import re
import time
from bs4 import BeautifulSoup
import cloudscraper

# Настройки
FORUM_ID = '1605'
BASE_URL = "https://rutracker.org/forum/"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(BASE_DIR, 'switch_games.json')

def clean_title(title):
    title = re.sub(r'^\[Nintendo Switch\]\s*', '', title, flags=re.IGNORECASE).strip()
    return title.replace('"', "'")

def create_cf_scraper():
    """Создает сессию, умеющую обходить защиту Cloudflare"""
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

def get_topic_data(scraper, topic_id):
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    data = {"magnet": None, "size": "Unknown"}
    try:
        resp = scraper.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"    [!] Ошибка темы {topic_id}: HTTP {resp.status_code}")
            return data
            
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
        
        time.sleep(1.2)  # Небольшая пауза между темами
    except Exception as e:
        print(f"    [!] Ошибка запроса темы {topic_id}: {e}")
    return data

def get_total_pages(scraper):
    url = f"{BASE_URL}viewforum.php?f={FORUM_ID}"
    try:
        resp = scraper.get(url, timeout=15)
        print(f"[*] Проверка главной страницы раздела: HTTP {resp.status_code}")
        if resp.status_code != 200:
            return 1
            
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        pages_nav = soup.select('a.pg')
        page_nums = [int(link.text) for link in pages_nav if link.text.isdigit()]
        return max(page_nums) if page_nums else 1
    except Exception as e:
        print(f"[!] Ошибка получения количества страниц: {e}")
        return 1

def run_scraper():
    scraper = create_cf_scraper()
    
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
            print(f"(!) Ошибка чтения локального файла {JSON_FILE}: {e}")

    if not existing_data:
        print("[*] Первый запуск: сканирую весь раздел.")
        total_pages = get_total_pages(scraper)
    else:
        print(f"[*] В базе {len(existing_data)} игр. Проверяю 15 страниц обновлений.")
        total_pages = 15

    new_entries = []

    for p in range(total_pages):
        start = p * 50
        url = f"{BASE_URL}viewforum.php?f={FORUM_ID}&start={start}"
        print(f"--- Страница {p+1}/{total_pages} ---")
        
        try:
            resp = scraper.get(url, timeout=15)
            
            if resp.status_code != 200:
                print(f"[!] Ошибка доступа: HTTP {resp.status_code} для страницы {p+1}")
                continue

            resp.encoding = 'windows-1251'
            soup = BeautifulSoup(resp.text, 'html.parser')
            rows = soup.select('tr.hl-tr')
            
            if not rows:
                print(f"[?] Ни одной темы не найдено на странице {p+1}.")
                continue

            if p == 0 and len(rows) > 15:
                rows = rows[15:]

            for row in rows:
                link_tag = row.select_one('a.tt-text')
                if not link_tag: 
                    continue
                
                topic_id = link_tag['href'].split('=')[-1]
                if topic_id in existing_ids: 
                    continue 

                title = clean_title(link_tag.text)
                print(f"  > Найдена НОВАЯ игра: {title[:60]}...")
                
                details = get_topic_data(scraper, topic_id)
                new_entries.append({
                    "title": title,
                    "size": details["size"],
                    "magnet": details["magnet"],
                    "topic_id": topic_id,
                    "url": f"{BASE_URL}viewtopic.php?t={topic_id}"
                })
                
        except Exception as e:
            print(f"[!] Исключение на странице {p+1}: {e}")
            continue

    if new_entries:
        full_db = new_entries + existing_data
        try:
            with open(JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(full_db, f, ensure_ascii=False, indent=4)
            print(f"[+] Успех! Добавлено новых игр: {len(new_entries)}. Всего в базе: {len(full_db)}")
        except Exception as e:
            print(f"[!] Ошибка записи в JSON: {e}")
    else:
        print("[=] Сканирование завершено. Новых раздач на проверенных страницах нет.")

if __name__ == "__main__":
    run_scraper()
