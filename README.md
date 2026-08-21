# switch-games

Парсер раздач Nintendo Switch с RuTracker (форум `f=1605`). Собирает базу `switch_games.json` (игры, размеры, magnet-ссылки, обложки, описание, title_id), ежедневно проверяет новые и обновлённые раздачи через Atom-ленту и выкладывает изменения на GitHub.

## Как работает

- **Нет базы** → полный парсинг всех страниц форума (первые 15 закреплённых тем пропускаются).
- **База есть** → проверка Atom-ленты `https://feed.rutracker.cc/atom/f/1605.atom` (50 последних раздач): новые добавляются в начало базы, у уже известных тем **всегда** перечитывается страница (чтобы подхватить перезалив magnet при том же названии/размере). Затем дообогащаются первые 100 записей и ещё 50 magnet'ов круговым проходом по остальной базе.
- **Лог изменений** → `changes.txt` (добавлено/обновлено/дообогащено) перезаписывается при каждом запуске и коммитится в репозиторий.
- **Cloudflare** → обход через локальный сервис [CloudflareBypassForScraping](https://github.com/sarperavci/CloudflareBypassForScraping) (Docker-контейнер), с запасным путём через `undetected-chromedriver`.

## Структура

| Файл | Назначение |
|---|---|
| `scraper.py` | основной парсер |
| `run.sh` | ежедневный запуск: pull → парсер → коммит → push |
| `setup_vps.sh` | автоматическая установка всего на VPS одной командой |
| `login_rutracker.py` | получение кук RuTracker по логину/паролю |
| `test_connection.py` | диагностика доступа к RuTracker (curl/Chrome/bypass) |
| `cf_utils.py` | клик по Turnstile-чекбоксу Cloudflare |
| `switch_games.json` | база игр |
| `changes.txt` | лог последнего запуска (генерируется) |
| `.env` | куки и настройки (не коммитится) |

## Быстрая установка на VPS

Требования: **Debian/Ubuntu, x86_64, ≥4 ГБ свободного места на диске**.

```bash
curl -fsSL -o setup_vps.sh https://raw.githubusercontent.com/Langegen/switch-games/main/setup_vps.sh
sudo bash setup_vps.sh
```

Скрипт по шагам:

1. Устанавливает системные пакеты, Google Chrome, xvfb, Docker
2. Запускает контейнер `cf-bypass` (CloudflareBypassForScraping, порт 8000)
3. Клонирует/обновляет репозиторий в `/root/switch-games-bot`, создаёт venv, ставит зависимости
4. Настраивает GitHub-токен для push (спросит Personal Access Token с правами `repo`)
5. Получает куки RuTracker (два варианта на выбор):
   - **Автоматически** — вход по логину/паролю на самом VPS (через CloudflareBypassForScraping или Chrome)
   - **Вручную** — вставить строку куки `bb_session=...; bb_guid=...` из браузера
6. Настраивает cron (ежедневный час спрашивается, по умолчанию 6:00)
7. Предлагает сразу выполнить тестовый прогон

Скрипт идемпотентен — повторный запуск только обновляет (для перелогина ответьте `y` на вопрос о куках).

## Ручная установка

```bash
# 1. Пакеты и Chrome
apt update && apt install -y git python3-venv wget xvfb docker.io
wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt install -y /tmp/chrome.deb

# 2. Репозиторий
git clone https://github.com/Langegen/switch-games.git /root/switch-games-bot
cd /root/switch-games-bot
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# 3. Сервис обхода Cloudflare
docker run -d --name cf-bypass --restart unless-stopped -p 8000:8000 \
    ghcr.io/sarperavci/cloudflarebypassforscraping:latest

# 4. Куки в .env
cat > .env <<'EOF'
RUTRACKER_COOKIES='bb_guid=...; bb_session=...'
RUTRACKER_CF_BYPASS=http://localhost:8000
EOF
chmod 600 .env

# 5. GitHub-токен для push
git remote set-url origin https://<TOKEN>@github.com/Langegen/switch-games.git

# 6. Cron (ежедневно в 3:00)
(crontab -l 2>/dev/null; echo "0 3 * * * /root/switch-games-bot/run.sh >> /root/switch-games-bot/cron_log.txt 2>&1") | crontab -
```

## Конфигурация `.env`

| Переменная | Назначение |
|---|---|
| `RUTRACKER_COOKIES` | куки авторизации RuTracker (`bb_guid` + `bb_session`) |
| `RUTRACKER_CF_BYPASS` | адрес CloudflareBypassForScraping, напр. `http://localhost:8000` |
| `RUTRACKER_UA` | User-Agent браузера, который решал Cloudflare (для работы чужих `cf_clearance`) |
| `RUTRACKER_PROXY` | прокси для всех запросов, напр. `socks5://127.0.0.1:1080` |
| `RUTRACKER_NO_CURL` | `1` — отключить `curl_cffi` (на VPS он не проходит Cloudflare) |

## Запуск вручную

```bash
bash run.sh                                        # полный цикл: pull → парсер → push
./venv/bin/python3 login_rutracker.py ЛОГИН ПАРОЛЬ  # обновить куки
./venv/bin/python3 test_connection.py               # диагностика (запускать через xvfb-run)
```

## Формат записи в базе

```json
{
  "title": "Drakkar Crew [NSZ][RUS/Multi10]",
  "size": "442.3 MB",
  "magnet": "magnet:?xt=urn:btih:1718E610...",
  "topic_id": "6890951",
  "url": "https://rutracker.org/forum/viewtopic.php?t=6890951",
  "year": "2025, август",
  "genre": "Action, Role-Playing, Beatemup",
  "developer": "SiBear",
  "publisher": "SiBear Games",
  "image_format": ".NSZ (сжато ~64%, установленный объём 1.25 ГБ)",
  "interface_lang": "Русский, Английский [RUS / ENG / Multi 10]",
  "voice_lang": "не озвучивается",
  "performance": "Да (на 22.5.0, Atmosphere 1.11.2)",
  "multiplayer": "нет",
  "cover": "https://i7.imageban.ru/out/...",
  "screenshots": ["https://i128.fastpic.org/thumb/..."],
  "description": "«Сумерки, природа, флейты голос нервный...",
  "title_id": "01003CB02246E000"
}
```

## Примечания

- Cloudflare решает челлендж один раз за сессию, дальше `cf_clearance` переиспользуется — обычный прогон по ленте занимает ~1 минуту.
- Если контейнер `cf-bypass` упал: `docker restart cf-bypass` (при перезагрузке VPS поднимется сам — `--restart unless-stopped`).
- Логи: `cron_log.txt` (вывод cron), `docker logs cf-bypass`.
