import requests
from bs4 import BeautifulSoup
import json
import re
import time
import os

FORUM_ID = '1605'
BASE_URL = "https://rutracker.org/forum/"
JSON_FILE = 'switch_games.json'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9'
}

def clean_title(title):
    # Убираем [Nintendo Switch], кавычки и лишние пробелы для корректного UTF-8 на Switch
    title = re.sub(r'^\[Nintendo Switch\]\s*', '', title, flags=re.IGNORECASE).strip()
    return title.replace('"', '').replace('«', '').replace('»', '')

def get_topic_data(session, topic_id):
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    data = {"magnet": None, "size": "Unknown"}
    try:
        resp = session.get(url, headers=HEADERS, timeout=10)
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        attach_div = soup.find('div', class_='attach_link')
        if attach_div:
            mag = attach_div.find('a', class_='magnet-link')
            if mag: data["magnet"] = mag.get('href')
            items = attach_div.find_all('li')
            if items: 
                data["size"] = items[-1].get_text(strip=True).replace('\xa0', ' ')
        time.sleep(1.5)
    except: pass
    return data

def run_scraper():
    session = requests.Session()
    
    # Сначала обеспечим существование файла, чтобы Actions не падал
    if not os.path.exists(JSON_FILE):
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)

    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        db = json.load(f)
    
    existing_ids = {str(item.get('topic_id')) for item in db if item.get('topic_id')}

    print("[*] Проверка первой страницы...")
    try:
        resp = session.get(f"{BASE_URL}viewforum.php?f={FORUM_ID}", headers=HEADERS)
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select('tr.hl-tr')[15:25] # Берем 10 свежих тем для теста
        
        new_entries = []
        for row in rows:
            link = row.select_one('a.tt-text')
            if not link: continue
            tid = link['href'].split('=')[-1]
            if tid in existing_ids: continue
            
            print(f"  > Новое: {link.text[:50]}")
            details = get_topic_data(session, tid)
            new_entries.append({
                "title": clean_title(link.text),
                "size": details["size"],
                "magnet": details["magnet"],
                "topic_id": tid
            })
        
        if new_entries:
            db = new_entries + db
            with open(JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=4)
            print(f"[+] Добавлено {len(new_entries)} игр.")
        else:
            print("[=] Ничего нового не найдено.")
            
    except Exception as e:
        print(f"[!] Ошибка: {e}")

if __name__ == "__main__":
    run_scraper()
