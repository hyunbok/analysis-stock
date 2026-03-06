"""Client 엔티티 DB 접근 계층 — 디바이스 세션 관리."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Client


class ClientRepository:
    """Client(디바이스 세션) CRUD."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        user_id: uuid.UUID,
        *,
        device_type: str,
        device_name: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        device_fingerprint: str | None = None,
        fcm_token: str | None = None,
    ) -> Client:
        """신규 Client 생성.

        Args:
            user_id: 사용자 UUID.
            device_type: ios | android | web.
            device_name: 디바이스 표시 이름 (선택).
            user_agent: HTTP User-Agent (선택).
            ip_address: 요청 IP (선택).
            device_fingerprint: SHA-256 핑거프린트 (선택).
            fcm_token: FCM 푸시 토큰 (선택).

        Returns:
            생성된 Client.
        """
        client = Client(
            user_id=user_id,
            device_type=device_type,
            device_name=device_name,
            user_agent=user_agent,
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
            fcm_token=fcm_token,
            last_active_at=datetime.now(timezone.utc),
        )
        self._db.add(client)
        await self._db.flush()
        await self._db.refresh(client)
        return client

    async def get_by_id(self, client_id: uuid.UUID) -> Client | None:
        """UUID로 Client 조회.

        Args:
            client_id: Client UUID.

        Returns:
            Client 또는 None.
        """
        result = await self._db.execute(
            select(Client).where(Client.id == client_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_and_fingerprint(
        self, user_id: uuid.UUID, fingerprint: str
    ) -> Client | None:
        """user_id + device_fingerprint 복합 인덱스로 기존 세션 조회.

        Args:
            user_id: 사용자 UUID.
            fingerprint: SHA-256 디바이스 핑거프린트.

        Returns:
            활성 Client 또는 None.
        """
        result = await self._db.execute(
            select(Client).where(
                Client.user_id == user_id,
                Client.device_fingerprint == fingerprint,
                Client.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(self, user_id: uuid.UUID) -> list[Client]:
        """사용자의 모든 활성 세션 목록 (is_active=True).

        Args:
            user_id: 사용자 UUID.

        Returns:
            활성 Client 리스트.
        """
        result = await self._db.execute(
            select(Client).where(
                Client.user_id == user_id,
                Client.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def deactivate(self, client_id: uuid.UUID) -> None:
        """세션 비활성화 (soft-delete).

        Args:
            client_id: Client UUID.
        """
        await self._db.execute(
            update(Client).where(Client.id == client_id).values(is_active=False)
        )
        await self._db.flush()

    async def deactivate_all(
        self,
        user_id: uuid.UUID,
        except_client_id: uuid.UUID | None = None,
    ) -> int:
        """사용자의 모든 활성 세션 비활성화 (현재 세션 제외 옵션).

        단일 bulk UPDATE로 N+1 쿼리 방지.

        Args:
            user_id: 사용자 UUID.
            except_client_id: 제외할 Client UUID (현재 세션).

        Returns:
            비활성화된 세션 수.
        """
        conditions = [Client.user_id == user_id, Client.is_active.is_(True)]
        if except_client_id is not None:
            conditions.append(Client.id != except_client_id)

        result = await self._db.execute(
            update(Client).where(and_(*conditions)).values(is_active=False)
        )
        await self._db.flush()
        return result.rowcount

    async def update_last_active(self, client_id: uuid.UUID) -> None:
        """last_active_at을 현재 시각으로 갱신.

        Args:
            client_id: Client UUID.
        """
        now = datetime.now(timezone.utc)
        await self._db.execute(
            update(Client)
            .where(Client.id == client_id)
            .values(last_active_at=now)
        )
        await self._db.flush()
