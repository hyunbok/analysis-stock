---
name: uv 테스트 실행 방법
description: server/ 디렉토리에서 uv run으로 단위 테스트 실행 시 conftest 충돌 회피 방법
type: feedback
---

root conftest.py가 SQLAlchemy 등을 import하므로 `uv run pytest` 단독 실행 시 conftest 로딩 오류 발생.

**Why:** tests/conftest.py가 DB fixture를 위해 SQLAlchemy, MongoDB를 import하는데, uv가 격리된 환경에서 실행 시 충돌

**How to apply:** upbit 단위 테스트처럼 DB 의존성 없는 테스트는 다음 명령어 사용:
```
uv run --with pytest python -m pytest tests/unit/providers/upbit/ -v
```
pytest-asyncio가 필요한 경우:
```
uv run --with pytest --with pytest-asyncio python -m pytest tests/unit/providers/upbit/test_websocket.py -v
```
