"""
Диагностика доступа к RuTracker с VPS.
Запуск: xvfb-run -a ./venv/bin/python3 test_connection.py

Показывает:
- ресурсы машины (память, swap) - чтобы понять, не OOM ли убивает Chrome
- проходит ли curl_cffi (разные отпечатки TLS)
- запускается ли Chrome и решает ли Cloudflare
- какой способ доступа рабочий
"""
import os
import sys
import time

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- Куки из .env ----------
cookies = {}
try:
    with open(os.path.join(BASE_DIR, '.env'), encoding='utf-8') as f:
        for line in f:
            if line.startswith('RUTRACKER_COOKIES='):
                raw = line.split('=', 1)[1].strip().strip("'\"")
                for item in raw.split(';'):
                    if '=' in item:
                        k, v = item.strip().split('=', 1)
                        cookies[k.strip()] = v.strip()
except FileNotFoundError:
    pass

TEST_URL = 'https://rutracker.org/forum/viewtopic.php?t=6890951'


def res_info():
    print("\n=== Ресурсы машины ===")
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith(('MemTotal', 'MemAvailable', 'SwapTotal')):
                    print(' ', line.strip())
    except OSError:
        pass
    try:
        n = os.cpu_count()
        print(f'  CPU: {n} ядер')
    except OSError:
        pass


def test_curl():
    print("\n=== Проверка curl_cffi (разные отпечатки TLS) ===")
    from curl_cffi import requests as cf
    UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ok_any = False
    for imp in ('chrome120', 'chrome131', 'safari17_0', 'chrome110'):
        try:
            r = cf.get(TEST_URL, headers={'User-Agent': UA}, cookies=cookies,
                       impersonate=imp, timeout=20)
            chal = 'Один момент' in r.text or 'Just a moment' in r.text
            ok = r.status_code == 200 and 'post_body' in r.text
            if ok:
                ok_any = True
            print(f'  {imp:12s} status={r.status_code} len={len(r.text):6d} '
                  f'challenge={chal} valid_page={ok}')
        except Exception as e:
            print(f'  {imp:12s} ОШИБКА: {e}')
    print(f'  -> curl_cffi {"РАБОТАЕТ" if ok_any else "НЕ работает (нужен Chrome)"}')
    return ok_any


def test_chrome():
    print("\n=== Проверка Chrome (Cloudflare) ===")
    import undetected_chromedriver as uc
    options = uc.ChromeOptions()
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--no-first-run')
    options.add_argument('--window-size=1920,1080')
    print("  Запуск Chrome (может занять 1-2 минуты)...")
    driver = uc.Chrome(options=options)
    try:
        driver.set_page_load_timeout(90)
        t0 = time.time()
        driver.get(TEST_URL)
        title = driver.title
        html = driver.page_source
        el = time.time() - t0
        chal = 'Один момент' in html or 'Just a moment' in html
        ok = 'post_body' in html
        print(f'  Загрузка за {el:.1f} сек, title={title!r}')
        print(f'  challenge={chal} valid_page={ok}')
        if ok:
            print('  -> Chrome РАБОТАЕТ')
            return True
        try:
            driver.save_screenshot(os.path.join(BASE_DIR, 'conn_debug.png'))
            print('  Скриншот сохранён: conn_debug.png')
        except Exception:
            pass
        print('  -> Cloudflare не пройден')
        return False
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == '__main__':
    res_info()
    print(f"\nКуки в .env: {'есть (' + ', '.join(cookies) + ')' if cookies else 'НЕТ'}")
    curl_ok = test_curl()
    chrome_ok = test_chrome()

    print("\n=== ВЕРДИКТ ===")
    if curl_ok:
        print("  Достаточно curl_cffi - скраппер заработает без Chrome.")
    elif chrome_ok:
        print("  Работает только Chrome - парсер будет использовать fallback (xvfb).")
    else:
        print("  Оба способа не прошли Cloudflare.")
        print("  Варианты: прокси через другой IP (RUTRACKER_PROXY) или куки с рабочего браузера.")
