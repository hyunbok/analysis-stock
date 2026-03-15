"""Celery 앱 설정 검증 단위 테스트."""
import pytest

from tasks.celery_app import celery_app


class TestCeleryAppConfig:
    """Celery 앱 설정값 검증."""

    def test_app_name(self):
        assert celery_app.main == "cointrader"

    def test_task_queues(self):
        queue_names = {q.name for q in celery_app.conf.task_queues}
        assert queue_names == {"ai", "scraper", "default"}

    def test_default_queue(self):
        assert celery_app.conf.task_default_queue == "default"

    def test_task_serializer(self):
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.result_serializer == "json"
        assert "json" in celery_app.conf.accept_content

    def test_timezone_utc(self):
        assert celery_app.conf.timezone == "UTC"
        assert celery_app.conf.enable_utc is True

    def test_task_acks_late(self):
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.task_reject_on_worker_lost is True

    def test_worker_prefetch_multiplier(self):
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_worker_max_tasks_per_child(self):
        assert celery_app.conf.worker_max_tasks_per_child == 100

    def test_task_time_limits(self):
        assert celery_app.conf.task_soft_time_limit == 240
        assert celery_app.conf.task_time_limit == 300

    def test_result_expires(self):
        assert celery_app.conf.result_expires == 3600


class TestBeatSchedule:
    """Beat 스케줄 설정 검증."""

    def test_ai_trading_schedule_exists(self):
        schedule = celery_app.conf.beat_schedule
        assert "run-all-active-configs-every-5min" in schedule

    def test_ai_trading_schedule_interval(self):
        entry = celery_app.conf.beat_schedule["run-all-active-configs-every-5min"]
        assert entry["task"] == "tasks.ai_trading.run_all_active_configs"
        assert entry["schedule"] == 300.0
        assert entry["options"]["queue"] == "ai"

    def test_news_scraper_schedule_exists(self):
        schedule = celery_app.conf.beat_schedule
        assert "scrape-news-hourly" in schedule

    def test_news_scraper_interval(self):
        entry = celery_app.conf.beat_schedule["scrape-news-hourly"]
        assert entry["task"] == "tasks.news_scraper.scrape_news"
        assert entry["schedule"] == 3600.0
        assert entry["options"]["queue"] == "scraper"

    def test_pnl_report_schedule_exists(self):
        schedule = celery_app.conf.beat_schedule
        assert "generate-daily-pnl-reports" in schedule

    def test_pnl_report_queue(self):
        entry = celery_app.conf.beat_schedule["generate-daily-pnl-reports"]
        assert entry["task"] == "tasks.reports.generate_daily_pnl_reports"
        assert entry["options"]["queue"] == "default"

    def test_cleanup_schedule_exists(self):
        schedule = celery_app.conf.beat_schedule
        assert "cleanup-expired-tokens-daily" in schedule

    def test_cleanup_queue(self):
        entry = celery_app.conf.beat_schedule["cleanup-expired-tokens-daily"]
        assert entry["task"] == "tasks.cleanup.cleanup_expired_tokens"
        assert entry["options"]["queue"] == "default"


class TestTaskRouting:
    """태스크 라우팅 설정 검증."""

    def test_ai_trading_routes_to_ai_queue(self):
        routes = celery_app.conf.task_routes
        assert routes["tasks.ai_trading.*"]["queue"] == "ai"

    def test_news_scraper_routes_to_scraper_queue(self):
        routes = celery_app.conf.task_routes
        assert routes["tasks.news_scraper.*"]["queue"] == "scraper"

    def test_reports_routes_to_default_queue(self):
        routes = celery_app.conf.task_routes
        assert routes["tasks.reports.*"]["queue"] == "default"

    def test_cleanup_routes_to_default_queue(self):
        routes = celery_app.conf.task_routes
        assert routes["tasks.cleanup.*"]["queue"] == "default"
