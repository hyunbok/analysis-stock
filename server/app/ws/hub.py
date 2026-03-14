"""WebSocket 연결 관리자 + 채널 구독 통합 — WSHub."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    """WebSocket 연결 정보."""

    conn_id: str
    websocket: "WebSocket"
    user_id: str
    client_id: str | None
    connected_at: datetime
    last_ping: datetime
    subscriptions: set[str] = field(default_factory=set)


class WSHub:
    """WebSocket 연결 + 채널 구독 통합 관리자.

    동시성 보호:
        - asyncio 단일 이벤트 루프, await 없는 dict/set 조작은 원자적
        - broadcast_to_channel 반복 중 변경은 set.copy()로 방어
        - asyncio.Lock 미사용 (불필요한 경합 방지)
    """

    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}
        self._user_connections: dict[str, set[str]] = {}
        self._channel_subscribers: dict[str, set[str]] = {}
        self._conn_channels: dict[str, set[str]] = {}

    # ── 연결 관리 ──────────────────────────────────────────────────────────────

    async def connect(
        self,
        websocket: "WebSocket",
        user_id: str,
        client_id: str | None = None,
    ) -> str | None:
        """WebSocket 연결 등록.

        Returns:
            성공 시 conn_id (UUID4 문자열), 한계 초과 시 None.
        """
        if len(self._connections) >= settings.WS_MAX_CONNECTIONS:
            logger.warning("WS connection limit reached max=%d", settings.WS_MAX_CONNECTIONS)
            return None

        user_conn_count = len(self._user_connections.get(user_id, set()))
        if user_conn_count >= settings.WS_MAX_CONNECTIONS_PER_USER:
            logger.warning(
                "WS per-user connection limit reached user_id=%s max=%d",
                user_id, settings.WS_MAX_CONNECTIONS_PER_USER,
            )
            return None

        conn_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        conn = Connection(
            conn_id=conn_id,
            websocket=websocket,
            user_id=user_id,
            client_id=client_id,
            connected_at=now,
            last_ping=now,
        )
        self._connections[conn_id] = conn
        self._user_connections.setdefault(user_id, set()).add(conn_id)
        self._conn_channels[conn_id] = set()

        logger.info("WS connected conn_id=%s user_id=%s", conn_id, user_id)
        return conn_id

    async def disconnect(self, conn_id: str) -> None:
        """WebSocket 연결 해제 + 채널 구독 정리."""
        conn = self._connections.pop(conn_id, None)
        if conn is None:
            return

        duration = (datetime.now(timezone.utc) - conn.connected_at).total_seconds()
        logger.info("WS disconnected conn_id=%s duration=%.1fs", conn_id, duration)

        # 사용자 인덱스 정리
        user_conns = self._user_connections.get(conn.user_id)
        if user_conns:
            user_conns.discard(conn_id)
            if not user_conns:
                del self._user_connections[conn.user_id]

        # 채널 구독 정리
        channels = self._conn_channels.pop(conn_id, set())
        for channel in channels:
            subs = self._channel_subscribers.get(channel)
            if subs:
                subs.discard(conn_id)
                if not subs:
                    del self._channel_subscribers[channel]

    def get_connection(self, conn_id: str) -> Connection | None:
        return self._connections.get(conn_id)

    def get_connection_count(self) -> int:
        return len(self._connections)

    def update_ping(self, conn_id: str) -> None:
        """클라이언트 ping 수신 시 last_ping 갱신."""
        conn = self._connections.get(conn_id)
        if conn:
            conn.last_ping = datetime.now(timezone.utc)

    # ── 구독 관리 ──────────────────────────────────────────────────────────────

    def subscribe(self, conn_id: str, channel: str) -> bool:
        """채널 구독 등록.

        Returns:
            True: 새로 구독 성공. False: 이미 구독 중이거나 연결 없음.
        """
        conn = self._connections.get(conn_id)
        if conn is None:
            return False
        if channel in conn.subscriptions:
            return False

        conn.subscriptions.add(channel)
        self._conn_channels[conn_id].add(channel)
        self._channel_subscribers.setdefault(channel, set()).add(conn_id)
        logger.debug("subscribe conn_id=%s channel=%s", conn_id, channel)
        return True

    def unsubscribe(self, conn_id: str, channel: str) -> bool:
        """채널 구독 해제.

        Returns:
            True: 해제 성공. False: 구독 중이 아니거나 연결 없음.
        """
        conn = self._connections.get(conn_id)
        if conn is None:
            return False
        if channel not in conn.subscriptions:
            return False

        conn.subscriptions.discard(channel)
        self._conn_channels[conn_id].discard(channel)
        subs = self._channel_subscribers.get(channel)
        if subs:
            subs.discard(conn_id)
            if not subs:
                del self._channel_subscribers[channel]

        logger.debug("unsubscribe conn_id=%s channel=%s", conn_id, channel)
        return True

    def get_subscriptions(self, conn_id: str) -> set[str]:
        """현재 연결의 구독 채널 집합 반환 (복사본)."""
        conn = self._connections.get(conn_id)
        return conn.subscriptions.copy() if conn else set()

    def get_channel_subscriber_count(self, channel: str) -> int:
        return len(self._channel_subscribers.get(channel, set()))

    # ── 브로드캐스트 ────────────────────────────────────────────────────────────

    async def broadcast_to_channel(self, channel: str, message: dict | str) -> int:
        """채널의 모든 구독자에게 전송.

        Returns:
            전송 성공 수.

        Note:
            JSON 직렬화 1회 후 send_text()로 전송 (재직렬화 방지).
            asyncio.gather로 병렬 전송.
        """
        subscriber_ids = self._channel_subscribers.get(channel)
        if not subscriber_ids:
            return 0

        payload = json.dumps(message, ensure_ascii=False) if isinstance(message, dict) else message

        tasks = [
            self._safe_send(conn, payload)
            for conn_id in subscriber_ids.copy()
            if (conn := self._connections.get(conn_id)) is not None
        ]
        if not tasks:
            return 0

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return sum(1 for r in results if r is True)

    async def send_to_user(self, user_id: str, message: dict) -> int:
        """특정 사용자의 모든 연결에 전송.

        Returns:
            전송 성공 수.
        """
        conn_ids = self._user_connections.get(user_id)
        if not conn_ids:
            return 0

        payload = json.dumps(message, ensure_ascii=False)
        tasks = [
            self._safe_send(conn, payload)
            for conn_id in conn_ids.copy()
            if (conn := self._connections.get(conn_id)) is not None
        ]
        if not tasks:
            return 0

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return sum(1 for r in results if r is True)

    async def send_to_connection(self, conn_id: str, message: dict) -> bool:
        """특정 연결에 전송.

        Returns:
            전송 성공 여부.
        """
        conn = self._connections.get(conn_id)
        if not conn:
            return False
        payload = json.dumps(message, ensure_ascii=False)
        return await self._safe_send(conn, payload)

    async def _safe_send(self, conn: Connection, payload: str) -> bool:
        """전송 실패 시 해당 연결 disconnect 예약 (예외 전파 금지)."""
        try:
            await conn.websocket.send_text(payload)
            return True
        except Exception:
            logger.debug(
                "WS send failed conn_id=%s — scheduling disconnect", conn.conn_id
            )
            asyncio.create_task(self.disconnect(conn.conn_id))
            return False

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    async def heartbeat_loop(self) -> None:
        """Heartbeat 루프 — 타임아웃 연결 강제 종료.

        30초 간격으로 모든 연결의 last_ping 확인.
        60초 이상 ping 없는 연결은 강제 종료.
        """
        logger.info("WSHub heartbeat loop started")
        try:
            while True:
                await asyncio.sleep(settings.WS_HEARTBEAT_INTERVAL)
                await self._check_heartbeats()
        except asyncio.CancelledError:
            logger.info("WSHub heartbeat loop stopped")

    async def _check_heartbeats(self) -> None:
        now = datetime.now(timezone.utc)
        timeout_secs = settings.WS_HEARTBEAT_TIMEOUT

        stale_ids = [
            conn_id
            for conn_id, conn in list(self._connections.items())
            if (now - conn.last_ping).total_seconds() > timeout_secs
        ]
        for conn_id in stale_ids:
            logger.warning(
                "WS heartbeat timeout conn_id=%s — force disconnect", conn_id
            )
            conn = self._connections.get(conn_id)
            if conn:
                try:
                    await conn.websocket.close(code=1001, reason="Heartbeat timeout")
                except Exception:
                    pass
            await self.disconnect(conn_id)
