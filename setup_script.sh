#!/bin/bash

# Скрипт для настройки и развертывания Telegram Bitcoin Shop Bot

echo "🚀 Настройка Telegram Bitcoin Shop Bot"

# Обновление системы
echo "📦 Обновление системы..."
sudo apt update && sudo apt upgrade -y

# Установка необходимых пакетов
echo "📦 Установка необходимых пакетов..."
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib nginx certbot python3-certbot-nginx

# Создание пользователя для бота
echo "👤 Создание пользователя bot..."
sudo useradd -m -s /bin/bash bot

# Создание директории для бота
echo "📁 Создание директории для бота..."
sudo mkdir -p /opt/telegram-bot
sudo chown bot:bot /opt/telegram-bot

# Переход в директорию бота
cd /opt/telegram-bot

# Создание виртуального окружения
echo "🐍 Создание виртуального окружения..."
sudo -u bot python3 -m venv venv
sudo -u bot ./venv/bin/pip install --upgrade pip

# Установка зависимостей
echo "📦 Установка зависимостей Python..."
sudo -u bot ./venv/bin/pip install -r requirements.txt

# Настройка PostgreSQL
echo "🗃️ Настройка PostgreSQL..."
sudo -u postgres createuser --interactive --pwprompt botuser
sudo -u postgres createdb -O botuser botdb

# Копирование файлов
echo "📄 Копирование файлов..."
sudo cp main.py /opt/telegram-bot/
sudo cp requirements.txt /opt/telegram-bot/
sudo cp .env.example /opt/telegram-bot/.env
sudo chown -R bot:bot /opt/telegram-bot

# Настройка systemd
echo "⚙️ Настройка systemd сервиса..."
sudo cp telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot

echo "✅ Настройка завершена!"
echo ""
echo "🔧 Дальнейшие шаги:"
echo "1. Отредактируйте файл /opt/telegram-bot/.env"
echo "2. Укажите BOT_TOKEN от @BotFather"
echo "3. Укажите DATABASE_URL для PostgreSQL"
echo "4. Укажите BITCOIN_ADDRESS для приема платежей"
echo "5. Укажите ADMIN_IDS администраторов"
echo "6. Запустите бота: sudo systemctl start telegram-bot"
echo "7. Проверьте статус: sudo systemctl status telegram-bot"
echo ""
echo "📊 Команды для управления:"
echo "- Запуск: sudo systemctl start telegram-bot"
echo "- Остановка: sudo systemctl stop telegram-bot"
echo "- Перезапуск: sudo systemctl restart telegram-bot"
echo "- Статус: sudo systemctl status telegram-bot"
echo "- Логи: sudo journalctl -u telegram-bot -f"