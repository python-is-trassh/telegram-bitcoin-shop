import decimal
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from states import AdminStates
from config import ADMIN_IDS, logger
# ИСПРАВЛЕНИЕ: Импортируем только необходимые функции клавиатур из admin_handlers
from admin_handlers import (
    create_admin_menu, create_manage_categories_menu, 
    create_manage_products_menu, create_manage_locations_menu
)

router = Router()

# Глобальные переменные для доступа к db и bot
_db = None
_bot = None

def setup_edit_handlers(db, bot):
    """Инициализация обработчиков редактирования"""
    global _db, _bot
    _db = db
    _bot = bot

# ИСПРАВЛЕНИЕ: Убраны дублирующиеся функции клавиатур (они импортируются из admin_handlers)

# РЕДАКТИРОВАНИЕ КАТЕГОРИЙ
@router.callback_query(F.data.startswith("admin_edit_category_"))
async def admin_edit_category_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования категории"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        category_id = int(callback.data.split("_")[3])
        category = await _db.get_category(category_id)
        
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
        
        await _db.update_category(category_id, name, description)
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
        category = await _db.get_category(category_id)
        
        if not category:
            await callback.answer("❌ Категория не найдена")
            return
        
        # Пробуем удалить категорию
        is_physical_delete = await _db.delete_category(category_id)
        
        if is_physical_delete:
            await callback.answer(f"✅ Категория '{category['name']}' полностью удалена")
            logger.info(f"Админ {callback.from_user.id} физически удалил категорию {category_id}")
        else:
            await callback.answer(f"⚠️ Категория '{category['name']}' деактивирована (есть связанные заказы)")
            logger.info(f"Админ {callback.from_user.id} деактивировал категорию {category_id}")
        
        # Обновляем список
        categories = await _db.get_categories(active_only=False)
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

# РЕДАКТИРОВАНИЕ ТОВАРОВ
@router.callback_query(F.data.startswith("admin_edit_product_"))
async def admin_edit_product_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования товара"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        product_id = int(callback.data.split("_")[3])
        product = await _db.get_product(product_id)
        
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
        
        await _db.update_product(product_id, name, description, price_rub)
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
        product = await _db.get_product(product_id)
        
        if not product:
            await callback.answer("❌ Товар не найден")
            return
        
        # Пробуем удалить товар
        is_physical_delete = await _db.delete_product(product_id)
        
        if is_physical_delete:
            await callback.answer(f"✅ Товар '{product['name']}' полностью удален")
            logger.info(f"Админ {callback.from_user.id} физически удалил товар {product_id}")
        else:
            await callback.answer(f"⚠️ Товар '{product['name']}' деактивирован (есть связанные заказы)")
            logger.info(f"Админ {callback.from_user.id} деактивировал товар {product_id}")
        
        # Обновляем список
        categories = await _db.get_categories(active_only=False)
        all_products = []
        
        for category in categories:
            products = await _db.get_products(category['id'], active_only=False)
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

# РЕДАКТИРОВАНИЕ ЛОКАЦИЙ
@router.callback_query(F.data.startswith("admin_edit_location_"))
async def admin_edit_location_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования локации"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет прав")
        return
    
    try:
        location_id = int(callback.data.split("_")[3])
        location = await _db.get_location(location_id)
        
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
        
        await _db.update_location(location_id, name, content_links)
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
        location = await _db.get_location(location_id)
        
        if not location:
            await callback.answer("❌ Локация не найдена")
            return
        
        # Пробуем удалить локацию
        is_physical_delete = await _db.delete_location(location_id)
        
        if is_physical_delete:
            await callback.answer(f"✅ Локация '{location['name']}' полностью удалена")
            logger.info(f"Админ {callback.from_user.id} физически удалил локацию {location_id}")
        else:
            await callback.answer(f"⚠️ Локация '{location['name']}' деактивирована (есть связанные заказы)")
            logger.info(f"Админ {callback.from_user.id} деактивировал локацию {location_id}")
        
        # Обновляем список
        categories = await _db.get_categories(active_only=False)
        all_locations = []
        
        for category in categories:
            products = await _db.get_products(category['id'], active_only=False)
            for product in products:
                locations = await _db.get_locations(product['id'], active_only=False)
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
