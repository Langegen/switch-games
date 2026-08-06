"""Помощники для прохождения Cloudflare Turnstile через Selenium/uc.

- wait_page: ждёт настоящую страницу, кликая чекбокс Turnstile
  в iframe challenges.cloudflare.com и перезагружая страницу при зависании.
- inject_cookies: добавляет куки (bb_session/cf_clearance) в драйвер.
"""
import time

from selenium.webdriver.common.by import By

CHALLENGE_MARKERS = ('Just a moment', 'Один момент',
                     'cf-browser-verification', 'challenges.cloudflare.com')
SUCCESS_KEYWORDS = ('post_body', 'attach_link', 'hl-tr',
                    'forumtable', 'viewtopic', 'login_username')


def is_challenge(html):
    return any(m in html for m in CHALLENGE_MARKERS)


def click_turnstile(driver):
    """Кликает чекбокс 'я не робот' в iframe Cloudflare, если он виден."""
    try:
        for fr in driver.find_elements(By.TAG_NAME, 'iframe'):
            src = fr.get_attribute('src') or ''
            if 'challenges.cloudflare.com' in src:
                driver.switch_to.frame(fr)
                try:
                    cb = driver.find_element(By.CSS_SELECTOR, 'input[type=checkbox]')
                    if cb.is_displayed():
                        cb.click()
                        print("[~] Клик по Turnstile-чекбоксу")
                        return True
                except Exception:
                    pass
                finally:
                    driver.switch_to.default_content()
    except Exception:
        pass
    return False


def wait_page(driver, timeout=120, reload_every=45,
              success_keywords=SUCCESS_KEYWORDS):
    """Ждёт, пока страница станет настоящей (не челленджем).

    Периодически кликает Turnstile и перезагружает страницу.
    """
    deadline = time.time() + timeout
    last_reload = time.time()
    while time.time() < deadline:
        try:
            html = driver.page_source
        except Exception:
            html = ''
        if not is_challenge(html) and any(kw in html for kw in success_keywords):
            return True
        click_turnstile(driver)
        if time.time() - last_reload > reload_every:
            try:
                driver.refresh()
            except Exception:
                pass
            last_reload = time.time()
        time.sleep(1)
    return False


def inject_cookies(driver, cookies, domain='.rutracker.org'):
    """Добавляет куки в браузер (перед этим нужно открыть страницу домена)."""
    for k, v in cookies.items():
        try:
            driver.add_cookie({'name': k, 'value': v, 'domain': domain})
        except Exception:
            pass
