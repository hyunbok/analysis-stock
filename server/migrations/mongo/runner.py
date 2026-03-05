"""MongoDB 마이그레이션 러너.

사용법: python -m migrations.mongo.runner
"""
import asyncio
import importlib
import pkgutil
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

VERSIONS_PACKAGE = "migrations.mongo.versions"
MIGRATION_COLLECTION = "migration_versions"


async def get_applied_versions(db) -> set[str]:
    collection = db[MIGRATION_COLLECTION]
    cursor = collection.find({}, {"version": 1})
    return {doc["version"] async for doc in cursor}


async def record_version(db, version: str, description: str):
    from datetime import datetime, UTC
    await db[MIGRATION_COLLECTION].insert_one({
        "version": version,
        "description": description,
        "applied_at": datetime.now(UTC),
    })


async def run_migrations():
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    applied = await get_applied_versions(db)

    # versions 패키지에서 모듈 자동 탐색
    versions_pkg = importlib.import_module(VERSIONS_PACKAGE)
    modules = sorted(pkgutil.iter_modules(versions_pkg.__path__))

    for _, name, _ in modules:
        module = importlib.import_module(f"{VERSIONS_PACKAGE}.{name}")
        version = getattr(module, "VERSION")
        if version in applied:
            continue
        description = getattr(module, "DESCRIPTION", "")
        print(f"Applying migration {version}: {description}")
        await module.upgrade(db)
        await record_version(db, version, description)
        print(f"  Applied {version}")

    client.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
