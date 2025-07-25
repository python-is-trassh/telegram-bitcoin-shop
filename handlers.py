import decimal
from datetime import datetime
from typing import Dict, List
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from states import UserStates, AdminStates
from keyboards import (
    create_main_menu, create_categories_menu, create_products_menu,
    create_product_detail_menu, create_locations_menu, 
    create_back_to_main_menu
)
from bitcoin_utils import get_btc_rate, check_bitcoin_payment
from config import ADMIN_IDS, BITCOIN_ADDRESS, logger

router = Router()

# Глобальные переменные для доступа к db и bot
_db = None
_bot = None

def setup_handlers(db, bot: Bot):
    """Инициализация обработчиков"""
    global _db, _bot
    _db = db
    _bot = bot

# Функции клавиатуры для админ панели (локальные)
def create_admin_menu():
    """Создание админ меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Добавить категорию", callback_data="admin_add_category"))
    builder.add(InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add_product"))
    builder.add(InlineKeyboardButton(text="➕ Добавить локацию", callback_data="admin_add_location"))
    builder.add(InlineKeyboardButton(text="🎟️ Добавить промокод", callback_data="admin_add_promo"))
    builder.add(InlineKeyboardButton(text="📝 Управление категориями", callback_data="admin_manage_categories"))
    builder.add(InlineKeyboardButton(text="📦 Управление товарами", callback_data="admin_manage_products"))
    builder.add(InlineKeyboardButton(text="📍 Управление локациями", callback_data="admin_manage_locations"))
    builder.add(InlineKeyboardButton(text="🎟️ Управление промокодами", callback_data="admin_manage_promos"))
    builder.add(InlineKeyboardButton(text="⭐ Просмотр отзывов", callback_data="admin_view_reviews"))
    builder.add(InlineKeyboardButton(text="✏️ Редактировать «О магазине»", callback_data="admin_edit_about"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
    builder.adjust(2, 2, 2, 2, 2, 1, 1, 1)
    return builder.as_markup()

# Основные команды
@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.set_state(UserStates.MAIN_MENU)
    
    try:
        welcome_text = await _db.get_setting('welcome_message')
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

# Основные обработчики callback'ов
@router.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик главного меню"""
    await state.set_state(UserStates.MAIN_MENU)
    try:
        await callback.message.edit_text("🏠 Главное меню", reply_markup=create_main_menu())
        await callback.answer()
    except TelegramBadRequest:
        await callback.message.answer("🏠 Главное меню", reply_markup=create_main_menu())

@router.callback_query(F.data == "admin_menu")
async def admin_menu_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик возврата в админ меню"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    await state.set_state(AdminStates.ADMIN_MENU)
    try:
        await callback.message.edit_text("🔧 Панель администратора", reply_markup=create_admin_menu())
        await callback.answer()
    except TelegramBadRequest:
        await callback.message.answer("🔧 Панель администратора", reply_markup=create_admin_menu())

@router.callback_query(F.data == "categories")
async def categories_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик каталога"""
    await state.set_state(UserStates.BROWSING_CATEGORIES)
    
    try:
        categories = await _db.get_categories()
        
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

@router.callback_query(F.data == "about")
async def about_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик информации о магазине"""
    try:
        about_text = await _db.get_setting('about_text')
        await callback.message.edit_text(about_text, reply_markup=create_back_to_main_menu())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в about_handler: {e}")
        await callback.answer("❌ Ошибка загрузки информации")

@router.callback_query(F.data == "btc_rate")
async def btc_rate_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик курса Bitcoin"""
    try:
        await callback.answer("🔄 Получаем актуальный курс...")
        rate = await get_btc_rate()
        
        text = f"₿ *Текущий курс Bitcoin*\n\n"
        text += f"💰 1 BTC = {rate:,.2f} ₽\n\n"
        text += f"📊 Данные обновляются каждые 5 минут"
        
        await callback.message.edit_text(text, reply_markup=create_back_to_main_menu(), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка в btc_rate_handler: {e}")
        await callback.answer("❌ Ошибка получения курса")

@router.callback_query(F.data == "stats")
async def stats_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик общей статистики"""
    try:
        stats = await _db.get_stats()
        
        text = f"📊 *Статистика магазина*\n\n"
        text += f"📦 Всего заказов: {stats['total_orders']}\n"
        text += f"✅ Выполнено: {stats['completed_orders']}\n"
        text += f"⏳ В ожидании: {stats['pending_orders']}\n"
        text += f"💰 Общая выручка: {stats['total_revenue']:,.2f} ₽\n"
        text += f"⭐ Отзывов: {stats['total_reviews']}\n"
        if stats['total_reviews'] > 0:
            text += f"📈 Средний рейтинг: {stats['avg_rating']:.1f}/5\n"
        text += f"\n📅 *Сегодня:*\n"
        text += f"🆕 Заказов: {stats['today_orders']}\n"
        text += f"💵 Выручка: {stats['today_revenue']:,.2f} ₽"
        
        await callback.message.edit_text(text, reply_markup=create_back_to_main_menu(), parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в stats_handler: {e}")
        await callback.answer("❌ Ошибка загрузки статистики")

# Обработчики категорий и товаров
@router.callback_query(F.data.startswith("category_"))
async def category_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора категории"""
    try:
        category_id = int(callback.data.split("_")[1])
        products = await _db.get_products(category_id)
        
        if not products:
            categories = await _db.get_categories()
            await callback.message.edit_text("📦 В этой категории пока нет товаров в наличии", 
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
        product = await _db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден")
            return
        
        locations = await _db.get_locations(product_id)
        reviews = await _db.get_product_reviews(product_id, limit=3)
        
        await state.set_state(UserStates.VIEWING_PRODUCT)
        await state.update_data(product_id=product_id)
        
        # Получаем курс Bitcoin
        btc_rate = await get_btc_rate()
        price_btc = product['price_rub'] / btc_rate
        
        text = f"📦 *{product['name']}*\n\n"
        text += f"📝 {product['description']}\n\n"
        text += f"💰 Цена: {product['price_rub']} ₽ (~{price_btc:.8f} BTC)\n\n"
        
        # Добавляем рейтинг
        if product['review_count'] > 0:
            stars = "⭐" * int(product['rating'])
            text += f"⭐ Рейтинг: {stars} {product['rating']:.1f}/5 ({product['review_count']} отзывов)\n\n"
        
        # Показываем последние отзывы
        if reviews:
            text += "💬 *Последние отзывы:*\n"
            for review in reviews:
                stars = "⭐" * review['rating']
                comment = review['comment'][:100] + "..." if len(review['comment']) > 100 else review['comment']
                text += f"{stars} {comment}\n"
            text += "\n"
        
        if locations:
            text += "✅ Товар в наличии"
        else:
            text += "❌ Товар временно отсутствует"
        
        await callback.message.edit_text(
            text,
            reply_markup=create_product_detail_menu(product_id, bool(locations), bool(reviews)),
            parse_mode='Markdown'
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в product_handler: {e}")
        await callback.answer("❌ Ошибка загрузки товара")

# Промокоды
@router.callback_query(F.data == "enter_promo")
async def enter_promo_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик ввода промокода"""
    await state.set_state(UserStates.ENTERING_PROMO)
    
    text = "🎟️ *Промокод*\n\n"
    text += "Введите промокод для получения скидки:"
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
    await callback.answer()

@router.message(StateFilter(UserStates.ENTERING_PROMO))
async def process_promo_code(message: Message, state: FSMContext):
    """Обработка промокода"""
    try:
        promo_code = message.text.strip().upper()
        
        # Временно сохраняем промокод (проверим при создании заказа)
        await state.update_data(promo_code=promo_code)
        
        text = f"✅ *Промокод сохранен*\n\n"
        text += f"🎟️ Промокод: `{promo_code}`\n\n"
        text += f"Скидка будет применена при оформлении заказа"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🛍 В каталог", callback_data="categories"))
        builder.add(InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu"))
        builder.adjust(1)
        
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await state.set_state(UserStates.MAIN_MENU)
        
        logger.info(f"Пользователь {message.from_user.id} ввел промокод {promo_code}")
    except Exception as e:
        logger.error(f"Ошибка в process_promo_code: {e}")
        await message.answer("❌ Ошибка сохранения промокода")

# Обработчик неизвестных сообщений
@router.message()
async def unknown_message_handler(message: Message):
    """Обработчик неизвестных сообщений"""
    await message.answer("❓ Неизвестная команда. Используйте /start для начала работы")

# Обработчик ошибок callback'ов
@router.callback_query()
async def unknown_callback_handler(callback: CallbackQuery):
    """Обработчик неизвестных callback'ов"""
    await callback.answer("❓ Неизвестная команда")
