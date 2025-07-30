import decimal
import random
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
# ИСПРАВЛЕНИЕ: Добавляем недостающий импорт функции админ меню
from admin_handlers import create_admin_menu
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
    # ТЕПЕРЬ ФУНКЦИЯ create_admin_menu КОРРЕКТНО ИМПОРТИРОВАНА
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
        
        # Безопасное получение рейтинга и количества отзывов
        rating = product.get('rating', 0)
        review_count = product.get('review_count', 0)
        
        # Добавляем рейтинг только если есть отзывы
        if review_count and review_count > 0 and rating and rating > 0:
            stars = "⭐" * int(rating)
            text += f"⭐ Рейтинг: {stars} {rating:.1f}/5 ({review_count} отзывов)\n\n"
        
        # Показываем последние отзывы
        if reviews:
            text += "💬 *Последние отзывы:*\n"
            for review in reviews:
                stars = "⭐" * review['rating']
                comment = review.get('comment', '')
                if comment:
                    comment = comment[:100] + "..." if len(comment) > 100 else comment
                    text += f"{stars} {comment}\n"
                else:
                    text += f"{stars}\n"
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

# Покупка товара
@router.callback_query(F.data.startswith("buy_product_"))
async def buy_product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик покупки товара"""
    try:
        product_id = int(callback.data.split("_")[2])
        locations = await _db.get_locations(product_id)
        
        if not locations:
            await callback.answer("❌ Товар временно отсутствует")
            return
        
        await state.set_state(UserStates.SELECTING_LOCATION)
        await state.update_data(product_id=product_id)
        
        await callback.message.edit_text(
            "📍 Выберите локацию:",
            reply_markup=create_locations_menu(locations, product_id)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в buy_product_handler: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("location_"))
async def location_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора локации"""
    try:
        location_id = int(callback.data.split("_")[1])
        data = await state.get_data()
        product_id = data.get('product_id')
        promo_code = data.get('promo_code')
        
        product = await _db.get_product(product_id)
        btc_rate = await get_btc_rate()
        
        # Рассчитываем цену с учетом промокода
        final_price = product['price_rub']
        discount_amount = decimal.Decimal('0')
        
        if promo_code:
            promo = await _db.validate_promo_code(promo_code, final_price, callback.from_user.id)
            if promo:
                discount_amount = await _db.calculate_discount(promo, final_price)
                final_price = final_price - discount_amount
        
        # Добавляем случайное количество сатоши для уникальности
        extra_satoshi = random.randint(1, 300)
        price_btc = final_price / btc_rate
        payment_amount = price_btc + decimal.Decimal(extra_satoshi) / 100000000
        
        # Создаем заказ
        order_id = await _db.create_order(
            user_id=callback.from_user.id,
            product_id=product_id,
            location_id=location_id,
            price_rub=product['price_rub'],
            price_btc=price_btc,
            btc_rate=btc_rate,
            payment_amount=payment_amount,
            promo_code=promo_code,
            discount_amount=discount_amount
        )
        
        # Если промокод использовался, применяем его
        if promo_code:
            promo = await _db.validate_promo_code(promo_code, product['price_rub'], callback.from_user.id)
            if promo:
                await _db.apply_promo_code(promo['id'], callback.from_user.id, order_id)
        
        await state.set_state(UserStates.PAYMENT_WAITING)
        await state.update_data(order_id=order_id)
        await state.update_data(promo_code=None)  # Очищаем промокод
        
        text = f"💳 *Оплата заказа #{order_id}*\n\n"
        text += f"📦 Товар: {product['name']}\n"
        
        if discount_amount > 0:
            text += f"💰 Цена: {product['price_rub']} ₽\n"
            text += f"🎟️ Скидка: -{discount_amount} ₽\n"
            text += f"💳 К оплате: {final_price} ₽ (`{payment_amount:.8f}` BTC)\n\n"
        else:
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
                
                admin_text = f"🆕 *Новый заказ #{order_id}*\n\n"
                admin_text += f"👤 Покупатель: @{username}\n"
                admin_text += f"📦 Товар: {product['name']}\n"
                if discount_amount > 0:
                    admin_text += f"💰 Цена: {product['price_rub']} ₽\n"
                    admin_text += f"🎟️ Скидка: -{discount_amount} ₽ (код: {promo_code})\n"
                    admin_text += f"💳 К оплате: {final_price} ₽\n"
                admin_text += f"💰 Сумма: `{payment_amount:.8f}` BTC\n"
                admin_text += f"📍 Адрес: `{BITCOIN_ADDRESS}`\n\n"
                admin_text += f"Используйте кнопку ниже для ручной выдачи товара"
                
                await _bot.send_message(
                    admin_id, 
                    admin_text,
                    reply_markup=admin_builder.as_markup(),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
                
        logger.info(f"Создан заказ #{order_id} пользователем {callback.from_user.id}")
                
    except Exception as e:
        logger.error(f"Ошибка в location_handler: {e}")
        await callback.answer("❌ Ошибка создания заказа")

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

# Проверка оплаты
@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик проверки оплаты"""
    try:
        order_id = int(callback.data.split("_")[2])
        order = await _db.get_order(order_id)
        
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
        transaction_hash = await check_bitcoin_payment(
            order['bitcoin_address'], 
            order['payment_amount'], 
            order['created_at'],
            _db
        )
        
        if transaction_hash:
            # Проверяем, не использовалась ли уже эта транзакция
            if await _db.is_transaction_used(transaction_hash):
                await callback.answer("❌ Эта транзакция уже была использована для другого заказа")
                return
            
            # Помечаем транзакцию как использованную
            await _db.mark_transaction_used(transaction_hash, order_id, order['payment_amount'])
            
            # Получаем доступную ссылку
            content_link = await _db.get_available_link(order['location_id'])
            
            if content_link:
                await _db.complete_order(order_id, content_link, transaction_hash)
                
                text = f"✅ *Оплата подтверждена!*\n\n"
                text += f"📦 Заказ #{order_id} выполнен\n\n"
                text += f"🔗 Ваш контент:\n{content_link}\n\n"
                text += f"Спасибо за покупку! 🎉\n\n"
                text += f"💬 Оставьте отзыв о товаре в разделе \"📋 Мои покупки\""
                
                await callback.message.edit_text(text, parse_mode='Markdown')
                await state.set_state(UserStates.MAIN_MENU)
                
                # Уведомляем админов о выполненном заказе
                for admin_id in ADMIN_IDS:
                    try:
                        username = callback.from_user.username or "без username"
                        await _bot.send_message(admin_id, f"✅ Заказ #{order_id} от @{username} выполнен автоматически")
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

# История покупок
@router.callback_query(F.data == "user_history")
async def user_history_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик истории покупок"""
    try:
        orders = await _db.get_user_history(callback.from_user.id)
        
        if not orders:
            text = "📋 *Мои покупки*\n\nУ вас пока нет завершенных покупок"
            builder = create_back_to_main_menu()
        else:
            text = "📋 *Мои покупки*\n\n"
            builder = InlineKeyboardBuilder()
            
            for order in orders:
                # Безопасное получение даты
                completed_at = order.get('completed_at')
                if completed_at:
                    date = completed_at.strftime("%d.%m.%Y %H:%M")
                else:
                    date = "Дата неизвестна"
                
                # Безопасное вычисление цены
                price_rub = order.get('price_rub', 0) or 0
                discount_amount = order.get('discount_amount', 0) or 0
                price = price_rub - discount_amount
                
                # Безопасное получение названий
                product_name = order.get('product_name', 'Неизвестный товар')
                location_name = order.get('location_name', 'Неизвестная локация')
                
                order_text = f"📦 {product_name}\n"
                order_text += f"📍 {location_name}\n"
                order_text += f"💰 {price} ₽ • {date}\n"
                
                # Безопасная проверка рейтинга
                user_rating = order.get('user_rating')
                if user_rating and user_rating > 0:
                    stars = "⭐" * int(user_rating)
                    order_text += f"⭐ Ваша оценка: {stars}"
                else:
                    order_text += "💬 Можете оставить отзыв"
                    # Ограничиваем длину названия товара для кнопки
                    short_product_name = product_name[:20] + "..." if len(product_name) > 20 else product_name
                    builder.add(InlineKeyboardButton(
                        text=f"⭐ Оценить \"{short_product_name}\"",
                        callback_data=f"review_order_{order['id']}"
                    ))
                
                text += order_text + "\n\n"
            
            builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
            builder.adjust(1)
        
        await state.set_state(UserStates.VIEWING_HISTORY)
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в user_history_handler: {e}")
        await callback.answer("❌ Ошибка загрузки истории")

# Обработчик ручного подтверждения платежа админом
@router.callback_query(F.data.startswith("admin_confirm_payment_"))
async def admin_confirm_payment_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик ручного подтверждения платежа админом"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        order_id = int(callback.data.split("_")[3])
        order = await _db.get_order(order_id)
        
        if not order:
            await callback.answer("❌ Заказ не найден")
            return
        
        if order['status'] != 'pending':
            await callback.answer("❌ Заказ уже обработан")
            return
        
        # Получаем доступную ссылку
        content_link = await _db.get_available_link(order['location_id'])
        
        if content_link:
            await _db.complete_order(order_id, content_link, "manual_confirmation")
            
            # Уведомляем пользователя
            try:
                user_text = f"✅ *Оплата подтверждена!*\n\n"
                user_text += f"📦 Заказ #{order_id} выполнен\n\n"
                user_text += f"🔗 Ваш контент:\n{content_link}\n\n"
                user_text += f"Спасибо за покупку! 🎉\n\n"
                user_text += f"💬 Оставьте отзыв о товаре в разделе \"📋 Мои покупки\""
                
                await _bot.send_message(order['user_id'], user_text, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Ошибка уведомления пользователя {order['user_id']}: {e}")
            
            await callback.answer("✅ Заказ выполнен")
            await callback.message.edit_text(f"✅ Заказ #{order_id} выполнен вручную")
            
            logger.info(f"Админ {callback.from_user.id} вручную выполнил заказ #{order_id}")
        else:
            await callback.answer("❌ Нет доступных ссылок")
            
    except Exception as e:
        logger.error(f"Ошибка в admin_confirm_payment_handler: {e}")
        await callback.answer("❌ Ошибка")

# Отмена заказа
@router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены заказа"""
    try:
        order_id = int(callback.data.split("_")[2])
        order = await _db.get_order(order_id)
        
        if not order or order['user_id'] != callback.from_user.id:
            await callback.answer("❌ Заказ не найден")
            return
        
        if order['status'] != 'pending':
            await callback.answer("❌ Заказ нельзя отменить")
            return
        
        # Отменяем заказ
        async with _db.pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order_id)
        
        text = f"❌ *Заказ #{order_id} отменен*\n\n"
        text += f"Вы можете оформить новый заказ в любое время"
        
        await callback.message.edit_text(text, reply_markup=create_main_menu(), parse_mode='Markdown')
        await callback.answer("✅ Заказ отменен")
        await state.set_state(UserStates.MAIN_MENU)
        
        logger.info(f"Пользователь {callback.from_user.id} отменил заказ #{order_id}")
    except Exception as e:
        logger.error(f"Ошибка в cancel_order_handler: {e}")
        await callback.answer("❌ Ошибка отмены заказа")

# Обработчик неизвестных сообщений
@router.message()
async def unknown_message_handler(message: Message):
    """Обработчик неизвестных сообщений"""
    await message.answer("❓ Неизвестная команда. Используйте /start для начала работы")
