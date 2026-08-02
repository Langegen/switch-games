import os
import json
import re
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Настройки
FORUM_ID = '1605'
BASE_URL = "https://rutracker.org/forum/"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(BASE_DIR, 'switch_games.json')

def clean_title(title):
    title = re.sub(r'^\[Nintendo Switch\]\s*', '', title, flags=re.IGNORECASE).strip()
    return title.replace('"', "'")

def apply_stealth_scripts(page):
    """Скрывает следы автоматизации Chromium"""
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        window.chrome = { runtime: {} };
    """)

def fetch_page_smart(page, url, expected_selector=None):
    """
    Быстрая загрузка страницы без зависимостей от медленных счетчиков.
    Ждет конкретный селектор для мгновенной отдачи HTML.
    """
    try:
        # commit = реагировать как только сервер прислал первые данные
        page.goto(url, wait_until="commit", timeout=30000)
        
        # Если передан ожидаемый селектор — ждем только его появления (макс 8 сек)
        if expected_selector:
            try:
                page.wait_for_selector(expected_selector, timeout=8000)
                return page.content()
            except:
                pass # Если селектор не появился за 8 сек, проверяем на Cloudflare
                
        content = page.content()
        
        # Проверяем НАСТОЯЩИЕ маркеры Cloudflare (БЕЗ слова "Проверка")
        cf_markers = ["Just a moment...", "Checking your browser", "cf-turnstile", "DDoS protection by Cloudflare"]
        if any(marker in content for marker in cf_markers):
            print("[-] Обнаружена проверка Cloudflare, ждем 7 секунд...")
            time.sleep(7)
            return page.content()
            
        return content
        
    except Exception as e:
        print(f"[!] Ошибка загрузки {url}: {e}")
        return None

def get_topic_data(page, topic_id):
    """Загружает страницу темы и ищет .attach_link"""
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    data = {"magnet": None, "size": "Unknown"}
    
    # Ждем селектор блока скачивания, а не таблицу раздела!
    html = fetch_page_smart(page, url, expected_selector="div.attach_link")
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

def get_total_pages(page):
    url = f"{BASE_URL}viewforum.php?f={FORUM_ID}"
    html = fetch_page_smart(page, url, expected_selector="a.pg")
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

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox', 
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars'
            ]
        )
        
        # SOCKS5 Прокси:
        # Если используешь Tor — оставь 9050.
        # Если используешь 3X-UI SOCKS inbound — измени на 10808 (или свой порт).
        context = browser.new_context(
            proxy={"server": "socks5://127.0.0.1:9050"},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='ru-RU,ru'
        )
        
        page = context.new_page()
        apply_stealth_scripts(page)

        if not existing_data:
            print("[*] Первый запуск: сканирую весь раздел.")
            total_pages = get_total_pages(page)
        else:
            print(f"[*] В базе {len(existing_data)} игр. Проверяю 10 страниц обновлений.")
            total_pages = 10

        new_entries = []

        for p_num in range(total_pages):
            start = p_num * 50
            url = f"{BASE_URL}viewforum.php?f={FORUM_ID}&start={start}"
            print(f"--- Страница {p_num + 1}/{total_pages} ---")
            
            html = fetch_page_smart(page, url, expected_selector="tr.hl-tr")
            if not html:
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
                
                details = get_topic_data(page, topic_id)
                new_entries.append({
                    "title": title,
                    "size": details["size"],
                    "magnet": details["magnet"],
                    "topic_id": topic_id,
                    "url": f"{BASE_URL}viewtopic.php?t={topic_id}"
                })

        browser.close()

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
