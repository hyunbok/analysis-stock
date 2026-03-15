"""뉴스 수집 + GPT 감성 분석 태스크.

Beat(1시간) → scrape_news()
"""
import asyncio
import logging

from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from .context import TaskContext

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.news_scraper.scrape_news",
    max_retries=2,
    default_retry_delay=60,          # 1분 후 재시도
    queue="scraper",
    soft_time_limit=540,             # 9분
    time_limit=600,                  # 10분
)
def scrape_news(self, symbols: list[str] | None = None) -> dict:
    """뉴스 수집 + GPT 감성 분석.

    Flow:
      1. 활성 코인 목록 조회 (symbols=None이면 DB에서 전체)
      2. 외부 뉴스 API (CryptoPanic / NewsAPI) 크롤링
      3. NewsData Document insert (URL 중복 시 skip — unique index)
      4. GPT 감성 분석 → sentiment_score 업데이트
      5. AICacheService.set_news_sentiment() → Redis 캐시

    Args:
        symbols: 특정 심볼 리스트 (None이면 전체 활성 코인)

    Returns:
        {"scraped": int, "duplicates": int, "sentiment_updated": int, "failed": int}
    """
    from app.core.config import settings
    if not settings.NEWS_SCRAPER_ENABLED:
        return {"scraped": 0, "duplicates": 0, "sentiment_updated": 0, "failed": 0,
                "reason": "disabled"}

    try:
        return asyncio.run(_scrape_news_async(self, symbols))
    except SoftTimeLimitExceeded:
        logger.error("News scraper timed out")
        return {"scraped": 0, "duplicates": 0, "sentiment_updated": 0, "failed": 0,
                "reason": "timeout"}
    except Exception as exc:
        logger.exception("News scraper failed")
        raise self.retry(exc=exc)


async def _scrape_news_async(task, symbols: list[str] | None) -> dict:
    """scrape_news async 구현.

    v1-19 범위: 스캐폴딩 + 인터페이스만.
    실제 뉴스 소스 크롤러 및 GPT 감성 분석은 별도 태스크(v2)에서 구현.
    """
    ctx = await TaskContext.get()

    from app.core.pubsub import RedisPublisher
    from app.services.ai_cache_service import AICacheService
    publisher = RedisPublisher(ctx.redis)
    ai_cache = AICacheService(ctx.redis, publisher)  # noqa: F841

    # TODO: 뉴스 소스별 크롤링 로직 (CryptoPanic, NewsAPI, RSS)
    # TODO: GPT 감성 분석 배치 호출
    # TODO: NewsData.insert_many() + 중복 필터링
    # TODO: ai_cache.set_news_sentiment() 코인별 갱신

    logger.info("News scraper: stub completed (no sources configured)")
    return {"scraped": 0, "duplicates": 0, "sentiment_updated": 0, "failed": 0}
