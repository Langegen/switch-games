import os
import sys
import time
import urllib.parse
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from cf_utils import click_turnstile, inject_cookies, wait_page

LOGIN_URL = 'https://rutracker.org/forum/login.php'

# Опциональный прокси для обхода Cloudflare: RUTRACKER_PROXY=socks5://127.0.0.1:1080
PROXY_URL = os.environ.get("RUTRACKER_PROXY", "").strip()
# Переопределение User-Agent (если используются куки cf_clearance с другого браузера)
UA_OVERRIDE = os.environ.get("RUTRACKER_UA", "").strip()


def _save_cookies_to_env(cookie_str):
    with open('.env', 'w', encoding='utf-8') as f:
        f.write(f"RUTRACKER_COOKIES='{cookie_str}'\n")
    try:
        os.chmod('.env', 0o600)
    except Exception:
        pass
    print("[+] Куки сохранены в .env")


def _cp1251_quote(s):
    return urllib.parse.quote(s.encode('cp1251', errors='replace'))


def _jar_to_dict(cookies):
    jar = cookies.jar if hasattr(cookies, 'jar') else cookies
    result = {}
    try:
        for c in jar:
            result[c.name] = c.value
    except Exception:
        pass
    return result


def login_with_curl(username, password):
    """Быстрый логин POST-запросом (curl_cffi, impersonate Chrome).
    Возвращает строку куки или None."""
    try:
        from curl_cffi import requests as cf_requests
    except ImportError:
        print("[~] curl_cffi не установлен, пропускаю быстрый логин.")
        return None

    body = (
        f"login_username={_cp1251_quote(username)}"
        f"&login_password={_cp1251_quote(password)}"
        f"&login={_cp1251_quote('Вход')}"
    ).encode()
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': 'https://rutracker.org',
        'Referer': LOGIN_URL,
        'User-Agent': UA_OVERRIDE or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    try:
        print("[*] Пробую быстрый логин через curl_cffi...")
        kwargs = {'impersonate': 'chrome120', 'timeout': 30, 'allow_redirects': False}
        if PROXY_URL:
            kwargs['proxies'] = {'http': PROXY_URL, 'https': PROXY_URL}
        resp = cf_requests.post(LOGIN_URL, data=body, headers=headers, **kwargs)
        if 'Один момент' in resp.text or 'Just a moment' in resp.text:
            print("[~] Cloudflare блокирует прямой запрос.")
            return None
        cookies = _jar_to_dict(resp.cookies)
        if 'bb_session' not in cookies:
            print(f"[~] bb_session не получен (статус {resp.status_code}).")
            return None
        # Догружаем bb_guid и свежий cf_clearance с главной
        try:
            r2 = cf_requests.get('https://rutracker.org/forum/index.php',
                                 cookies=resp.cookies, headers=headers,
                                 impersonate='chrome120', timeout=30)
            cookies.update(_jar_to_dict(r2.cookies))
        except Exception:
            pass
        print("[+] Успешный вход через curl_cffi!")
        return '; '.join(f'{k}={v}' for k, v in cookies.items())
    except Exception as e:
        print(f"[~] curl_cffi логин не удался: {e}")
        return None


def login_with_chrome(username, password, headless=True):
    """Логин через undetected-chromedriver (обходит Cloudflare).
    Возвращает строку куки или None."""
    print("[*] Инициализация Chrome...")
    options = uc.ChromeOptions()
    if headless:
        options.add_argument('--headless')
    if UA_OVERRIDE:
        options.add_argument(f'--user-agent={UA_OVERRIDE}')
    # VPS: запуск от root и мало shared-памяти
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
    if PROXY_URL:
        options.add_argument(f'--proxy-server={PROXY_URL}')
    # Экономим память на VPS
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--no-first-run')
    options.add_argument('--window-size=1920,1080')

    driver = uc.Chrome(options=options)
    try:
        print("[*] Открываем страницу входа...")
        driver.get(LOGIN_URL)

        # Ждём форму входа, кликая Turnstile и перезагружаясь при зависании
        form_ok = wait_page(driver, timeout=150, reload_every=40,
                            success_keywords=('login_username',))
        if not form_ok:
            print("[!] Форма входа не появилась (Cloudflare не пройден).")
            try:
                driver.save_screenshot('login_debug_fail.png')
            except Exception:
                pass
            return None

        # Дожидаемся видимой кликабельной формы (элемент может быть в DOM,
        # но скрыт, если Cloudflare ещё не завершил рендер)
        try:
            WebDriverWait(driver, 15).until(
                EC.visibility_of_element_located((By.NAME, 'login_username')))
        except Exception:
            print("[!] Форма не стала видимой за 15 сек.")
            try:
                driver.save_screenshot('login_debug_fail.png')
            except Exception:
                pass
            return None

        print("[*] Вводим логин и пароль...")
        time.sleep(1)  # дать странице доинициализироваться

        def robust_fill(name, value):
            """Ввод с ожиданием кликабельности и JS-fallback."""
            field = driver.find_element(By.NAME, name)
            try:
                WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.NAME, name)))
                field.click()
                field.clear()
                field.send_keys(value)
            except Exception:
                print(f"[~] Обычный ввод не сработал ({name}), ставлю через JS...")
                driver.execute_script(
                    "arguments[0].value = arguments[1];", field, value)
            return field

        robust_fill('login_username', username)
        robust_fill('login_password', password)

        submit = driver.find_element(By.NAME, 'login')
        try:
            WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.NAME, 'login')))
            submit.click()
        except Exception:
            print("[~] Клик по кнопке 'Вход' не сработал, жму через JS...")
            driver.execute_script("arguments[0].click();", submit)

        print("[*] Ожидание завершения авторизации...")
        deadline = time.time() + 30
        cookies = {}
        while time.time() < deadline:
            cookies = {c['name']: c['value'] for c in driver.get_cookies()}
            if 'bb_session' in cookies:
                break
            time.sleep(1)

        if 'bb_session' not in cookies:
            print("[!] bb_session не получен (проверьте логин/пароль).")
            try:
                driver.save_screenshot('login_debug_fail.png')
            except Exception:
                pass
            return None

        print("[+] Успешный вход!")
        return '; '.join(f'{k}={v}' for k, v in cookies.items())
    except Exception as e:
        print(f"[!] Ошибка во время авторизации: {e}")
        return None
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def login(username, password, headless=True):
    cookie_str = login_with_curl(username, password)
    if not cookie_str:
        cookie_str = login_with_chrome(username, password, headless=headless)
    if not cookie_str:
        print("[!] Авторизация не удалась.")
        sys.exit(1)
    _save_cookies_to_env(cookie_str)


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
