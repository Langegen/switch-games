import os
import json
import re
import time
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from curl_cffi import requests
import undetected_chromedriver as uc

BASE_URL = "https://rutracker.org/forum/"
FORUM_ID = '1605'
ATOM_FEED_URL = f"https://feed.rutracker.cc/atom/f/{FORUM_ID}.atom"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(BASE_DIR, 'switch_games.json')

SESSION_COOKIES = {}
USER_AGENT = ""

def clean_title(title):
    clean = title.strip()
    while re.match(r'^\[(?!Nintendo Switch)[^\]]+\]\s*', clean, re.IGNORECASE):
        clean = re.sub(r'^\[[^\]]+\]\s*', '', clean).strip()
    clean = re.sub(r'^\[Nintendo Switch\]\s*', '', clean, flags=re.IGNORECASE).strip()
    return clean.replace('"', "'")

def parse_feed_title(raw_title):
    clean = raw_title.strip()
    while re.match(r'^\[(?!Nintendo Switch)[^\]]+\]\s*', clean, re.IGNORECASE):
        clean = re.sub(r'^\[[^\]]+\]\s*', '', clean).strip()
    clean = re.sub(r'^\[Nintendo Switch\]\s*', '', clean, flags=re.IGNORECASE).strip()
    
    size = "Unknown"
    m = re.search(r'\s*\[([0-9.,]+\s*(?:B|KB|MB|GB|TB|КБ|МБ|ГБ|ТБ))\]$', clean, re.IGNORECASE)
    if m:
        size = m.group(1)
        clean = clean[:m.start()].strip()
    
    clean = clean.replace('"', "'")
    return clean, size

def init_cf_session(url):
    global SESSION_COOKIES, USER_AGENT
    print("[*] Инициализация обхода Cloudflare...")
    driver = None
    try:
        options = uc.ChromeOptions()
        try:
            driver = uc.Chrome(options=options, version_main=150)
        except Exception:
            driver = uc.Chrome(options=options)

        driver.get(url)
        for _ in range(20):
            cookies = {c['name']: c['value'] for c in driver.get_cookies()}
            if 'cf_clearance' in cookies:
                SESSION_COOKIES = cookies
                USER_AGENT = driver.execute_script('return navigator.userAgent')
                print(f"[+] Успешно получены cookies Cloudflare: {list(SESSION_COOKIES.keys())}")
                break
            time.sleep(1)
            
        if not SESSION_COOKIES and driver:
            SESSION_COOKIES = {c['name']: c['value'] for c in driver.get_cookies()}
            USER_AGENT = driver.execute_script('return navigator.userAgent')
    except Exception as e:
        print(f"[!] Ошибка при инициализации Cloudflare сессии: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

def fetch_url(url, max_retries=3):
    global SESSION_COOKIES, USER_AGENT
    if not SESSION_COOKIES:
        init_cf_session(url)

    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                cookies=SESSION_COOKIES,
                headers={'User-Agent': USER_AGENT} if USER_AGENT else None,
                impersonate="chrome120",
                timeout=20
            )
            if resp.status_code == 200 and 'Just a moment' not in resp.text:
                return resp.text
            elif resp.status_code == 403 or 'Just a moment' in resp.text:
                print(f"    [!] 403 / Cloudflare Challenge на попытке {attempt+1}, обновляем сессию...")
                init_cf_session(url)
        except Exception as e:
            print(f"    [!] Ошибка сети (попытка {attempt+1}): {e}")
        time.sleep(2)
    return None

def fetch_atom_feed():
    print(f"[*] Получение Atom-ленты {ATOM_FEED_URL}...")
    try:
        resp = requests.get(ATOM_FEED_URL, impersonate="chrome120", timeout=15)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content.decode('utf-8'))
            entries = []
            for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
                id_elem = entry.find('{http://www.w3.org/2005/Atom}id')
                title_elem = entry.find('{http://www.w3.org/2005/Atom}title')
                link_elem = entry.find('{http://www.w3.org/2005/Atom}link')
                
                if id_elem is None or title_elem is None:
                    continue
                
                topic_id = id_elem.text.split('/')[-1]
                raw_title = title_elem.text
                topic_url = link_elem.attrib.get('href', f"{BASE_URL}viewtopic.php?t={topic_id}") if link_elem is not None else f"{BASE_URL}viewtopic.php?t={topic_id}"
                
                clean, size = parse_feed_title(raw_title)
                entries.append({
                    "topic_id": topic_id,
                    "title": clean,
                    "size": size,
                    "url": topic_url
                })
            print(f"[+] Из Atom-ленты получено {len(entries)} последних раздач.")
            return entries
    except Exception as e:
        print(f"[!] Ошибка получения Atom-ленты: {e}")
    return []

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

def run_scraper():
    existing_data = []
    existing_map = {}
    
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                if content:
                    existing_data = json.loads(content)
                    existing_map = {str(item.get('topic_id')): item for item in existing_data if item.get('topic_id')}
        except Exception as e:
            print(f"(!) Ошибка чтения базы: {e}")

    atom_entries = fetch_atom_feed()
    if not atom_entries:
        print("[!] Не удалось получить Atom-ленту.")
        return

    added_count = 0
    updated_count = 0

    for item in atom_entries:
        t_id = item["topic_id"]
        title = item["title"]
        feed_size = item["size"]
        topic_url = item["url"]

        if t_id in existing_map:
            old_item = existing_map[t_id]
            if old_item.get('title') != title or (feed_size != "Unknown" and old_item.get('size') != feed_size):
                print(f"  [~] ОБНОВЛЕНА раздача: {title[:50]}...")
                details = get_topic_data(t_id)
                old_item['title'] = title
                old_item['size'] = details['size'] if details['size'] != 'Unknown' else feed_size
                if details['magnet']:
                    old_item['magnet'] = details['magnet']
                updated_count += 1
        else:
            print(f"  [+] Найдена НОВАЯ игра: {title[:50]}...")
            details = get_topic_data(t_id)
            new_entry = {
                "title": title,
                "size": details["size"] if details["size"] != "Unknown" else feed_size,
                "magnet": details["magnet"],
                "topic_id": t_id,
                "url": topic_url
            }
            existing_data.insert(0, new_entry)
            existing_map[t_id] = new_entry
            added_count += 1

    if added_count > 0 or updated_count > 0:
        try:
            with open(JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=4)
            print(f"[+] База обновлена. Добавлено: {added_count}, Обновлено: {updated_count}. Всего: {len(existing_data)}")
        except Exception as e:
            print(f"(!) Ошибка записи JSON: {e}")
    else:
        print("[=] Проверка завершена. Новых и обновленных раздач в Atom-ленте нет.")

if __name__ == "__main__":
    run_scraper()


