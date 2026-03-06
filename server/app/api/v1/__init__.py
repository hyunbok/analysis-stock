from fastapi import APIRouter

from app.api.v1.health import router as health_router

router = APIRouter()

router.include_router(health_router, tags=["health"])

# Routers will be included here as they are implemented:
# from app.api.v1 import auth, users, exchanges, orders, wallets, auto_trading, market
# router.include_router(auth.router, prefix="/auth", tags=["auth"])
# router.include_router(users.router, prefix="/users", tags=["users"])
# router.include_router(exchanges.router, prefix="/exchanges", tags=["exchanges"])
# router.include_router(orders.router, prefix="/orders", tags=["orders"])
# router.include_router(wallets.router, prefix="/wallets", tags=["wallets"])
# router.include_router(auto_trading.router, prefix="/auto-trading", tags=["auto-trading"])
# router.include_router(market.router, prefix="/market", tags=["market"])
