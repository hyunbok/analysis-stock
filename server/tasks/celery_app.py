"""Celery 앱 설정 + Beat 스케줄 + 큐 라우팅.

실행 명령:
  Worker: celery -A tasks.celery_app.celery_app worker -l info -c 4 -Q ai,scraper,default
  Beat:   celery -A tasks.celery_app.celery_app beat -l info --scheduler celery.beat.PersistentScheduler
"""
from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import settings

# ── Celery 앱 초기화 ──────────────────────────────────────────────────────────

celery_app = Celery("cointrader")

celery_app.conf.update(
    # Broker / Result Backend (Redis DB 분리)
    broker_url=settings.celery_broker_url,          # DB 1
    result_backend=settings.celery_result_backend,   # DB 2

    # 직렬화
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # 큐 정의 (kombu Queue)
    task_queues=[
        Queue("ai"),
        Queue("scraper"),
        Queue("default"),
    ],
    task_default_queue="default",

    # 태스크 라우팅
    task_routes={
        "tasks.ai_trading.*":     {"queue": "ai"},
        "tasks.news_scraper.*":   {"queue": "scraper"},
        "tasks.reports.*":        {"queue": "default"},
        "tasks.cleanup.*":        {"queue": "default"},
    },

    # Beat 스케줄
    beat_schedule={
        "run-all-active-configs-every-5min": {
            "task": "tasks.ai_trading.run_all_active_configs",
            "schedule": 300.0,                          # 5분 (300초)
            "options": {"queue": "ai"},
        },
        "scrape-news-hourly": {
            "task": "tasks.news_scraper.scrape_news",
            "schedule": 3600.0,                         # 1시간
            "options": {"queue": "scraper"},
        },
        "generate-daily-pnl-reports": {
            "task": "tasks.reports.generate_daily_pnl_reports",
            "schedule": crontab(minute=5, hour=0),      # 매일 00:05 UTC
            "options": {"queue": "default"},
        },
        "cleanup-expired-tokens-daily": {
            "task": "tasks.cleanup.cleanup_expired_tokens",
            "schedule": crontab(minute=0, hour=3),      # 매일 03:00 UTC
            "options": {"queue": "default"},
        },
    },

    # Worker 설정
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,  # 기본 4
    worker_prefetch_multiplier=1,           # 공정 분배 (긴 태스크 대비)
    worker_max_tasks_per_child=100,         # 메모리 누수 방지 (주기적 child 교체)
    worker_max_memory_per_child=512_000,    # 512MB 제한

    # 태스크 기본 타임아웃
    task_soft_time_limit=240,               # 4분 (soft — SoftTimeLimitExceeded 발생)
    task_time_limit=300,                    # 5분 (hard kill)

    # 안정성
    task_acks_late=True,                    # 실행 완료 후 ACK (worker 크래시 시 재실행)
    task_reject_on_worker_lost=True,        # worker 비정상 종료 시 재큐잉
    worker_send_task_events=True,           # 모니터링용 이벤트 전송
    task_send_sent_event=True,

    # Result backend
    result_expires=3600,                    # 1시간 후 결과 만료
)

# ── 태스크 모듈 자동 탐색 ──────────────────────────────────────────────────────

celery_app.autodiscover_tasks(["tasks"])
