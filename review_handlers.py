from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from states import UserStates
from config import logger

router = Router()

# Глобальные переменные для доступа к db и bot
_db = None
_bot = None

def setup_review_handlers(db, bot):
    """Инициализация обработчиков отзывов"""
    global _db, _bot
    _db = db
    _bot = bot

def create_review_menu(order_id: int):
    """Создание меню для оценки"""
    builder = InlineKeyboardBuilder()
    for i in range(1, 6):
        builder.add(InlineKeyboardButton(
            text=f"{'⭐' * i} {i}",
            callback_data=f"rate_{order_id}_{i}"
        ))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="user_history"))
    builder.adjust(5, 1)
    return builder.as_markup()

@router.callback_query(F.data.startswith("product_reviews_"))
async def product_reviews_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик просмотра отзывов о товаре"""
    try:
        product_id = int(callback.data.split("_")[2])
        product = await _db.get_product(product_id)
        reviews = await _db.get_product_reviews(product_id, limit=10)
        
        if not product:
            await callback.answer("❌ Товар не найден")
            return
        
        # Безопасное получение названия товара
        product_name = product.get('name', 'Неизвестный товар')
        
        if not reviews:
            text = f"📦 *{product_name}*\n\nℹ️ Пока нет отзывов о этом товаре"
        else:
            # Безопасное получение рейтинга и количества отзывов
            rating = product.get('rating', 0) or 0
            review_count = product.get('review_count', 0) or 0
            
            text = f"📦 *{product_name}*\n\n"
            
            if review_count > 0 and rating > 0:
                stars = "⭐" * int(rating)
                text += f"⭐ Рейтинг: {stars} {rating:.1f}/5\n"
                text += f"💬 Всего отзывов: {review_count}\n\n"
            
            text += "*Отзывы покупателей:*\n\n"
            
            for i, review in enumerate(reviews, 1):
                stars = "⭐" * review['rating']
                user_id_masked = f"***{str(review['user_id'])[-3:]}"
                
                # Безопасная обработка даты
                created_at = review.get('created_at')
                if created_at:
                    date = created_at.strftime("%d.%m.%Y")
                else:
                    date = "Дата неизвестна"
                
                text += f"{i}. {stars} от {user_id_masked} ({date})\n"
                
                # Безопасная обработка комментария
                comment = review.get('comment')
                if comment and comment.strip():
                    text += f"   {comment}\n"
                text += "\n"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔙 К товару", callback_data=f"product_{product_id}"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в product_reviews_handler: {e}")
        await callback.answer("❌ Ошибка загрузки отзывов")
        
@router.callback_query(F.data.startswith("review_order_"))
async def review_order_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик начала отзыва"""
    try:
        order_id = int(callback.data.split("_")[2])
        
        # Проверяем, может ли пользователь оставить отзыв
        if not await _db.can_review_order(callback.from_user.id, order_id):
            await callback.answer("❌ Вы уже оставили отзыв на этот заказ или заказ не найден")
            return
        
        order = await _db.get_order(order_id)
        product = await _db.get_product(order['product_id'])
        
        await state.set_state(UserStates.WRITING_REVIEW)
        await state.update_data(review_order_id=order_id, review_product_id=order['product_id'])
        
        text = f"⭐ *Оценка товара*\n\n"
        text += f"📦 {product['name']}\n\n"
        text += f"Поставьте оценку товару:"
        
        await callback.message.edit_text(text, reply_markup=create_review_menu(order_id), parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в review_order_handler: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("rate_"))
async def rate_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора рейтинга"""
    try:
        parts = callback.data.split("_")
        order_id = int(parts[1])
        rating = int(parts[2])
        
        await state.update_data(review_rating=rating)
        
        text = f"⭐ *Оценка: {'⭐' * rating}*\n\n"
        text += f"Теперь напишите комментарий к товару (или отправьте любое сообщение, чтобы пропустить):"
        
        await callback.message.edit_text(text, parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в rate_handler: {e}")
        await callback.answer("❌ Ошибка")

# Заменить функцию process_review_comment в review_handlers.py на эту исправленную версию:

@router.message(StateFilter(UserStates.WRITING_REVIEW))
async def process_review_comment(message: Message, state: FSMContext):
    """Обработка комментария к отзыву"""
    try:
        data = await state.get_data()
        order_id = data.get('review_order_id')
        product_id = data.get('review_product_id')
        rating = data.get('review_rating')
        
        if not all([order_id, product_id, rating]):
            await message.answer("❌ Ошибка данных отзыва")
            await state.set_state(UserStates.MAIN_MENU)
            return
        
        comment = message.text.strip() if message.text else ""
        
        # Добавляем отзыв
        await _db.add_review(message.from_user.id, product_id, order_id, rating, comment)
        
        text = f"✅ *Спасибо за отзыв!*\n\n"
        text += f"⭐ Ваша оценка: {'⭐' * rating}\n"
        if comment:
            text += f"💬 Комментарий: {comment}"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="📋 К покупкам", callback_data="user_history"))
        builder.add(InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu"))
        builder.adjust(1)
        
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode='Markdown')
        await state.set_state(UserStates.MAIN_MENU)
        
        logger.info(f"Пользователь {message.from_user.id} оставил отзыв для заказа {order_id}")
    except Exception as e:
        logger.error(f"Ошибка в process_review_comment: {e}")
        await message.answer("❌ Ошибка сохранения отзыва")
        await state.set_state(UserStates.MAIN_MENU)
