import os
import sys

# Принудительно UTF-8 для Windows консоли
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
import copy
import json
import re
import time
import xml.etree.ElementTree as ET
from html import unescape as html_unescape
from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests
import undetected_chromedriver as uc

BASE_URL = "https://rutracker.org/forum/"
FORUM_ID = '1605'
ATOM_FEED_URL = f"https://feed.rutracker.cc/atom/f/{FORUM_ID}.atom"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(BASE_DIR, 'switch_games.json')

# Куки сессии (заполняются при инициализации)
SESSION_COOKIES = {}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Опциональные куки авторизации из переменной окружения
ENV_COOKIES_RAW = os.environ.get("RUTRACKER_COOKIES", "").strip()
if ENV_COOKIES_RAW:
    for _item in ENV_COOKIES_RAW.split(';'):
        if '=' in _item:
            _k, _v = _item.strip().split('=', 1)
            SESSION_COOKIES[_k.strip()] = _v.strip()

CF_SESSION_INITIALIZED = False

# Опциональный прокси для обхода Cloudflare с датацентрового IP:
# RUTRACKER_PROXY=socks5://127.0.0.1:1080 (или http://user:pass@host:port)
PROXY_URL = os.environ.get("RUTRACKER_PROXY", "").strip()

# ──────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────

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

def _clean_magnet(url):
    """Убирает HTML-entities и параметр dn= из magnet-ссылки."""
    if not url:
        return url
    url = html_unescape(url).strip()
    url = re.sub(r'[?&]dn=[^&]*', '', url)
    return url

def _post_text(post_body):
    """Текст поста с корректными переводами строк.

    get_text('\\n') вставляет '\\n' между ЛЮБЫМИ тегами (в т.ч. инлайн
    <a>/<span>), из-за чего строки вида
    'Формат образа: .NSZ (сжато ~64%, установленный объём 1.25 ГБ)'
    разрывались и значения в скобках терялись.
    Здесь <br> и блочные теги заменяются на '\\n', инлайн-теги не разрывают строку.
    """
    pb = copy.deepcopy(post_body)
    for br in pb.find_all('br'):
        br.replace_with('\n')
    for block in pb.find_all(['div', 'ul', 'ol', 'li', 'tr', 'table']):
        block.insert_before('\n')
        block.insert_after('\n')
    return pb.get_text()

def extract_title_id(text):
    """Extract Nintendo Switch Title ID (16 hex chars starting with 0100).
    Base game IDs end in 000, DLC ends in 001-FFF, updates end in 800.
    We always normalize to base game ID (last 3 chars = 000).
    """
    if not text:
        return None
    matches = re.findall(r'0100[0-9A-Fa-f]{12}', text, re.IGNORECASE)
    if not matches:
        return None
    upper_matches = [m.upper() for m in matches]
    # Prefer base game IDs (ending in 000)
    for m in upper_matches:
        if m.endswith('000'):
            return m
    # Otherwise normalize: zero out last 3 hex digits to get base game
    return upper_matches[0][:-3] + '000'

# ──────────────────────────────────────────────────────────────
# HTTP / Cloudflare
# ──────────────────────────────────────────────────────────────

def _is_cf_challenge(html):
    """Признак страницы-челленджа Cloudflare (англ. и русская версии)."""
    if not html:
        return False
    return ('Just a moment' in html or 'cf-browser-verification' in html
            or 'Один момент' in html)

def _is_valid_html(html, keywords=('post_body', 'attach_link', 'hl-tr', 'forumtable', 'viewtopic')):
    """Проверяем, что страница настоящая (не Cloudflare challenge)."""
    if not html:
        return False
    if _is_cf_challenge(html):
        return False
    return any(kw in html for kw in keywords)

def _fetch_with_curl(url, wait_keywords=None, is_post=False, post_data=None):
    """Запрос через curl_cffi с текущими SESSION_COOKIES."""
    headers = {"User-Agent": USER_AGENT}
    if is_post:
        headers["X-Requested-With"] = "XMLHttpRequest"
    kwargs = {"impersonate": "chrome120", "timeout": 20}
    if PROXY_URL:
        kwargs["proxies"] = {"http": PROXY_URL, "https": PROXY_URL}
    try:
        if is_post:
            resp = cf_requests.post(url, data=post_data, headers=headers, cookies=SESSION_COOKIES, **kwargs)
        else:
            resp = cf_requests.get(url, headers=headers, cookies=SESSION_COOKIES, **kwargs)
            
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"    [!] curl_cffi ошибка: {e}")
        
    # Fallback to Chrome
    print("    [!] curl_cffi не смог получить страницу, переключаемся на Chrome...")
    return _fetch_with_chrome(url, wait_keywords, is_post, post_data)

GLOBAL_DRIVER = None

def _fetch_with_chrome(url, wait_keywords=None, is_post=False, post_data=None):
    """Запрос через undetected_chromedriver (fallback).
    wait_keywords: кортеж строк для проверки загрузки страницы.
    is_post: выполнить запрос через JS fetch POST.
    post_data: данные для POST запроса.
    """
    global SESSION_COOKIES, USER_AGENT, CF_SESSION_INITIALIZED, GLOBAL_DRIVER
    print("[*] Инициализация Chrome (Cloudflare fallback)...")
    page_html = None
    if wait_keywords is None:
        wait_keywords = ('post_body', 'attach_link', 'hl-tr', 'forumtable', 'viewtopic')
    try:
        if GLOBAL_DRIVER is None:
            options = uc.ChromeOptions()
            if os.environ.get("HEADLESS") == "1":
                options.add_argument('--headless')
            # VPS/контейнер: запуск от root и мало shared-памяти
            if os.environ.get("CHROME_NO_SANDBOX") == "1" or (hasattr(os, 'geteuid') and os.geteuid() == 0):
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
            if PROXY_URL:
                options.add_argument(f'--proxy-server={PROXY_URL}')
            # Экономим память на VPS
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-extensions')
            options.add_argument('--no-first-run')
            GLOBAL_DRIVER = uc.Chrome(options=options)
            GLOBAL_DRIVER.set_script_timeout(30)

        # Идём сразу на целевую страницу (CF challenge решится автоматически)
        if is_post:
            # Для POST сначала идём на корень, чтобы решить Cloudflare и инжектить куки
            GLOBAL_DRIVER.get("https://rutracker.org/forum/index.php")
        else:
            GLOBAL_DRIVER.get(url)
        time.sleep(2)

        # Инжектируем куки авторизации чтобы быть залогиненным
        if SESSION_COOKIES:
            for k, v in SESSION_COOKIES.items():
                try:
                    GLOBAL_DRIVER.add_cookie({'name': k, 'value': v, 'domain': '.rutracker.org'})
                except Exception as e:
                    print(f"    [!] Ошибка установки куки {k}: {e}")
            # Перезагружаем с куками
            if is_post:
                GLOBAL_DRIVER.get("https://rutracker.org/forum/index.php")
            else:
                GLOBAL_DRIVER.get(url)

        # Ждём загрузки целевой страницы (максимум 30 сек)
        for _ in range(30):
            src = GLOBAL_DRIVER.page_source
            title = GLOBAL_DRIVER.title
            if 'Just a moment' not in title and 'Один момент' not in title:
                # Если это is_post, мы ждём index.php. Если обычный GET - ждём wait_keywords
                if is_post or any(kw in src for kw in wait_keywords):
                    page_html = src
                    break
            time.sleep(1)

        if is_post:
            # Теперь, когда CF пройден, делаем POST запрос через JS внутри браузера
            import urllib.parse
            body_str = urllib.parse.urlencode(post_data or {})
            script = f"""
            var done = arguments[arguments.length - 1];
            fetch('{url}', {{
                method: 'POST',
                headers: {{ 
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest'
                }},
                body: '{body_str}'
            }}).then(response => response.text()).then(text => done(text)).catch(err => done(''));
            """
            print(f"    [~] Выполнение POST запроса через JS fetch к {url}")
            page_html = GLOBAL_DRIVER.execute_async_script(script)

        if not page_html:
            page_html = GLOBAL_DRIVER.page_source

        # Сохраняем cookies (включая cf_clearance и bb_session)
        new_cookies = {c['name']: c['value'] for c in GLOBAL_DRIVER.get_cookies()}
        SESSION_COOKIES.update(new_cookies)
        
        # Сохраняем актуальный User-Agent, чтобы curl_cffi не был заблокирован за mismatch
        try:
            real_ua = GLOBAL_DRIVER.execute_script("return navigator.userAgent;")
            if real_ua:
                USER_AGENT = real_ua
                print(f"    [~] Синхронизирован User-Agent с Chrome: {USER_AGENT[:50]}...")
        except Exception:
            pass

        # Восстанавливаем env cookies поверх (кроме cf_clearance, который должен оставаться свежим от Chrome)
        if ENV_COOKIES_RAW:
            for item in ENV_COOKIES_RAW.split(';'):
                if '=' in item:
                    kk, vv = item.strip().split('=', 1)
                    if kk.strip() != 'cf_clearance':
                        SESSION_COOKIES[kk.strip()] = vv.strip()
        ua = GLOBAL_DRIVER.execute_script('return navigator.userAgent')
        if ua:
            USER_AGENT = ua

        CF_SESSION_INITIALIZED = True
        print(f"[+] Chrome cookies получены: {list(new_cookies.keys())}")

    except Exception as e:
        print(f"[!] Chrome ошибка: {e}")
    finally:
        pass # Мы больше не закрываем браузер при каждом вызове

    return page_html

def fetch_url(url, forum_url=False, is_post=False, post_data=None, wait_keywords=None):
    """
    Основная функция получения страницы.
    1. Пробуем curl_cffi с cookies
    2. При ошибке — Chrome fallback (cf_clearance привязан к браузеру, поэтому
       возвращаем Chrome HTML напрямую, не пытаемся снова через curl_cffi)
    """
    keywords = ('hl-tr', 'forumtable') if forum_url else ('post_body', 'attach_link')
    wait_kw = wait_keywords or (('hl-tr', 'forumtable') if forum_url else ('post_body', 'attach_link', 'viewtopic'))

    # Пробуем curl_cffi
    html = _fetch_with_curl(url, wait_keywords=wait_kw, is_post=is_post, post_data=post_data)
    if html and (is_post or _is_valid_html(html, keywords)):
        return html

    if html:
        status = 'CF challenge' if ('Just a moment' in html or 'cf-browser-verification' in html) else 'нет нужных элементов'
        print(f"    [!] curl_cffi вернул {status}, переключаемся на Chrome...")
    else:
        print(f"    [!] curl_cffi не смог получить страницу, переключаемся на Chrome...")

    # Chrome fallback — возвращает страницу напрямую
    chrome_html = _fetch_with_chrome(url, wait_keywords=wait_kw, is_post=is_post, post_data=post_data)
    if chrome_html and (is_post or _is_valid_html(chrome_html, keywords)):
        return chrome_html

    # После Chrome пробуем curl_cffi ещё раз (теперь с обновлёнными cookies)
    html = _fetch_with_curl(url, wait_keywords=wait_kw, is_post=is_post, post_data=post_data)
    if html and (is_post or _is_valid_html(html, keywords)):
        return html

    # Если всё ещё ничего — вернём что есть из Chrome (хоть что-то)
    if chrome_html and len(chrome_html) > 500:
        print(f"    [~] Возвращаем неполный Chrome ответ для {url}")
        return chrome_html

    print(f"    [!] Не удалось получить страницу: {url}")
    return None

# ──────────────────────────────────────────────────────────────
# Парсинг данных темы
# ──────────────────────────────────────────────────────────────

def get_topic_data(topic_id):
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    data = {
        "magnet": None,
        "size": "Unknown",
        "title_id": None,
        "year": "Unknown",
        "genre": "Unknown",
        "developer": "Unknown",
        "publisher": "Unknown",
        "image_format": "Unknown",
        "interface_lang": "Unknown",
        "voice_lang": "Unknown",
        "performance": "Unknown",
        "multiplayer": "Unknown",
        "cover": None,
        "screenshots": [],
        "description": ""
    }

    html = fetch_url(url, forum_url=False)
    if not html:
        return data

    soup = BeautifulSoup(html, 'html.parser')

    data["title_id"] = extract_title_id(soup.get_text()) or extract_title_id(html)

    # Fallback для title_id: скачиваем список файлов раздачи (viewtorrent.php),
    # так как часто авторы не пишут ID в тексте, но он есть в имени файла (.nsp/.nsz)
    if not data["title_id"]:
        torrent_url = f"{BASE_URL}viewtorrent.php"
        # Для viewtorrent.php нужен POST запрос с ID топика
        torrent_html = fetch_url(torrent_url, is_post=True, post_data={"t": topic_id}, wait_keywords=('dir', 'file', 'ul', 'li', 'torrent'))
        if torrent_html:
            print(f"    [~] viewtorrent html length: {len(torrent_html)}")
            if len(torrent_html) < 200:
                print(f"    [~] viewtorrent html: {torrent_html}")
            data["title_id"] = extract_title_id(torrent_html)


    # Magnet: <a class="magnet-link"> есть и в гостевом виде (div.attach_link),
    # и в авторизованном (table.attach) — ищем по всей странице.
    mag_link = soup.find('a', class_='magnet-link')
    if mag_link and mag_link.get('href'):
        data["magnet"] = _clean_magnet(mag_link.get('href'))

    # Размер: авторизованный вид — <span id="tor-size-humn">442.3 MB</span>
    size_el = soup.find(id='tor-size-humn')
    if size_el:
        data["size"] = size_el.get_text(' ', strip=True).replace('\xa0', ' ').strip()

    # Размер: гостевой вид — <div class="attach_link">, размер в одном из <li>
    if data["size"] == "Unknown":
        attach_div = soup.find('div', class_='attach_link')
        if attach_div:
            for li in attach_div.find_all('li'):
                li_text = li.get_text(' ', strip=True).replace('\xa0', ' ').strip()
                if re.search(r'\d[0-9.,]*\s*(?:B|KB|MB|GB|TB|КБ|МБ|ГБ|ТБ)\b', li_text, re.IGNORECASE):
                    data["size"] = li_text
                    break

    # Fallback для magnet (если ссылки нет вообще)
    if not data["magnet"]:
        mag_match = re.search(r'(magnet:\?xt=urn:btih:[^\s\"\'<>]+)', html, re.IGNORECASE)
        if mag_match:
            data["magnet"] = _clean_magnet(mag_match.group(1))

    # Метаданные из тела поста
    post_body = soup.find('div', class_='post_body')
    if post_body:
        text_content = _post_text(post_body)

        patterns = {
            "year": r'(?:Год выпуска|Дата выхода|Год выхода)\s*:\s*([^\n]+)',
            "genre": r'Жанр\s*:\s*([^\n]+)',
            "developer": r'Разработчик\s*:\s*([^\n]+)',
            "publisher": r'Издатель\s*:\s*([^\n]+)',
            "image_format": r'Формат образа\s*:\s*([^\n]+)',
            "interface_lang": r'Язык интерфейса\s*:\s*([^\n]+)',
            "voice_lang": r'(?:Язык озвучки|Озвучка)\s*:\s*([^\n]+)',
            "performance": r'Работоспособность проверена\s*:\s*([^\n]+)',
            "multiplayer": r'Мультиплеер\s*:\s*([^\n]+)',
        }

        for key, pat in patterns.items():
            m = re.search(pat, text_content, re.IGNORECASE)
            if m:
                data[key] = m.group(1).strip()

        # Fallback для размера (если блок attach_link скрыт или отсутствует)
        if data["size"] == "Unknown":
            sz_match = re.search(r'(?:Размер|Объем|Size)\s*(?:раздачи|игры)?\s*:\s*(\d+[,.]\d+\s*(?:MB|GB|МБ|ГБ|KB|КБ))', text_content, re.IGNORECASE)
            if sz_match:
                data["size"] = sz_match.group(1).strip()

        # Обложка и скриншоты
        # RuTracker хранит [img]URL[/img] → <var class="postImg" title="URL">
        # JavaScript конвертирует их в <img>, но в статичном HTML (curl_cffi) нужно парсить <var>
        post_body_html = str(post_body)
        img_urls = []

        # 1. Парсим элементы с class="postImg" в порядке документа:
        #    - статичный HTML (curl_cffi): <var class="postImg" title="URL">
        #    - после JS (Chrome): <img class="postImg" src="URL">
        img_urls = []
        for el in post_body.find_all(['var', 'img'], class_='postImg'):
            url = (el.get('title') or el.get('src') or '').strip()
            if url.startswith('http') and 'rutracker.cc/smiles' not in url and url not in img_urls:
                img_urls.append(url)

        # 2. Fallback: regex по init-src, data-src, src атрибутам img тегов
        if not img_urls:
            for pattern in [
                r'init-src=["\']?(https://[^"\'>\s]+)',
                r'data-src=["\']?(https://[^"\'>\s]+)',
                r'<img[^>]+src=["\']?(https://[^"\'>\s]+)'
            ]:
                for m in re.finditer(pattern, post_body_html, re.IGNORECASE):
                    url = m.group(1).rstrip('/')
                    if 'rutracker.cc/smiles' not in url and url not in img_urls:
                        img_urls.append(url)

        if img_urls:
            data["cover"] = img_urls[0]
            data["screenshots"] = img_urls[1:10]

        # Описание
        desc_match = re.search(
            r'Описание\s*:\s*([\s\S]+?)(?=\n\s*(?:Доп\. информация|Скриншоты|Трейлер|Список файлов|FAQ|Системные требования)|$)',
            text_content, re.IGNORECASE
        )
        if desc_match:
            data["description"] = desc_match.group(1).strip()
        else:
            data["description"] = text_content[:500].strip()

    return data

# ──────────────────────────────────────────────────────────────
# Парсинг Atom-ленты
# ──────────────────────────────────────────────────────────────

def fetch_atom_feed():
    print(f"[*] Получение Atom-ленты {ATOM_FEED_URL}...")
    try:
        kwargs = {"impersonate": "chrome120", "timeout": 15}
        if PROXY_URL:
            kwargs["proxies"] = {"http": PROXY_URL, "https": PROXY_URL}
        resp = cf_requests.get(ATOM_FEED_URL, **kwargs)
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
                topic_url = (
                    link_elem.attrib.get('href', f"{BASE_URL}viewtopic.php?t={topic_id}")
                    if link_elem is not None
                    else f"{BASE_URL}viewtopic.php?t={topic_id}"
                )

                clean, size = parse_feed_title(raw_title)
                entries.append({
                    "topic_id": topic_id,
                    "title": clean,
                    "size": size,
                    "url": topic_url,
                    "raw_title": raw_title,
                })
            print(f"[+] Из Atom-ленты получено {len(entries)} последних раздач.")
            return entries
    except Exception as e:
        print(f"[!] Ошибка получения Atom-ленты: {e}")
    return []

# ──────────────────────────────────────────────────────────────
# Полный парсинг форума (когда БД не существует)
# ──────────────────────────────────────────────────────────────

def scrape_full_forum(output_file=None, max_pages=None):
    """Полный парсинг всех страниц форума. Первые 16 тем (закреплённые) пропускаются."""
    if output_file is None:
        output_file = JSON_FILE

    print("[*] Полный парсинг форума (switch_games.json не существует)...")

    results = []
    seen_ids = set()
    page_num = 0

    while True:
        if max_pages is not None and page_num >= max_pages:
            print(f"[*] Достигнут лимит страниц ({max_pages}).")
            break

        start = page_num * 50
        forum_url = f"{BASE_URL}viewforum.php?f={FORUM_ID}&start={start}"
        print(f"\n--- Страница {page_num + 1} ({forum_url}) ---")

        html = fetch_url(forum_url, forum_url=True)
        if not html:
            print(f"[!] Не удалось загрузить страницу {page_num + 1}. Прерываем.")
            break

        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.select('tr.hl-tr')

        if not rows:
            print(f"[*] Тем не найдено на странице {page_num + 1}. Конец форума.")
            break

        # Пропускаем первые 15 закреплённых тем ТОЛЬКО на первой странице
        if page_num == 0:
            rows = rows[15:]
            print(f"[*] Пропущено 15 закреплённых тем. Осталось: {len(rows)}")

        new_on_page = 0
        for row in rows:
            link_tag = row.select_one('a.tt-text')
            if not link_tag:
                continue

            href = link_tag.get('href', '')
            topic_id = href.split('=')[-1]
            if not topic_id or topic_id in seen_ids:
                continue
            seen_ids.add(topic_id)

            raw_title = link_tag.text.strip()
            title = clean_title(raw_title)
            topic_url = f"{BASE_URL}viewtopic.php?t={topic_id}"

            print(f"  [{len(results)+1}] [{topic_id}] {title[:60].encode('utf-8', errors='replace').decode('utf-8')}...")
            details = get_topic_data(topic_id)

            tid_val = details.get("title_id") or extract_title_id(raw_title)

            game_entry = {
                "title": title,
                "size": details.get("size", "Unknown"),
                "magnet": details.get("magnet"),
                "topic_id": str(topic_id),
                "url": topic_url,
                "year": details.get("year", "Unknown"),
                "genre": details.get("genre", "Unknown"),
                "developer": details.get("developer", "Unknown"),
                "publisher": details.get("publisher", "Unknown"),
                "image_format": details.get("image_format", "Unknown"),
                "interface_lang": details.get("interface_lang", "Unknown"),
                "voice_lang": details.get("voice_lang", "Unknown"),
                "performance": details.get("performance", "Unknown"),
                "multiplayer": details.get("multiplayer", "Unknown"),
                "cover": details.get("cover"),
                "screenshots": details.get("screenshots", []),
                "description": details.get("description", ""),
                "title_id": tid_val,
            }
            results.append(game_entry)
            new_on_page += 1

            # Сохраняем каждую игру (на случай прерывания)
            _save_json(results, output_file)
            if len(results) % 10 == 0:
                print(f"  [~] Промежуточное сохранение: {len(results)} игр")

            time.sleep(0.2)

        if new_on_page == 0:
            print("[*] Нет новых тем. Конец форума.")
            break

        page_num += 1
        time.sleep(0.5)

    _save_json(results, output_file)
    print(f"\n[+] Полный парсинг завершён. Сохранено {len(results)} игр в {output_file}")
    return results

# ──────────────────────────────────────────────────────────────
# Обновление по Atom-ленте
# ──────────────────────────────────────────────────────────────

def run_scraper():
    """
    Основной скрипт:
    - Если switch_games.json НЕ существует → полный парсинг всех страниц форума
    - Если существует → только Atom-лента (новые/обновлённые раздачи)
    """
    if not os.path.exists(JSON_FILE):
        print("[*] switch_games.json не найден. Запускаем полный парсинг форума...")
        scrape_full_forum()
        return

    # Загружаем существующую базу
    existing_data = []
    existing_map = {}
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            if content:
                existing_data = json.loads(content)
                existing_map = {
                    str(item.get('topic_id')): item
                    for item in existing_data
                    if item.get('topic_id')
                }
    except Exception as e:
        print(f"(!) Ошибка чтения базы: {e}")
        return

    print(f"[*] Загружена база: {len(existing_data)} игр.")

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
        raw_title = item.get("raw_title", "")

        if t_id in existing_map:
            old_item = existing_map[t_id]
            needs_update = (
                old_item.get('title') != title
                or (feed_size != "Unknown" and old_item.get('size') != feed_size)
                or not old_item.get('title_id')
                or 'year' not in old_item
                or old_item.get('year') == 'Unknown'
            )
            if needs_update:
                print(f"  [~] ОБНОВЛЯЕМ: {title[:60]}...")
                details = get_topic_data(t_id)
                old_item['title'] = title
                if details['size'] != 'Unknown':
                    old_item['size'] = details['size']
                elif feed_size != 'Unknown':
                    old_item['size'] = feed_size

                for k, v in details.items():
                    if k == 'size':
                        continue
                    if v is not None and v != "Unknown" and v != [] and v != "":
                        old_item[k] = v
                    elif k not in old_item:
                        old_item[k] = v

                if not old_item.get('title_id'):
                    old_item['title_id'] = extract_title_id(raw_title)

                updated_count += 1
        else:
            print(f"  [+] НОВАЯ игра: {title[:60]}...")
            details = get_topic_data(t_id)
            tid_val = details.get('title_id') or extract_title_id(raw_title)
            new_entry = {
                "title": title,
                "size": details["size"] if details["size"] != "Unknown" else feed_size,
                "magnet": details.get("magnet"),
                "topic_id": t_id,
                "url": topic_url,
                "year": details.get("year", "Unknown"),
                "genre": details.get("genre", "Unknown"),
                "developer": details.get("developer", "Unknown"),
                "publisher": details.get("publisher", "Unknown"),
                "image_format": details.get("image_format", "Unknown"),
                "interface_lang": details.get("interface_lang", "Unknown"),
                "voice_lang": details.get("voice_lang", "Unknown"),
                "performance": details.get("performance", "Unknown"),
                "multiplayer": details.get("multiplayer", "Unknown"),
                "cover": details.get("cover"),
                "screenshots": details.get("screenshots", []),
                "description": details.get("description", ""),
                "title_id": tid_val,
            }
            existing_data.insert(0, new_entry)
            existing_map[t_id] = new_entry
            added_count += 1

    if added_count > 0 or updated_count > 0:
        _save_json(existing_data, JSON_FILE)
        print(f"[+] База обновлена. Добавлено: {added_count}, Обновлено: {updated_count}. Всего: {len(existing_data)}")
    else:
        print("[=] Проверка завершена. Новых и обновлённых раздач нет.")

def _save_json(data, filepath):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"(!) Ошибка записи JSON: {e}")

if __name__ == "__main__":
    run_scraper()
