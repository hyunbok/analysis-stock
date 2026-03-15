"""뉴스 스크랩 태스크 단위 테스트."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def reset_task_context():
    import tasks.context as ctx_module
    ctx_module._task_context = None
    yield
    ctx_module._task_context = None


class TestNewsScraper:
    """scrape_news 태스크 검증."""

    def test_feature_flag_disabled_returns_early(self):
        """NEWS_SCRAPER_ENABLED=False 시 즉시 반환."""
        from tasks.news_scraper import scrape_news

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.NEWS_SCRAPER_ENABLED = False
            result = scrape_news.run()

        assert result["scraped"] == 0
        assert result["reason"] == "disabled"

    @pytest.mark.anyio
    async def test_stub_returns_zero_counts(self):
        """스텁 구현은 모든 카운트 0 반환."""
        from tasks.news_scraper import _scrape_news_async

        mock_ctx = MagicMock()
        mock_ctx.redis = MagicMock()  # RedisPublisher는 redis 인자만 전달받음

        with patch("tasks.news_scraper.TaskContext") as mock_ctx_cls:
            mock_ctx_cls.get = AsyncMock(return_value=mock_ctx)
            mock_task = MagicMock()
            result = await _scrape_news_async(mock_task, None)

        assert result["scraped"] == 0
        assert result["duplicates"] == 0
        assert result["sentiment_updated"] == 0
        assert result["failed"] == 0

    def test_task_name(self):
        from tasks.news_scraper import scrape_news
        assert scrape_news.name == "tasks.news_scraper.scrape_news"

    def test_task_queue(self):
        from tasks.news_scraper import scrape_news
        assert scrape_news.queue == "scraper"

    def test_task_max_retries(self):
        from tasks.news_scraper import scrape_news
        assert scrape_news.max_retries == 2
