"""앱 버전 엔드포인트 — 클라이언트 최소 버전 요구사항 및 강제 업데이트 여부 제공."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class AppVersionResponse(BaseModel):
    server_version: str
    min_client_version: str
    force_update: bool
    update_message: str | None


@router.get(
    "/app-version",
    response_model=AppVersionResponse,
    summary="앱 버전 정보 조회",
    description="서버 버전 및 클라이언트 최소 요구 버전을 반환합니다.",
)
async def get_app_version() -> AppVersionResponse:
    return AppVersionResponse(
        server_version="0.1.0",
        min_client_version="1.0.0",
        force_update=False,
        update_message=None,
    )
