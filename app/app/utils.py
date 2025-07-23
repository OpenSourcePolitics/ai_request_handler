import requests
import redis
from .models import Host


def increase_spam_count(h: Host, r: redis.Redis, spam_limit: int, spam_period_limit: int) -> True | False:
    """Increase the host spam count and send webhook request"""
    r.incr(h.total_redis_key())
    if r.get(h.period_redis_key()) is None:
        r.set(h.period_redis_key(), 1)
        r.expire(h.period_redis_key(), spam_period_limit)
    else:
        r.incr(h.period_redis_key())

    current_period_count = int(r.get(h.period_redis_key()))
    return current_period_count > spam_limit


def send_webhook_notification(h: Host, webhook: tuple, r: redis.Redis, **kwargs) -> True | False:
    """Send webhook notification"""
    limit = kwargs.get("limit")
    total_count = kwargs.get("total_count")
    webhook_url, webhook_auth_name, webhook_auth_token = webhook

    payload = {'host': h.host, "limit": limit, "total": total_count}
    requests.post(webhook_url,
                  json=payload,
                  headers={"Content-Type": "application/json", webhook_auth_name: webhook_auth_token})
    r.delete(h.period_redis_key())
