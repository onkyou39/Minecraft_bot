import pytest
import time

from services import watchdog
@pytest.fixture
def clean_watchdog():
    watchdog.watchdog_state.reset()
    yield
    watchdog.watchdog_state.reset()


@pytest.mark.asyncio
async def test_online_with_players(monkeypatch):
    state = {"notified": False, "shutdown": False}

    # игроки есть
    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = True
        watchdog.mc_server.players_online = 3

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)

    # Сбрасываем состояние датакласса перед тестом
    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.is_fresh_start = True

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "✅ Minecraft сервер доступен" in state["notified"]
    assert not state["shutdown"]


@pytest.mark.asyncio
async def test_empty_server_timer_not_expired(monkeypatch):
    state = {"notified": None, "shutdown": False}

    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = True
        watchdog.mc_server.players_online = 0

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)

    # Подготавливаем состояние датакласса
    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.empty_since = time.time() - watchdog.mc_server.wd_poweroff_cooldown + 120
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_3m_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "никого нет" in state["notified"]
    assert not state["shutdown"]


@pytest.mark.asyncio
async def test_empty_server_shutdown(monkeypatch):
    state = {"notified": None, "shutdown": False}

    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = True
        watchdog.mc_server.players_online = 0

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.empty_since = time.time() - watchdog.mc_server.wd_poweroff_cooldown - 5
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_3m_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "выключен" in state["notified"]
    assert state["shutdown"]


@pytest.mark.asyncio
async def test_server_crashed(monkeypatch):
    state = {"notified": None, "shutdown": False}
    crashes = {"count": 2}

    # сервер упал
    async def mock_refresh_mc_server_state():
        watchdog.mc_server.online = False
        watchdog.mc_server.players_online = None

    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_state)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.crashed = crashes["count"]
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_3m_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert "временно недоступен" in state["notified"]


@pytest.mark.asyncio
async def test_first_start(monkeypatch):
    state = {"notified": None, "shutdown": False}

    # сервер недоступен, первый запуск
    async def mock_refresh_mc_server_status():
        watchdog.mc_server.online = False
        watchdog.mc_server.players_online = None


    async def notify_cb(msg): state["notified"] = msg
    async def shutdown_cb(): state["shutdown"] = True

    monkeypatch.setattr(watchdog, "refresh_mc_server_state", mock_refresh_mc_server_status)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.crashed = 0
    watchdog.watchdog_state.is_fresh_start = True
    watchdog.watchdog_state.warning_3m_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
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

    monkeypatch.setattr(watchdog,"fast_check", mock_fast_check)
    monkeypatch.setattr(watchdog.JavaServer,"async_lookup", mock_lookup)

    watchdog.watchdog_state.reset()
    watchdog.watchdog_state.crashed = crashes["count"]
    watchdog.watchdog_state.is_fresh_start = False
    watchdog.watchdog_state.warning_3m_sent = False

    await watchdog.watchdog_tick(shutdown_cb, notify_cb)
    assert state["notified"] is None

