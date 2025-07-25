import asyncpg
import decimal
from datetime import datetime
from typing import Dict, List, Optional
from config import logger

class DatabaseManager:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None
    
    async def init_pool(self):
        """Инициализация пула соединений"""
        try:
            self.pool = await asyncpg.create_pool(
                self.db_url,
                min_size=1,
                max_size=10,
                command_timeout=60
            )
            await self.create_tables()
            logger.info("База данных инициализирована")
        except Exception as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            raise
    
    async def create_tables(self):
        """Создание всех необходимых таблиц"""
        async with self.pool.acquire() as conn:
            # Создаем таблицы с правильными типами данных и foreign key constraints
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    description TEXT DEFAULT '',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT DEFAULT '',
                    price_rub DECIMAL(10,2) NOT NULL CHECK (price_rub > 0),
                    rating DECIMAL(3,2) DEFAULT 0.00 CHECK (rating >= 0 AND rating <= 5),
                    review_count INTEGER DEFAULT 0 CHECK (review_count >= 0),
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS locations (
                    id SERIAL PRIMARY KEY,
                    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    content_links TEXT[] NOT NULL CHECK (array_length(content_links, 1) > 0),
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                    location_id INTEGER REFERENCES locations(id) ON DELETE CASCADE,
                    price_rub DECIMAL(10,2) NOT NULL CHECK (price_rub > 0),
                    price_btc DECIMAL(16,8) NOT NULL CHECK (price_btc > 0),
                    btc_rate DECIMAL(12,2) NOT NULL CHECK (btc_rate > 0),
                    bitcoin_address VARCHAR(255) NOT NULL,
                    payment_amount DECIMAL(16,8) NOT NULL CHECK (payment_amount > 0),
                    promo_code VARCHAR(50),
                    discount_amount DECIMAL(10,2) DEFAULT 0 CHECK (discount_amount >= 0),
                    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled', 'expired')),
                    content_link TEXT,
                    transaction_hash VARCHAR(64),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP + INTERVAL '30 minutes',
                    completed_at TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS used_links (
                    id SERIAL PRIMARY KEY,
                    location_id INTEGER REFERENCES locations(id) ON DELETE CASCADE,
                    link TEXT NOT NULL,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(location_id, link)
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS used_transactions (
                    id SERIAL PRIMARY KEY,
                    transaction_hash VARCHAR(64) NOT NULL UNIQUE,
                    order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
                    amount DECIMAL(16,8) NOT NULL CHECK (amount > 0),
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS reviews (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                    order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
                    rating INTEGER CHECK (rating >= 1 AND rating <= 5) NOT NULL,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(order_id)
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS promo_codes (
                    id SERIAL PRIMARY KEY,
                    code VARCHAR(50) NOT NULL UNIQUE,
                    discount_type VARCHAR(20) CHECK (discount_type IN ('percent', 'fixed')) NOT NULL,
                    discount_value DECIMAL(10,2) NOT NULL CHECK (discount_value > 0),
                    min_order_amount DECIMAL(10,2) DEFAULT 0 CHECK (min_order_amount >= 0),
                    max_uses INTEGER DEFAULT 0 CHECK (max_uses >= 0),
                    current_uses INTEGER DEFAULT 0 CHECK (current_uses >= 0),
                    expires_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS promo_usage (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    promo_code_id INTEGER REFERENCES promo_codes(id) ON DELETE CASCADE,
                    order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, promo_code_id)
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Создаем индексы для производительности
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_reviews_product_id ON reviews(product_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_used_transactions_hash ON used_transactions(transaction_hash)')
            
            # Вставка настроек по умолчанию
            await conn.execute('''
                INSERT INTO settings (key, value) VALUES 
                ('about_text', 'Добро пожаловать в наш магазин! Мы продаем цифровые товары за Bitcoin.'),
                ('welcome_message', 'Здравствуйте! Добро пожаловать в наш магазин.')
                ON CONFLICT (key) DO NOTHING
            ''')
    
    async def get_categories(self, active_only: bool = True) -> List[Dict]:
        """Получение списка категорий"""
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM categories"
            if active_only:
                query += " WHERE is_active = TRUE"
            query += " ORDER BY name"
            
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]
    
    async def get_category(self, category_id: int) -> Optional[Dict]:
        """Получение категории по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM categories WHERE id = $1", category_id)
            return dict(row) if row else None
    
    async def get_products(self, category_id: int, active_only: bool = True) -> List[Dict]:
        """Получение товаров категории с проверкой наличия ссылок"""
        async with self.pool.acquire() as conn:
            query = '''
                SELECT p.*, 
                       COALESCE(available_links.count, 0) as available_links_count
                FROM products p
                LEFT JOIN (
                    SELECT l.product_id, 
                           SUM(GREATEST(array_length(l.content_links, 1) - COALESCE(used_count.count, 0), 0)) as count
                    FROM locations l
                    LEFT JOIN (
                        SELECT location_id, COUNT(*) as count
                        FROM used_links
                        GROUP BY location_id
                    ) used_count ON l.id = used_count.location_id
                    WHERE l.is_active = TRUE
                    GROUP BY l.product_id
                ) available_links ON p.id = available_links.product_id
                WHERE p.category_id = $1
            '''
            
            if active_only:
                query += " AND p.is_active = TRUE AND COALESCE(available_links.count, 0) > 0"
            
            query += " ORDER BY p.name"
            
            rows = await conn.fetch(query, category_id)
            return [dict(row) for row in rows]
    
    async def get_product(self, product_id: int) -> Optional[Dict]:
        """Получение товара по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
            return dict(row) if row else None
    
    async def get_locations(self, product_id: int, active_only: bool = True) -> List[Dict]:
        """Получение локаций товара с проверкой наличия ссылок"""
        async with self.pool.acquire() as conn:
            query = '''
                SELECT l.*, 
                       GREATEST(array_length(l.content_links, 1) - COALESCE(used_count.count, 0), 0) as available_links_count
                FROM locations l
                LEFT JOIN (
                    SELECT location_id, COUNT(*) as count
                    FROM used_links
                    GROUP BY location_id
                ) used_count ON l.id = used_count.location_id
                WHERE l.product_id = $1
            '''
            
            if active_only:
                query += " AND l.is_active = TRUE AND GREATEST(array_length(l.content_links, 1) - COALESCE(used_count.count, 0), 0) > 0"
            
            query += " ORDER BY l.name"
            
            rows = await conn.fetch(query, product_id)
            return [dict(row) for row in rows]
    
    async def get_location(self, location_id: int) -> Optional[Dict]:
        """Получение локации по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM locations WHERE id = $1", location_id)
            return dict(row) if row else None
    
    async def validate_promo_code(self, code: str, order_amount: decimal.Decimal, user_id: int) -> Optional[Dict]:
        """Проверка промокода"""
        async with self.pool.acquire() as conn:
            # Получаем информацию о промокоде
            promo = await conn.fetchrow('''
                SELECT * FROM promo_codes 
                WHERE code = $1 AND is_active = TRUE
                AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                AND (max_uses = 0 OR current_uses < max_uses)
                AND min_order_amount <= $2
            ''', code, order_amount)
            
            if not promo:
                return None
            
            # Проверяем, использовал ли пользователь уже этот промокод
            usage = await conn.fetchrow('''
                SELECT 1 FROM promo_usage 
                WHERE user_id = $1 AND promo_code_id = $2
            ''', user_id, promo['id'])
            
            if usage:
                return None
            
            return dict(promo)
    
    async def apply_promo_code(self, promo_id: int, user_id: int, order_id: int):
        """Применение промокода"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Проверяем, что промокод еще можно использовать
                promo = await conn.fetchrow('''
                    SELECT max_uses, current_uses FROM promo_codes 
                    WHERE id = $1 AND is_active = TRUE
                ''', promo_id)
                
                if not promo:
                    raise ValueError("Промокод недействителен")
                
                if promo['max_uses'] > 0 and promo['current_uses'] >= promo['max_uses']:
                    raise ValueError("Промокод исчерпан")
                
                # Проверяем, не использовал ли уже пользователь этот промокод
                existing_usage = await conn.fetchval('''
                    SELECT 1 FROM promo_usage 
                    WHERE user_id = $1 AND promo_code_id = $2
                ''', user_id, promo_id)
                
                if existing_usage:
                    raise ValueError("Промокод уже использован")
                
                # Добавляем запись об использовании
                await conn.execute('''
                    INSERT INTO promo_usage (user_id, promo_code_id, order_id)
                    VALUES ($1, $2, $3)
                ''', user_id, promo_id, order_id)
                
                # Увеличиваем счетчик использований
                await conn.execute('''
                    UPDATE promo_codes SET current_uses = current_uses + 1
                    WHERE id = $1
                ''', promo_id)
    
    async def calculate_discount(self, promo: Dict, amount: decimal.Decimal) -> decimal.Decimal:
        """Расчет скидки"""
        if promo['discount_type'] == 'percent':
            discount = amount * (promo['discount_value'] / 100)
        else:  # fixed
            discount = promo['discount_value']
        
        # Скидка не может быть больше суммы заказа
        return min(discount, amount)
    
    async def create_order(self, user_id: int, product_id: int, location_id: int, 
                          price_rub: decimal.Decimal, price_btc: decimal.Decimal, 
                          btc_rate: decimal.Decimal, payment_amount: decimal.Decimal,
                          promo_code: str = None, discount_amount: decimal.Decimal = 0) -> int:
        """Создание заказа"""
        from config import BITCOIN_ADDRESS
        async with self.pool.acquire() as conn:
            # Проверяем существование товара и локации
            product_exists = await conn.fetchval(
                "SELECT 1 FROM products WHERE id = $1 AND is_active = TRUE", product_id
            )
            if not product_exists:
                raise ValueError("Товар не найден или неактивен")
            
            location_exists = await conn.fetchval(
                "SELECT 1 FROM locations WHERE id = $1 AND is_active = TRUE", location_id
            )
            if not location_exists:
                raise ValueError("Локация не найдена или неактивна")
            
            order_id = await conn.fetchval('''
                INSERT INTO orders (user_id, product_id, location_id, price_rub, 
                                  price_btc, btc_rate, bitcoin_address, payment_amount,
                                  promo_code, discount_amount)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
            ''', user_id, product_id, location_id, price_rub, price_btc, 
                btc_rate, BITCOIN_ADDRESS, payment_amount, promo_code, discount_amount)
            return order_id
    
    async def get_order(self, order_id: int) -> Optional[Dict]:
        """Получение заказа"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
            return dict(row) if row else None
    
    async def complete_order(self, order_id: int, content_link: str, transaction_hash: str = None):
        """Завершение заказа"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE orders SET status = 'completed', content_link = $2, 
                       transaction_hash = $3, completed_at = CURRENT_TIMESTAMP
                WHERE id = $1 AND status = 'pending'
            ''', order_id, content_link, transaction_hash)
    
    async def get_available_link(self, location_id: int) -> Optional[str]:
        """Получение доступной ссылки из локации"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Получаем все ссылки локации
                location = await conn.fetchrow(
                    "SELECT content_links FROM locations WHERE id = $1 AND is_active = TRUE", location_id
                )
                if not location or not location['content_links']:
                    return None
                
                # Получаем использованные ссылки
                used_links = await conn.fetch(
                    "SELECT link FROM used_links WHERE location_id = $1", location_id
                )
                used_set = {row['link'] for row in used_links}
                
                # Находим первую неиспользованную ссылку
                for link in location['content_links']:
                    if link not in used_set:
                        # Помечаем как использованную
                        await conn.execute(
                            "INSERT INTO used_links (location_id, link) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                            location_id, link
                        )
                        return link
                
                return None
    
    async def is_transaction_used(self, tx_hash: str) -> bool:
        """Проверка, использовалась ли уже транзакция"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT 1 FROM used_transactions WHERE transaction_hash = $1", tx_hash
            )
            return result is not None
    
    async def mark_transaction_used(self, tx_hash: str, order_id: int, amount: decimal.Decimal):
        """Отметить транзакцию как использованную"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO used_transactions (transaction_hash, order_id, amount)
                VALUES ($1, $2, $3)
                ON CONFLICT (transaction_hash) DO NOTHING
            ''', tx_hash, order_id, amount)
    
    async def get_user_history(self, user_id: int) -> List[Dict]:
        """Получение истории покупок пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT o.*, p.name as product_name, l.name as location_name,
                       r.rating as user_rating, r.comment as user_review
                FROM orders o
                JOIN products p ON o.product_id = p.id
                JOIN locations l ON o.location_id = l.id
                LEFT JOIN reviews r ON o.id = r.order_id
                WHERE o.user_id = $1 AND o.status = 'completed'
                ORDER BY o.completed_at DESC
            ''', user_id)
            return [dict(row) for row in rows]
    
    async def can_review_order(self, user_id: int, order_id: int) -> bool:
        """Проверка, может ли пользователь оставить отзыв"""
        async with self.pool.acquire() as conn:
            # Проверяем, что заказ принадлежит пользователю и выполнен
            order = await conn.fetchrow('''
                SELECT 1 FROM orders 
                WHERE id = $1 AND user_id = $2 AND status = 'completed'
            ''', order_id, user_id)
            
            if not order:
                return False
            
            # Проверяем, что отзыв еще не оставлен
            review = await conn.fetchval(
                "SELECT 1 FROM reviews WHERE order_id = $1", order_id
            )
            
            return review is None
    
    async def add_review(self, user_id: int, product_id: int, order_id: int, 
                        rating: int, comment: str):
        """Добавление отзыва"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Проверяем, что отзыв можно оставить
                can_review = await self.can_review_order(user_id, order_id)
                if not can_review:
                    raise ValueError("Нельзя оставить отзыв на этот заказ")
                
                # Добавляем отзыв
                await conn.execute('''
                    INSERT INTO reviews (user_id, product_id, order_id, rating, comment)
                    VALUES ($1, $2, $3, $4, $5)
                ''', user_id, product_id, order_id, rating, comment)
                
                # Обновляем рейтинг товара
                await conn.execute('''
                    UPDATE products SET 
                        rating = (SELECT AVG(rating)::DECIMAL(3,2) FROM reviews WHERE product_id = $1),
                        review_count = (SELECT COUNT(*) FROM reviews WHERE product_id = $1)
                    WHERE id = $1
                ''', product_id)
    
    async def get_product_reviews(self, product_id: int, limit: int = 10) -> List[Dict]:
        """Получение отзывов о товаре"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT r.rating, r.comment, r.created_at, r.user_id
                FROM reviews r
                WHERE r.product_id = $1
                ORDER BY r.created_at DESC
                LIMIT $2
            ''', product_id, limit)
            return [dict(row) for row in rows]
    
    # Методы управления промокодами
    async def add_promo_code(self, code: str, discount_type: str, discount_value: decimal.Decimal,
                           min_order_amount: decimal.Decimal = 0, max_uses: int = 0,
                           expires_at: datetime = None) -> int:
        """Добавление промокода"""
        async with self.pool.acquire() as conn:
            # Проверяем уникальность кода
            existing = await conn.fetchval("SELECT 1 FROM promo_codes WHERE code = $1", code)
            if existing:
                raise ValueError("Промокод с таким кодом уже существует")
            
            return await conn.fetchval('''
                INSERT INTO promo_codes (code, discount_type, discount_value, 
                                       min_order_amount, max_uses, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            ''', code, discount_type, discount_value, min_order_amount, max_uses, expires_at)
    
    async def get_promo_codes(self, active_only: bool = True) -> List[Dict]:
        """Получение списка промокодов"""
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM promo_codes"
            if active_only:
                query += " WHERE is_active = TRUE"
            query += " ORDER BY created_at DESC"
            
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]
    
    async def deactivate_promo_code(self, promo_id: int):
        """Деактивация промокода"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE promo_codes SET is_active = FALSE WHERE id = $1", promo_id
            )
    
    # CRUD операции для категорий
    async def add_category(self, name: str, description: str = "") -> int:
        """Добавление категории"""
        async with self.pool.acquire() as conn:
            try:
                return await conn.fetchval(
                    "INSERT INTO categories (name, description) VALUES ($1, $2) RETURNING id",
                    name, description
                )
            except asyncpg.UniqueViolationError:
                raise ValueError("Категория с таким названием уже существует")
    
    async def update_category(self, category_id: int, name: str, description: str):
        """Обновление категории"""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute(
                    "UPDATE categories SET name = $2, description = $3 WHERE id = $1",
                    category_id, name, description
                )
                if result == "UPDATE 0":
                    raise ValueError("Категория не найдена")
            except asyncpg.UniqueViolationError:
                raise ValueError("Категория с таким названием уже существует")
    
    async def delete_category(self, category_id: int) -> bool:
        """Удаление категории с проверкой связанных заказов"""
        async with self.pool.acquire() as conn:
            # Проверяем есть ли заказы на товары из этой категории
            orders_count = await conn.fetchval('''
                SELECT COUNT(*) FROM orders o
                JOIN products p ON o.product_id = p.id
                WHERE p.category_id = $1
            ''', category_id)
            
            if orders_count > 0:
                # Если есть заказы, делаем мягкое удаление
                await conn.execute(
                    "UPDATE categories SET is_active = FALSE WHERE id = $1",
                    category_id
                )
                # Также деактивируем все товары в категории
                await conn.execute('''
                    UPDATE products SET is_active = FALSE 
                    WHERE category_id = $1
                ''', category_id)
                return False  # Мягкое удаление
            else:
                # Если нет заказов, делаем физическое удаление
                result = await conn.execute("DELETE FROM categories WHERE id = $1", category_id)
                if result == "DELETE 0":
                    raise ValueError("Категория не найдена")
                return True  # Физическое удаление
    
    # CRUD операции для товаров
    async def add_product(self, category_id: int, name: str, description: str, price_rub: decimal.Decimal) -> int:
        """Добавление товара"""
        async with self.pool.acquire() as conn:
            # Проверяем существование категории
            category_exists = await conn.fetchval(
                "SELECT 1 FROM categories WHERE id = $1 AND is_active = TRUE", category_id
            )
            if not category_exists:
                raise ValueError("Категория не найдена или неактивна")
            
            return await conn.fetchval(
                "INSERT INTO products (category_id, name, description, price_rub) VALUES ($1, $2, $3, $4) RETURNING id",
                category_id, name, description, price_rub
            )
    
    async def update_product(self, product_id: int, name: str, description: str, price_rub: decimal.Decimal):
        """Обновление товара"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE products SET name = $2, description = $3, price_rub = $4 WHERE id = $1",
                product_id, name, description, price_rub
            )
            if result == "UPDATE 0":
                raise ValueError("Товар не найден")
    
    async def delete_product(self, product_id: int) -> bool:
        """Удаление товара с проверкой связанных заказов"""
        async with self.pool.acquire() as conn:
            # Проверяем есть ли заказы на этот товар
            orders_count = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE product_id = $1",
                product_id
            )
            
            if orders_count > 0:
                # Если есть заказы, делаем мягкое удаление
                await conn.execute(
                    "UPDATE products SET is_active = FALSE WHERE id = $1",
                    product_id
                )
                # Также деактивируем все локации товара
                await conn.execute(
                    "UPDATE locations SET is_active = FALSE WHERE product_id = $1",
                    product_id
                )
                return False  # Мягкое удаление
            else:
                # Если нет заказов, делаем физическое удаление
                result = await conn.execute("DELETE FROM products WHERE id = $1", product_id)
                if result == "DELETE 0":
                    raise ValueError("Товар не найден")
                return True  # Физическое удаление
    
    # CRUD операции для локаций
    async def add_location(self, product_id: int, name: str, content_links: List[str]) -> int:
        """Добавление локации"""
        async with self.pool.acquire() as conn:
            # Проверяем существование товара
            product_exists = await conn.fetchval(
                "SELECT 1 FROM products WHERE id = $1 AND is_active = TRUE", product_id
            )
            if not product_exists:
                raise ValueError("Товар не найден или неактивен")
            
            # Проверяем, что ссылки не пустые
            if not content_links or not all(link.strip() for link in content_links):
                raise ValueError("Все ссылки должны быть непустыми")
            
            return await conn.fetchval(
                "INSERT INTO locations (product_id, name, content_links) VALUES ($1, $2, $3) RETURNING id",
                product_id, name, content_links
            )
    
    async def update_location(self, location_id: int, name: str, content_links: List[str]):
        """Обновление локации"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Проверяем, что ссылки не пустые
                if not content_links or not all(link.strip() for link in content_links):
                    raise ValueError("Все ссылки должны быть непустыми")
                
                # Сначала очищаем старые использованные ссылки для этой локации
                await conn.execute("DELETE FROM used_links WHERE location_id = $1", location_id)
                
                # Затем обновляем локацию
                result = await conn.execute(
                    "UPDATE locations SET name = $2, content_links = $3 WHERE id = $1",
                    location_id, name, content_links
                )
                if result == "UPDATE 0":
                    raise ValueError("Локация не найдена")
    
    async def delete_location(self, location_id: int) -> bool:
        """Удаление локации с проверкой связанных заказов"""
        async with self.pool.acquire() as conn:
            # Проверяем есть ли заказы на эту локацию
            orders_count = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE location_id = $1",
                location_id
            )
            
            if orders_count > 0:
                # Если есть заказы, делаем мягкое удаление
                await conn.execute(
                    "UPDATE locations SET is_active = FALSE WHERE id = $1",
                    location_id
                )
                return False  # Мягкое удаление
            else:
                # Если нет заказов, делаем физическое удаление (CASCADE удалит used_links)
                result = await conn.execute("DELETE FROM locations WHERE id = $1", location_id)
                if result == "DELETE 0":
                    raise ValueError("Локация не найдена")
                return True  # Физическое удаление
    
    # Настройки
    async def get_setting(self, key: str) -> str:
        """Получение настройки"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM settings WHERE key = $1", key)
            return row['value'] if row else ""
    
    async def set_setting(self, key: str, value: str):
        """Установка настройки"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = CURRENT_TIMESTAMP
            ''', key, value)
    
    # Статистика
    async def get_stats(self) -> Dict:
        """Получение статистики"""
        async with self.pool.acquire() as conn:
            stats = {}
            
            # Общая статистика
            stats['total_orders'] = await conn.fetchval("SELECT COUNT(*) FROM orders") or 0
            stats['completed_orders'] = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'completed'") or 0
            stats['pending_orders'] = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'pending'") or 0
            stats['total_revenue'] = await conn.fetchval("SELECT COALESCE(SUM(price_rub - discount_amount), 0) FROM orders WHERE status = 'completed'") or 0
            stats['total_reviews'] = await conn.fetchval("SELECT COUNT(*) FROM reviews") or 0
            
            avg_rating = await conn.fetchval("SELECT AVG(rating) FROM reviews")
            stats['avg_rating'] = float(avg_rating) if avg_rating else 0
            
            # Статистика за сегодня
            today = datetime.now().date()
            stats['today_orders'] = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE DATE(created_at) = $1", today
            ) or 0
            stats['today_revenue'] = await conn.fetchval(
                "SELECT COALESCE(SUM(price_rub - discount_amount), 0) FROM orders WHERE DATE(created_at) = $1 AND status = 'completed'", 
                today
            ) or 0
            
            return stats
