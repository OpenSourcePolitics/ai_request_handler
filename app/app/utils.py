import requests
import redis
import time
from .models import Host


def increase_spam_count(h: Host, r: redis.Redis, spam_limit: int, spam_period_limit: int) -> tuple:
    """Increase the host spam count and returns true if limit exceeded"""
    period_key, total_key = h.redis_keys()

    now = int(time.time())
    window_start = now - spam_period_limit

    pipe = r.pipeline(transaction=True)
    # Remove outdated records
    pipe.zremrangebyscore(period_key, 0, window_start)

    pipe.zadd(period_key, {str(now): now})
    pipe.zcard(period_key)
    pipe.incr(total_key)
    pipe.expire(period_key, spam_period_limit + 5)
    _, _, current, total, _ = pipe.execute()

    return current, total, current > spam_limit


def send_webhook_notification(h: Host, webhook: tuple, r: redis.Redis, **kwargs) -> None:
    """Send webhook notification"""
    limit = kwargs.get("limit")
    current = kwargs.get("current")
    total_count = kwargs.get("total_count")
    webhook_url, webhook_auth_name, webhook_auth_token = webhook

    payload = {'host': h.host, "limit": limit, "current": current, "total": total_count}
    requests.post(webhook_url,
                  json=payload,
                  headers={"Content-Type": "application/json", webhook_auth_name: webhook_auth_token})
    r.delete(h.period_redis_key())
