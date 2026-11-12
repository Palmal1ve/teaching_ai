from celery import Celery

from app.core.config import get_settings

celery = Celery("course", broker=get_settings().redis_url, include=["app.pipeline.runner"])
celery.conf.update(
    task_default_queue="ai",
    task_acks_late=False,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "sweep": {"task": "sweep", "schedule": 30.0},
        "nightly_graph_sweep": {"task": "sweep_graph", "schedule": 24 * 3600.0},
    },
)
