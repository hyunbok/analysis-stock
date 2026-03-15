"""포트폴리오/자산 조회 API 스키마."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# -- 내부 데이터 타입 (서비스 계층) -----------------------------------------------


class AvgEntryPrice(BaseModel):
    """코인별 평균 매입가 + 총 매수 수량."""

    avg_price: Decimal
    total_buy_quantity: Decimal


class TradeCounts(BaseModel):
    """거래 횟수 통계."""

    total: int
    ai_count: int
    manual_count: int


# -- 응답 서브 모델 ---------------------------------------------------------------


class CoinHolding(BaseModel):
    """단일 코인 보유 현황."""

    symbol: str                         # e.g. "BTC/KRW"
    currency: str                       # e.g. "BTC" — Balance.currency 그대로
    quantity: Decimal                   # 총 보유 수량 (available + locked)
    available: Decimal                  # 사용 가능
    locked: Decimal                     # 주문 잠금
    avg_entry_price: Decimal | None     # 체결 주문 없으면 None (외부 입금)
    current_price: Decimal | None       # Redis ticker 없으면 None
    value_krw: Decimal | None           # current_price * quantity
    pnl_amount: Decimal | None          # 미실현 평가손익
    pnl_ratio: Decimal | None           # 수익률 % (e.g. 2.94 = +2.94%)
    weight_percent: Decimal | None      # 총자산 대비 비중 0.0~100.0, 소수점 2자리


class ExchangeSummary(BaseModel):
    """거래소별 요약 (by_exchange 항목)."""

    exchange_account_id: uuid.UUID
    exchange_type: str                  # "upbit" | "coinone"
    nickname: str | None                # UserExchangeAccount.nickname 그대로
    balance_krw: Decimal | None         # 원화 환산 총자산
    pnl_amount: Decimal | None
    pnl_ratio: Decimal | None


class TopCoin(BaseModel):
    """전체 포트폴리오 상위 코인 (top_coins 항목)."""

    symbol: str                         # "BTC/KRW" — CoinResponse.symbol 패턴
    exchange_type: str
    quantity: Decimal
    avg_price: Decimal | None
    current_price: Decimal | None
    pnl_amount: Decimal | None


# -- 메인 응답 스키마 -------------------------------------------------------------


class PortfolioSummaryResponse(BaseModel):
    """GET /api/v1/portfolio 응답."""

    total_balance_krw: Decimal | None       # 전 거래소 합산 원화 환산 총자산
    total_pnl_amount: Decimal | None        # 합산 평가손익
    total_pnl_ratio: Decimal | None         # 합산 수익률 %
    total_trade_count: int                  # 전체 체결 주문 수
    # AI 매매 통계
    ai_pnl_amount: Decimal | None
    ai_pnl_ratio: Decimal | None
    ai_trade_count: int
    # 수동 매매 통계
    manual_pnl_amount: Decimal | None
    manual_pnl_ratio: Decimal | None
    manual_trade_count: int
    # 거래소별 breakdown
    by_exchange: list[ExchangeSummary]
    # 상위 5 코인
    top_coins: list[TopCoin] = Field(default_factory=list, max_length=5)
    # 메타
    cached_at: datetime | None              # None = 실시간 계산


class ExchangePortfolioResponse(BaseModel):
    """GET /api/v1/portfolio/{exchange_account_id} 응답."""

    exchange_account_id: uuid.UUID
    exchange_type: str
    nickname: str | None                    # UserExchangeAccount.nickname
    total_balance_krw: Decimal | None
    krw_balance: Decimal | None             # KRW 현금 잔고 (별도 표시)
    coins: list[CoinHolding]               # KRW 제외한 코인만 (KRW는 krw_balance 필드로)
    balance_fetched_at: datetime | None    # 거래소 잔고 조회 시각
    cached_at: datetime | None
