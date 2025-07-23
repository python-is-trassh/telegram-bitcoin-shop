import os
import logging
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

# Проверка обязательных переменных
def validate_config():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен")
        return False
    
    if not BITCOIN_ADDRESS:
        logger.error("BITCOIN_ADDRESS не установлен")
        return False
    
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS не установлены - админские функции будут недоступны")
    
    return True
