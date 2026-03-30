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
# Добавляем расширенные заголовки, чтобы походить на реальный браузер
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
}

def clean_title(title):
    """Очистка для Switch: UTF-8 без лишних символов"""
    title = re.sub(r'^\[Nintendo Switch\]\s*', '', title, flags=re.IGNORECASE).strip()
    # Убираем символы, которые могут плохо отображаться в некоторых хоумбрю
    return title.replace('"', '').replace('«', '').replace('»', '')

def get_topic_data(session, topic_id):
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    data = {"magnet": None, "size": "Unknown"}
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'windows-1251'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        attach_div = soup.find('div', class_='attach_link')
        if attach_div:
            mag_link = attach_div.find('a', class_='magnet-link')
            if mag_link: data["magnet"] = mag_link.get('href')
            
            list_items = attach_div.find_all('li')
            if list_items:
                raw_size = list_items[-1].get_text(strip=True)
                data["size"] = raw_size.replace('\xa0', ' ').replace('&nbsp;', ' ')
        time.sleep(2) 
    except:
        pass
    return data

def get_total_pages(session):
    url = f"{BASE_URL}viewforum.php?f={FORUM_ID}"
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'windows-1251'
        if "Для продолжения работы с сайтом введите код" in resp.text:
            print("[!] Ой! Rutracker выдал капчу серверу GitHub. Полный скан невозможен.")
            return 1
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Ищем все ссылки на страницы
        pages = soup.find_all('a', class_='pg')
        nums = [int(p.text) for p in pages if p.text.isdigit()]
        return max(nums) if nums else 1
    except:
        return 1

def run_scraper():
    session = requests.Session()
    existing_data = []
    existing_ids = set()
    
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                existing_ids = {str(item.get('topic_id')) for item in existing_data if item.get('topic_id')}
        except:
            existing_data = []

    # Если база пуста — пробуем взять хотя бы первые 10 страниц (для начала)
    # Если база есть — берем 2 страницы обновлений
    is_first_run = not existing_data
    total_pages = get_total_pages(session) if is_first_run else 2
    
    if is_first_run:
        print(f"[*] База пуста. Найдено страниц: {total_pages}. Начинаю сбор...")
    
    new_entries = []

    for p in range(total_pages):
        start = p * 50
        url = f"{BASE_URL}viewforum.php?f={FORUM_ID}&start={start}"
        print(f"--- Страница {p+1}/{total_pages} ---")
        
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            resp.encoding = 'windows-1251'
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Проверка: нашли ли мы таблицу вообще?
            rows = soup.select('tr.hl-tr')
            if not rows:
                print(f" [!] На странице {p+1} не найдено раздач. Возможно, бан IP.")
                break
                
            if p == 0: rows = rows[15:]

            for row in rows:
                link_tag = row.select_one('a.tt-text')
                if not link_tag: continue
                
                topic_id = link_tag['href'].split('=')[-1]
                if topic_id in existing_ids: continue 

                title = clean_title(link_tag.text)
                print(f"  [+] {title[:50]}...")
                
                details = get_topic_data(session, topic_id)
                new_entries.append({
                    "title": title,
                    "size": details["size"],
                    "magnet": details["magnet"],
                    "topic_id": topic_id
                })
        except Exception as e:
            print(f" [!] Ошибка: {e}")
            continue

    if new_entries:
        full_db = new_entries + existing_data
        # Сохраняем в UTF-8 без ASCII-экранирования
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(full_db, f, ensure_ascii=False, indent=4)
        print(f"\nГотово! Добавлено: {len(new_entries)} игр.")
    else:
        print("\nНовых игр не найдено (или доступ заблокирован).")

if __name__ == "__main__":
    run_scraper()
