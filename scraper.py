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

    title = re.sub(r'^\[Nintendo Switch\]\s*', '', title, flags=re.IGNORECASE).strip()

    return title.replace('"', "'")



def get_topic_data(session, topic_id):

    """Заходит внутрь темы и вытаскивает все метаданные, обложку, скриншоты, описание и магнет"""

    url = f"{BASE_URL}viewtopic.php?t={topic_id}"

    

    # Заготовка со всеми дефолтными значениями

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

        "performance": "Unknown",

        "cover": None,

        "screenshots": [],

        "description": "Unknown"

    }

    

    try:

        resp = session.get(url, headers=HEADERS, timeout=10)

        resp.encoding = 'windows-1251'

        soup = BeautifulSoup(resp.text, 'html.parser')

        

        # 1. Парсим блок скачивания (магнет и точный размер)

        attach_div = soup.find('div', class_='attach_link')

        if attach_div:

            mag_link = attach_div.find('a', class_='magnet-link')

            if mag_link:

                data["magnet"] = mag_link.get('href')

            

            list_items = attach_div.find_all('li')

            if list_items:

                raw_size = list_items[-1].get_text(strip=True)

                data["size"] = raw_size.replace('\xa0', ' ').replace('&nbsp;', ' ')

        

        # Находим главный блок сообщения с описанием игры

        post_body = soup.select_one('div.post_body')

        if post_body:

            # Получаем чистый текст поста для регулярных выражений

            full_text = post_body.get_text()

            

            # Вспомогательная функция для поиска параметров через регулярки

            def extract_field(pattern, text):

                match = re.search(pattern, text, re.IGNORECASE)

                return match.group(1).strip() if match else "Unknown"



            # 2. Вытаскиваем текстовые параметры

            data["year"] = extract_field(r'(?:Год выпуска|Год|Дата выхода)\s*:\s*([^\n]+)', full_text)

            data["genre"] = extract_field(r'Жанр\s*:\s*([^\n]+)', full_text)

            data["developer"] = extract_field(r'Разработчик\s*:\s*([^\n]+)', full_text)

            data["publisher"] = extract_field(r'Издатель\s*:\s*([^\n]+)', full_text)

            data["image_format"] = extract_field(r'(?:Формат образа|Формат)\s*:\s*([^\n]+)', full_text)

            data["interface_lang"] = extract_field(r'(?:Язык интерфейса|Интерфейс)\s*:\s*([^\n]+)', full_text)

            data["voice_lang"] = extract_field(r'(?:Озвучка|Язык озвучки)\s*:\s*([^\n]+)', full_text)

            data["performance"] = extract_field(r'(?:Работоспособность|Проверено)\s*:\s*([^\n]+)', full_text)



            # 3. Вытаскиваем Описание (Description) до первой пустой строки или следующего блока

            desc_label = post_body.find(lambda tag: tag.name in ['span', 'b'] and 'Описание' in tag.get_text())

            if desc_label:

                desc_fragments = []

                for sibling in desc_label.next_siblings:

                    # Если встретили перенос строки <span class="post-br"><br></span>

                    if sibling.name == 'span' and 'post-br' in sibling.get('class', []):

                        if desc_fragments and ''.join(desc_fragments).strip():

                            # Проверяем, идет ли следом еще один перенос (т.е. пустая строка)

                            next_sib = sibling.find_next_sibling()

                            if next_sib and next_sib.name == 'span' and 'post-br' in next_sib.get('class', []):

                                break

                            desc_fragments.append("\n")

                            continue

                    

                    # Если наткнулись на следующий жирный заголовок раздачи — выходим

                    if sibling.name in ['span', 'b', 'div'] and any(word in sibling.get_text() for word in ['Скриншоты', 'Особенности', 'Дополнительно']):

                        break

                        

                    if isinstance(sibling, str):

                        desc_fragments.append(sibling)

                    elif sibling.name not in ['var', 'div']:

                        desc_fragments.append(sibling.get_text())



                final_desc = "".join(desc_fragments).strip()

                if final_desc:

                    data["description"] = re.sub(r'\n+', '\n', final_desc)



            # 4. Ссылки на картинки (Обложка справа)

            cover_var = post_body.find('var', class_='img-right')

            if cover_var and cover_var.get('title'):

                data["cover"] = cover_var.get('title')

            else:

                # Фолбэк: если специального класса нет, берем самую первую картинку релиза

                first_var = post_body.find('var', class_='postImg')

                if first_var:

                    data["cover"] = first_var.get('title')



            # 5. Ссылки на 3 скриншота (из спойлеров)

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



        time.sleep(1.5) # Анти-бан пауза

    except:

        pass

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

    

    # 1. Загрузка базы

    existing_data = []

    if os.path.exists(JSON_FILE):

        try:

            with open(JSON_FILE, 'r', encoding='utf-8') as f:

                existing_data = json.load(f)

        except:

            print("(!) Ошибка файла базы данных. Создаем новый.")



    # Пересобираем существующую базу в словарь для быстрого поиска и обновления по ID

    existing_dict = {str(item.get('topic_id')): item for item in existing_data if item.get('topic_id')}



    # 2. Определение глубины сканирования

    if not existing_dict:

        print("[*] Первый запуск: сканирую ВСЕ страницы раздела.")

        total_pages = get_total_pages(session)

    else:

        print(f"[*] В базе {len(existing_dict)} игр. Проверяю 5 страниц на новинки и обновления.")

        total_pages = 5



    new_entries = []

    has_updates = False  # Флаг изменения старых раздач



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

            if p == 0: 

                rows = rows[16:]  # Пропускаем закрепленные темы/шапки на первой странице



            for row in rows:

                link_tag = row.select_one('a.tt-text')

                if not link_tag: 

                    continue

                

                topic_id = link_tag['href'].split('=')[-1]

                title = clean_title(link_tag.text)



                # Вытаскиваем размер раздачи, который виден в общем списке тем форума

                size_td = row.select_one('td.tor-size')

                forum_size = size_td.get_text(strip=True).replace('\xa0', ' ') if size_td else "Unknown"



                # СИТУАЦИЯ 1: Тема уже есть в нашей базе данных

                if topic_id in existing_dict:

                    old_entry = existing_dict[topic_id]

                    

                    # Проверяем, входит ли короткая строка размера с форума ("1.45 GB") 

                    # в нашу длинную строку точного размера из JSON ("1.45 GB (1554123 байт)").

                    if forum_size != "Unknown" and forum_size in old_entry.get('size', ''):

                        # Размеры совпали, раздача не обновлялась. Пропускаем тему без захода внутрь.

                        continue

                    

                    # Если размеры не совпали — раздача обновилась (залили патч, DLC или новую версию)

                    print(f"[*] Обнаружено обновление в теме [{topic_id}]: {title[:40]}...")

                    details = get_topic_data(session, topic_id)

                    

                    # Обновляем все поля в существующей записи

                    existing_dict[topic_id].update({

                        "title": title,

                        "size": details["size"],

                        "magnet": details["magnet"],

                        "year": details["year"],

                        "genre": details["genre"],

                        "developer": details["developer"],

                        "publisher": details["publisher"],

                        "image_format": details["image_format"],

                        "interface_lang": details["interface_lang"],

                        "voice_lang": details["voice_lang"],

                        "performance": details["performance"],

                        "cover": details["cover"],

                        "screenshots": details["screenshots"],

                        "description": details["description"]

                    })

                    

                    has_updates = True



                # СИТУАЦИЯ 2: Это абсолютно новая тема, которой нет в базе

                else:

                    print(f"  > Найдена новинка: {title[:50]}...")

                    details = get_topic_data(session, topic_id)

                    

                    new_entries.append({

                        "title": title,

                        "size": details["size"],

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

                        "performance": details["performance"],

                        "cover": details["cover"],

                        "screenshots": details["screenshots"],

                        "description": details["description"]

                    })

        except Exception as e:

            print(f"(!) Ошибка при обработке страницы {p+1}: {e}")

            continue



    # 4. Сохранение результатов

    if new_entries or has_updates:

        # Новые записи пойдут в самое начало файла, обновленные старые остаются на своих позициях

        full_db = new_entries + list(existing_dict.values())

        try:

            with open(JSON_FILE, 'w', encoding='utf-8') as f:

                json.dump(full_db, f, ensure_ascii=False, indent=4)

            print(f"[+] База успешно сохранена. Добавлено новинок: {len(new_entries)}.")

        except Exception as e:

            print(f"(!) Не удалось сохранить данные в файл: {e}")

    else:

        print("[=] Изменений и новых игр на проверенных страницах не обнаружено.")



if __name__ == "__main__":

    run_scraper() 

