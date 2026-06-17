import pytest
import services.vps_service as vps_service
from integrations import api


@pytest.mark.asyncio
async def test_shutdown_vps_success(monkeypatch):
    async def mock_request(action):
        return {"State": "InProgress"}

    monkeypatch.setattr(api, "api_request", mock_request)

    result = await vps_service.shutdown_vps()

    assert result["State"] == "InProgress"
    assert vps_service.vps_state.last_poweron_time > 0