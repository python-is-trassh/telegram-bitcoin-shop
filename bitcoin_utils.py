import decimal
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import logging

from config import BLOCKCHAIN_API_KEY, TEST_MODE

logger = logging.getLogger(__name__)

# Кэш для курса Bitcoin
btc_rate_cache = {'rate': None, 'timestamp': None}

async def get_btc_rate() -> decimal.Decimal:
    """Получение курса Bitcoin с кэшированием"""
    global btc_rate_cache
    
    now = datetime.now()
    if (btc_rate_cache['timestamp'] and 
        now - btc_rate_cache['timestamp'] < timedelta(minutes=5)):
        return btc_rate_cache['rate']
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            # Пробуем несколько API для получения курса
            apis = [
                'https://api.coindesk.com/v1/bpi/currentprice/RUB.json',
                'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=rub'
            ]
            
            for api_url in apis:
                try:
                    async with session.get(api_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            
                            if 'coindesk.com' in api_url:
                                rate = decimal.Decimal(str(data['bpi']['RUB']['rate_float']))
                            else:  # coingecko
                                rate = decimal.Decimal(str(data['bitcoin']['rub']))
                            
                            # ИСПРАВЛЕНИЕ: Валидация полученного курса
                            if rate <= 0:
                                logger.warning(f"Получен некорректный курс: {rate}")
                                continue
                                
                            btc_rate_cache['rate'] = rate
                            btc_rate_cache['timestamp'] = now
                            logger.info(f"Курс Bitcoin обновлен: {rate:,.2f} RUB")
                            return rate
                except Exception as e:
                    logger.warning(f"Ошибка получения курса с {api_url}: {e}")
                    continue
                    
        raise Exception("Все API недоступны")
        
    except Exception as e:
        logger.error(f"Ошибка получения курса Bitcoin: {e}")
        # Если курс в кэше есть, используем его
        if btc_rate_cache['rate']:
            logger.info(f"Используем кэшированный курс: {btc_rate_cache['rate']:,.2f}")
            return btc_rate_cache['rate']
        # Иначе используем fallback
        logger.warning("Используем fallback курс: 5,000,000 RUB")
        return decimal.Decimal('5000000')

async def check_bitcoin_payment(address: str, amount: decimal.Decimal, order_created_at: datetime, db) -> Optional[str]:
    """Проверка Bitcoin платежа с возвратом хеша транзакции"""
    try:
        # Тестовый режим для отладки
        if TEST_MODE:
            logger.info("🧪 ТЕСТОВЫЙ РЕЖИМ: платеж считается подтвержденным")
            return "test_transaction_hash"
        
        logger.info(f"🔍 Проверка платежа: адрес={address}, точная сумма={amount} BTC")
        logger.info(f"⏰ Время создания заказа: {order_created_at}")
        
        # ИСПРАВЛЕНИЕ: Уменьшена погрешность до минимума для предотвращения ложных срабатываний
        # Только 1 сатоши погрешность для учета особенностей сети Bitcoin
        tolerance = decimal.Decimal('0.00000001')  # 1 сатоши
        min_amount = amount - tolerance
        max_amount = amount + tolerance
        
        # ИСПРАВЛЕНИЕ: Дополнительная проверка на разумность суммы
        if amount <= decimal.Decimal('0.00000001'):  # Менее 1 сатоши
            logger.error(f"❌ Сумма слишком мала: {amount} BTC")
            return None
            
        if amount > decimal.Decimal('10'):  # Больше 10 BTC - подозрительно
            logger.warning(f"⚠️ Очень большая сумма: {amount} BTC")
        
        logger.info(f"💰 Диапазон принимаемых сумм: {min_amount:.8f} - {max_amount:.8f} BTC (±1 сатоши)")
        
        # ИСПРАВЛЕНИЕ: Добавлен retry механизм для API
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                    url = f"https://blockchain.info/rawaddr/{address}?limit=50"
                    logger.info(f"📡 Запрос к API (попытка {attempt + 1}): {url}")
                    
                    async with session.get(url) as resp:
                        logger.info(f"📊 Статус ответа API: {resp.status}")
                        
                        if resp.status == 429:  # Rate limit
                            wait_time = 2 ** attempt  # Exponential backoff
                            logger.warning(f"⏸️ Rate limit, ждем {wait_time} секунд...")
                            await asyncio.sleep(wait_time)
                            continue
                            
                        if resp.status != 200:
                            logger.warning(f"❌ Blockchain API вернул статус {resp.status}")
                            if attempt == max_retries - 1:
                                return None
                            await asyncio.sleep(1)
                            continue
                            
                        data = await resp.json()
                        
                        # ИСПРАВЛЕНИЕ: Валидация ответа API
                        if not isinstance(data, dict) or 'txs' not in data:
                            logger.error("❌ Некорректный ответ от API")
                            continue
                            
                        tx_count = len(data.get('txs', []))
                        logger.info(f"📋 Получено транзакций: {tx_count}")
                        
                        if tx_count == 0:
                            logger.info("📭 Нет транзакций на адресе")
                            return None
                        
                        # Конвертируем время создания заказа в Unix timestamp для сравнения
                        order_timestamp = int(order_created_at.timestamp())
                        logger.info(f"🕐 Timestamp заказа: {order_timestamp}")
                        
                        # Проверяем транзакции после создания заказа
                        relevant_transactions = 0
                        for i, tx in enumerate(data.get('txs', [])):
                            tx_hash = tx.get('hash')
                            tx_time = tx.get('time', 0)
                            
                            # ИСПРАВЛЕНИЕ: Дополнительная валидация транзакции
                            if not tx_hash or not isinstance(tx_hash, str):
                                logger.warning(f"⚠️ Транзакция {i+1} имеет некорректный хеш")
                                continue
                                
                            # Проверяем только транзакции после создания заказа
                            # ИСПРАВЛЕНИЕ: Добавлен небольшой буфер времени (30 секунд) на случай рассинхронизации часов
                            time_buffer = 30
                            if tx_time <= (order_timestamp - time_buffer):
                                logger.info(f"⏭️ Пропускаем старую транзакцию {i+1}: {tx_hash[:16]}... (время: {tx_time}, заказ: {order_timestamp})")
                                continue
                            
                            # Проверяем, не использовалась ли уже эта транзакция
                            if await db.is_transaction_used(tx_hash):
                                logger.info(f"♻️ Транзакция {tx_hash[:16]}... уже использована")
                                continue
                            
                            relevant_transactions += 1
                            logger.info(f"🔄 Проверка новой транзакции {relevant_transactions}: {tx_hash[:16]}... (время: {tx_time})")
                            
                            # ИСПРАВЛЕНИЕ: Дополнительная валидация outputs
                            if not isinstance(tx.get('out'), list):
                                logger.warning(f"⚠️ Транзакция {tx_hash[:16]}... имеет некорректные outputs")
                                continue
                            
                            for j, output in enumerate(tx.get('out', [])):
                                output_addr = output.get('addr')
                                output_value = output.get('value', 0)
                                
                                # ИСПРАВЛЕНИЕ: Валидация output данных
                                if not output_addr or not isinstance(output_value, (int, float)):
                                    logger.warning(f"⚠️ Некорректные данные в output {j}")
                                    continue
                                
                                if output_addr == address:
                                    received_amount = decimal.Decimal(output_value) / 100000000
                                    logger.info(f"💳 Найден платеж: {received_amount:.8f} BTC (требуется: {amount:.8f} BTC)")
                                    
                                    # Проверяем точное совпадение с допустимой погрешностью 1 сатоши
                                    if min_amount <= received_amount <= max_amount:
                                        logger.info(f"✅ ПЛАТЕЖ ПОДТВЕРЖДЕН! Сумма в допустимом диапазоне: {received_amount:.8f} BTC")
                                        return tx_hash
                                    elif received_amount < min_amount:
                                        diff = min_amount - received_amount
                                        logger.info(f"❌ Сумма меньше требуемой на {diff:.8f} BTC ({diff * 100000000:.0f} сатоши)")
                                    else:
                                        diff = received_amount - max_amount
                                        logger.info(f"❌ Сумма больше допустимой на {diff:.8f} BTC ({diff * 100000000:.0f} сатоши)")
                        
                        logger.info(f"📊 Проверено новых транзакций: {relevant_transactions}")
                        if relevant_transactions == 0:
                            logger.info("❌ Нет новых транзакций после создания заказа")
                        else:
                            logger.info("❌ Платеж с точной суммой не найден среди новых транзакций")
                        return None
                        
            except aiohttp.ClientError as e:
                logger.error(f"💥 Ошибка сети при попытке {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return None
                await asyncio.sleep(2 ** attempt)
            except asyncio.TimeoutError:
                logger.error(f"⏰ Таймаут при попытке {attempt + 1}")
                if attempt == max_retries - 1:
                    return None
                await asyncio.sleep(2 ** attempt)
                
        logger.error("💥 Все попытки исчерпаны")
        return None
                
    except Exception as e:
        logger.error(f"💥 Критическая ошибка проверки платежа: {e}")
        return None
