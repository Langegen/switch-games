import requests
from bs4 import BeautifulSoup
import json
import re
import time
import os

# НАСТРОЙКИ
FORUM_ID = '1605'
BASE_URL = "https://rutracker.org/forum/"
JSON_FILE = 'switch_games.json'  # Твой основной файл базы данных
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def clean_title(title):
    """Удаляет [Nintendo Switch] и чистит спецсимволы"""
    title = re.sub(r'^\[Nintendo Switch\]\s*', '', title, flags=re.IGNORECASE).strip()
    return title.replace('"', "'")

def get_topic_data(session, topic_id):
    """Заходит внутрь темы и вытаскивает все метаданные с логированием и ретраями при сбоях"""
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    
    # Заготовка со всеми дефолтными значениями (убрали performance)
    data = {
        "magnet": None, 
        "size": "Unknown",
        "year": "Unknown",
        "genre": "Unknown",
        "developer": "Unknown",
        "publisher": "Unknown",
        "image_format": "Unknown",
        "interface_lang": "Unknown",
        "voice_lang": "Unknown",
        "cover": None,
        "screenshots": [],
        "description": "Unknown"
    }
    
    soup = None
    # Автоповтор до 3 попыток при падении сети или таймауте
    for attempt in range(3):
        try:
            resp = session.get(url, headers=HEADERS, timeout=12)
            resp.encoding = 'windows-1251'
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                break
            else:
                print(f"    [Попытка {attempt+1}/3] Сервер вернул код {resp.status_code}, ожидание...")
        except requests.exceptions.RequestException as err:
            print(f"    [Попытка {attempt+1}/3] Ошибка соединения: {err}, повторяем...")
        time.sleep(2)

    if not soup:
        print(f"  (!) Не удалось загрузить тему {topic_id} после всех попыток.")
        return data

    # 1. Блок скачивания (магнет и точный размер)
    try:
        attach_div = soup.find('div', class_='attach_link')
        if attach_div:
            mag_link = attach_div.find('a', class_='magnet-link')
            if mag_link:
                data["magnet"] = mag_link.get('href')
            
            list_items = attach_div.find_all('li')
            if list_items:
                raw_size = list_items[-1].get_text(strip=True)
                data["size"] = raw_size.replace('\xa0', ' ').replace('&nbsp;', ' ')
    except Exception as e:
        print(f"    [!] Ошибка сбора магнета/размера в теме {topic_id}: {e}")
        
    # Находим главный блок сообщения с описанием игры
    post_body = soup.select_one('div.post_body')
    if post_body:
        full_text = post_body.get_text()
        
        def extract_field(pattern, text):
            try:
                match = re.search(pattern, text, re.IGNORECASE)
                return match.group(1).strip() if match else "Unknown"
            except:
                return "Unknown"

        # 2. Вытаскиваем текстовые параметры (убрали performance)
        try:
            data["year"] = extract_field(r'(?:Год выпуска|Год|Дата выхода)\s*:\s*([^\n]+)', full_text)
            data["genre"] = extract_field(r'Жанр\s*:\s*([^\n]+)', full_text)
            data["developer"] = extract_field(r'Разработчик\s*:\s*([^\n]+)', full_text)
            data["publisher"] = extract_field(r'Издатель\s*:\s*([^\n]+)', full_text)
            data["image_format"] = extract_field(r'(?:Формат образа|Формат)\s*:\s*([^\n]+)', full_text)
            data["interface_lang"] = extract_field(r'(?:Язык интерфейса|Интерфейс)\s*:\s*([^\n]+)', full_text)
            data["voice_lang"] = extract_field(r'(?:Озвучка|Язык озвучки)\s*:\s*([^\n]+)', full_text)
        except Exception as e:
            print(f"    [!] Ошибка регулярных выражений в теме {topic_id}: {e}")

        # 3. Вытаскиваем Описание (Description) до первой пустой строки
        try:
            desc_label = post_body.find(lambda tag: tag.name in ['span', 'b'] and 'Описание' in tag.get_text())
            if desc_label:
                desc_fragments = []
                for sibling in desc_label.next_siblings:
                    if sibling.name == 'span' and 'post-br' in sibling.get('class', []):
                        if desc_fragments and ''.join(desc_fragments).strip():
                            next_sib = sibling.find_next_sibling()
                            if next_sib and next_sib.name == 'span' and 'post-br' in next_sib.get('class', []):
                                break
                            desc_fragments.append("\n")
                            continue
                    
                    if sibling.name in ['span', 'b', 'div'] and any(word in sibling.get_text() for word in ['Скриншоты', 'Особенности', 'Дополнительно']):
                        break
                        
                    if isinstance(sibling, str):
                        desc_fragments.append(sibling)
                    elif sibling.name not in ['var', 'div']:
                        desc_fragments.append(sibling.get_text())

                final_desc = "".join(desc_fragments).strip()
                if final_desc:
                    data["description"] = re.sub(r'\n+', '\n', final_desc)
        except Exception as e:
            print(f"    [!] Ошибка сбора описания в теме {topic_id}: {e}")

        # 4. Ссылки на картинки (Обложка справа)
        try:
            cover_var = post_body.find('var', class_='img-right')
            if cover_var and cover_var.get('title'):
                data["cover"] = cover_var.get('title')
            else:
                first_var = post_body.find('var', class_='postImg')
                if first_var:
                    data["cover"] = first_var.get('title')
        except Exception as e:
            print(f"    [!] Ошибка сбора обложки в теме {topic_id}: {e}")

        # 5. Ссылки на 3 скриншота (из спойлеров)
        try:
            screenshots = []
            spoiler_bodies = post_body.select('div.sp-body')
            for spoiler in spoiler_bodies:
                img_vars = spoiler.find_all('var', class_='postImg')
                for var in img_vars:
                    img_url = var.get('title')
                    if img_url and img_url.startswith('http'):
                        screenshots.append(img_url)
                        if len(screenshots) == 3:
                            break
                if len(screenshots) == 3:
                    break
            data["screenshots"] = screenshots
        except Exception as e:
            print(f"    [!] Ошибка сбора скриншотов в теме {topic_id}: {e}")

    time.sleep(1.5) # Анти-бан пауза
    return data

def get_total_pages(session):
    """Определяет общее количество страниц в подразделе"""
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
    
    # 1. Загрузка существующей базы
    existing_data = []
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except Exception as e:
            print(f"(!) Ошибка файла базы данных: {e}. Создаем новый.")

    existing_dict = {str(item.get('topic_id')): item for item in existing_data if item.get('topic_id')}

    # 2. Интеллектуальный выбор глубины сканирования
    if not existing_dict:
        print("[*] Первый запуск: файл базы пуст. Сканирую абсолютно ВСЕ страницы раздела...")
        total_pages = get_total_pages(session)
    else:
        print(f"[*] База содержит {len(existing_dict)} игр. Включаю режим обновлений (проверяю первые 5 страниц).")
        total_pages = 5

    print(f"[*] Глубина сканирования установлена на: {total_pages} страниц(ы).")

    new_entries = []
    has_updates = False  

    # 3. Парсинг страниц
    for p in range(total_pages):
        start = p * 50
        url = f"{BASE_URL}viewforum.php?f={FORUM_ID}&start={start}"
        print(f"\n--- Сканирование подраздела: Страница {p+1}/{total_pages} ---")
        
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            resp.encoding = 'windows-1251'
            soup = BeautifulSoup(resp.text, 'html.parser')
            rows = soup.select('tr.hl-tr')
            
            if p == 0: 
                rows = rows[16:]  # Надежно срезаем закрепы на первой странице

            for row in rows:
                link_tag = row.select_one('a.tt-text')
                if not link_tag: 
                    continue
                
                topic_id = link_tag['href'].split('=')[-1]
                title = clean_title(link_tag.text)

                size_td = row.select_one('td.tor-size')
                forum_size = size_td.get_text(strip=True).replace('\xa0', ' ') if size_td else "Unknown"

                # СИТУАЦИЯ 1: Тема уже есть в нашей базе данных
                if topic_id in existing_dict:
                    old_entry = existing_dict[topic_id]
                    
                    if forum_size != "Unknown" and forum_size in old_entry.get('size', ''):
                        continue
                    
                    print(f"[*] Зафиксировано обновление раздачи [{topic_id}]: {title[:40]}...")
                    details = get_topic_data(session, topic_id)
                    
                    # Обновляем все поля в существующей записи (убрали performance)
                    existing_dict[topic_id].update({
                        "title": title,
                        "size": details["size"] if details["size"] != "Unknown" else forum_size,
                        "magnet": details["magnet"],
                        "year": details["year"],
                        "genre": details["genre"],
                        "developer": details["developer"],
                        "publisher": details["publisher"],
                        "image_format": details["image_format"],
                        "interface_lang": details["interface_lang"],
                        "voice_lang": details["voice_lang"],
                        "cover": details["cover"],
                        "screenshots": details["screenshots"],
                        "description": details["description"]
                    })
                    has_updates = True

                # СИТУАЦИЯ 2: Это абсолютно новая тема, которой нет в базе
                else:
                    print(f"  > Найдена новинка на трекере: {title[:50]}...")
                    details = get_topic_data(session, topic_id)
                    
                    # Создаем запись (убрали performance)
                    new_entries.append({
                        "title": title,
                        "size": details["size"] if details["size"] != "Unknown" else forum_size,
                        "magnet": details["magnet"],
                        "topic_id": topic_id,
                        "url": f"{BASE_URL}viewtopic.php?t={topic_id}",
                        "year": details["year"],
                        "genre": details["genre"],
                        "developer": details["developer"],
                        "publisher": details["publisher"],
                        "image_format": details["image_format"],
                        "interface_lang": details["interface_lang"],
                        "voice_lang": details["voice_lang"],
                        "cover": details["cover"],
                        "screenshots": details["screenshots"],
                        "description": details["description"]
                    })
        except Exception as e:
            print(f"(!) Ошибка при обработке списка на странице {p+1}: {e}")
            continue

    # 4. Сохранение результатов в файл
    if new_entries or has_updates:
        full_db = new_entries + list(existing_dict.values())
        try:
            with open(JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(full_db, f, ensure_ascii=False, indent=4)
            print(f"\n[+] База успешно обновлена и записана в {JSON_FILE}.")
            print(f"[+] Всего в базе сохранено: {len(full_db)} игр.")
            print(f"[+] Добавлено новых релизов за этот сеанс: {len(new_entries)}.")
        except Exception as e:
            print(f"(!) Не удалось сохранить данные в файл: {e}")
    else:
        print("\n[=] На проверенных страницах изменений и новых раздач не обнаружено.")

if __name__ == "__main__":
    run_scraper()
