import sys
import time
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def login(username, password, headless=True):
    print("[*] Инициализация Chrome...")
    options = uc.ChromeOptions()
    if headless:
        options.add_argument('--headless')
    
    driver = uc.Chrome(options=options)
    try:
        print("[*] Открываем страницу входа...")
        driver.get('https://rutracker.org/forum/login.php')
        
        # Ждём, пока Cloudflare пропустит (появится форма логина)
        print("[*] Ожидание формы входа (прохождение Cloudflare)...")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.NAME, "login_username"))
        )
        
        print("[*] Вводим логин и пароль...")
        driver.find_element(By.NAME, 'login_username').send_keys(username)
        driver.find_element(By.NAME, 'login_password').send_keys(password)
        
        print("[*] Нажимаем кнопку Вход...")
        driver.find_element(By.NAME, 'login').click()
        
        # Ждём, пока произойдет редирект на главную после успешного входа
        print("[*] Ожидание завершения авторизации...")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "logged-in-username"))
        )
        
        print("[+] Успешный вход!")
        
        # Собираем куки
        cookies = driver.get_cookies()
        cookie_parts = []
        for c in cookies:
            cookie_parts.append(f"{c['name']}={c['value']}")
        
        cookie_str = "; ".join(cookie_parts)
        print("\n" + "="*50)
        print("ВАШИ КУКИ ДЛЯ .env ФАЙЛА (скопируйте строку ниже):")
        print("="*50)
        print(f"RUTRACKER_COOKIES='{cookie_str}'")
        print("="*50 + "\n")
        
        # Сохраняем в .env если файла нет
        env_path = '.env'
        if not os.path.exists(env_path):
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(f"RUTRACKER_COOKIES='{cookie_str}'\n")
            print("[+] Файл .env автоматически создан.")
        else:
            print("[!] Файл .env уже существует, обновите переменную RUTRACKER_COOKIES вручную.")
            
    except Exception as e:
        print(f"[!] Ошибка во время авторизации: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python login_rutracker.py <имя_пользователя> <пароль> [--gui]")
        print("  --gui : запустить с видимым окном браузера (по умолчанию headless)")
        sys.exit(1)
        
    user = sys.argv[1]
    pwd = sys.argv[2]
    use_headless = True
    
    if len(sys.argv) > 3 and sys.argv[3] == '--gui':
        use_headless = False
        
    login(user, pwd, headless=use_headless)
