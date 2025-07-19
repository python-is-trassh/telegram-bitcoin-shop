#!/bin/bash

# Скрипт для настройки и развертывания Telegram Bitcoin Shop Bot

echo "🚀 Настройка Telegram Bitcoin Shop Bot"

# Проверка прав суперпользователя
if [[ $EUID -ne 0 ]]; then
   echo "❌ Этот скрипт должен запускаться с правами root (sudo)"
   exit 1
fi

# Обновление системы
echo "📦 Обновление системы..."
apt update && apt upgrade -y

# Установка необходимых пакетов
echo "📦 Установка необходимых пакетов..."
apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib git curl

# Создание пользователя для бота
echo "👤 Создание пользователя bot..."
if ! id "bot" &>/dev/null; then
    useradd -m -s /bin/bash bot
    echo "✅ Пользователь bot создан"
else
    echo "ℹ️ Пользователь bot уже существует"
fi

# Создание директории для бота
echo "📁 Создание директории для бота..."
mkdir -p /opt/telegram-bot
chown bot:bot /opt/telegram-bot

# Переход в директорию бота
cd /opt/telegram-bot

# Копирование файлов если они есть в текущей директории
if [ -f "../main.py" ]; then
    cp ../main.py .
    cp ../requirements.txt .
    cp ../.env.example .env
    chown bot:bot main.py requirements.txt .env
    echo "✅ Файлы скопированы"
fi

# Создание виртуального окружения
echo "🐍 Создание виртуального окружения..."
sudo -u bot python3 -m venv venv
sudo -u bot ./venv/bin/pip install --upgrade pip

# Установка зависимостей
echo "📦 Установка зависимостей Python..."
sudo -u bot ./venv/bin/pip install -r requirements.txt

# Настройка PostgreSQL
echo "🗃️ Настройка PostgreSQL..."

# Запуск PostgreSQL
systemctl start postgresql
systemctl enable postgresql

# Создание пользователя и базы данных
sudo -u postgres psql -c "SELECT 1 FROM pg_roles WHERE rolname='botuser'" | grep -q 1
if [ $? -ne 0 ]; then
    echo "Создание пользователя PostgreSQL..."
    echo "Введите пароль для пользователя botuser:"
    sudo -u postgres createuser --interactive --pwprompt botuser
else
    echo "ℹ️ Пользователь botuser уже существует"
fi

sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw botdb
if [ $? -ne 0 ]; then
    echo "Создание базы данных..."
    sudo -u postgres createdb -O botuser botdb
    echo "✅ База данных botdb создана"
else
    echo "ℹ️ База данных botdb уже существует"
fi

# Создание systemd сервиса
echo "⚙️ Настройка systemd сервиса..."
cat > /etc/systemd/system/telegram-bot.service << 'EOF'
[Unit]
Description=Telegram Bitcoin Shop Bot
After=network.target postgresql.service

[Service]
Type=simple
User=bot
WorkingDirectory=/opt/telegram-bot
ExecStart=/opt/telegram-bot/venv/bin/python main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

# Загрузка переменных окружения
EnvironmentFile=/opt/telegram-bot/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable telegram-bot

# Создание скрипта для управления ботом
cat > /usr/local/bin/botctl << 'EOF'
#!/bin/bash

case "$1" in
    start)
        systemctl start telegram-bot
        echo "🚀 Бот запущен"
        ;;
    stop)
        systemctl stop telegram-bot
        echo "⏹️ Бот остановлен"
        ;;
    restart)
        systemctl restart telegram-bot
        echo "🔄 Бот перезапущен"
        ;;
    status)
        systemctl status telegram-bot
        ;;
    logs)
        journalctl -u telegram-bot -f
        ;;
    edit)
        nano /opt/telegram-bot/.env
        ;;
    *)
        echo "Использование: botctl {start|stop|restart|status|logs|edit}"
        echo ""
        echo "start   - запустить бота"
        echo "stop    - остановить бота"
        echo "restart - перезапустить бота"
        echo "status  - показать статус бота"
        echo "logs    - показать логи бота"
        echo "edit    - редактировать настройки"
        ;;
esac
EOF

chmod +x /usr/local/bin/botctl

echo ""
echo "✅ Настройка завершена!"
echo ""
echo "🔧 Дальнейшие шаги:"
echo "1. Отредактируйте файл конфигурации:"
echo "   botctl edit"
echo ""
echo "2. Укажите следующие параметры:"
echo "   - BOT_TOKEN: токен от @BotFather"
echo "   - DATABASE_URL: postgresql://botuser:ВАШ_ПАРОЛЬ@localhost:5432/botdb"
echo "   - BITCOIN_ADDRESS: ваш Bitcoin адрес"
echo "   - ADMIN_IDS: ID администраторов через запятую"
echo ""
echo "3. Запустите бота:"
echo "   botctl start"
echo ""
echo "📊 Команды для управления:"
echo "- Запуск: botctl start"
echo "- Остановка: botctl stop"
echo "- Перезапуск: botctl restart"
echo "- Статус: botctl status"
echo "- Логи: botctl logs"
echo "- Настройки: botctl edit"
echo ""
echo "📁 Файлы бота находятся в: /opt/telegram-bot"
echo "📋 Конфигурация: /opt/telegram-bot/.env
