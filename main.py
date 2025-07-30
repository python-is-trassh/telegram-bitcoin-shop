import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, DB_URL, BITCOIN_ADDRESS, ADMIN_IDS, TEST_MODE, validate_config, logger
from database import DatabaseManager

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = DatabaseManager(DB_URL)

# Импортируем роутеры и setup функции
from handlers import router as main_router, setup_handlers
from admin_handlers import router as admin_router, setup_admin_handlers
from review_handlers import router as review_router, setup_review_handlers
from edit_handlers import router as edit_router, setup_edit_handlers

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
        setup_handlers(db, bot)
        setup_admin_handlers(db, bot)
        setup_review_handlers(db, bot)
        setup_edit_handlers(db, bot)
        
        # ИСПРАВЛЕНИЕ: Правильный порядок регистрации роутеров
        # Важно: более специфичные роутеры должны быть ПОСЛЕДНИМИ
        dp.include_router(main_router)      # ОСНОВНОЙ - первый (общие callback)
        dp.include_router(review_router)    # ОТЗЫВЫ - второй  
        dp.include_router(edit_router)      # РЕДАКТИРОВАНИЕ - третий (admin_edit_*, admin_delete_*)
        dp.include_router(admin_router)     # АДМИН - последний (admin_menu, admin_add_*, admin_manage_*)
        
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
        logger.info("🔧 ИСПРАВЛЕНИЯ:")
        logger.info("  ✅ Убрано дублирование функций клавиатур")
        logger.info("  ✅ Исправлены импорты")
        logger.info("  ✅ Правильный порядок роутеров")
        logger.info("  ✅ Исправлены отступы в database.py")
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
