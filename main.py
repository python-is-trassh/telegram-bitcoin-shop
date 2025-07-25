import asyncio
import decimal
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, CallbackQuery, Message
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from config import BOT_TOKEN, DB_URL, BITCOIN_ADDRESS, ADMIN_IDS, TEST_MODE, validate_config, logger
from database import DatabaseManager
from bitcoin_utils import check_bitcoin_payment, get_btc_rate
from states import UserStates

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = DatabaseManager(DB_URL)

# Импортируем роутеры
from handlers import router as main_router
from admin_handlers import router as admin_router, setup_admin_handlers
from review_handlers import router as review_router, setup_review_handlers
from edit_handlers import router as edit_router, setup_edit_handlers

# Недостающие обработчики для основного функционала
@main_router.callback_query(F.data.startswith("buy_product_"))
async def buy_product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик покупки товара"""
    try:
        product_id = int(callback.data.split("_")[2])
        locations = await db.get_locations(product_id)
        
        if not locations:
            await callback.answer("❌ Товар временно отсутствует")
            return
        
        await state.set_state(UserStates.SELECTING_LOCATION)
        await state.update_data(product_id=product_id)
        
        from keyboards import create_locations_menu
        await callback.message.edit_text(
            "📍 Выберите локацию:",
            reply_markup=create_locations_menu(locations, product_id)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в buy_product_handler: {e}")
        await callback.answer("❌ Ошибка")

@main_router.callback_query(F.data.startswith("location_"))
async def location_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора локации"""
    try:
        location_id = int(callback.data.split("_")[1])
        data = await state.get_data()
        product_id = data.get('product_id')
        promo_code = data.get('promo_code')
        
        product = await db.get_product(product_id)
        btc_rate = await get_btc_rate()
        
        # Рассчитываем цену с учетом промокода
        final_price = product['price_rub']
        discount_amount = decimal.Decimal('0')
        
        if promo_code:
            promo = await db.validate_promo_code(promo_code, final_price, callback.from_user.id)
            if promo:
                discount_amount = await db.calculate_discount(promo, final_price)
                final_price = final_price - discount_amount
        
        # Добавляем случайное количество сатоши для уникальности
        extra_satoshi = random.randint(1, 300)
        price_btc = final_price / btc_rate
        payment_amount = price_btc + decimal.Decimal(extra_satoshi) / 100000000
        
        # Создаем заказ
        order_id = await db.create_order(
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
            promo = await db.validate_promo_code(promo_code, product['price_rub'], callback.from_user.id)
            if promo:
                await db.apply_promo_code(promo['id'], callback.from_user.id, order_id)
        
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
                
                await bot.send_message(
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

@main_router.callback_query(F.data.startswith("check_payment_"))
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
        transaction_hash = await check_bitcoin_payment(
            order['bitcoin_address'], 
            order['payment_amount'], 
            order['created_at'],
            db
        )
        
        if transaction_hash:
            # Проверяем, не использовалась ли уже эта транзакция
            if await db.is_transaction_used(transaction_hash):
                await callback.answer("❌ Эта транзакция уже была использована для другого заказа")
                return
            
            # Помечаем транзакцию как использованную
            await db.mark_transaction_used(transaction_hash, order_id, order['payment_amount'])
            
            # Получаем доступную ссылку
            content_link = await db.get_available_link(order['location_id'])
            
            if content_link:
                await db.complete_order(order_id, content_link, transaction_hash)
                
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

# История покупок и отзывы
@main_router.callback_query(F.data == "user_history")
async def user_history_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик истории покупок"""
    try:
        orders = await db.get_user_history(callback.from_user.id)
        
        if not orders:
            text = "📋 *Мои покупки*\n\nУ вас пока нет завершенных покупок"
            from keyboards import create_back_to_main_menu
            builder = create_back_to_main_menu()
        else:
            text = "📋 *Мои покупки*\n\n"
            builder = InlineKeyboardBuilder()
            
            for order in orders:
                date = order['completed_at'].strftime("%d.%m.%Y %H:%M")
                price = order['price_rub'] - order['discount_amount']
                
                order_text = f"📦 {order['product_name']}\n"
                order_text += f"📍 {order['location_name']}\n"
                order_text += f"💰 {price} ₽ • {date}\n"
                
                if order['user_rating']:
                    stars = "⭐" * order['user_rating']
                    order_text += f"⭐ Ваша оценка: {stars}"
                else:
                    order_text += "💬 Можете оставить отзыв"
                    builder.add(InlineKeyboardButton(
                        text=f"⭐ Оценить \"{order['product_name'][:20]}...\"",
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
@main_router.callback_query(F.data.startswith("admin_confirm_payment_"))
async def admin_confirm_payment_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик ручного подтверждения платежа админом"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        order_id = int(callback.data.split("_")[3])
        order = await db.get_order(order_id)
        
        if not order:
            await callback.answer("❌ Заказ не найден")
            return
        
        if order['status'] != 'pending':
            await callback.answer("❌ Заказ уже обработан")
            return
        
        # Получаем доступную ссылку
        content_link = await db.get_available_link(order['location_id'])
        
        if content_link:
            await db.complete_order(order_id, content_link, "manual_confirmation")
            
            # Уведомляем пользователя
            try:
                user_text = f"✅ *Оплата подтверждена!*\n\n"
                user_text += f"📦 Заказ #{order_id} выполнен\n\n"
                user_text += f"🔗 Ваш контент:\n{content_link}\n\n"
                user_text += f"Спасибо за покупку! 🎉\n\n"
                user_text += f"💬 Оставьте отзыв о товаре в разделе \"📋 Мои покупки\""
                
                await bot.send_message(order['user_id'], user_text, parse_mode='Markdown')
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
@main_router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены заказа"""
    try:
        order_id = int(callback.data.split("_")[2])
        order = await db.get_order(order_id)
        
        if not order or order['user_id'] != callback.from_user.id:
            await callback.answer("❌ Заказ не найден")
            return
        
        if order['status'] != 'pending':
            await callback.answer("❌ Заказ нельзя отменить")
            return
        
        # Отменяем заказ
        async with db.pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order_id)
        
        text = f"❌ *Заказ #{order_id} отменен*\n\n"
        text += f"Вы можете оформить новый заказ в любое время"
        
        from keyboards import create_main_menu
        await callback.message.edit_text(text, reply_markup=create_main_menu(), parse_mode='Markdown')
        await callback.answer("✅ Заказ отменен")
        await state.set_state(UserStates.MAIN_MENU)
        
        logger.info(f"Пользователь {callback.from_user.id} отменил заказ #{order_id}")
    except Exception as e:
        logger.error(f"Ошибка в cancel_order_handler: {e}")
        await callback.answer("❌ Ошибка отмены заказа")

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

async def main():
    """Основная функция"""
    try:
        # Проверяем конфигурацию
        if not validate_config():
            return
        
        # Инициализируем базу данных
        logger.info("Инициализация базы данных...")
        await db.init_pool()
        
        # Инициализируем обработчики с доступом к db и bot
        setup_admin_handlers(db, bot)
        setup_review_handlers(db, bot)
        setup_edit_handlers(db, bot)
        
        # Регистрируем роутеры
        dp.include_router(main_router)
        dp.include_router(admin_router)
        dp.include_router(review_router)
        dp.include_router(edit_router)
        
        # Запускаем задачу отмены просроченных заказов
        cancel_task = asyncio.create_task(cancel_expired_orders())
        
        logger.info("🚀 Расширенный Bitcoin магазин запущен!")
        logger.info(f"₿ Bitcoin адрес: {BITCOIN_ADDRESS}")
        logger.info(f"👥 Администраторы: {ADMIN_IDS}")
        logger.info("✨ Новые функции:")
        logger.info("  🔒 Защита от повторного использования платежей")
        logger.info("  📦 Автоскрытие товаров без ссылок")
        logger.info("  📋 История покупок")
        logger.info("  ⭐ Система рейтингов и отзывов")
        logger.info("  🎟️ Промокоды и скидки")
        logger.info("  📱 Уведомления о статусе заказов")
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
        logger.error(f"Фатальная ошибка: {e}")
