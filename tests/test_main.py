"""Tests for the FastAPI app entry point: lifespan wiring and health check."""

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from src.main import app, lifespan


class TestLifespan:
    """Tests for app startup/shutdown resource wiring."""

    async def test_initializes_and_tears_down_resources(self) -> None:
        mock_client = AsyncMock()

        with (
            patch("src.main.KrakenClient", return_value=mock_client),
            patch("src.main.init_database", new_callable=AsyncMock) as mock_init_db,
        ):
            async with lifespan(app):
                assert app.state.client is mock_client
                assert app.state.executor is not None
                assert app.state.risk_manager is not None
                assert app.state.engine is not None

            mock_client.initialize.assert_awaited_once()
            mock_init_db.assert_awaited_once()
            mock_client.close.assert_awaited_once()


class TestHealthCheck:
    """Tests for GET /health."""

    async def test_returns_ok(self) -> None:
        mock_client = AsyncMock()

        with (
            patch("src.main.KrakenClient", return_value=mock_client),
            patch("src.main.init_database", new_callable=AsyncMock),
        ):
            async with lifespan(app):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
