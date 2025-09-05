import json
import logging
import os
import time
import uuid
from typing import Optional
from uuid import uuid4
import redis
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .models import Host

_engine: Optional[Engine] = None

def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL") or os.getenv("PG_DSN")
        if not url:
            raise RuntimeError("DATABASE_URL (or PG_DSN) is not set")
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            future=True,
        )
    return _engine

def sql_alchemy_execute(sql: str, params: dict):
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(sql), params)


def _insert_model_call_pg(
    *,
    host: str,
    content_type: str,
    provider: str,
    model: str,
    latency_ms: int,
    status: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    cost: float | None,
    tags: list[str],
    metadata: dict,
    input: str | None,
    output: str | None,
):
    try:
        payload_meta = {
            "metadata": metadata or {},
            "output": output,
        }
        sql = """
        INSERT INTO public.model_calls
        (id, ts, host, content_type, provider, model,
         latency_ms, status, input_tokens, output_tokens, total_tokens,
         cost, tags, metadata, input, output)
        VALUES (:id, now(), :host, :content_type, :provider, :model,
                :latency_ms, :status, :input_tokens, :output_tokens, :total_tokens,
                :cost, :tags, CAST(:metadata AS JSONB),:input, :output)
        """
        params = {
            "id": str(uuid.uuid4()),
            "host": host,
            "content_type": content_type,
            "provider": provider,
            "model": model,
            "latency_ms": latency_ms,
            "status": status,
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost": cost,
            "tags": tags or [],
            "metadata": json.dumps(payload_meta, ensure_ascii=False),
            "input": input,
            "output": output,
        }
        sql_alchemy_execute(sql, params)
    except Exception:
        logging.exception("PG insert failed")


def increase_spam_count(h: Host, r: redis.Redis, spam_limit: int, spam_period_limit: int) -> tuple:
    """Increase the host spam count and returns true if limit exceeded"""
    period_key, total_key = h.redis_keys()

    now = int(time.time())
    window_start = now - spam_period_limit

    pipe = r.pipeline(transaction=True)
    # Remove outdated records
    pipe.zremrangebyscore(period_key, 0, window_start)

    member = f"{now}:{uuid4().hex}"
    pipe.zadd(period_key, {member: now})

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
