from typing import List, Dict
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import ADMIN_IDS

def create_main_menu() -> InlineKeyboardMarkup:
    """Создание главного меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🛍 Каталог", callback_data="categories"))
    builder.add(InlineKeyboardButton(text="📋 Мои покупки", callback_data="user_history"))
    builder.add(InlineKeyboardButton(text="🎟️ Промокод", callback_data="enter_promo"))
    builder.add(InlineKeyboardButton(text="ℹ️ О магазине", callback_data="about"))
    builder.add(InlineKeyboardButton(text="₿ Курс Bitcoin", callback_data="btc_rate"))
    if ADMIN_IDS:
        builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="stats"))
    builder.adjust(2, 2, 1, 1)
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
        rating_stars = "⭐" * int(product.get('rating', 0)) if product.get('rating', 0) > 0 else ""
        review_text = f" ({product.get('review_count', 0)} отз.)" if product.get('review_count', 0) > 0 else ""
        
        builder.add(InlineKeyboardButton(
            text=f"{product['name']} - {product['price_rub']} ₽ {rating_stars}{review_text}",
            callback_data=f"product_{product['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 К категориям", callback_data="categories"))
    builder.adjust(1)
    return builder.as_markup()

def create_product_detail_menu(product_id: int, has_locations: bool, has_reviews: bool) -> InlineKeyboardMarkup:
    """Создание меню просмотра товара"""
    builder = InlineKeyboardBuilder()
    
    if has_locations:
        builder.add(InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy_product_{product_id}"))
    
    if has_reviews:
        builder.add(InlineKeyboardButton(text="⭐ Отзывы", callback_data=f"product_reviews_{product_id}"))
    
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="categories"))
    builder.adjust(2 if has_locations and has_reviews else 1)
    return builder.as_markup()

def create_locations_menu(locations: List[Dict], product_id: int) -> InlineKeyboardMarkup:
    """Создание меню локаций"""
    builder = InlineKeyboardBuilder()
    for location in locations:
        available_count = location.get('available_links_count', 0)
        builder.add(InlineKeyboardButton(
            text=f"{location['name']} ({available_count} в наличии)",
            callback_data=f"location_{location['id']}"
        ))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"product_{product_id}"))
    builder.adjust(1)
    return builder.as_markup()

def create_review_menu(order_id: int) -> InlineKeyboardMarkup:
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

def create_admin_menu() -> InlineKeyboardMarkup:
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

def create_manage_categories_menu(categories: List[Dict]) -> InlineKeyboardMarkup:
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

def create_manage_products_menu(products: List[Dict]) -> InlineKeyboardMarkup:
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

def create_manage_locations_menu(locations: List[Dict]) -> InlineKeyboardMarkup:
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

def create_manage_promos_menu(promos: List[Dict]) -> InlineKeyboardMarkup:
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

def create_back_to_admin_menu() -> InlineKeyboardMarkup:
    """Создание кнопки возврата в админ меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Админ меню", callback_data="admin_menu"))
    return builder.as_markup()

def create_back_to_main_menu() -> InlineKeyboardMarkup:
    """Создание кнопки возврата в главное меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
    return builder.as_markup()
