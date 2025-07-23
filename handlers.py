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
    create_product_detail_menu, create_locations_menu, create_review_menu,
    create_admin_menu, create_manage_categories_menu, create_manage_products_menu,
    create_manage_locations_menu, create_manage_promos_menu,
    create_back_to_admin_menu, create_back_to_main_menu
)
from bitcoin_utils import get_btc_rate, check_bitcoin_payment
from config import ADMIN_IDS, BITCOIN_ADDRESS, logger

router = Router()

class Handlers:
    def __init__(self, db, bot: Bot):
        self.db = db
        self.bot = bot

    # Основные команды
    @router.message(Command("start"))
    async def start_handler(self, message: Message, state: FSMContext):
        """Обработчик команды /start"""
        await state.set_state(UserStates.MAIN_MENU)
        
        try:
            welcome_text = await self.db.get_setting('welcome_message')
            await message.answer(welcome_text, reply_markup=create_main_menu())
            logger.info(f"Пользователь {message.from_user.id} (@{message.from_user.username}) запустил бота")
        except Exception as e:
            logger.error(f"Ошибка в start_handler: {e}")
            await message.answer("Добро пожаловать в наш магазин!", reply_markup=create_main_menu())

    @router.message(Command("admin"))
    async def admin_handler(self, message: Message, state: FSMContext):
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
    async def main_menu_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик главного меню"""
        await state.set_state(UserStates.MAIN_MENU)
        try:
            await callback.message.edit_text("🏠 Главное меню", reply_markup=create_main_menu())
            await callback.answer()
        except TelegramBadRequest:
            await callback.message.answer("🏠 Главное меню", reply_markup=create_main_menu())

    @router.callback_query(F.data == "admin_menu")
    async def admin_menu_handler(self, callback: CallbackQuery, state: FSMContext):
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
    async def categories_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик каталога"""
        await state.set_state(UserStates.BROWSING_CATEGORIES)
        
        try:
            categories = await self.db.get_categories()
            
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
    async def about_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик информации о магазине"""
        try:
            about_text = await self.db.get_setting('about_text')
            await callback.message.edit_text(about_text, reply_markup=create_back_to_main_menu())
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в about_handler: {e}")
            await callback.answer("❌ Ошибка загрузки информации")

    @router.callback_query(F.data == "btc_rate")
    async def btc_rate_handler(self, callback: CallbackQuery, state: FSMContext):
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
    async def stats_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик общей статистики"""
        try:
            stats = await self.db.get_stats()
            
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

    @router.callback_query(F.data.startswith("cancel_order_"))
    async def cancel_order_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик отмены заказа"""
        try:
            order_id = int(callback.data.split("_")[2])
            order = await self.db.get_order(order_id)
            
            if not order or order['user_id'] != callback.from_user.id:
                await callback.answer("❌ Заказ не найден")
                return
            
            if order['status'] != 'pending':
                await callback.answer("❌ Заказ нельзя отменить")
                return
            
            # Отменяем заказ
            async with self.db.pool.acquire() as conn:
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

    @router.callback_query(F.data.startswith("admin_confirm_payment_"))
    async def admin_confirm_payment_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик ручного подтверждения платежа админом"""
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ Нет прав")
            return
        
        try:
            order_id = int(callback.data.split("_")[3])
            order = await self.db.get_order(order_id)
            
            if not order:
                await callback.answer("❌ Заказ не найден")
                return
            
            if order['status'] != 'pending':
                await callback.answer("❌ Заказ уже обработан")
                return
            
            # Получаем доступную ссылку
            content_link = await self.db.get_available_link(order['location_id'])
            
            if content_link:
                await self.db.complete_order(order_id, content_link, "manual_confirmation")
                
                # Уведомляем пользователя
                try:
                    user_text = f"✅ *Оплата подтверждена!*\n\n"
                    user_text += f"📦 Заказ #{order_id} выполнен\n\n"
                    user_text += f"🔗 Ваш контент:\n{content_link}\n\n"
                    user_text += f"Спасибо за покупку! 🎉\n\n"
                    user_text += f"💬 Оставьте отзыв о товаре в разделе \"📋 Мои покупки\""
                    
                    await self.bot.send_message(order['user_id'], user_text, parse_mode='Markdown')
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

    # Обработчики категорий и товаров (остаются без изменений из оригинального кода)
    @router.callback_query(F.data.startswith("category_"))
    async def category_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора категории"""
        try:
            category_id = int(callback.data.split("_")[1])
            products = await self.db.get_products(category_id)
            
            if not products:
                categories = await self.db.get_categories()
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
    async def product_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора товара"""
        try:
            product_id = int(callback.data.split("_")[1])
            product = await self.db.get_product(product_id)
            
            if not product:
                await callback.answer("❌ Товар не найден")
                return
            
            locations = await self.db.get_locations(product_id)
            reviews = await self.db.get_product_reviews(product_id, limit=3)
            
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
    async def enter_promo_handler(self, callback: CallbackQuery, state: FSMContext):
        """Обработчик ввода промокода"""
        await state.set_state(UserStates.ENTERING_PROMO)
        
        text = "🎟️ *Промокод*\n\n"
        text += "Введите промокод для получения скидки:"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await callback.answer()

    @router.message(StateFilter(UserStates.ENTERING_PROMO))
    async def process_promo_code(self, message: Message, state: FSMContext):
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
    async def unknown_message_handler(self, message: Message):
        """Обработчик неизвестных сообщений"""
        await message.answer("❓ Неизвестная команда. Используйте /start для начала работы")

    # Обработчик ошибок callback'ов
    @router.callback_query()
    async def unknown_callback_handler(self, callback: CallbackQuery):
        """Обработчик неизвестных callback'ов"""
        await callback.answer("❓ Неизвестная команда")
