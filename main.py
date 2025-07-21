import asyncio
import logging
import decimal
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import random

import asyncpg
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from dotenv import load_dotenv

# Настройка окружения
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
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не установлен")
    exit(1)

if not BITCOIN_ADDRESS:
    logger.error("BITCOIN_ADDRESS не установлен")
    exit(1)

if not ADMIN_IDS:
    logger.warning("ADMIN_IDS не установлены - админские функции будут недоступны")

# Состояния FSM
class UserStates(StatesGroup):
    MAIN_MENU = State()
    BROWSING_CATEGORIES = State()
    BROWSING_PRODUCTS = State()
    VIEWING_PRODUCT = State()
    SELECTING_LOCATION = State()
    PAYMENT_WAITING = State()
    PAYMENT_CHECKING = State()

class AdminStates(StatesGroup):
    ADMIN_MENU = State()
    ADDING_CATEGORY = State()
    ADDING_PRODUCT = State()
    ADDING_LOCATION = State()
    EDITING_CONTENT = State()
    EDITING_ABOUT = State()
    MANAGE_CATEGORIES = State()
    MANAGE_PRODUCTS = State()
    MANAGE_LOCATIONS = State()
    EDITING_CATEGORY = State()
    EDITING_PRODUCT = State()
    EDITING_LOCATION = State()

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Кэш для курса Bitcoin
btc_rate_cache = {'rate': None, 'timestamp': None}

class DatabaseManager:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None
    
    async def init_pool(self):
        """Инициализация пула соединений"""
        try:
            self.pool = await asyncpg.create_pool(
                self.db_url,
                min_size=1,
                max_size=5,
                command_timeout=60
            )
            await self.create_tables()
            logger.info("База данных инициализирована")
        except Exception as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            raise
    
    async def create_tables(self):
        """Создание всех необходимых таблиц"""
        async with self.pool.acquire() as conn:
            # Создаем таблицы с правильными типами данных и foreign key constraints
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    description TEXT DEFAULT '',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    category_id INTEGER REFERENCES categories(id),
                    name VARCHAR(255) NOT NULL,
                    description TEXT DEFAULT '',
                    price_rub DECIMAL(10,2) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS locations (
                    id SERIAL PRIMARY KEY,
                    product_id INTEGER REFERENCES products(id),
                    name VARCHAR(255) NOT NULL,
                    content_links TEXT[] NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_id INTEGER REFERENCES products(id),
                    location_id INTEGER REFERENCES locations(id),
                    price_rub DECIMAL(10,2) NOT NULL,
                    price_btc DECIMAL(16,8) NOT NULL,
                    btc_rate DECIMAL(10,2) NOT NULL,
                    bitcoin_address VARCHAR(255) NOT NULL,
                    payment_amount DECIMAL(16,8) NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    content_link TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP + INTERVAL '30 minutes'
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS used_links (
                    id SERIAL PRIMARY KEY,
                    location_id INTEGER REFERENCES locations(id) ON DELETE CASCADE,
                    link TEXT NOT NULL,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Вставка настроек по умолчанию
            await conn.execute('''
                INSERT INTO settings (key, value) VALUES 
                ('about_text', 'Добро пожаловать в наш магазин! Мы продаем цифровые товары за Bitcoin.'),
                ('welcome_message', 'Здравствуйте! Добро пожаловать в наш магазин.')
                ON CONFLICT (key) DO NOTHING
            ''')
    
    async def get_categories(self, active_only: bool = True) -> List[Dict]:
        """Получение списка категорий"""
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM categories"
            if active_only:
                query += " WHERE is_active = TRUE"
            query += " ORDER BY name"
            
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]
    
    async def get_category(self, category_id: int) -> Optional[Dict]:
        """Получение категории по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM categories WHERE id = $1", category_id)
            return dict(row) if row else None
    
    async def get_products(self, category_id: int, active_only: bool = True) -> List[Dict]:
        """Получение товаров категории"""
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM products WHERE category_id = $1"
            if active_only:
                query += " AND is_active = TRUE"
            query += " ORDER BY name"
            
            rows = await conn.fetch(query, category_id)
            return [dict(row) for row in rows]
    
    async def get_product(self, product_id: int) -> Optional[Dict]:
        """Получение товара по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
            return dict(row) if row else None
    
    async def get_locations(self, product_id: int, active_only: bool = True) -> List[Dict]:
        """Получение локаций товара"""
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM locations WHERE product_id = $1"
            if active_only:
                query += " AND is_active = TRUE"
            query += " ORDER BY name"
            
            rows = await conn.fetch(query, product_id)
            return [dict(row) for row in rows]
    
    async def get_location(self, location_id: int) -> Optional[Dict]:
        """Получение локации по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM locations WHERE id = $1", location_id)
            return dict(row) if row else None
    
    async def create_order(self, user_id: int, product_id: int, location_id: int, 
                          price_rub: decimal.Decimal, price_btc: decimal.Decimal, 
                          btc_rate: decimal.Decimal, payment_amount: decimal.Decimal) -> int:
        """Создание заказа"""
        async with self.pool.acquire() as conn:
            order_id = await conn.fetchval('''
                INSERT INTO orders (user_id, product_id, location_id, price_rub, 
                                  price_btc, btc_rate, bitcoin_address, payment_amount)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
            ''', user_id, product_id, location_id, price_rub, price_btc, 
                btc_rate, BITCOIN_ADDRESS, payment_amount)
            return order_id
    
    async def get_order(self, order_id: int) -> Optional[Dict]:
        """Получение заказа"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
            return dict(row) if row else None
    
    async def complete_order(self, order_id: int, content_link: str):
        """Завершение заказа"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE orders SET status = 'completed', content_link = $2 
                WHERE id = $1
            ''', order_id, content_link)
    
    async def get_available_link(self, location_id: int) -> Optional[str]:
        """Получение доступной ссылки из локации"""
        async with self.pool.acquire() as conn:
            # Получаем все ссылки локации
            location = await conn.fetchrow(
                "SELECT content_links FROM locations WHERE id = $1", location_id
            )
            if not location:
                return None
            
            # Получаем использованные ссылки
            used_links = await conn.fetch(
                "SELECT link FROM used_links WHERE location_id = $1", location_id
            )
            used_set = {row['link'] for row in used_links}
            
            # Находим первую неиспользованную ссылку
            for link in location['content_links']:
                if link not in used_set:
                    # Помечаем как использованную
                    await conn.execute(
                        "INSERT INTO used_links (location_id, link) VALUES ($1, $2)",
                        location_id, link
                    )
                    return link
            
            return None
    
    async def add_category(self, name: str, description: str = "") -> int:
        """Добавление категории"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO categories (name, description) VALUES ($1, $2) RETURNING id",
                name, description
            )
    
    async def update_category(self, category_id: int, name: str, description: str):
        """Обновление категории"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE categories SET name = $2, description = $3 WHERE id = $1",
                category_id, name, description
            )
    
    async def delete_category(self, category_id: int) -> bool:
        """Удаление категории с проверкой связанных заказов"""
        async with self.pool.acquire() as conn:
            # Проверяем есть ли заказы на товары из этой категории
            orders_count = await conn.fetchval('''
                SELECT COUNT(*) FROM orders o
                JOIN products p ON o.product_id = p.id
                WHERE p.category_id = $1
            ''', category_id)
            
            if orders_count > 0:
                # Если есть заказы, делаем мягкое удаление
                await conn.execute(
                    "UPDATE categories SET is_active = FALSE WHERE id = $1",
                    category_id
                )
                # Также деактивируем все товары в категории
                await conn.execute('''
                    UPDATE products SET is_active = FALSE 
                    WHERE category_id = $1
                ''', category_id)
                return False  # Мягкое удаление
            else:
                # Если нет заказов, делаем физическое удаление
                await conn.execute("DELETE FROM categories WHERE id = $1", category_id)
                return True  # Физическое удаление
    
    async def add_product(self, category_id: int, name: str, description: str, price_rub: decimal.Decimal) -> int:
        """Добавление товара"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO products (category_id, name, description, price_rub) VALUES ($1, $2, $3, $4) RETURNING id",
                category_id, name, description, price_rub
            )
    
    async def update_product(self, product_id: int, name: str, description: str, price_rub: decimal.Decimal):
        """Обновление товара"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE products SET name = $2, description = $3, price_rub = $4 WHERE id = $1",
                product_id, name, description, price_rub
            )
    
    async def delete_product(self, product_id: int) -> bool:
        """Удаление товара с проверкой связанных заказов"""
        async with self.pool.acquire() as conn:
            # Проверяем есть ли заказы на этот товар
            orders_count = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE product_id = $1",
                product_id
            )
            
            if orders_count > 0:
                # Если есть заказы, делаем мягкое удаление
                await conn.execute(
                    "UPDATE products SET is_active = FALSE WHERE id = $1",
                    product_id
                )
                # Также деактивируем все локации товара
                await conn.execute(
                    "UPDATE locations SET is_active = FALSE WHERE product_id = $1",
                    product_id
                )
                return False  # Мягкое удаление
            else:
                # Если нет заказов, делаем физическое удаление
                await conn.execute("DELETE FROM products WHERE id = $1", product_id)
                return True  # Физическое удаление
    
    async def add_location(self, product_id: int, name: str, content_links: List[str]) -> int:
        """Добавление локации"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO locations (product_id, name, content_links) VALUES ($1, $2, $3) RETURNING id",
                product_id, name, content_links
            )
    
    async def update_location(self, location_id: int, name: str, content_links: List[str]):
        """Обновление локации"""
        async with self.pool.acquire() as conn:
            # Сначала очищаем старые использованные ссылки для этой локации
            await conn.execute("DELETE FROM used_links WHERE location_id = $1", location_id)
            # Затем обновляем локацию
            await conn.execute(
                "UPDATE locations SET name = $2, content_links = $3 WHERE id = $1",
                location_id, name, content_links
            )
    
    async def delete_location(self, location_id: int) -> bool:
        """Удаление локации с проверкой связанных заказов"""
        async with self.pool.acquire() as conn:
            # Проверяем есть ли заказы на эту локацию
            orders_count = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE location_id = $1",
                location_id
            )
            
            if orders_count > 0:
                # Если есть заказы, делаем мягкое удаление
                await conn.execute(
                    "UPDATE locations SET is_active = FALSE WHERE id = $1",
                    location_id
                )
                return False  # Мягкое удаление
            else:
                # Если нет заказов, делаем физическое удаление (CASCADE удалит used_links)
                await conn.execute("DELETE FROM locations WHERE id = $1", location_id)
                return True  # Физическое удаление
    
    async def get_setting(self, key: str) -> str:
        """Получение настройки"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM settings WHERE key = $1", key)
            return row['value'] if row else ""
    
    async def set_setting(self, key: str, value: str):
        """Установка настройки"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = CURRENT_TIMESTAMP
            ''', key, value)
    
    async def get_stats(self) -> Dict:
        """Получение статистики"""
        async with self.pool.acquire() as conn:
            stats = {}
            
            # Общая статистика
            stats['total_orders'] = await conn.fetchval("SELECT COUNT(*) FROM orders")
            stats['completed_orders'] = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
            stats['pending_orders'] = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
            stats['total_revenue'] = await conn.fetchval("SELECT COALESCE(SUM(price_rub), 0) FROM orders WHERE status = 'completed'")
            
            # Статистика за сегодня
            today = datetime.now().date()
            stats['today_orders'] = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE DATE(created_at) = $1", today
            )
            stats['today_revenue'] = await conn.fetchval(
                "SELECT COALESCE(SUM(price_rub), 0) FROM orders WHERE DATE(created_at) = $1 AND status = 'completed'", 
                today
            )
            
            return stats

# Инициализация менеджера БД
db = DatabaseManager(DB_URL)

async def get_btc_rate() -> decimal.Decimal:
    """Получение курса Bitcoin с кэшированием"""
    global btc_rate_cache
    
    now = datetime.now()
    if (btc_rate_cache['timestamp'] and 
        now - btc_rate_cache['timestamp'] < timedelta(minutes=5)):
        return btc_rate_cache['rate']
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            # Пробуем несколько API для получения курса
            apis = [
                'https://api.coindesk.com/v1/bpi/currentprice/RUB.json',
                'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=rub'
            ]
            
            for api_url in apis:
                try:
                    async with session.get(api_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            
                            if 'coindesk.com' in api_url:
                                rate = decimal.Decimal(str(data['bpi']['RUB']['rate_float']))
                            else:  # coingecko
                                rate = decimal.Decimal(str(data['bitcoin']['rub']))
                            
                            btc_rate_cache['rate'] = rate
                            btc_rate_cache['timestamp'] = now
                            logger.info(f"Курс Bitcoin обновлен: {rate} RUB")
                            return rate
                except Exception as e:
                    logger.warning(f"Ошибка получения курса с {api_url}: {e}")
                    continue
                    
        raise Exception("Все API недоступны")
        
    except Exception as e:
        logger.error(f"Ошибка получения курса Bitcoin: {e}")
        # Если курс в кэше есть, используем его
        if btc_rate_cache['rate']:
            logger.info(f"Используем кэшированный курс: {btc_rate_cache['rate']}")
            return btc_rate_cache['rate']
        # Иначе используем fallback
        logger.warning("Используем fallback курс: 5000000 RUB")
        return decimal.Decimal('5000000')

async def check_bitcoin_payment(address: str, amount: decimal.Decimal, order_created_at: datetime) -> bool:
    """Проверка Bitcoin платежа с точным совпадением суммы и проверкой только новых транзакций"""
    try:
        # Тестовый режим для отладки
        if TEST_MODE:
            logger.info("🧪 ТЕСТОВЫЙ РЕЖИМ: платеж считается подтвержденным")
            return True
        
        logger.info(f"🔍 Проверка платежа: адрес={address}, точная сумма={amount} BTC")
        logger.info(f"⏰ Время создания заказа: {order_created_at}")
        
        # Допустимая погрешность ±1 сатоши для учета особенностей сети
        tolerance = decimal.Decimal('0.00000001')  # 1 сатоши
        min_amount = amount - tolerance
        max_amount = amount + tolerance
        
        logger.info(f"💰 Диапазон принимаемых сумм: {min_amount} - {max_amount} BTC (±1 сатоши)")
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            url = f"https://blockchain.info/rawaddr/{address}?limit=50"  # Увеличиваем лимит для проверки
            logger.info(f"📡 Запрос к API: {url}")
            
            async with session.get(url) as resp:
                logger.info(f"📊 Статус ответа API: {resp.status}")
                
                if resp.status != 200:
                    logger.warning(f"❌ Blockchain API вернул статус {resp.status}")
                    return False
                    
                data = await resp.json()
                tx_count = len(data.get('txs', []))
                logger.info(f"📋 Получено транзакций: {tx_count}")
                
                # Конвертируем время создания заказа в Unix timestamp для сравнения
                order_timestamp = int(order_created_at.timestamp())
                logger.info(f"🕐 Timestamp заказа: {order_timestamp}")
                
                # Проверяем транзакции после создания заказа
                relevant_transactions = 0
                for i, tx in enumerate(data.get('txs', [])):
                    tx_hash = tx.get('hash', 'unknown')[:16] + '...'
                    tx_time = tx.get('time', 0)
                    
                    # Проверяем только транзакции после создания заказа
                    if tx_time <= order_timestamp:
                        logger.info(f"⏭️ Пропускаем старую транзакцию {i+1}: {tx_hash} (время: {tx_time}, заказ: {order_timestamp})")
                        continue
                    
                    relevant_transactions += 1
                    logger.info(f"🔄 Проверка новой транзакции {relevant_transactions}: {tx_hash} (время: {tx_time})")
                    
                    for j, output in enumerate(tx.get('out', [])):
                        output_addr = output.get('addr')
                        output_value = output.get('value', 0)
                        
                        if output_addr == address:
                            received_amount = decimal.Decimal(output_value) / 100000000
                            logger.info(f"💳 Найден платеж: {received_amount} BTC (требуется точно: {amount} BTC)")
                            
                            # Проверяем точное совпадение с допустимой погрешностью 1 сатоши
                            if min_amount <= received_amount <= max_amount:
                                logger.info(f"✅ ПЛАТЕЖ ПОДТВЕРЖДЕН! Сумма в допустимом диапазоне: {received_amount} BTC")
                                return True
                            elif received_amount < min_amount:
                                logger.info(f"❌ Сумма меньше требуемой: {received_amount} < {min_amount}")
                            else:
                                logger.info(f"❌ Сумма больше допустимой: {received_amount} > {max_amount}")
                
                logger.info(f"📊 Проверено новых транзакций: {relevant_transactions}")
                logger.info("❌ Платеж с точной суммой не найден среди новых транзакций")
                return False
                
    except Exception as e:
        logger.error(f"💥 Ошибка проверки платежа: {e}")
        return False

def create_main_menu() -> InlineKeyboardMarkup:
    """Создание главного меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🛍 Каталог", callback_data="categories"))
    builder.add(InlineKeyboardButton(text="ℹ️ О магазине", callback_data="about"))
    builder.add(InlineKeyboardButton(text="₿ Курс Bitcoin", callback_data="btc_rate"))
    if ADMIN_IDS:
        builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="stats"))
    builder.adjust(1)
    return builder.as_markup()

def create_categories_menu(categories: List[Dict]) -> InlineKeyboardMarkup:
    """Создание меню категорий"""
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.add(InlineKeyboardButton(
            text=category['name'], 
            callback_data=f"category_{category['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
    builder.adjust(1)
    return builder.as_markup()

def create_products_menu(products: List[Dict], category_id: int) -> InlineKeyboardMarkup:
    """Создание меню товаров"""
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.add(InlineKeyboardButton(
            text=f"{product['name']} - {product['price_rub']} ₽",
            callback_data=f"product_{product['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 К категориям", callback_data="categories"))
    builder.adjust(1)
    return builder.as_markup()

def create_locations_menu(locations: List[Dict], product_id: int) -> InlineKeyboardMarkup:
    """Создание меню локаций"""
    builder = InlineKeyboardBuilder()
    for location in locations:
        builder.add(InlineKeyboardButton(
            text=location['name'],
            callback_data=f"location_{location['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"product_{product_id}"))
    builder.adjust(1)
    return builder.as_markup()

def create_admin_menu() -> InlineKeyboardMarkup:
    """Создание админ меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Добавить категорию", callback_data="admin_add_category"))
    builder.add(InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add_product"))
    builder.add(InlineKeyboardButton(text="➕ Добавить локацию", callback_data="admin_add_location"))
    builder.add(InlineKeyboardButton(text="📝 Управление категориями", callback_data="admin_manage_categories"))
    builder.add(InlineKeyboardButton(text="📦 Управление товарами", callback_data="admin_manage_products"))
    builder.add(InlineKeyboardButton(text="📍 Управление локациями", callback_data="admin_manage_locations"))
    builder.add(InlineKeyboardButton(text="✏️ Редактировать «О магазине»", callback_data="admin_edit_about"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
    builder.adjust(2, 2, 2, 1, 1, 1)
    return builder.as_markup()

def create_manage_categories_menu(categories: List[Dict]) -> InlineKeyboardMarkup:
    """Создание меню управления категориями"""
    builder = InlineKeyboardBuilder()
    for category in categories:
        status_icon = "⚠️" if not category['is_active'] else ""
        builder.add(InlineKeyboardButton(
            text=f"📝 {category['name']}{status_icon}",
            callback_data=f"admin_edit_category_{category['id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🗑",
            callback_data=f"admin_delete_category_{category['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    builder.adjust(2)
    return builder.as_markup()

def create_manage_products_menu(products: List[Dict]) -> InlineKeyboardMarkup:
    """Создание меню управления товарами"""
    builder = InlineKeyboardBuilder()
    for product in products:
        status_icon = "⚠️" if not product['is_active'] else ""
        builder.add(InlineKeyboardButton(
            text=f"📝 {product['name']} - {product['price_rub']}₽{status_icon}",
            callback_data=f"admin_edit_product_{product['id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🗑",
            callback_data=f"admin_delete_product_{product['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    builder.adjust(2)
    return builder.as_markup()

def create_manage_locations_menu(locations: List[Dict]) -> InlineKeyboardMarkup:
    """Создание меню управления локациями"""
    builder = InlineKeyboardBuilder()
    for location in locations:
        available_links = len(location['content_links'])
        status_icon = "⚠️" if not location['is_active'] else ""
        builder.add(InlineKeyboardButton(
            text=f"📝 {location['name']} ({available_links} ссылок){status_icon}",
            callback_data=f"admin_edit_location_{location['id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🗑",
            callback_data=f"admin_delete_location_{location['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    builder.adjust(2)
    return builder.as_markup()

# Обработчики команд
@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.set_state(UserStates.MAIN_MENU)
    
    try:
        welcome_text = await db.get_setting('welcome_message')
        await message.answer(welcome_text, reply_markup=create_main_menu())
        logger.info(f"Пользователь {message.from_user.id} (@{message.from_user.username}) запустил бота")
    except Exception as e:
        logger.error(f"Ошибка в start_handler: {e}")
        await message.answer("Добро пожаловать в наш магазин!", reply_markup=create_main_menu())

@router.message(Command("admin"))
async def admin_handler(message: Message, state: FSMContext):
    """Обработчик команды /admin"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав администратора")
        logger.warning(f"Попытка доступа к админке от {message.from_user.id} (@{message.from_user.username})")
        return
    
    await state.set_state(AdminStates.ADMIN_MENU)
    await message.answer("🔧 Панель администратора", reply_markup=create_admin_menu())
    logger.info(f"Админ {message.from_user.id} вошел в панель управления")

# Обработчики callback'ов
@router.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик главного меню"""
    await state.set_state(UserStates.MAIN_MENU)
    try:
        await callback.message.edit_text("🏠 Главное меню", reply_markup=create_main_menu())
        await callback.answer()
    except TelegramBadRequest:
        await callback.message.answer("🏠 Главное меню", reply_markup=create_main_menu())

@router.callback_query(F.data == "categories")
async def categories_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик каталога"""
    await state.set_state(UserStates.BROWSING_CATEGORIES)
    
    try:
        categories = await db.get_categories()
        
        if not categories:
            await callback.message.edit_text("📦 Каталог пуст", reply_markup=create_main_menu())
            await callback.answer()
            return
        
        await callback.message.edit_text(
            "🛍 Выберите категорию:",
            reply_markup=create_categories_menu(categories)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в categories_handler: {e}")
        await callback.answer("❌ Ошибка загрузки каталога")

@router.callback_query(F.data.startswith("category_"))
async def category_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора категории"""
    try:
        category_id = int(callback.data.split("_")[1])
        products = await db.get_products(category_id)
        
        if not products:
            categories = await db.get_categories()
            await callback.message.edit_text("📦 В этой категории пока нет товаров", 
                                           reply_markup=create_categories_menu(categories))
            await callback.answer()
            return
        
        await state.set_state(UserStates.BROWSING_PRODUCTS)
        await callback.message.edit_text(
            "📦 Выберите товар:",
            reply_markup=create_products_menu(products, category_id)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в category_handler: {e}")
        await callback.answer("❌ Ошибка загрузки категории")

@router.callback_query(F.data.startswith("product_"))
async def product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора товара"""
    try:
        product_id = int(callback.data.split("_")[1])
        product = await db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден")
            return
        
        locations = await db.get_locations(product_id)
        
        if not locations:
            await callback.message.edit_text("📍 Для этого товара пока нет доступных локаций")
            await callback.answer()
            return
        
        await state.set_state(UserStates.SELECTING_LOCATION)
        await state.update_data(product_id=product_id)
        
        # Получаем курс Bitcoin
        btc_rate = await get_btc_rate()
        price_btc = product['price_rub'] / btc_rate
        
        text = f"📦 *{product['name']}*\n\n"
        text += f"📝 {product['description']}\n\n"
        text += f"💰 Цена: {product['price_rub']} ₽ (~{price_btc:.8f} BTC)\n\n"
        text += f"📍 Выберите локацию:"
        
        await callback.message.edit_text(
            text,
            reply_markup=create_locations_menu(locations, product_id),
            parse_mode='Markdown'
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в product_handler: {e}")
        await callback.answer("❌ Ошибка загрузки товара")

@router.callback_query(F.data.startswith("location_"))
async def location_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора локации"""
    try:
        location_id = int(callback.data.split("_")[1])
        data = await state.get_data()
        product_id = data.get('product_id')
        
        product = await db.get_product(product_id)
        btc_rate = await get_btc_rate()
        
        # Добавляем случайное количество сатоши для уникальности
        extra_satoshi = random.randint(1, 300)
        price_btc = product['price_rub'] / btc_rate
        payment_amount = price_btc + decimal.Decimal(extra_satoshi) / 100000000
        
        # Создаем заказ
        order_id = await db.create_order(
            user_id=callback.from_user.id,
            product_id=product_id,
            location_id=location_id,
            price_rub=product['price_rub'],
            price_btc=price_btc,
            btc_rate=btc_rate,
            payment_amount=payment_amount
        )
        
        await state.set_state(UserStates.PAYMENT_WAITING)
        await state.update_data(order_id=order_id)
        
        text = f"💳 *Оплата заказа #{order_id}*\n\n"
        text += f"📦 Товар: {product['name']}\n"
        text += f"💰 К оплате: `{payment_amount:.8f}` BTC\n\n"
        text += f"📍 Bitcoin адрес:\n`{BITCOIN_ADDRESS}`\n\n"
        text += f"⚠️ *КРИТИЧЕСКИ ВАЖНО:*\n"
        text += f"🎯 Отправьте ТОЧНО указанную сумму: `{payment_amount:.8f}` BTC\n"
        text += f"🚫 НЕ округляйте и НЕ изменяйте сумму\n"
        text += f"📱 Скопируйте сумму полностью из сообщения\n"
        text += f"⚡ Допустимая погрешность: только ±1 сатоши\n"
        text += f"⏰ Платеж должен быть отправлен ПОСЛЕ создания заказа\n\n"
        text += f"❌ При отправке другой суммы заказ НЕ будет выполнен!\n\n"
        text += f"⏰ Заказ автоматически отменится через 30 минут\n\n"
        text += f"💡 Для копирования нажмите на сумму выше ☝️"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔍 Проверить оплату", callback_data=f"check_payment_{order_id}"))
        builder.add(InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_order_{order_id}"))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await callback.answer()
        
        # Уведомляем админов о новом заказе
        for admin_id in ADMIN_IDS:
            try:
                username = callback.from_user.username or "без username"
                admin_builder = InlineKeyboardBuilder()
                admin_builder.add(InlineKeyboardButton(
                    text="✅ Выдать товар вручную", 
                    callback_data=f"admin_confirm_payment_{order_id}"
                ))
                
                await bot.send_message(
                    admin_id, 
                    f"🆕 *Новый заказ #{order_id}*\n\n"
                    f"👤 Покупатель: @{username}\n"
                    f"📦 Товар: {product['name']}\n"
                    f"💰 Сумма: `{payment_amount:.8f}` BTC\n"
                    f"📍 Адрес: `{BITCOIN_ADDRESS}`\n\n"
                    f"Используйте кнопку ниже для ручной выдачи товара",
                    reply_markup=admin_builder.as_markup(),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
                
        logger.info(f"Создан заказ #{order_id} пользователем {callback.from_user.id}")
                
    except Exception as e:
        logger.error(f"Ошибка в location_handler: {e}")
        await callback.answer("❌ Ошибка создания заказа")

@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик проверки оплаты"""
    try:
        order_id = int(callback.data.split("_")[2])
        order = await db.get_order(order_id)
        
        if not order:
            await callback.answer("❌ Заказ не найден")
            return
        
        if order['status'] == 'completed':
            await callback.answer("✅ Заказ уже выполнен")
            return
        
        # Проверяем, не истек ли заказ
        if datetime.now() > order['expires_at']:
            await callback.answer("⏰ Время оплаты заказа истекло")
            return
        
        await callback.answer("🔍 Проверяем оплату...")
        
        # Проверяем платеж с учетом времени создания заказа
        payment_received = await check_bitcoin_payment(
            order['bitcoin_address'], 
            order['payment_amount'], 
            order['created_at']
        )
        
        if payment_received:
            # Получаем доступную ссылку
            content_link = await db.get_available_link(order['location_id'])
            
            if content_link:
                await db.complete_order(order_id, content_link)
                
                text = f"✅ *Оплата подтверждена!*\n\n"
                text += f"📦 Заказ #{order_id} выполнен\n\n"
                text += f"🔗 Ваш контент:\n{content_link}\n\n"
                text += f"Спасибо за покупку! 🎉"
                
                await callback.message.edit_text(text, parse_mode='Markdown')
                await state.set_state(UserStates.MAIN_MENU)
                
                # Уведомляем админов о выполненном заказе
                for admin_id in ADMIN_IDS:
                    try:
                        username = callback.from_user.username or "без username"
                        await bot.send_message(admin_id, f"✅ Заказ #{order_id} от @{username} выполнен автоматически")
                    except Exception as e:
                        logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
                
                logger.info(f"Заказ #{order_id} выполнен автоматически")
            else:
                await callback.message.edit_text("❌ К сожалению, контент в выбранной локации закончился")
                logger.warning(f"Нет доступных ссылок для заказа #{order_id}")
        else:
            await callback.answer("❌ Точная оплата не найдена среди новых транзакций. Убедитесь, что отправили платеж ПОСЛЕ создания заказа точной суммой (±1 сатоши)")
            
    except Exception as e:
        logger.error(f"Ошибка в check_payment_handler: {e}")
        await callback.answer("❌ Ошибка проверки оплаты")

@router.callback_query(F.data.startswith("admin_confirm_payment_"))
async def admin_confirm_payment(callback: CallbackQuery, state: FSMContext):
    """Ручная выдача товара админом"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        order_id = int(callback.data.split("_")[3])
        order = await db.get_order(order_id)
        
        if not order:
            await callback.answer("❌ Заказ не найден")
            return
        
        if order['status'] == 'completed':
            await callback.answer("✅ Заказ уже выполнен")
            return
        
        # Получаем доступную ссылку
        content_link = await db.get_available_link(order['location_id'])
        
        if content_link:
            await db.complete_order(order_id, content_link)
            
            # Уведомляем покупателя
            try:
                await bot.send_message(
                    order['user_id'],
                    f"✅ *Ваш заказ #{order_id} выполнен администратором!*\n\n"
                    f"🔗 Ваш контент:\n{content_link}\n\n"
                    f"Спасибо за покупку! 🎉",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления пользователя: {e}")
            
            await callback.message.edit_text(
                f"✅ *Заказ #{order_id} выполнен вручную*\n\n"
                f"🔗 Выданный контент:\n{content_link}\n\n"
                f"Покупатель уведомлен.",
                parse_mode='Markdown'
            )
            await callback.answer()
            
            logger.info(f"Админ {callback.from_user.id} вручную выдал заказ #{order_id}")
        else:
            await callback.answer("❌ Нет доступных ссылок")
            
    except Exception as e:
        logger.error(f"Ошибка в admin_confirm_payment: {e}")
        await callback.answer("❌ Ошибка выдачи заказа")

@router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены заказа"""
    try:
        order_id = int(callback.data.split("_")[2])
        await state.set_state(UserStates.MAIN_MENU)
        await callback.message.edit_text("❌ Заказ отменен", reply_markup=create_main_menu())
        await callback.answer()
        logger.info(f"Заказ #{order_id} отменен пользователем")
    except Exception as e:
        logger.error(f"Ошибка в cancel_order_handler: {e}")

@router.callback_query(F.data == "about")
async def about_handler(callback: CallbackQuery):
    """Обработчик информации о магазине"""
    try:
        about_text = await db.get_setting('about_text')
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
        
        await callback.message.edit_text(about_text, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в about_handler: {e}")
        await callback.answer("❌ Ошибка загрузки информации")

@router.callback_query(F.data == "btc_rate")
async def btc_rate_handler(callback: CallbackQuery):
    """Обработчик отображения курса Bitcoin"""
    try:
        btc_rate = await get_btc_rate()
        
        text = f"₿ *Курс Bitcoin*\n\n"
        text += f"1 BTC = {btc_rate:,.2f} ₽\n\n"
        text += f"_Курс обновляется каждые 5 минут_"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_stats_handler: {e}")
        await callback.answer("❌ Ошибка загрузки статистики")

@router.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик админ меню"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    await state.set_state(AdminStates.ADMIN_MENU)
    await callback.message.edit_text("🔧 Панель администратора", reply_markup=create_admin_menu())
    await callback.answer()

# Автоматическая отмена просроченных заказов
async def cancel_expired_orders():
    """Отмена просроченных заказов"""
    while True:
        try:
            if db.pool:
                async with db.pool.acquire() as conn:
                    expired_orders = await conn.fetch('''
                        SELECT id, user_id FROM orders 
                        WHERE status = 'pending' AND expires_at < NOW()
                    ''')
                    
                    for order in expired_orders:
                        await conn.execute(
                            "UPDATE orders SET status = 'expired' WHERE id = $1",
                            order['id']
                        )
                        
                        # Уведомляем пользователя
                        try:
                            await bot.send_message(
                                order['user_id'],
                                f"⏰ Заказ #{order['id']} отменен из-за истечения времени оплаты"
                            )
                        except Exception as e:
                            logger.error(f"Ошибка уведомления пользователя {order['user_id']}: {e}")
                    
                    if expired_orders:
                        logger.info(f"Отменено {len(expired_orders)} просроченных заказов")
                        
        except Exception as e:
            logger.error(f"Ошибка при отмене просроченных заказов: {e}")
        
        await asyncio.sleep(300)  # Проверяем каждые 5 минут

# Обработчик неизвестных команд
@router.message()
async def unknown_message_handler(message: Message):
    """Обработчик неизвестных сообщений"""
    await message.answer("❓ Неизвестная команда. Используйте /start для начала работы")

# Обработчик ошибок callback'ов
@router.callback_query()
async def unknown_callback_handler(callback: CallbackQuery):
    """Обработчик неизвестных callback'ов"""
    await callback.answer("❓ Неизвестная команда")

async def main():
    """Основная функция"""
    try:
        # Инициализируем базу данных
        logger.info("Инициализация базы данных...")
        await db.init_pool()
        
        # Регистрируем роутер
        dp.include_router(router)
        
        # Запускаем задачу отмены просроченных заказов
        cancel_task = asyncio.create_task(cancel_expired_orders())
        
        logger.info("Бот запущен и готов к работе!")
        logger.info(f"Bitcoin адрес: {BITCOIN_ADDRESS}")
        logger.info(f"Администраторы: {ADMIN_IDS}")
        logger.info("⚡ Погрешность платежей: ±1 сатоши")
        logger.info("🕐 Проверка только новых транзакций после создания заказа")
        logger.info("🔄 Умное удаление: физическое/мягкое в зависимости от связанных заказов")
        if TEST_MODE:
            logger.warning("🧪 ВКЛЮЧЕН ТЕСТОВЫЙ РЕЖИМ - все платежи будут считаться подтвержденными!")
        
        # Запускаем бота
        await dp.start_polling(bot)
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        logger.info("Завершение работы бота...")
        if 'cancel_task' in locals():
            cancel_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass
        
        if db.pool:
            await db.pool.close()
        
        if bot.session:
            await bot.session.close()
        
        logger.info("Бот остановлен")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа прервана пользователем")
    except Exception as e:
        logger.error(f"Фатальная ошибка: {e}") as e:
        logger.error(f"Ошибка в btc_rate_handler: {e}")
        await callback.answer("❌ Ошибка получения курса")

@router.callback_query(F.data == "stats")
async def stats_handler(callback: CallbackQuery):
    """Обработчик отображения статистики"""
    try:
        stats = await db.get_stats()
        
        text = f"📊 *Статистика магазина*\n\n"
        text += f"📈 Всего заказов: {stats['total_orders']}\n"
        text += f"✅ Выполнено: {stats['completed_orders']}\n"
        text += f"⏳ В ожидании: {stats['pending_orders']}\n"
        text += f"💰 Общая выручка: {stats['total_revenue']:.2f} ₽\n\n"
        text += f"📅 Сегодня:\n"
        text += f"├ Заказов: {stats['today_orders']}\n"
        text += f"└ Выручка: {stats['today_revenue']:.2f} ₽"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в stats_handler: {e}")
        await callback.answer("❌ Ошибка загрузки статистики")

# Админские обработчики - добавление
@router.callback_query(F.data == "admin_add_category")
async def admin_add_category_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик добавления категории"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    await state.set_state(AdminStates.ADDING_CATEGORY)
    await callback.message.edit_text("📝 Введите название категории:")
    await callback.answer()

@router.message(StateFilter(AdminStates.ADDING_CATEGORY))
async def process_add_category(message: Message, state: FSMContext):
    """Обработка добавления категории"""
    category_name = message.text.strip()
    
    if not category_name:
        await message.answer("❌ Название не может быть пустым")
        return
    
    try:
        category_id = await db.add_category(category_name)
        await message.answer(f"✅ Категория '{category_name}' добавлена (ID: {category_id})", 
                           reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} добавил категорию '{category_name}'")
    except Exception as e:
        logger.error(f"Ошибка добавления категории: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data == "admin_add_product")
async def admin_add_product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик добавления товара"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        categories = await db.get_categories(active_only=False)
        if not categories:
            await callback.message.edit_text("❌ Сначала создайте категории", reply_markup=create_admin_menu())
            await callback.answer()
            return
        
        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.add(InlineKeyboardButton(
                text=category['name'],
                callback_data=f"admin_select_category_{category['id']}"
            ))
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_menu"))
        builder.adjust(1)
        
        await callback.message.edit_text("📦 Выберите категорию для товара:", reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_add_product_handler: {e}")
        await callback.answer("❌ Ошибка загрузки категорий")

@router.callback_query(F.data.startswith("admin_select_category_"))
async def admin_select_category_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора категории для товара"""
    category_id = int(callback.data.split("_")[3])
    await state.set_state(AdminStates.ADDING_PRODUCT)
    await state.update_data(category_id=category_id)
    
    await callback.message.edit_text("📝 Введите данные товара в формате:\n\n"
                                   "Название\n"
                                   "Описание\n"
                                   "Цена в рублях\n\n"
                                   "Пример:\n"
                                   "Премиум аккаунт\n"
                                   "Доступ на 30 дней\n"
                                   "1500")
    await callback.answer()

@router.message(StateFilter(AdminStates.ADDING_PRODUCT))
async def process_add_product(message: Message, state: FSMContext):
    """Обработка добавления товара"""
    data = await state.get_data()
    category_id = data.get('category_id')
    
    lines = message.text.strip().split('\n')
    if len(lines) < 3:
        await message.answer("❌ Неверный формат. Укажите название, описание и цену")
        return
    
    try:
        name = lines[0].strip()
        description = lines[1].strip()
        price_rub = decimal.Decimal(lines[2].strip())
        
        if price_rub <= 0:
            await message.answer("❌ Цена должна быть больше нуля")
            return
        
        product_id = await db.add_product(category_id, name, description, price_rub)
        await message.answer(f"✅ Товар '{name}' добавлен (ID: {product_id})", 
                           reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} добавил товар '{name}'")
    except (ValueError, decimal.InvalidOperation):
        await message.answer("❌ Неверный формат цены")
    except Exception as e:
        logger.error(f"Ошибка добавления товара: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data == "admin_add_location")
async def admin_add_location_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик добавления локации"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        # Получаем все товары
        categories = await db.get_categories(active_only=False)
        all_products = []
        
        for category in categories:
            products = await db.get_products(category['id'], active_only=False)
            for product in products:
                product['category_name'] = category['name']
                all_products.append(product)
        
        if not all_products:
            await callback.message.edit_text("❌ Сначала создайте товары", reply_markup=create_admin_menu())
            await callback.answer()
            return
        
        builder = InlineKeyboardBuilder()
        for product in all_products:
            builder.add(InlineKeyboardButton(
                text=f"{product['category_name']} - {product['name']}",
                callback_data=f"admin_select_product_{product['id']}"
            ))
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_menu"))
        builder.adjust(1)
        
        await callback.message.edit_text("📦 Выберите товар для локации:", reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_add_location_handler: {e}")
        await callback.answer("❌ Ошибка загрузки товаров")

@router.callback_query(F.data.startswith("admin_select_product_"))
async def admin_select_product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора товара для локации"""
    product_id = int(callback.data.split("_")[3])
    await state.set_state(AdminStates.ADDING_LOCATION)
    await state.update_data(product_id=product_id)
    
    await callback.message.edit_text("📝 Введите данные локации в формате:\n\n"
                                   "Название локации\n"
                                   "Ссылка1\n"
                                   "Ссылка2\n"
                                   "Ссылка3\n"
                                   "...\n\n"
                                   "Пример:\n"
                                   "Москва\n"
                                   "https://example.com/link1\n"
                                   "https://example.com/link2\n"
                                   "https://example.com/link3")
    await callback.answer()

@router.message(StateFilter(AdminStates.ADDING_LOCATION))
async def process_add_location(message: Message, state: FSMContext):
    """Обработка добавления локации"""
    data = await state.get_data()
    product_id = data.get('product_id')
    
    lines = message.text.strip().split('\n')
    if len(lines) < 2:
        await message.answer("❌ Неверный формат. Укажите название и хотя бы одну ссылку")
        return
    
    try:
        name = lines[0].strip()
        content_links = [line.strip() for line in lines[1:] if line.strip()]
        
        if not content_links:
            await message.answer("❌ Укажите хотя бы одну ссылку")
            return
        
        if not name:
            await message.answer("❌ Название локации не может быть пустым")
            return
        
        location_id = await db.add_location(product_id, name, content_links)
        await message.answer(f"✅ Локация '{name}' добавлена с {len(content_links)} ссылками (ID: {location_id})", 
                           reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} добавил локацию '{name}' с {len(content_links)} ссылками")
    except Exception as e:
        logger.error(f"Ошибка добавления локации: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# Админские обработчики - управление
@router.callback_query(F.data == "admin_manage_categories")
async def admin_manage_categories_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик управления категориями"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        categories = await db.get_categories(active_only=False)
        if not categories:
            await callback.message.edit_text("❌ Категории не найдены", reply_markup=create_admin_menu())
            await callback.answer()
            return
        
        await state.set_state(AdminStates.MANAGE_CATEGORIES)
        await callback.message.edit_text(
            "📝 Управление категориями\n\n"
            "📝 - редактировать, 🗑 - удалить\n"
            "⚠️ - неактивные (есть связанные заказы)",
            reply_markup=create_manage_categories_menu(categories)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_manage_categories_handler: {e}")
        await callback.answer("❌ Ошибка загрузки категорий")

@router.callback_query(F.data == "admin_manage_products")
async def admin_manage_products_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик управления товарами"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        categories = await db.get_categories(active_only=False)
        all_products = []
        
        for category in categories:
            products = await db.get_products(category['id'], active_only=False)
            for product in products:
                product['category_name'] = category['name']
                all_products.append(product)
        
        if not all_products:
            await callback.message.edit_text("❌ Товары не найдены", reply_markup=create_admin_menu())
            await callback.answer()
            return
        
        await state.set_state(AdminStates.MANAGE_PRODUCTS)
        await callback.message.edit_text(
            "📦 Управление товарами\n\n"
            "📝 - редактировать, 🗑 - удалить\n"
            "⚠️ - неактивные (есть связанные заказы)",
            reply_markup=create_manage_products_menu(all_products)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_manage_products_handler: {e}")
        await callback.answer("❌ Ошибка загрузки товаров")

@router.callback_query(F.data == "admin_manage_locations")
async def admin_manage_locations_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик управления локациями"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        categories = await db.get_categories(active_only=False)
        all_locations = []
        
        for category in categories:
            products = await db.get_products(category['id'], active_only=False)
            for product in products:
                locations = await db.get_locations(product['id'], active_only=False)
                for location in locations:
                    location['product_name'] = product['name']
                    location['category_name'] = category['name']
                    all_locations.append(location)
        
        if not all_locations:
            await callback.message.edit_text("❌ Локации не найдены", reply_markup=create_admin_menu())
            await callback.answer()
            return
        
        await state.set_state(AdminStates.MANAGE_LOCATIONS)
        await callback.message.edit_text(
            "📍 Управление локациями\n\n"
            "📝 - редактировать, 🗑 - удалить\n"
            "⚠️ - неактивные (есть связанные заказы)",
            reply_markup=create_manage_locations_menu(all_locations)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_manage_locations_handler: {e}")
        await callback.answer("❌ Ошибка загрузки локаций")

# Редактирование категорий
@router.callback_query(F.data.startswith("admin_edit_category_"))
async def admin_edit_category_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования категории"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        category_id = int(callback.data.split("_")[3])
        category = await db.get_category(category_id)
        
        if not category:
            await callback.answer("❌ Категория не найдена")
            return
        
        await state.set_state(AdminStates.EDITING_CATEGORY)
        await state.update_data(category_id=category_id)
        
        status_text = " (НЕАКТИВНА)" if not category['is_active'] else ""
        await callback.message.edit_text(
            f"📝 Редактирование категории{status_text}\n\n"
            f"Текущее название: {category['name']}\n"
            f"Текущее описание: {category['description']}\n\n"
            f"Введите новые данные в формате:\n"
            f"Название\n"
            f"Описание"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_edit_category_handler: {e}")
        await callback.answer("❌ Ошибка загрузки категории")

@router.message(StateFilter(AdminStates.EDITING_CATEGORY))
async def process_edit_category(message: Message, state: FSMContext):
    """Обработка редактирования категории"""
    data = await state.get_data()
    category_id = data.get('category_id')
    
    lines = message.text.strip().split('\n')
    if len(lines) < 1:
        await message.answer("❌ Укажите хотя бы название")
        return
    
    try:
        name = lines[0].strip()
        description = lines[1].strip() if len(lines) > 1 else ""
        
        if not name:
            await message.answer("❌ Название не может быть пустым")
            return
        
        await db.update_category(category_id, name, description)
        await message.answer(f"✅ Категория обновлена", reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} обновил категорию {category_id}")
    except Exception as e:
        logger.error(f"Ошибка обновления категории: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data.startswith("admin_delete_category_"))
async def admin_delete_category_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик удаления категории"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        category_id = int(callback.data.split("_")[3])
        category = await db.get_category(category_id)
        
        if not category:
            await callback.answer("❌ Категория не найдена")
            return
        
        # Пробуем удалить категорию
        is_physical_delete = await db.delete_category(category_id)
        
        if is_physical_delete:
            await callback.answer(f"✅ Категория '{category['name']}' полностью удалена")
            logger.info(f"Админ {callback.from_user.id} физически удалил категорию {category_id}")
        else:
            await callback.answer(f"⚠️ Категория '{category['name']}' деактивирована (есть связанные заказы)")
            logger.info(f"Админ {callback.from_user.id} деактивировал категорию {category_id}")
        
        # Обновляем список
        categories = await db.get_categories(active_only=False)
        if categories:
            await callback.message.edit_text(
                "📝 Управление категориями\n\n"
                "📝 - редактировать, 🗑 - удалить\n"
                "⚠️ - неактивные (есть связанные заказы)",
                reply_markup=create_manage_categories_menu(categories)
            )
        else:
            await callback.message.edit_text("❌ Категории не найдены", reply_markup=create_admin_menu())
        
    except Exception as e:
        logger.error(f"Ошибка удаления категории: {e}")
        await callback.answer("❌ Ошибка удаления категории")

# Редактирование товаров
@router.callback_query(F.data.startswith("admin_edit_product_"))
async def admin_edit_product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования товара"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        product_id = int(callback.data.split("_")[3])
        product = await db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден")
            return
        
        await state.set_state(AdminStates.EDITING_PRODUCT)
        await state.update_data(product_id=product_id)
        
        status_text = " (НЕАКТИВЕН)" if not product['is_active'] else ""
        await callback.message.edit_text(
            f"📦 Редактирование товара{status_text}\n\n"
            f"Текущее название: {product['name']}\n"
            f"Текущее описание: {product['description']}\n"
            f"Текущая цена: {product['price_rub']} ₽\n\n"
            f"Введите новые данные в формате:\n"
            f"Название\n"
            f"Описание\n"
            f"Цена в рублях"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_edit_product_handler: {e}")
        await callback.answer("❌ Ошибка загрузки товара")

@router.message(StateFilter(AdminStates.EDITING_PRODUCT))
async def process_edit_product(message: Message, state: FSMContext):
    """Обработка редактирования товара"""
    data = await state.get_data()
    product_id = data.get('product_id')
    
    lines = message.text.strip().split('\n')
    if len(lines) < 3:
        await message.answer("❌ Укажите название, описание и цену")
        return
    
    try:
        name = lines[0].strip()
        description = lines[1].strip()
        price_rub = decimal.Decimal(lines[2].strip())
        
        if not name:
            await message.answer("❌ Название не может быть пустым")
            return
        
        if price_rub <= 0:
            await message.answer("❌ Цена должна быть больше нуля")
            return
        
        await db.update_product(product_id, name, description, price_rub)
        await message.answer(f"✅ Товар обновлен", reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} обновил товар {product_id}")
    except (ValueError, decimal.InvalidOperation):
        await message.answer("❌ Неверный формат цены")
    except Exception as e:
        logger.error(f"Ошибка обновления товара: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data.startswith("admin_delete_product_"))
async def admin_delete_product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик удаления товара"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        product_id = int(callback.data.split("_")[3])
        product = await db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден")
            return
        
        # Пробуем удалить товар
        is_physical_delete = await db.delete_product(product_id)
        
        if is_physical_delete:
            await callback.answer(f"✅ Товар '{product['name']}' полностью удален")
            logger.info(f"Админ {callback.from_user.id} физически удалил товар {product_id}")
        else:
            await callback.answer(f"⚠️ Товар '{product['name']}' деактивирован (есть связанные заказы)")
            logger.info(f"Админ {callback.from_user.id} деактивировал товар {product_id}")
        
        # Обновляем список
        categories = await db.get_categories(active_only=False)
        all_products = []
        
        for category in categories:
            products = await db.get_products(category['id'], active_only=False)
            for prod in products:
                prod['category_name'] = category['name']
                all_products.append(prod)
        
        if all_products:
            await callback.message.edit_text(
                "📦 Управление товарами\n\n"
                "📝 - редактировать, 🗑 - удалить\n"
                "⚠️ - неактивные (есть связанные заказы)",
                reply_markup=create_manage_products_menu(all_products)
            )
        else:
            await callback.message.edit_text("❌ Товары не найдены", reply_markup=create_admin_menu())
        
    except Exception as e:
        logger.error(f"Ошибка удаления товара: {e}")
        await callback.answer("❌ Ошибка удаления товара")

# Редактирование локаций
@router.callback_query(F.data.startswith("admin_edit_location_"))
async def admin_edit_location_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования локации"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        location_id = int(callback.data.split("_")[3])
        location = await db.get_location(location_id)
        
        if not location:
            await callback.answer("❌ Локация не найдена")
            return
        
        await state.set_state(AdminStates.EDITING_LOCATION)
        await state.update_data(location_id=location_id)
        
        links_text = '\n'.join(location['content_links'])
        status_text = " (НЕАКТИВНА)" if not location['is_active'] else ""
        
        await callback.message.edit_text(
            f"📍 Редактирование локации{status_text}\n\n"
            f"Текущее название: {location['name']}\n"
            f"Количество ссылок: {len(location['content_links'])}\n\n"
            f"Текущие ссылки:\n{links_text}\n\n"
            f"Введите новые данные в формате:\n"
            f"Название локации\n"
            f"Ссылка1\n"
            f"Ссылка2\n"
            f"..."
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_edit_location_handler: {e}")
        await callback.answer("❌ Ошибка загрузки локации")

@router.message(StateFilter(AdminStates.EDITING_LOCATION))
async def process_edit_location(message: Message, state: FSMContext):
    """Обработка редактирования локации"""
    data = await state.get_data()
    location_id = data.get('location_id')
    
    lines = message.text.strip().split('\n')
    if len(lines) < 2:
        await message.answer("❌ Укажите название и хотя бы одну ссылку")
        return
    
    try:
        name = lines[0].strip()
        content_links = [line.strip() for line in lines[1:] if line.strip()]
        
        if not name:
            await message.answer("❌ Название не может быть пустым")
            return
        
        if not content_links:
            await message.answer("❌ Укажите хотя бы одну ссылку")
            return
        
        await db.update_location(location_id, name, content_links)
        await message.answer(f"✅ Локация обновлена", reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} обновил локацию {location_id}")
    except Exception as e:
        logger.error(f"Ошибка обновления локации: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data.startswith("admin_delete_location_"))
async def admin_delete_location_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик удаления локации"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        location_id = int(callback.data.split("_")[3])
        location = await db.get_location(location_id)
        
        if not location:
            await callback.answer("❌ Локация не найдена")
            return
        
        # Пробуем удалить локацию
        is_physical_delete = await db.delete_location(location_id)
        
        if is_physical_delete:
            await callback.answer(f"✅ Локация '{location['name']}' полностью удалена")
            logger.info(f"Админ {callback.from_user.id} физически удалил локацию {location_id}")
        else:
            await callback.answer(f"⚠️ Локация '{location['name']}' деактивирована (есть связанные заказы)")
            logger.info(f"Админ {callback.from_user.id} деактивировал локацию {location_id}")
        
        # Обновляем список
        categories = await db.get_categories(active_only=False)
        all_locations = []
        
        for category in categories:
            products = await db.get_products(category['id'], active_only=False)
            for product in products:
                locations = await db.get_locations(product['id'], active_only=False)
                for loc in locations:
                    loc['product_name'] = product['name']
                    loc['category_name'] = category['name']
                    all_locations.append(loc)
        
        if all_locations:
            await callback.message.edit_text(
                "📍 Управление локациями\n\n"
                "📝 - редактировать, 🗑 - удалить\n"
                "⚠️ - неактивные (есть связанные заказы)",
                reply_markup=create_manage_locations_menu(all_locations)
            )
        else:
            await callback.message.edit_text("❌ Локации не найдены", reply_markup=create_admin_menu())
        
    except Exception as e:
        logger.error(f"Ошибка удаления локации: {e}")
        await callback.answer("❌ Ошибка удаления локации")

@router.callback_query(F.data == "admin_edit_about")
async def admin_edit_about_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования текста 'О магазине'"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    await state.set_state(AdminStates.EDITING_ABOUT)
    try:
        current_text = await db.get_setting('about_text')
        
        await callback.message.edit_text(f"📝 Текущий текст 'О магазине':\n\n{current_text}\n\n"
                                       "Введите новый текст:")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_edit_about_handler: {e}")
        await callback.answer("❌ Ошибка загрузки настроек")

@router.message(StateFilter(AdminStates.EDITING_ABOUT))
async def process_edit_about(message: Message, state: FSMContext):
    """Обработка редактирования текста 'О магазине'"""
    new_text = message.text.strip()
    
    if not new_text:
        await message.answer("❌ Текст не может быть пустым")
        return
    
    try:
        await db.set_setting('about_text', new_text)
        await message.answer("✅ Текст 'О магазине' обновлен", reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} обновил текст 'О магазине'")
    except Exception as e:
        logger.error(f"Ошибка обновления настроек: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    """Обработчик админской статистики"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        stats = await db.get_stats()
        
        text = f"📊 *Подробная статистика*\n\n"
        text += f"📈 Всего заказов: {stats['total_orders']}\n"
        text += f"✅ Выполнено: {stats['completed_orders']}\n"
        text += f"⏳ В ожидании: {stats['pending_orders']}\n"
        text += f"💰 Общая выручка: {stats['total_revenue']:.2f} ₽\n\n"
        text += f"📅 Статистика за сегодня:\n"
        text += f"├ Заказов: {stats['today_orders']}\n"
        text += f"└ Выручка: {stats['today_revenue']:.2f} ₽\n\n"
        
        if stats['total_orders'] > 0:
            conversion_rate = (stats['completed_orders'] / stats['total_orders']) * 100
            text += f"📊 Конверсия: {conversion_rate:.1f}%"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await callback.answer()
    except Exception
