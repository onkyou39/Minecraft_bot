import pytest
import time
from watchdog import watchdog_tick, WD_POWEROFF_COOLDOWN, watchdog_state

@pytest.mark.asyncio
async def test_online_with_players(monkeypatch):
    state = {"notified": False, "shutdown": False}

    async def check_server_players(server, port):
        return 3  # игроки есть

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr("watchdog.check_server_players", check_server_players)

    # Сбрасываем состояние датакласса перед тестом
    watchdog_state.reset()
    watchdog_state.is_fresh_start = True

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

    # Подготавливаем состояние датакласса
    watchdog_state.reset()
    watchdog_state.empty_since = time.time() - 100
    watchdog_state.is_fresh_start = False
    watchdog_state.notified = False

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

    watchdog_state.reset()
    watchdog_state.empty_since = time.time() - WD_POWEROFF_COOLDOWN - 5
    watchdog_state.is_fresh_start = False
    watchdog_state.notified = False

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

    watchdog_state.reset()
    watchdog_state.crashed = crashes["count"]
    watchdog_state.is_fresh_start = False
    watchdog_state.notified = False

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

    watchdog_state.reset()
    watchdog_state.crashed = 0
    watchdog_state.is_fresh_start = True
    watchdog_state.notified = False

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

    watchdog_state.reset()
    watchdog_state.crashed = crashes["count"]
    watchdog_state.is_fresh_start = False
    watchdog_state.notified = False

    await watchdog_tick(shutdown_cb, notify_cb)
    assert state["notified"] is None

