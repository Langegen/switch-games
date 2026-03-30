import requests
from bs4 import BeautifulSoup
import time

# --- НАСТРОЙКИ ТЕСТА ---
COOKIES = {
    'bb_guid': 'CrOOBNfe69GK',
    'bb_session': '0-54834590-UDNVOQMt392dMLkGkblA',
    # Вставь сюда свежий cf_clearance из браузера (он часто меняется!)
    'cf_clearance': 'zxe2TJDKJSD19PBIOwQG2JZZJ1Xr5sZMSEWfw6eFWdk-1774861581-1.2.1.1-OH3lX48cUIICTyaI4Fk4SS3hbZcfSMGbFyJoO071fzx5uMdIWpTHikm21FgBmpGZccSCnYyzSvBdhLEOrO10UnfrtEhAdoLshhllSQKTcyKSXTY_5e1E37m0.LkQmifFhVoud.JBTqV3GqaE5Bi.h9lMZhWz8IxcsBwKuPr2toeHTFFBcyAeaFxqRP.WJ8CPQW2kzeaQbJAJV0CfzI0MqWsMKVd2kkUaUMI7A_R67zA', 
}

FORUM_ID = '1605'
BASE_URL = "https://rutracker.org/forum/"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
}

def run_test():
    session = requests.Session()
    session.cookies.update(COOKIES)
    
    print(f"[*] Запуск теста для раздела {FORUM_ID}...") # ИСПРАВЛЕНО
    
    try:
        # 1. Проверка авторизации
        print("[*] Шаг 1: Проверка входа...")
        resp = session.get(f"{BASE_URL}index.php", headers=HEADERS, timeout=15)
        resp.encoding = 'windows-1251'
        
        if "profile.php?mode=register" in resp.text or "login-php" in resp.text:
            print("[!] ОШИБКА: Сайт видит вас как ГОСТЯ. Обновите cf_clearance и bb_session!")
        else:
            print("[УСПЕХ] Вы успешно авторизованы.")

        # 2. Загрузка первой страницы раздела
        print(f"[*] Шаг 2: Загрузка списка игр...")
        forum_url = f"{BASE_URL}viewforum.php?f={FORUM_ID}"
        resp = session.get(forum_url, headers=HEADERS, timeout=15)
        resp.encoding = 'windows-1251'
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Ищем темы по классу 'tt-text'
        topics = soup.find_all('a', class_='tt-text')
        
        if not topics:
            print("[!] ОШИБКА: Темы не найдены. Проверьте debug.html")
            with open("debug.html", "w", encoding="windows-1251") as f:
                f.write(resp.text)
            return

        print(f"[УСПЕХ] Найдено тем на странице: {len(topics)}")
        print("\n--- ПОСЛЕДНИЕ 10 ИГР ---")
        
        for i, topic in enumerate(topics[:10]):
            title = topic.get_text(strip=True)
            topic_id = topic['href'].split('=')[-1]
            print(f"{i+1}. [{topic_id}] {title[:70]}...")

    except Exception as e:
        print(f"[!!!] Критическая ошибка: {e}")

if __name__ == "__main__":
    run_test()
