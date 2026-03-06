from datetime import datetime, UTC
from typing import Optional

import pymongo
from beanie import Document
from pydantic import Field


class NewsData(Document):
    coin_symbols: list[str]  # Multiple coins may be relevant
    source: str
    title: str
    content: Optional[str] = None
    url: str
    published_at: datetime
    sentiment_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    embedding_vector: Optional[list[float]] = None  # 384 or 768 dimensions
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "news_data"
        indexes = [
            pymongo.IndexModel([("coin_symbols", pymongo.ASCENDING)]),
            pymongo.IndexModel([("published_at", pymongo.DESCENDING)]),
            pymongo.IndexModel([("url", pymongo.ASCENDING)], unique=True),
        ]
