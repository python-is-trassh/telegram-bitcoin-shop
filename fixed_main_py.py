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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
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
            # Создаем таблицы с правильными типами данных
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
                    category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
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
                    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
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
                    location_id INTEGER REFERENCES locations(id),
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
    
    async def add_product(self, category_id: int, name: str, description: str, price_rub: decimal.Decimal) -> int:
        """Добавление товара"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO products (category_id, name, description, price_rub) VALUES ($1, $2, $3, $4) RETURNING id",
                category_id, name, description, price_rub
            )
    
    async def add_location(self, product_id: int, name: str, content_links: List[str]) -> int:
        """Добавление локации"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO locations (product_id, name, content_links) VALUES ($1, $2, $3) RETURNING id",
                product_id, name, content_links
            )
    
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

async def check_bitcoin_payment(address: str, amount: decimal.Decimal) -> bool:
    """Проверка Bitcoin платежа через blockchain.info"""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            url = f"https://blockchain.info/rawaddr/{address}?limit=10"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Blockchain API вернул статус {resp.status}")
                    return False
                    
                data = await resp.json()
                
                # Проверяем последние транзакции
                for tx in data.get('txs', [])[:10]:
                    for output in tx.get('out', []):
                        if output.get('addr') == address:
                            received_amount = decimal.Decimal(output.get('value', 0)) / 100000000
                            logger.info(f"Найдена транзакция: {received_amount} BTC (требуется: {amount})")
                            if received_amount >= amount:
                                return True
                                
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки платежа: {e}")
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
    builder.add(InlineKeyboardButton(text="✏️ Редактировать «О магазине»", callback_data="admin_edit_about"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
    builder.adjust(1)
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
        text += f"💰 К оплате: {payment_amount:.8f} BTC\n\n"
        text += f"📍 Bitcoin адрес:\n`{BITCOIN_ADDRESS}`\n\n"
        text += f"⏰ Заказ будет отменен через 30 минут, если оплата не поступит\n\n"
        text += f"💡 Отправьте точную сумму на указанный адрес"
        
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
                await bot.send_message(admin_id, f"🆕 Новый заказ #{order_id} от @{username}\nТовар: {product['name']}\nСумма: {payment_amount:.8f} BTC")
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
        
        # Проверяем платеж
        payment_received = await check_bitcoin_payment(order['bitcoin_address'], order['payment_amount'])
        
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
                        await bot.send_message(admin_id, f"✅ Заказ #{order_id} от @{username} выполнен")
                    except Exception as e:
                        logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
                
                logger.info(f"Заказ #{order_id} выполнен")
            else:
                await callback.message.edit_text("❌ К сожалению, контент в выбранной локации закончился")
                logger.warning(f"Нет доступных ссылок для заказа #{order_id}")
        else:
            await callback.answer("❌ Оплата не найдена. Попробуйте еще раз через несколько минут")
            
    except Exception as e:
        logger.error(f"Ошибка в check_payment_handler: {e}")
        await callback.answer("❌ Ошибка проверки оплаты")

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

# Админские обработчики
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
        logger.error(f"Фатальная ошибка: {e}")