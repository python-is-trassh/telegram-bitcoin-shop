import os
import logging
import re
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
DB_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost/botdb')
BITCOIN_ADDRESS = os.getenv('BITCOIN_ADDRESS')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
BLOCKCHAIN_API_KEY = os.getenv('BLOCKCHAIN_API_KEY', '')
TEST_MODE = os.getenv('TEST_MODE', 'false').lower() == 'true'

# ИСПРАВЛЕНИЕ: Дополнительные настройки безопасности
MAX_ORDERS_PER_USER = int(os.getenv('MAX_ORDERS_PER_USER', '5'))
ORDER_TIMEOUT_MINUTES = int(os.getenv('ORDER_TIMEOUT_MINUTES', '30'))
RATE_LIMIT_ENABLED = os.getenv('RATE_LIMIT_ENABLED', 'true').lower() == 'true'
MAX_REQUESTS_PER_MINUTE = int(os.getenv('MAX_REQUESTS_PER_MINUTE', '30'))

# ИСПРАВЛЕНИЕ: Валидация Bitcoin адреса
def validate_bitcoin_address(address: str) -> bool:
    """Базовая валидация Bitcoin адреса"""
    if not address:
        return False
    
    # Проверяем длину и формат для разных типов адресов
    if address.startswith('1'):  # P2PKH
        return len(address) >= 26 and len(address) <= 35 and address.isalnum()
    elif address.startswith('3'):  # P2SH
        return len(address) >= 26 and len(address) <= 35 and address.isalnum()
    elif address.startswith('bc1'):  # Bech32
        return len(address) >= 42 and len(address) <= 62 and re.match(r'^bc1[a-z0-9]+$', address)
    
    return False

def validate_config():
    """Проверка обязательных переменных с улучшенной валидацией"""
    errors = []
    warnings = []
    
    # ИСПРАВЛЕНИЕ: Проверка токена бота
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN не установлен")
    elif not BOT_TOKEN.endswith(':AAG') and not BOT_TOKEN.endswith(':AAH'):
        # Базовая проверка формата токена Telegram
        if len(BOT_TOKEN.split(':')) != 2:
            warnings.append("BOT_TOKEN имеет подозрительный формат")
    
    # ИСПРАВЛЕНИЕ: Проверка Bitcoin адреса
    if not BITCOIN_ADDRESS:
        errors.append("BITCOIN_ADDRESS не установлен")
    elif not validate_bitcoin_address(BITCOIN_ADDRESS):
        errors.append(f"BITCOIN_ADDRESS имеет некорректный формат: {BITCOIN_ADDRESS}")
    
    # ИСПРАВЛЕНИЕ: Проверка базы данных
    if not DB_URL:
        errors.append("DATABASE_URL не установлен")
    elif not DB_URL.startswith('postgresql://'):
        warnings.append("DATABASE_URL должен начинаться с 'postgresql://'")
    
    # ИСПРАВЛЕНИЕ: Проверка админов
    if not ADMIN_IDS:
        warnings.append("ADMIN_IDS не установлены - админские функции будут недоступны")
    else:
        # Проверяем, что все ID положительные числа
        invalid_ids = [aid for aid in ADMIN_IDS if aid <= 0]
        if invalid_ids:
            errors.append(f"Некорректные ADMIN_IDS: {invalid_ids}")
    
    # ИСПРАВЛЕНИЕ: Проверка лимитов
    if MAX_ORDERS_PER_USER <= 0:
        errors.append("MAX_ORDERS_PER_USER должен быть больше 0")
    elif MAX_ORDERS_PER_USER > 20:
        warnings.append("MAX_ORDERS_PER_USER слишком большой (рекомендуется <= 20)")
    
    if ORDER_TIMEOUT_MINUTES <= 0:
        errors.append("ORDER_TIMEOUT_MINUTES должен быть больше 0")
    elif ORDER_TIMEOUT_MINUTES > 60:
        warnings.append("ORDER_TIMEOUT_MINUTES слишком большой (рекомендуется <= 60)")
    
    if MAX_REQUESTS_PER_MINUTE <= 0:
        errors.append("MAX_REQUESTS_PER_MINUTE должен быть больше 0")
    elif MAX_REQUESTS_PER_MINUTE > 100:
        warnings.append("MAX_REQUESTS_PER_MINUTE слишком большой (рекомендуется <= 100)")
    
    # ИСПРАВЛЕНИЕ: Проверка тестового режима в продакшене
    if TEST_MODE:
        warnings.append("🧪 ВКЛЮЧЕН ТЕСТОВЫЙ РЕЖИМ - отключите для продакшена!")
    
    # Выводим ошибки и предупреждения
    if warnings:
        for warning in warnings:
            logger.warning(f"⚠️ {warning}")
    
    if errors:
        for error in errors:
            logger.error(f"❌ {error}")
        return False
    
    # ИСПРАВЛЕНИЕ: Выводим итоговую конфигурацию
    logger.info("✅ Конфигурация валидна")
    logger.info(f"📍 Bitcoin адрес: {BITCOIN_ADDRESS}")
    logger.info(f"👥 Администраторов: {len(ADMIN_IDS)}")
    logger.info(f"📊 Лимиты: {MAX_ORDERS_PER_USER} заказов/{ORDER_TIMEOUT_MINUTES} мин")
    if RATE_LIMIT_ENABLED:
        logger.info(f"🛡️ Rate limit: {MAX_REQUESTS_PER_MINUTE} запросов/мин")
    
    return True

# ИСПРАВЛЕНИЕ: Дополнительные настройки для безопасности
SENSITIVE_PATTERNS = [
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
    r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',  # Кредитные карты
    r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
]

def contains_sensitive_data(text: str) -> bool:
    """Проверка на чувствительные данные в тексте"""
    if not text or not isinstance(text, str):
        return False
    
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

# ИСПРАВЛЕНИЕ: Blacklist для подозрительных доменов
SUSPICIOUS_DOMAINS = [
    'bit.ly', 'tinyurl.com', 'short.link', 't.co',
    'telegram.me', 'telegram.org'  # Фишинговые домены
]

def is_suspicious_link(url: str) -> bool:
    """Проверка на подозрительные ссылки"""
    if not url or not isinstance(url, str):
        return False
    
    url_lower = url.lower()
    for domain in SUSPICIOUS_DOMAINS:
        if domain in url_lower:
            return True
    return False
