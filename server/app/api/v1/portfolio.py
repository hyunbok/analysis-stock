"""포트폴리오/자산 조회 API 엔드포인트."""
from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.deps import CurrentUser, PortfolioServiceDep
from app.schemas.common import ApiResponse
from app.schemas.portfolio import ExchangePortfolioResponse, PortfolioSummaryResponse

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# ── OpenAPI 응답 예시 ───────────────────────────────────────────────────────────

_SUMMARY_EXAMPLE = {
    "data": {
        "total_balance_krw": "15234500.00",
        "total_pnl_amount": "234500.00",
        "total_pnl_ratio": "1.56",
        "total_trade_count": 42,
        "ai_pnl_amount": None,
        "ai_pnl_ratio": None,
        "ai_trade_count": 28,
        "manual_pnl_amount": None,
        "manual_pnl_ratio": None,
        "manual_trade_count": 14,
        "by_exchange": [
            {
                "exchange_account_id": "550e8400-e29b-41d4-a716-446655440000",
                "exchange_type": "upbit",
                "nickname": "내 업비트",
                "balance_krw": "10234500.00",
                "pnl_amount": "134500.00",
                "pnl_ratio": "1.33",
            }
        ],
        "top_coins": [
            {
                "symbol": "BTC/KRW",
                "exchange_type": "upbit",
                "quantity": "0.05000000",
                "avg_price": "85000000.00",
                "current_price": "87500000.00",
                "pnl_amount": "125000.00",
            }
        ],
        "cached_at": "2026-03-15T10:30:00Z",
    },
    "error": None,
    "meta": {"timestamp": "2026-03-15T10:30:00Z"},
}

# 도넛 차트 데이터 소스: coins[].weight_percent
# 각 코인의 weight_percent = coin_value_krw / total_balance_krw * 100
# KRW 현금 슬라이스는 클라이언트에서 krw_balance / total_balance_krw * 100 으로 계산
# 도넛 렌더링: coins[].weight_percent 슬라이스 + KRW 암묵 슬라이스 = 합계 100%
_EXCHANGE_EXAMPLE = {
    "data": {
        "exchange_account_id": "550e8400-e29b-41d4-a716-446655440000",
        "exchange_type": "upbit",
        "nickname": "내 업비트",
        "total_balance_krw": "10234500.00",
        "krw_balance": "500000.00",
        "coins": [
            {
                "symbol": "BTC/KRW",
                "currency": "BTC",
                "quantity": "0.05000000",
                "available": "0.04500000",
                "locked": "0.00500000",
                "avg_entry_price": "85000000.00",
                "current_price": "87500000.00",
                "value_krw": "4375000.00",
                "pnl_amount": "125000.00",
                "pnl_ratio": "2.94",
                # weight_percent = 4375000 / 10234500 * 100 ≈ 42.75
                # KRW 암묵 비중 = 500000 / 10234500 * 100 ≈ 4.89
                # 클라이언트: BTC슬라이스(42.75) + ETH슬라이스(...) + KRW슬라이스(4.89) = 100%
                "weight_percent": "42.75",
            },
            {
                "symbol": "ETH/KRW",
                "currency": "ETH",
                "quantity": "2.00000000",
                "available": "2.00000000",
                "locked": "0.00000000",
                "avg_entry_price": "2500000.00",
                "current_price": "2679750.00",
                "value_krw": "5359500.00",
                "pnl_amount": "359500.00",
                "pnl_ratio": "7.19",
                # weight_percent = 5359500 / 10234500 * 100 ≈ 52.37
                "weight_percent": "52.37",
            },
        ],
        "balance_fetched_at": "2026-03-15T10:29:55Z",
        "cached_at": None,
    },
    "error": None,
    "meta": {"timestamp": "2026-03-15T10:30:00Z"},
}


@router.get(
    "",
    response_model=ApiResponse[PortfolioSummaryResponse],
    openapi_extra={"responses": {"200": {"content": {"application/json": {"example": _SUMMARY_EXAMPLE}}}}},
)
async def get_portfolio_summary(
    current_user: CurrentUser,
    service: PortfolioServiceDep,
) -> ApiResponse[PortfolioSummaryResponse]:
    """전체 자산 요약 조회.

    모든 등록된 거래소 계정의 자산을 합산하여 반환한다.
    Redis 캐시 HIT 시 즉시 반환 (TTL 5분), MISS 시 실시간 조회.

    Returns:
        total_balance_krw: 전 거래소 합산 원화 환산 총자산
        total_pnl_amount: 합산 미실현 평가손익
        total_pnl_ratio: 합산 수익률 %
        by_exchange: 거래소별 breakdown
        top_coins: 보유 가치 기준 상위 5개 코인 (value_krw 내림차순)
        cached_at: 캐시 저장 시각 (None = 실시간)
    """
    data = await service.get_portfolio_summary(current_user.id)
    return ApiResponse(data=data)


@router.get(
    "/{exchange_account_id}",
    response_model=ApiResponse[ExchangePortfolioResponse],
    openapi_extra={"responses": {"200": {"content": {"application/json": {"example": _EXCHANGE_EXAMPLE}}}}},
)
async def get_exchange_portfolio(
    exchange_account_id: uuid.UUID,
    current_user: CurrentUser,
    service: PortfolioServiceDep,
) -> ApiResponse[ExchangePortfolioResponse]:
    """거래소별 상세 포트폴리오 조회.

    지정된 거래소 계정의 보유 자산, 평균 매입가, PnL, 비중을 반환한다.
    Redis 캐시 HIT 시 즉시 반환 (TTL 1분), MISS 시 실시간 조회.

    ### 도넛 차트 데이터 소스 (`weight_percent`)

    - `coins[].weight_percent` = `coin_value_krw / total_balance_krw * 100` (소수점 2자리)
    - `current_price` 없는 코인 → `weight_percent = None` (차트 제외)
    - `total_balance_krw == 0` → 모든 코인 `weight_percent = None`
    - KRW 현금은 `krw_balance`로 별도 제공. 클라이언트에서 슬라이스 추가:
      `krw_weight = krw_balance / total_balance_krw * 100`
    - 전체 슬라이스 합계: `sum(coins[].weight_percent) + krw_weight ≈ 100%`

    **Flutter 소비 패턴 예시:**
    ```dart
    final coinSlices = coins
        .where((c) => c.weightPercent != null)
        .map((c) => DonutSlice(label: c.symbol, value: c.weightPercent!.toDouble()))
        .toList();
    if (krwBalance != null && totalBalanceKrw != null && totalBalanceKrw > 0) {
      final krwWeight = krwBalance / totalBalanceKrw * 100;
      coinSlices.add(DonutSlice(label: 'KRW', value: krwWeight.toDouble()));
    }
    ```

    Args:
        exchange_account_id: 조회할 거래소 계정 UUID.

    Returns:
        coins: 코인별 보유 현황 (KRW 제외, weight_percent 포함)
        krw_balance: KRW 현금 잔고
        total_balance_krw: 원화 환산 총자산 (KRW + 코인)

    Raises:
        404 EXCHANGE_ACCOUNT_NOT_FOUND: 계정 존재하지 않음.
        403 PORTFOLIO_EXCHANGE_ACCOUNT_NOT_OWNED: 타 사용자 소유 계정.
        503 PORTFOLIO_BALANCE_FETCH_FAILED: 거래소 잔고 조회 실패.
    """
    data = await service.get_exchange_portfolio(current_user.id, exchange_account_id)
    return ApiResponse(data=data)
