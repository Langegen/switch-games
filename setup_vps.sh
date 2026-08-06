#!/bin/bash
# ============================================================
# Универсальная установка парсера switch-games на VPS
# Debian/Ubuntu, x86_64. Запуск: bash setup_vps.sh
# Скрипт идемпотентен - повторный запуск только обновляет.
# ============================================================
set -e

REPO_URL_DEFAULT="https://github.com/Langegen/switch-games.git"
INSTALL_DIR="${INSTALL_DIR:-/root/switch-games-bot}"

log()  { echo -e "\n\033[1;32m[setup]\033[0m $1"; }
warn() { echo -e "\n\033[1;33m[!]\033[0m $1"; }
ask()  { read -r -p "$1" "$2" < /dev/tty; }

# ---------- 0. Проверки ----------
if [ "$(id -u)" != "0" ]; then
    echo "Запустите от root: sudo bash setup_vps.sh"
    exit 1
fi
if [ "$(uname -m)" != "x86_64" ]; then
    echo "Нужен VPS с архитектурой x86_64 (Google Chrome не поддерживает $(uname -m))"
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive

# ---------- 1. Системные пакеты ----------
log "Установка системных пакетов (git, python3, xvfb, cron)..."
apt-get update -qq
apt-get install -y -qq git python3 python3-venv wget cron xvfb >/dev/null

# ---------- 2. Google Chrome ----------
if command -v google-chrome >/dev/null 2>&1; then
    log "Google Chrome уже установлен: $(google-chrome --version)"
else
    log "Установка Google Chrome..."
    wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y -qq /tmp/chrome.deb >/dev/null
    rm -f /tmp/chrome.deb
fi

# ---------- 3. Репозиторий ----------
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Обновление репозитория в $INSTALL_DIR..."
    git -C "$INSTALL_DIR" pull --rebase || warn "git pull не удался (возможно, есть локальные изменения)"
elif [ -f "$(pwd)/run.sh" ] && [ -d "$(pwd)/.git" ]; then
    INSTALL_DIR="$(pwd)"
    log "Используем текущий каталог: $INSTALL_DIR"
else
    log "Клонирование репозитория в $INSTALL_DIR..."
    git clone "$REPO_URL_DEFAULT" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ---------- 4. Python-окружение ----------
if [ ! -x venv/bin/python3 ]; then
    log "Создание виртуального окружения..."
    python3 -m venv venv
fi
log "Установка Python-зависимостей..."
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

# ---------- 5. GitHub: авторизация для push ----------
git config user.name "switch-games-bot"
git config user.email "switch-games-bot@users.noreply.github.com"
origin_url="$(git remote get-url origin 2>/dev/null || echo '')"
case "$origin_url" in
    https://*@github.com*|git@github.com*)
        log "Авторизация GitHub уже настроена."
        ;;
    *)
        echo ""
        echo "Для выгрузки базы в GitHub нужен Personal Access Token:"
        echo "  GitHub -> Settings -> Developer settings -> Personal access tokens -> Tokens (classic)"
        echo "  Права: repo (достаточно contents:write)."
        ask "Вставьте токен (Enter - пропустить, настроить позже): " GH_TOKEN
        if [ -n "$GH_TOKEN" ]; then
            repo_path="$(echo "$origin_url" | sed -E 's|https://github.com/||; s|\.git$||')"
            git remote set-url origin "https://${GH_TOKEN}@github.com/${repo_path}.git"
            log "GitHub-токен сохранён в remote."
        else
            warn "Push без токена работать не будет. Настроить позже:"
            warn "  git remote set-url origin https://<TOKEN>@github.com/${repo_path:-Langegen/switch-games}.git"
        fi
        ;;
esac

# ---------- 6. Куки RuTracker ----------
need_login=1
if [ -f .env ] && grep -q "RUTRACKER_COOKIES='[^']\+'" .env; then
    ask "Куки RuTracker уже есть в .env. Перелогиниться? [y/N]: " RELOGIN
    case "$RELOGIN" in y|Y|yes|YES) need_login=1 ;; *) need_login=0 ;; esac
fi
if [ "$need_login" = "1" ]; then
    echo ""
    echo "Как получить куки RuTracker?"
    echo "  1) Автоматически: вход по логину/паролю на самом VPS (Chrome обходит Cloudflare)"
    echo "  2) Вручную: вставить куки из браузера на ПК (если Cloudflare не проходится)"
    ask "Выбор [1]: " COOKIE_MODE
    COOKIE_MODE="${COOKIE_MODE:-1}"
    if [ "$COOKIE_MODE" = "2" ]; then
        ask "Вставьте строку куки (bb_session=...; bb_guid=...): " MANUAL_COOKIES
        if [ -n "$MANUAL_COOKIES" ]; then
            printf "RUTRACKER_COOKIES='%s'\n" "$MANUAL_COOKIES" > .env
            chmod 600 .env
            log "Куки сохранены в .env"
        else
            warn "Куки не вставлены, пропускаю."
        fi
    else
        ask "Логин RuTracker: " RT_USER
        read -r -s -p "Пароль RuTracker: " RT_PASS < /dev/tty
        echo ""
        log "Вход на RuTracker через Chrome (xvfb)..."
        if xvfb-run -a ./venv/bin/python3 login_rutracker.py "$RT_USER" "$RT_PASS" --gui; then
            log "Куки получены и сохранены в .env"
        else
            warn "Не удалось получить куки. Повторить позже:"
            warn "  cd $INSTALL_DIR && xvfb-run -a ./venv/bin/python3 login_rutracker.py ЛОГИН ПАРОЛЬ --gui"
            warn "Или вручную: редактор .env -> RUTRACKER_COOKIES='...'"
        fi
    fi
fi

# ---------- 7. Cron: ежедневный запуск ----------
ask "Час ежедневной проверки обновлений (0-23, по умолчанию 6): " CRON_HOUR
CRON_HOUR="${CRON_HOUR:-6}"
case "$CRON_HOUR" in (*[!0-9]*|'') CRON_HOUR=6 ;; esac
CRON_LINE="0 $CRON_HOUR * * * $INSTALL_DIR/run.sh >> $INSTALL_DIR/cron_log.txt 2>&1"
( crontab -l 2>/dev/null | grep -vF "$INSTALL_DIR/run.sh"; echo "$CRON_LINE" ) | crontab -
service cron start >/dev/null 2>&1 || true
log "Cron настроен: ежедневно в $CRON_HOUR:00"

# ---------- 8. Тестовый запуск ----------
ask "Запустить парсер прямо сейчас для проверки? [Y/n]: " RUN_NOW
case "$RUN_NOW" in
    n|N|no|NO) ;;
    *) log "Тестовый запуск run.sh..."; bash "$INSTALL_DIR/run.sh" ;;
esac

log "Готово! Логи: $INSTALL_DIR/cron_log.txt"
