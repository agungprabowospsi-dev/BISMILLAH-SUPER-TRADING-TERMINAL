import os
import redis.asyncio as redis
import logging

logger = logging.getLogger(__name__)

_redis_client = None

async def init_redis():
    global _redis_client
    _redis_client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await _redis_client.ping()
    logger.info("✅ Redis connected")

def get_redis():
    return _redis_client

async def cache_get(key: str):
    try:
        return await _redis_client.get(key)
    except:
        return None

async def cache_set(key: str, value: str, ttl: int = 300):
    try:
        await _redis_client.setex(key, ttl, value)
    except:
        pass

async def cache_delete(key: str):
    try:
        await _redis_client.delete(key)
    except:
        pass
