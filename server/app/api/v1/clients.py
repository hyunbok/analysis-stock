"""Client(기기 세션) API — FCM 토큰 등록/목록/삭제."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request, Response, status

from app.core.deps import ClientRepoDep, CurrentUser, DbSession
from app.core.exceptions import ClientErrors
from app.schemas.client import ClientListResponse, ClientRegisterRequest, ClientResponse
from app.schemas.common import ApiResponse

router = APIRouter()


def _to_response(client) -> ClientResponse:
    return ClientResponse(
        client_id=client.id,
        device_type=client.device_type,
        device_name=client.device_name,
        fcm_token=client.fcm_token,
        is_active=client.is_active,
        created_at=client.created_at,
        last_active_at=client.last_active_at,
    )


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    summary="FCM 토큰 등록/갱신 (upsert)",
)
async def register_client(
    body: ClientRegisterRequest,
    request: Request,
    response: Response,
    current_user: CurrentUser,
    client_repo: ClientRepoDep,
    db: DbSession,
    x_device_fingerprint: str | None = Header(default=None, alias="X-Device-Fingerprint"),
) -> ApiResponse[ClientResponse]:
    """FCM 토큰 등록/갱신.

    - X-Device-Fingerprint 헤더가 있으면 기존 Client 조회 → 갱신(200).
    - 없거나 미존재 시 신규 생성(201).
    """
    user_agent = request.headers.get("User-Agent")
    ip_address = request.client.host if request.client else None

    if x_device_fingerprint:
        existing = await client_repo.get_by_user_and_fingerprint(
            current_user.id, x_device_fingerprint
        )
        if existing:
            updated = await client_repo.update_fcm_token(
                existing.id,
                body.fcm_token,
                device_name=body.device_name,
                user_agent=user_agent,
                ip_address=ip_address,
            )
            await db.commit()
            return ApiResponse(data=_to_response(updated))

    # 신규 생성
    client = await client_repo.create(
        user_id=current_user.id,
        device_type=body.device_type,
        device_name=body.device_name,
        fcm_token=body.fcm_token,
        user_agent=user_agent,
        ip_address=ip_address,
        device_fingerprint=x_device_fingerprint,
    )
    await db.commit()
    response.status_code = status.HTTP_201_CREATED
    return ApiResponse(data=_to_response(client))


@router.get(
    "",
    summary="사용자 클라이언트(기기) 목록 조회",
)
async def list_clients(
    current_user: CurrentUser,
    client_repo: ClientRepoDep,
) -> ApiResponse[ClientListResponse]:
    """사용자의 활성 기기 세션 목록 반환."""
    clients = await client_repo.get_by_user(current_user.id)
    return ApiResponse(data=ClientListResponse(clients=[_to_response(c) for c in clients]))


@router.delete(
    "/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="클라이언트(기기) 제거",
)
async def delete_client(
    client_id: uuid.UUID,
    current_user: CurrentUser,
    client_repo: ClientRepoDep,
    db: DbSession,
) -> None:
    """기기 세션 soft-delete.

    - 미존재 시 404.
    - 타인 소유 시 403.
    """
    client = await client_repo.get_by_id(client_id)
    if client is None:
        raise ClientErrors.not_found()
    if client.user_id != current_user.id:
        raise ClientErrors.access_denied()

    await client_repo.deactivate(client_id)
    await db.commit()
