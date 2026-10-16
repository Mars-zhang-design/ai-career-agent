"""Optional Redis progress summaries, not graph checkpoints or resume storage."""
import json
import logging
import os
import redis

logger = logging.getLogger(__name__)


def client():
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                                decode_responses=True, socket_timeout=1, socket_connect_timeout=1)


def save_summary(user_id, state):
    if user_id is None:
        return
    summary = {"task_id": state["task_id"], "status": state["status"],
               "steps": state["step_count"], "record_id": state.get("record_id"),
               "trace": state.get("trace", [])}
    try:
        client().set(f"agent:{user_id}:{state['task_id']}", json.dumps(summary), ex=600)
    except redis.RedisError:
        logger.warning("task_store_unavailable task=%s", state["task_id"])


def get_summary(user_id, task_id):
    value = client().get(f"agent:{user_id}:{task_id}")
    return json.loads(value) if value else None
