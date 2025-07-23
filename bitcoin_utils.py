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
                            
                            btc_rate_cache['rate'] = rate
                            btc_rate_cache['timestamp'] = now
                            logger.info(f"Курс Bitcoin обновлен: {rate} RUB")
                            return rate
                except Exception as e:
                    logger.warning(f"Ошибка получения курса с {api_url}: {e}")
                    continue
                    
        raise Exception("Все API недоступны")
        
    except Exception as e:
        logger.error(f"Ошибка получения курса Bitcoin: {e}")
        # Если курс в кэше есть, используем его
        if btc_rate_cache['rate']:
            logger.info(f"Используем кэшированный курс: {btc_rate_cache['rate']}")
            return btc_rate_cache['rate']
        # Иначе используем fallback
        logger.warning("Используем fallback курс: 5000000 RUB")
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
        
        # Допустимая погрешность ±1 сатоши для учета особенностей сети
        tolerance = decimal.Decimal('0.00000001')  # 1 сатоши
        min_amount = amount - tolerance
        max_amount = amount + tolerance
        
        logger.info(f"💰 Диапазон принимаемых сумм: {min_amount} - {max_amount} BTC (±1 сатоши)")
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            url = f"https://blockchain.info/rawaddr/{address}?limit=50"
            logger.info(f"📡 Запрос к API: {url}")
            
            async with session.get(url) as resp:
                logger.info(f"📊 Статус ответа API: {resp.status}")
                
                if resp.status != 200:
                    logger.warning(f"❌ Blockchain API вернул статус {resp.status}")
                    return None
                    
                data = await resp.json()
                tx_count = len(data.get('txs', []))
                logger.info(f"📋 Получено транзакций: {tx_count}")
                
                # Конвертируем время создания заказа в Unix timestamp для сравнения
                order_timestamp = int(order_created_at.timestamp())
                logger.info(f"🕐 Timestamp заказа: {order_timestamp}")
                
                # Проверяем транзакции после создания заказа
                relevant_transactions = 0
                for i, tx in enumerate(data.get('txs', [])):
                    tx_hash = tx.get('hash')
                    tx_time = tx.get('time', 0)
                    
                    # Проверяем только транзакции после создания заказа
                    if tx_time <= order_timestamp:
                        logger.info(f"⏭️ Пропускаем старую транзакцию {i+1}: {tx_hash[:16]}... (время: {tx_time}, заказ: {order_timestamp})")
                        continue
                    
                    # Проверяем, не использовалась ли уже эта транзакция
                    if await db.is_transaction_used(tx_hash):
                        logger.info(f"♻️ Транзакция {tx_hash[:16]}... уже использована")
                        continue
                    
                    relevant_transactions += 1
                    logger.info(f"🔄 Проверка новой транзакции {relevant_transactions}: {tx_hash[:16]}... (время: {tx_time})")
                    
                    for j, output in enumerate(tx.get('out', [])):
                        output_addr = output.get('addr')
                        output_value = output.get('value', 0)
                        
                        if output_addr == address:
                            received_amount = decimal.Decimal(output_value) / 100000000
                            logger.info(f"💳 Найден платеж: {received_amount} BTC (требуется точно: {amount} BTC)")
                            
                            # Проверяем точное совпадение с допустимой погрешностью 1 сатоши
                            if min_amount <= received_amount <= max_amount:
                                logger.info(f"✅ ПЛАТЕЖ ПОДТВЕРЖДЕН! Сумма в допустимом диапазоне: {received_amount} BTC")
                                return tx_hash
                            elif received_amount < min_amount:
                                logger.info(f"❌ Сумма меньше требуемой: {received_amount} < {min_amount}")
                            else:
                                logger.info(f"❌ Сумма больше допустимой: {received_amount} > {max_amount}")
                
                logger.info(f"📊 Проверено новых транзакций: {relevant_transactions}")
                logger.info("❌ Платеж с точной суммой не найден среди новых транзакций")
                return None
                
    except Exception as e:
        logger.error(f"💥 Ошибка проверки платежа: {e}")
        return None
