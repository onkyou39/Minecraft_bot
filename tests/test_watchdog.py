import pytest
import time
from watchdog import watchdog_tick, WD_POWEROFF_COOLDOWN

@pytest.mark.asyncio
async def test_online_with_players(monkeypatch):
    state = {"notified": False, "shutdown": False}

    async def check_server_players(server, port):
        return 3  # игроки есть

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr("watchdog.check_server_players", check_server_players)
    monkeypatch.setattr("watchdog.empty_since", None)
    monkeypatch.setattr("watchdog.is_fresh_start", True)

    await watchdog_tick(shutdown_cb, notify_cb)
    assert state["notified"] == "✅ Minecraft сервер доступен для подключения."
    assert not state["shutdown"]


@pytest.mark.asyncio
async def test_empty_server_timer_not_expired(monkeypatch):
    state = {"notified": None, "shutdown": False}

    async def check_server_players(server, port):
        return 0

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr("watchdog.check_server_players", check_server_players)
    monkeypatch.setattr("watchdog.empty_since", time.time() - 100)  # ещё не истек
    monkeypatch.setattr("watchdog.is_fresh_start", False)
    monkeypatch.setattr("watchdog.notified", False)

    await watchdog_tick(shutdown_cb, notify_cb)
    assert "нет игроков" in state["notified"]
    assert not state["shutdown"]


@pytest.mark.asyncio
async def test_empty_server_shutdown(monkeypatch):
    state = {"notified": None, "shutdown": False}

    async def check_server_players(server, port):
        return 0

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr("watchdog.check_server_players", check_server_players)
    monkeypatch.setattr("watchdog.empty_since", time.time() - WD_POWEROFF_COOLDOWN - 5)
    monkeypatch.setattr("watchdog.is_fresh_start", False)
    monkeypatch.setattr("watchdog.notified", False)

    await watchdog_tick(shutdown_cb, notify_cb)
    assert "выключен" in state["notified"]
    assert state["shutdown"]


@pytest.mark.asyncio
async def test_server_crashed(monkeypatch):
    state = {"notified": None, "shutdown": False}
    crashes = {"count": 2}

    async def check_server_players(server, port):
        return None  # сервер упал

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr("watchdog.check_server_players", check_server_players)
    monkeypatch.setattr("watchdog.crashed", crashes["count"])
    monkeypatch.setattr("watchdog.is_fresh_start", False)
    monkeypatch.setattr("watchdog.notified", False)

    await watchdog_tick(shutdown_cb, notify_cb)
    assert "временно недоступен" in state["notified"]


@pytest.mark.asyncio
async def test_first_start(monkeypatch):
    state = {"notified": None, "shutdown": False}

    async def check_server_players(server, port):
        return None  # сервер недоступен, первый запуск

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr("watchdog.check_server_players", check_server_players)
    monkeypatch.setattr("watchdog.crashed", 0)
    monkeypatch.setattr("watchdog.is_fresh_start", True)
    monkeypatch.setattr("watchdog.notified", False)

    await watchdog_tick(shutdown_cb, notify_cb)
    assert "запускается" in state["notified"]


@pytest.mark.asyncio
async def test_failed_server_status(monkeypatch):
    state = {"notified": None, "shutdown": False}
    crashes = {"count": 1}

    async def mock_fast_check(host, port, timeout=2.0):
        return True  # порт открыт

    class MockServer:
        async def async_status(self):
            raise TimeoutError("Сервер завис")

    async def mock_lookup(address_port, timeout=3):
        return MockServer()

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr("watchdog.fast_check", mock_fast_check)
    monkeypatch.setattr("watchdog.JavaServer.async_lookup", mock_lookup)
    monkeypatch.setattr("watchdog.crashed", crashes["count"])
    monkeypatch.setattr("watchdog.is_fresh_start", False)
    monkeypatch.setattr("watchdog.notified", False)

    await watchdog_tick(shutdown_cb, notify_cb)
    assert state["notified"] is None

