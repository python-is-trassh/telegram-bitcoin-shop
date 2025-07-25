import decimal
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from states import AdminStates
from config import ADMIN_IDS, logger

router = Router()

# Глобальные переменные для доступа к db и bot
_db = None
_bot = None

def setup_admin_handlers(db, bot):
    """Инициализация обработчиков"""
    global _db, _bot
    _db = db
    _bot = bot

# Функции клавиатуры (перенесены сюда чтобы избежать циклических импортов)
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

def create_manage_categories_menu(categories):
    """Создание меню управления категориями"""
    builder = InlineKeyboardBuilder()
    for category in categories:
        status_icon = "⚠️" if not category['is_active'] else ""
        builder.add(InlineKeyboardButton(
            text=f"📝 {category['name']} {status_icon}",
            callback_data=f"admin_edit_category_{category['id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🗑",
            callback_data=f"admin_delete_category_{category['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    builder.adjust(2)
    return builder.as_markup()

def create_manage_products_menu(products):
    """Создание меню управления товарами"""
    builder = InlineKeyboardBuilder()
    for product in products:
        status_icon = "⚠️" if not product['is_active'] else ""
        builder.add(InlineKeyboardButton(
            text=f"📝 {product['category_name']} - {product['name']} {status_icon}",
            callback_data=f"admin_edit_product_{product['id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🗑",
            callback_data=f"admin_delete_product_{product['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    builder.adjust(2)
    return builder.as_markup()

def create_manage_locations_menu(locations):
    """Создание меню управления локациями"""
    builder = InlineKeyboardBuilder()
    for location in locations:
        status_icon = "⚠️" if not location['is_active'] else ""
        available_count = location.get('available_links_count', 0)
        builder.add(InlineKeyboardButton(
            text=f"📝 {location['product_name']} - {location['name']} ({available_count}) {status_icon}",
            callback_data=f"admin_edit_location_{location['id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🗑",
            callback_data=f"admin_delete_location_{location['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    builder.adjust(2)
    return builder.as_markup()

def create_manage_promos_menu(promos):
    """Создание меню управления промокодами"""
    builder = InlineKeyboardBuilder()
    for promo in promos:
        status_icon = "⚠️" if not promo['is_active'] else ""
        usage_text = f"({promo['current_uses']}/{promo['max_uses']})" if promo['max_uses'] > 0 else ""
        builder.add(InlineKeyboardButton(
            text=f"📝 {promo['code']} {usage_text} {status_icon}",
            callback_data=f"admin_edit_promo_{promo['id']}"
        ))
        builder.add(InlineKeyboardButton(
            text="🗑",
            callback_data=f"admin_delete_promo_{promo['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    builder.adjust(2)
    return builder.as_markup()

def create_back_to_admin_menu():
    """Создание кнопки возврата в админ меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    return builder.as_markup()

# Промокоды - добавление
@router.callback_query(F.data == "admin_add_promo")
async def admin_add_promo_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик добавления промокода"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    await state.set_state(AdminStates.ADDING_PROMO)
    await callback.message.edit_text(
        "🎟️ Добавление промокода\n\n"
        "Введите данные в формате:\n"
        "КОД\n"
        "Тип скидки (percent/fixed)\n"
        "Размер скидки\n"
        "Минимальная сумма заказа (0 = без ограничений)\n"
        "Максимальное количество использований (0 = без ограничений)\n"
        "Срок действия в днях (0 = без ограничений)\n\n"
        "Пример:\n"
        "SALE20\n"
        "percent\n"
        "20\n"
        "1000\n"
        "100\n"
        "30"
    )
    await callback.answer()

@router.message(StateFilter(AdminStates.ADDING_PROMO))
async def process_add_promo(message: Message, state: FSMContext):
    """Обработка добавления промокода"""
    lines = message.text.strip().split('\n')
    if len(lines) < 6:
        await message.answer("❌ Неверный формат. Укажите все параметры")
        return
    
    try:
        code = lines[0].strip().upper()
        discount_type = lines[1].strip().lower()
        discount_value = decimal.Decimal(lines[2].strip())
        min_order_amount = decimal.Decimal(lines[3].strip())
        max_uses = int(lines[4].strip())
        days_valid = int(lines[5].strip())
        
        if discount_type not in ['percent', 'fixed']:
            await message.answer("❌ Тип скидки должен быть 'percent' или 'fixed'")
            return
        
        if discount_type == 'percent' and (discount_value <= 0 or discount_value > 100):
            await message.answer("❌ Процентная скидка должна быть от 1 до 100")
            return
        
        if discount_type == 'fixed' and discount_value <= 0:
            await message.answer("❌ Фиксированная скидка должна быть больше 0")
            return
        
        expires_at = None
        if days_valid > 0:
            expires_at = datetime.now() + timedelta(days=days_valid)
        
        promo_id = await _db.add_promo_code(
            code, discount_type, discount_value, min_order_amount, max_uses, expires_at
        )
        
        await message.answer(f"✅ Промокод '{code}' добавлен (ID: {promo_id})", 
                           reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} добавил промокод '{code}'")
    except (ValueError, decimal.InvalidOperation):
        await message.answer("❌ Неверный формат чисел")
    except Exception as e:
        logger.error(f"Ошибка добавления промокода: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# Промокоды - управление
@router.callback_query(F.data == "admin_manage_promos")
async def admin_manage_promos_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик управления промокодами"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        promos = await _db.get_promo_codes(active_only=False)
        if not promos:
            await callback.message.edit_text("❌ Промокоды не найдены", reply_markup=create_admin_menu())
            await callback.answer()
            return
        
        await state.set_state(AdminStates.MANAGE_PROMOS)
        await callback.message.edit_text(
            "🎟️ Управление промокодами\n\n"
            "📝 - редактировать, 🗑 - удалить\n"
            "⚠️ - неактивные промокоды",
            reply_markup=create_manage_promos_menu(promos)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_manage_promos_handler: {e}")
        await callback.answer("❌ Ошибка загрузки промокодов")

@router.callback_query(F.data.startswith("admin_delete_promo_"))
async def admin_delete_promo_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик удаления промокода"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        promo_id = int(callback.data.split("_")[3])
        
        # Деактивируем промокод
        await _db.deactivate_promo_code(promo_id)
        await callback.answer("✅ Промокод деактивирован")
        
        # Обновляем список
        promos = await _db.get_promo_codes(active_only=False)
        if promos:
            await callback.message.edit_text(
                "🎟️ Управление промокодами\n\n"
                "📝 - редактировать, 🗑 - удалить\n"
                "⚠️ - неактивные промокоды",
                reply_markup=create_manage_promos_menu(promos)
            )
        else:
            await callback.message.edit_text("❌ Промокоды не найдены", reply_markup=create_admin_menu())
        
        logger.info(f"Админ {callback.from_user.id} деактивировал промокод {promo_id}")
    except Exception as e:
        logger.error(f"Ошибка удаления промокода: {e}")
        await callback.answer("❌ Ошибка удаления промокода")

# НЕДОСТАЮЩИЕ ОБРАБОТЧИКИ для управления товарами
@router.callback_query(F.data == "admin_manage_products")
async def admin_manage_products_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик управления товарами"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        categories = await _db.get_categories(active_only=False)
        all_products = []
        
        for category in categories:
            products = await _db.get_products(category['id'], active_only=False)
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

# НЕДОСТАЮЩИЕ ОБРАБОТЧИКИ для управления локациями
@router.callback_query(F.data == "admin_manage_locations")
async def admin_manage_locations_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик управления локациями"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        categories = await _db.get_categories(active_only=False)
        all_locations = []
        
        for category in categories:
            products = await _db.get_products(category['id'], active_only=False)
            for product in products:
                locations = await _db.get_locations(product['id'], active_only=False)
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

# Статистика для админов
@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик админской статистики"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        stats = await _db.get_stats()
        
        text = f"📊 *Детальная статистика*\n\n"
        text += f"📦 **Заказы:**\n"
        text += f"• Всего: {stats['total_orders']}\n"
        text += f"• Выполнено: {stats['completed_orders']}\n"
        text += f"• Ожидают: {stats['pending_orders']}\n\n"
        text += f"💰 **Финансы:**\n"
        text += f"• Общая выручка: {stats['total_revenue']:,.2f} ₽\n"
        text += f"• Сегодня: {stats['today_revenue']:,.2f} ₽\n\n"
        text += f"⭐ **Отзывы:**\n"
        text += f"• Всего отзывов: {stats['total_reviews']}\n"
        if stats['total_reviews'] > 0:
            text += f"• Средний рейтинг: {stats['avg_rating']:.1f}/5\n\n"
        text += f"📅 **Сегодня:**\n"
        text += f"• Новых заказов: {stats['today_orders']}"
        
        await callback.message.edit_text(text, reply_markup=create_back_to_admin_menu(), parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_stats_handler: {e}")
        await callback.answer("❌ Ошибка загрузки статистики")

# Просмотр отзывов
@router.callback_query(F.data == "admin_view_reviews")
async def admin_view_reviews_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик просмотра отзывов для админа"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        # Получаем последние отзывы
        async with _db.pool.acquire() as conn:
            reviews = await conn.fetch('''
                SELECT r.*, p.name as product_name, r.user_id
                FROM reviews r
                JOIN products p ON r.product_id = p.id
                ORDER BY r.created_at DESC
                LIMIT 20
            ''')
        
        if not reviews:
            text = "⭐ *Просмотр отзывов*\n\nОтзывов пока нет"
        else:
            text = f"⭐ *Последние отзывы* (показано {len(reviews)})\n\n"
            
            for i, review in enumerate(reviews, 1):
                stars = "⭐" * review['rating']
                user_masked = f"***{str(review['user_id'])[-3:]}"
                date = review['created_at'].strftime("%d.%m.%Y %H:%M")
                
                text += f"{i}. **{review['product_name']}**\n"
                text += f"{stars} от {user_masked} ({date})\n"
                if review['comment']:
                    text += f"💬 {review['comment']}\n"
                text += "\n"
        
        await state.set_state(AdminStates.VIEWING_REVIEWS)
        await callback.message.edit_text(text, reply_markup=create_back_to_admin_menu(), parse_mode='Markdown')
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_view_reviews_handler: {e}")
        await callback.answer("❌ Ошибка загрузки отзывов")

# Редактирование "О магазине"
@router.callback_query(F.data == "admin_edit_about")
async def admin_edit_about_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования информации о магазине"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        current_about = await _db.get_setting('about_text')
        
        await state.set_state(AdminStates.EDITING_ABOUT)
        await callback.message.edit_text(
            f"✏️ Редактирование \"О магазине\"\n\n"
            f"Текущий текст:\n{current_about}\n\n"
            f"Введите новый текст:"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_edit_about_handler: {e}")
        await callback.answer("❌ Ошибка загрузки текста")

@router.message(StateFilter(AdminStates.EDITING_ABOUT))
async def process_edit_about(message: Message, state: FSMContext):
    """Обработка редактирования информации о магазине"""
    try:
        new_about_text = message.text.strip()
        
        if not new_about_text:
            await message.answer("❌ Текст не может быть пустым")
            return
        
        await _db.set_setting('about_text', new_about_text)
        await message.answer("✅ Информация о магазине обновлена", reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} обновил информацию о магазине")
    except Exception as e:
        logger.error(f"Ошибка обновления информации о магазине: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# Добавление категории
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
        category_id = await _db.add_category(category_name)
        await message.answer(f"✅ Категория '{category_name}' добавлена (ID: {category_id})", 
                           reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} добавил категорию '{category_name}'")
    except Exception as e:
        logger.error(f"Ошибка добавления категории: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# Добавление товара
@router.callback_query(F.data == "admin_add_product")
async def admin_add_product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик добавления товара"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        categories = await _db.get_categories(active_only=False)
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
        
        product_id = await _db.add_product(category_id, name, description, price_rub)
        await message.answer(f"✅ Товар '{name}' добавлен (ID: {product_id})", 
                           reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} добавил товар '{name}'")
    except (ValueError, decimal.InvalidOperation):
        await message.answer("❌ Неверный формат цены")
    except Exception as e:
        logger.error(f"Ошибка добавления товара: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# Добавление локации
@router.callback_query(F.data == "admin_add_location")
async def admin_add_location_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик добавления локации"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        # Получаем все товары
        categories = await _db.get_categories(active_only=False)
        all_products = []
        
        for category in categories:
            products = await _db.get_products(category['id'], active_only=False)
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
        
        location_id = await _db.add_location(product_id, name, content_links)
        await message.answer(f"✅ Локация '{name}' добавлена с {len(content_links)} ссылками (ID: {location_id})", 
                           reply_markup=create_admin_menu())
        await state.set_state(AdminStates.ADMIN_MENU)
        logger.info(f"Админ {message.from_user.id} добавил локацию '{name}' с {len(content_links)} ссылками")
    except Exception as e:
        logger.error(f"Ошибка добавления локации: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# Управление категориями
@router.callback_query(F.data == "admin_manage_categories")
async def admin_manage_categories_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик управления категориями"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        categories = await _db.get_categories(active_only=False)
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
