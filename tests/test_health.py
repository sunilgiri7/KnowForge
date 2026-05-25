from app.api.v1.health import health_check


async def test_health_check() -> None:
    assert await health_check() == {"status": "ok"}
