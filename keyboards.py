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

def create_back_to_main_menu() -> InlineKeyboardMarkup:
    """Создание кнопки возврата в главное меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
    return builder.as_markup()
