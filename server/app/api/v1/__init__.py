from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.coins import router as coins_router
from app.api.v1.exchanges import router as exchanges_router
from app.api.v1.health import router as health_router
from app.api.v1.social_auth import router as social_auth_router
from app.api.v1.users import router as users_router
from app.api.v1.watchlist import router as watchlist_router

router = APIRouter()

router.include_router(health_router, tags=["health"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(social_auth_router, prefix="/auth/social", tags=["auth:social"])
router.include_router(users_router, prefix="/users", tags=["users"])
router.include_router(exchanges_router, prefix="/exchanges", tags=["exchanges"])
router.include_router(coins_router, prefix="/coins", tags=["coins"])
router.include_router(watchlist_router, prefix="/watchlist", tags=["watchlist"])

# Routers will be included here as they are implemented:
# from app.api.v1 import orders, wallets, auto_trading, market
# router.include_router(orders.router, prefix="/orders", tags=["orders"])
# router.include_router(wallets.router, prefix="/wallets", tags=["wallets"])
# router.include_router(auto_trading.router, prefix="/auto-trading", tags=["auto-trading"])
# router.include_router(market.router, prefix="/market", tags=["market"])
