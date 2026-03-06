"""통합 테스트용 conftest — MongoDB document 모듈 mock (Pydantic v2 호환성 우회)."""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


def _mock_mongodb_modules() -> None:
    """MongoDB document 모델 모듈을 sys.modules에 mock으로 등록.

    app.core.mongodb → app.documents 를 import할 때 발생하는
    bson.Decimal128 / Beanie Indexed(UUID) 의 Pydantic v2 비호환 문제를 우회한다.
    각 서브모듈을 명시적으로 등록해야 'is not a package' 오류를 방지할 수 있다.
    """
    if "app.documents" in sys.modules:
        return  # 이미 로드된 경우 skip

    _AuditLog = MagicMock()
    _TradeLog = MagicMock()
    _AiDecision = MagicMock()
    _DailyPnlReport = MagicMock()
    _Notification = MagicMock()
    _NewsData = MagicMock()

    # ── 서브모듈 ────────────────────────────────────────────────────────────

    def _submodule(name: str, **attrs: object) -> ModuleType:
        mod = ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        return mod

    sys.modules["app.documents.audit_logs"] = _submodule(
        "app.documents.audit_logs", AuditLog=_AuditLog
    )
    sys.modules["app.documents.trading_logs"] = _submodule(
        "app.documents.trading_logs",
        TradeLog=_TradeLog,
        AiDecision=_AiDecision,
        DailyPnlReport=_DailyPnlReport,
    )
    sys.modules["app.documents.notifications"] = _submodule(
        "app.documents.notifications", Notification=_Notification
    )
    sys.modules["app.documents.news_data"] = _submodule(
        "app.documents.news_data", NewsData=_NewsData
    )

    # ── app.documents 패키지 ──────────────────────────────────────────────

    documents_mod = _submodule(
        "app.documents",
        AuditLog=_AuditLog,
        TradeLog=_TradeLog,
        AiDecision=_AiDecision,
        DailyPnlReport=_DailyPnlReport,
        Notification=_Notification,
        NewsData=_NewsData,
        init_timeseries_collections=MagicMock(),
    )
    # 서브모듈 속성도 설정 (from app.documents import xxx 대응)
    documents_mod.audit_logs = sys.modules["app.documents.audit_logs"]
    documents_mod.trading_logs = sys.modules["app.documents.trading_logs"]
    documents_mod.notifications = sys.modules["app.documents.notifications"]
    documents_mod.news_data = sys.modules["app.documents.news_data"]
    sys.modules["app.documents"] = documents_mod

    # ── app.core.mongodb (get_mongodb DI 팩토리용) ────────────────────────
    mongodb_mod = _submodule(
        "app.core.mongodb",
        get_mongodb=MagicMock(return_value=MagicMock()),
        init_mongodb=MagicMock(),
        close_mongodb=MagicMock(),
        get_mongo_client=MagicMock(),
        ALL_DOCUMENT_MODELS=[],
    )
    sys.modules["app.core.mongodb"] = mongodb_mod


_mock_mongodb_modules()
