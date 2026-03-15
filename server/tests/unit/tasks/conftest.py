"""Celery 태스크 테스트 공통 fixtures."""
import pytest


@pytest.fixture
def celery_config():
    """Celery task_always_eager 설정 — 태스크를 동기 직접 실행."""
    return {
        "task_always_eager": True,
        "task_eager_propagates": True,
    }
